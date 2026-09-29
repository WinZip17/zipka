"""Фоновый воркер LoRA-дообучения. Запуск: python -m zipka.evolve.finetune_worker --job ..."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any


def _log(msg: str) -> None:
    print(msg, flush=True)


def _write_job(path: Path, job: dict[str, Any]) -> None:
    path.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_status(data_dir: Path, patch: dict[str, Any]) -> None:
    status_path = data_dir / "finetune" / "status.json"
    cur: dict[str, Any] = {}
    if status_path.exists():
        try:
            cur = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cur = {}
    cur.update(patch)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    cur["updated_at"] = now
    # при финальных состояниях фиксируем finished_at (таймер в UI замирает)
    if cur.get("state") in {
        "done",
        "failed",
        "interrupted",
        "succeeded_pending_apply",
    } and not cur.get("finished_at"):
        cur["finished_at"] = now
    status_path.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


def _require_train_deps() -> None:
    missing = []
    for mod in ("torch", "transformers", "peft", "datasets", "accelerate"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        raise RuntimeError(
            "Нет зависимостей дообучения: "
            + ", ".join(missing)
            + '. Установи: pip install -e ".[finetune]"'
        )


def _load_dataset(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    if not rows:
        raise RuntimeError(f"Пустой датасет: {path}")
    return rows


def _format_example(row: dict[str, str], tokenizer: Any) -> str:
    user = row.get("instruction") or row.get("input") or ""
    out = row.get("output") or ""
    # ChatML-ish — совместимо с Qwen instruct
    text = (
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n{out}<|im_end|>\n"
    )
    return text


def _available_ram_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().available)
    except Exception:
        return None


def _vram_bytes() -> int | None:
    try:
        import torch

        if not torch.cuda.is_available():
            return None
        return int(torch.cuda.get_device_properties(0).total_memory)
    except Exception:
        return None


def _torch_cuda_hint() -> str | None:
    """Если nvidia есть, а torch CPU-only — подсказать переустановку."""
    try:
        import torch
    except Exception:
        return None
    if torch.cuda.is_available():
        return None
    # nvidia-smi без CUDA в torch
    try:
        import subprocess

        r = subprocess.run(
            ["nvidia-smi", "-L"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if r.returncode != 0 or "GPU" not in (r.stdout or ""):
            return None
    except Exception:
        return None
    ver = getattr(torch, "__version__", "?")
    return (
        f"Обнаружена NVIDIA GPU, но PyTorch без CUDA (torch={ver}). "
        "Переустанови: pip uninstall -y torch && "
        "pip install torch --index-url https://download.pytorch.org/whl/cu126 "
        "(или cu130). Тогда дообучение будет на VRAM+RAM."
    )


def _estimate_params_b(model_src: str) -> float:
    low = str(model_src).lower()
    for hint, n in (
        ("32b", 32.0),
        ("14b", 14.0),
        ("13b", 13.0),
        ("8b", 8.0),
        ("7b", 7.0),
        ("3b", 3.0),
        ("1.5b", 1.5),
        ("1b", 1.0),
    ):
        if hint in low:
            return n
    return 8.0


def _estimate_load_bytes(model_src: str, *, bytes_per_param: float) -> int:
    return int(_estimate_params_b(model_src) * 1e9 * bytes_per_param * 1.35)


def _exc_text(exc: BaseException) -> str:
    """MemoryError и часть OSError дают пустой str() — показываем имя типа."""
    name = type(exc).__name__
    msg = str(exc).strip()
    return f"{name}: {msg}" if msg else name


def _format_gb(n: float | int | None) -> str:
    if n is None:
        return "?"
    return f"{float(n) / 1e9:.1f} ГБ"


def train_lora(job: dict[str, Any], data_dir: Path) -> dict[str, Any]:
    _require_train_deps()
    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, TaskType
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    params = job.get("params") or {}
    max_steps = int(params.get("max_steps") or 60)
    lora_r = int(params.get("lora_r") or 8)
    max_seq_len = int(params.get("max_seq_len") or 512)
    batch_size = int(params.get("batch_size") or 1)
    grad_accum = int(params.get("grad_accum") or 4)
    lr = float(params.get("learning_rate") or 2e-4)

    base = job.get("base") or {}
    model_src = base.get("path") or base.get("hf_id")
    if not model_src:
        raise RuntimeError("В job нет base.path / base.hf_id")

    ds_path = Path(job["dataset"])
    rows = _load_dataset(ds_path)
    adapter_dir = Path(job["adapter_dir"])
    ckpt_dir = Path(job["checkpoint_dir"])
    adapter_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    offload_dir = adapter_dir / "offload"
    offload_dir.mkdir(parents=True, exist_ok=True)

    _write_status(data_dir, {"phase": "load_model", "model": str(model_src)})
    _log(f"Loading tokenizer/model: {model_src}")

    tokenizer = AutoTokenizer.from_pretrained(model_src, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    cuda = bool(torch.cuda.is_available())
    cuda_hint = _torch_cuda_hint()
    if cuda_hint:
        _log(cuda_hint)
    # На CPU fp32 для 8B ≈ 32 ГБ — почти всегда OOM. Грузим веса в fp16.
    dtype = torch.float16
    load_kwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "low_cpu_mem_usage": True,
        "torch_dtype": dtype,
    }

    # 4-bit если есть bitsandbytes (на Windows часто нет)
    use_4bit = False
    try:
        import bitsandbytes  # noqa: F401

        from transformers import BitsAndBytesConfig

        if cuda:
            load_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=dtype,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
            use_4bit = True
    except Exception as exc:
        _log(f"4-bit недоступен: {exc}")
        use_4bit = False

    bytes_per_param = 0.5 if use_4bit else 2.0
    need = _estimate_load_bytes(str(model_src), bytes_per_param=bytes_per_param)
    # Пик при materialize/copy часто на 40–50% выше размера весов
    peak = int(need * 1.45)
    avail = _available_ram_bytes()
    vram = _vram_bytes() if cuda else None
    pool = (avail or 0) + (vram or 0)
    _log(
        f"cuda={cuda} use_4bit={use_4bit} dtype={dtype} "
        f"estimate_weights≈{_format_gb(need)} peak≈{_format_gb(peak)} "
        f"available_ram≈{_format_gb(avail)} vram≈{_format_gb(vram)} "
        f"pool≈{_format_gb(pool or None)}"
    )
    if cuda_hint and not cuda:
        raise RuntimeError(cuda_hint)
    budget = pool if cuda else avail
    if budget and peak > budget and not use_4bit:
        raise RuntimeError(
            f"Скорее всего не хватит памяти для {model_src}: "
            f"веса ≈{_format_gb(need)}, пик ≈{_format_gb(peak)}, "
            f"RAM+VRAM ≈{_format_gb(budget)}. "
            "Поставь bitsandbytes (4-bit), освободи память, либо меньшую HF-базу "
            "(override_hf_base, напр. Qwen/Qwen2.5-3B-Instruct)."
        )

    # Гибрид: GPU VRAM + CPU RAM (+ disk offload)
    load_kwargs["device_map"] = "auto"
    load_kwargs["offload_folder"] = str(offload_dir)
    max_memory: dict[Any, str] = {}
    if cuda and vram is not None:
        gpu_budget_gb = max(2, int(vram / 1e9) - 1)
        max_memory[0] = f"{gpu_budget_gb}GiB"
    if avail is not None:
        cpu_budget_gb = max(4, int(avail / 1e9) - 3)
        max_memory["cpu"] = f"{cpu_budget_gb}GiB"
    if max_memory:
        load_kwargs["max_memory"] = max_memory
        _log(f"max_memory={max_memory}")

    def _load_model(kwargs: dict[str, Any]):
        return AutoModelForCausalLM.from_pretrained(model_src, **kwargs)

    try:
        model = _load_model(load_kwargs)
    except MemoryError as exc:
        _log(f"MemoryError при загрузке, пробую жёсткий offload: {_exc_text(exc)}")
        retry = dict(load_kwargs)
        retry["device_map"] = "auto"
        retry["offload_folder"] = str(offload_dir)
        retry["offload_state_dict"] = True
        retry_mem = dict(max_memory) if max_memory else {}
        if avail is not None:
            retry_mem["cpu"] = f"{max(4, int(avail / 1e9) - 4)}GiB"
        if cuda and vram is not None:
            retry_mem[0] = f"{max(2, int(vram / 1e9) - 2)}GiB"
        if retry_mem:
            retry["max_memory"] = retry_mem
        try:
            model = _load_model(retry)
        except Exception as exc2:
            raise RuntimeError(
                f"Не удалось загрузить {model_src}: {_exc_text(exc2)}. "
                f"Пик≈{_format_gb(peak)}, RAM≈{_format_gb(avail)}, "
                f"VRAM≈{_format_gb(vram)}. "
                "Нужны CUDA+bitsandbytes или меньшая база "
                "(override_hf_base → Qwen/Qwen2.5-3B-Instruct)."
            ) from exc2
    except Exception as exc:
        raise RuntimeError(
            f"Не удалось загрузить {model_src}: {_exc_text(exc)}. "
            f"Пик≈{_format_gb(peak)}, RAM≈{_format_gb(avail)}, "
            f"VRAM≈{_format_gb(vram)}."
        ) from exc
    if use_4bit:
        from peft import prepare_model_for_kbit_training

        model = prepare_model_for_kbit_training(model)

    lora = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_r,
        lora_alpha=lora_r * 2,
        lora_dropout=0.05,
        bias="none",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    model = get_peft_model(model, lora)
    model.print_trainable_parameters()
    try:
        model.enable_input_require_grads()
        model.gradient_checkpointing_enable()
        _log("gradient checkpointing включён")
    except Exception as exc:
        _log(f"gradient_checkpointing skip: {exc}")

    def tok_map(batch: dict[str, list[str]]) -> dict[str, Any]:
        texts = [
            _format_example(
                {"instruction": i, "output": o},
                tokenizer,
            )
            for i, o in zip(batch["instruction"], batch["output"])
        ]
        enc = tokenizer(
            texts,
            truncation=True,
            max_length=max_seq_len,
            padding=False,
        )
        enc["labels"] = [list(ids) for ids in enc["input_ids"]]
        return enc

    raw = Dataset.from_list(rows)
    tokenized = raw.map(
        tok_map,
        batched=True,
        remove_columns=raw.column_names,
        desc="tokenize",
    )

    _write_status(data_dir, {"phase": "train", "steps": max_steps, "use_4bit": use_4bit})
    args = TrainingArguments(
        output_dir=str(adapter_dir / "trainer_out"),
        max_steps=max_steps,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=lr,
        logging_steps=max(1, max_steps // 10),
        save_steps=max_steps,
        fp16=cuda and not use_4bit,
        bf16=False,
        gradient_checkpointing=True,
        report_to=[],
        remove_unused_columns=False,
        optim="paged_adamw_8bit" if use_4bit else "adamw_torch",
        dataloader_pin_memory=cuda,
    )
    collator = DataCollatorForLanguageModeling(tokenizer, mlm=False)
    trainer = Trainer(
        model=model,
        args=args,
        train_dataset=tokenized,
        data_collator=collator,
    )
    trainer.train()
    model.save_pretrained(str(adapter_dir))
    tokenizer.save_pretrained(str(adapter_dir))
    _log(f"Adapter saved: {adapter_dir}")

    _write_status(data_dir, {"phase": "merge"})
    _log("Merging LoRA into base…")
    # merge: перезагрузка базы без 4bit если нужно
    if use_4bit:
        # для merge нужен fp16/fp32 base
        del model
        del trainer
        torch.cuda.empty_cache()
        merge_model = AutoModelForCausalLM.from_pretrained(
            model_src,
            trust_remote_code=True,
            torch_dtype=dtype,
            device_map="cpu",
        )
        from peft import PeftModel

        merge_model = PeftModel.from_pretrained(merge_model, str(adapter_dir))
        merged = merge_model.merge_and_unload()
    else:
        merged = model.merge_and_unload()
        # на GPU → CPU для сохранения
        merged = merged.to("cpu")

    merged.save_pretrained(str(ckpt_dir), safe_serialization=True)
    tokenizer.save_pretrained(str(ckpt_dir))
    _log(f"Checkpoint saved: {ckpt_dir}")

    return {
        "adapter_dir": str(adapter_dir),
        "checkpoint_dir": str(ckpt_dir),
        "use_4bit": use_4bit,
        "pairs": len(rows),
    }


def export_gguf(job: dict[str, Any], data_dir: Path, ckpt_dir: Path) -> dict[str, Any]:
    """Конвертация HF → GGUF через llama.cpp convert, затем quantize если есть."""
    _write_status(data_dir, {"phase": "export_gguf"})
    models_dir = data_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    out_name = job.get("export_gguf_name") or "zipka-self.gguf"
    out_path = models_dir / out_name
    f16_path = models_dir / (Path(out_name).stem + ".f16.gguf")

    convert_script = os.environ.get("ZIPKA_LLAMA_CONVERT", "").strip()
    candidates = []
    if convert_script:
        candidates.append(Path(convert_script))
    # типичные локальные пути
    root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            root / "tools" / "llama.cpp" / "convert_hf_to_gguf.py",
            root / "third_party" / "llama.cpp" / "convert_hf_to_gguf.py",
            Path.home() / "llama.cpp" / "convert_hf_to_gguf.py",
        ]
    )
    convert = next((p for p in candidates if p.is_file()), None)
    if convert is None:
        return {
            "ok": False,
            "gguf": "",
            "hint": (
                "Чекпоинт готов, но нет convert_hf_to_gguf.py. "
                "Клонируй llama.cpp и задай ZIPKA_LLAMA_CONVERT=путь/к/convert_hf_to_gguf.py "
                f"затем: python -m zipka.evolve.finetune_worker --export-only --job … "
                f"Чекпоинт: {ckpt_dir}"
            ),
            "checkpoint": str(ckpt_dir),
        }

    _log(f"Converting with {convert}")
    cmd = [
        sys.executable,
        str(convert),
        str(ckpt_dir),
        "--outfile",
        str(f16_path),
        "--outtype",
        "f16",
    ]
    subprocess.run(cmd, check=True)

    quant = os.environ.get("ZIPKA_LLAMA_QUANTIZE", "").strip()
    quant_bin = Path(quant) if quant else None
    if quant_bin is None or not quant_bin.is_file():
        for name in ("llama-quantize.exe", "llama-quantize", "quantize.exe", "quantize"):
            found = shutil.which(name)
            if found:
                quant_bin = Path(found)
                break

    if quant_bin and quant_bin.is_file() and f16_path.is_file():
        _log(f"Quantizing → Q4_K_M via {quant_bin}")
        subprocess.run(
            [str(quant_bin), str(f16_path), str(out_path), "Q4_K_M"],
            check=True,
        )
        try:
            f16_path.unlink()
        except OSError:
            pass
    elif f16_path.is_file():
        # без quantize оставляем f16 под целевым именем
        target = models_dir / (Path(out_name).stem.replace(".Q4_K_M", "") + ".f16.gguf")
        if out_path.suffix == ".gguf" and "Q4" in out_name:
            shutil.move(str(f16_path), str(target))
            return {
                "ok": True,
                "gguf": target.name,
                "hint": (
                    "Экспорт f16 без quantize. Поставь llama-quantize в PATH "
                    "или ZIPKA_LLAMA_QUANTIZE для Q4_K_M."
                ),
                "checkpoint": str(ckpt_dir),
            }
        shutil.move(str(f16_path), str(out_path))

    if not out_path.is_file():
        return {
            "ok": False,
            "gguf": "",
            "hint": "convert прошёл, но выходной GGUF не найден",
            "checkpoint": str(ckpt_dir),
        }
    return {
        "ok": True,
        "gguf": out_path.name,
        "hint": None,
        "checkpoint": str(ckpt_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Zipka LoRA finetune worker")
    parser.add_argument("--job", required=True, help="path to job json")
    parser.add_argument("--data-dir", required=True, help="Zipka data dir")
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Только HF→GGUF из checkpoint_dir джоба",
    )
    args = parser.parse_args(argv)
    job_path = Path(args.job)
    data_dir = Path(args.data_dir)
    job = json.loads(job_path.read_text(encoding="utf-8"))

    try:
        if args.export_only:
            ckpt = Path(job["checkpoint_dir"])
            if not ckpt.is_dir():
                raise RuntimeError(f"Нет checkpoint: {ckpt}")
            export = export_gguf(job, data_dir, ckpt)
            job["export"] = export
            if export.get("ok") and export.get("gguf"):
                job["export_gguf_name"] = export["gguf"]
                job["status"] = "succeeded"
            else:
                job["status"] = "failed"
                job["error"] = export.get("hint") or "export failed"
            _write_job(job_path, job)
            _write_status(
                data_dir,
                {
                    "state": "done" if job["status"] == "succeeded" else "failed",
                    "phase": "export_only",
                    "result": export,
                },
            )
            return 0 if job["status"] == "succeeded" else 1

        train_meta = train_lora(job, data_dir)
        job["train"] = train_meta
        export = export_gguf(job, data_dir, Path(job["checkpoint_dir"]))
        job["export"] = export
        # успех если есть checkpoint; GGUF опционален на первом прогоне
        job["status"] = "succeeded"
        if export.get("ok") and export.get("gguf"):
            job["export_gguf_name"] = export["gguf"]
        elif not export.get("ok"):
            job["export_warning"] = export.get("hint")
        _write_job(job_path, job)
        _write_status(
            data_dir,
            {
                "state": "succeeded_pending_apply",
                "phase": "finished",
                "job_id": job.get("id"),
                "export": export,
                "job_path": str(job_path),
            },
        )
        # применить lineage из воркера
        try:
            from zipka.config import Settings
            from zipka.evolve.finetune import FinetuneEvolve
            from zipka.memory.store import MemoryStore

            settings = Settings(zipka_data_dir=str(data_dir))
            ft = FinetuneEvolve(MemoryStore(settings), settings)
            meta = ft.apply_success_from_job(job)
            _write_status(
                data_dir,
                {
                    "state": "done",
                    "phase": "applied",
                    "result": meta,
                    "export": export,
                    "job_id": job.get("id"),
                    "job_path": str(job_path),
                },
            )
            _log(f"Applied lineage: {meta}")
        except Exception as exc:
            _log(f"Lineage apply warning: {exc}")
            traceback.print_exc()
        return 0
    except Exception as exc:
        traceback.print_exc()
        job["status"] = "failed"
        job["error"] = str(exc)
        _write_job(job_path, job)
        _write_status(
            data_dir,
            {
                "state": "failed",
                "phase": "error",
                "error": str(exc),
                "job_id": job.get("id"),
                "job_path": str(job_path),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
