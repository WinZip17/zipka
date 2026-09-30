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
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


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
    return f"{float(n) / 1e9:.1f} GB"


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

    # освободить VRAM/RAM до merge полной базы
    del model
    del trainer
    import gc

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    merge_meta = merge_adapter_to_checkpoint(
        adapter_dir=adapter_dir,
        ckpt_dir=ckpt_dir,
        data_dir=data_dir,
        tokenizer=tokenizer,
    )
    return {
        "adapter_dir": str(adapter_dir),
        "checkpoint_dir": str(ckpt_dir),
        "use_4bit": use_4bit,
        "pairs": len(rows),
        **{k: v for k, v in merge_meta.items() if k not in {"adapter_dir", "checkpoint_dir"}},
    }


def merge_adapter_to_checkpoint(
    *,
    adapter_dir: Path,
    ckpt_dir: Path,
    data_dir: Path,
    tokenizer: Any | None = None,
) -> dict[str, Any]:
    """Слить LoRA в HF-базу на диске (по шардам), без полной загрузки 8B в RAM."""
    import gc
    import json
    import re
    import shutil

    import torch
    from huggingface_hub import snapshot_download
    from peft import PeftConfig
    from safetensors import safe_open
    from safetensors.torch import save_file
    from transformers import AutoTokenizer

    adapter_dir = Path(adapter_dir)
    ckpt_dir = Path(ckpt_dir)
    if not (adapter_dir / "adapter_config.json").is_file():
        raise RuntimeError(f"Нет adapter_config.json в {adapter_dir}")
    adapter_weights = adapter_dir / "adapter_model.safetensors"
    if not adapter_weights.is_file():
        raise RuntimeError(f"Нет adapter_model.safetensors в {adapter_dir}")

    _write_status(data_dir, {"phase": "merge", "adapter_dir": str(adapter_dir)})
    _log("Merging LoRA on-disk (shard-by-shard, low RAM)…")
    gc.collect()
    try:
        import torch as _t

        if _t.cuda.is_available():
            _t.cuda.empty_cache()
    except Exception:
        pass

    peft_cfg = PeftConfig.from_pretrained(str(adapter_dir))
    base_id = peft_cfg.base_model_name_or_path
    if not base_id:
        raise RuntimeError("В adapter_config нет base_model_name_or_path")
    alpha = float(getattr(peft_cfg, "lora_alpha", 16) or 16)
    rank = float(getattr(peft_cfg, "r", 8) or 8)
    scale = alpha / rank
    _log(f"base={base_id} alpha={alpha} r={rank} scale={scale}")

    _log("Ensuring HF snapshot is local…")
    snapshot = Path(
        snapshot_download(
            repo_id=str(base_id),
            allow_patterns=[
                "*.safetensors",
                "*.json",
                "*.txt",
                "*.model",
                "*.jinja",
                "tokenizer*",
                "vocab*",
                "merges.txt",
                "config.json",
                "generation_config.json",
                "*.py",
            ],
        )
    )
    _log(f"snapshot={snapshot}")

    # LoRA tensors (маленькие, ~80 МБ)
    lora_a: dict[str, torch.Tensor] = {}
    lora_b: dict[str, torch.Tensor] = {}
    with safe_open(str(adapter_weights), framework="pt", device="cpu") as f:
        for key in f.keys():
            # base_model.model.model.layers.N....lora_A.weight
            m = re.match(
                r"^base_model\.model\.(.+)\.lora_([AB])(?:\.default)?\.weight$",
                key,
            )
            if not m:
                continue
            base_key = m.group(1) + ".weight"
            tensor = f.get_tensor(key).to(torch.float32)
            if m.group(2) == "A":
                lora_a[base_key] = tensor
            else:
                lora_b[base_key] = tensor
    targets = sorted(set(lora_a) & set(lora_b))
    _log(f"LoRA target tensors: {len(targets)}")
    if not targets:
        raise RuntimeError("В adapter не найдены пары lora_A/lora_B")

    index_path = snapshot / "model.safetensors.index.json"
    single = snapshot / "model.safetensors"
    if index_path.is_file():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        weight_map: dict[str, str] = dict(index.get("weight_map") or {})
        shards = sorted(set(weight_map.values()))
    elif single.is_file():
        with safe_open(str(single), framework="pt", device="cpu") as f:
            keys = list(f.keys())
        weight_map = {k: single.name for k in keys}
        shards = [single.name]
        index = {"metadata": {}, "weight_map": weight_map}
    else:
        raise RuntimeError(f"В snapshot нет model.safetensors: {snapshot}")

    if ckpt_dir.exists():
        shutil.rmtree(ckpt_dir, ignore_errors=True)
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    # копируем конфиги токенизатора/модели
    for name in (
        "config.json",
        "generation_config.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.json",
        "merges.txt",
        "chat_template.jinja",
        "added_tokens.json",
    ):
        src = snapshot / name
        if src.is_file():
            shutil.copy2(src, ckpt_dir / name)
    # из адаптера — актуальный tokenizer, если есть
    for name in ("tokenizer.json", "tokenizer_config.json", "chat_template.jinja"):
        src = adapter_dir / name
        if src.is_file():
            shutil.copy2(src, ckpt_dir / name)

    new_weight_map: dict[str, str] = {}
    merged_count = 0
    for shard_name in shards:
        shard_path = snapshot / shard_name
        _log(f"shard {shard_name}…")
        out_tensors: dict[str, torch.Tensor] = {}
        with safe_open(str(shard_path), framework="pt", device="cpu") as f:
            for key in f.keys():
                tensor = f.get_tensor(key)
                if key in lora_a and key in lora_b:
                    # W' = W + B @ A * scale
                    w = tensor.to(torch.float32)
                    a = lora_a[key]
                    b = lora_b[key]
                    delta = (b @ a) * scale
                    if delta.shape != w.shape:
                        raise RuntimeError(
                            f"Shape mismatch for {key}: W{tuple(w.shape)} "
                            f"delta{tuple(delta.shape)}"
                        )
                    tensor = (w + delta).to(torch.float16).contiguous()
                    merged_count += 1
                    del w, delta
                elif tensor.dtype == torch.float32:
                    # база может быть bf16/fp16; нормализуем крупные веса в fp16
                    if tensor.ndim >= 2 and tensor.numel() > 1_000_000:
                        tensor = tensor.to(torch.float16).contiguous()
                out_tensors[key] = tensor
                new_weight_map[key] = shard_name
        out_path = ckpt_dir / shard_name
        save_file(out_tensors, str(out_path))
        del out_tensors
        gc.collect()

    # index
    if len(shards) == 1 and shards[0] == "model.safetensors":
        pass
    else:
        out_index = {
            "metadata": (index.get("metadata") or {}),
            "weight_map": new_weight_map,
        }
        (ckpt_dir / "model.safetensors.index.json").write_text(
            json.dumps(out_index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    missing = [k for k in targets if k not in new_weight_map]
    if missing:
        raise RuntimeError(
            f"Не удалось применить LoRA к {len(missing)} ключам, "
            f"пример: {missing[:3]}"
        )

    tok = tokenizer
    if tok is None:
        tok = AutoTokenizer.from_pretrained(str(adapter_dir), trust_remote_code=True)
    tok.save_pretrained(str(ckpt_dir))

    _log(f"Checkpoint saved: {ckpt_dir} (merged layers={merged_count})")
    return {
        "adapter_dir": str(adapter_dir),
        "checkpoint_dir": str(ckpt_dir),
        "merged": True,
        "merged_tensors": merged_count,
        "method": "on_disk_safetensors",
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

    quant = os.environ.get("ZIPKA_LLAMA_QUANTIZE", "").strip()
    quant_bin = Path(quant) if quant else None
    if quant_bin is None or not quant_bin.is_file():
        for name in ("llama-quantize.exe", "llama-quantize", "quantize.exe", "quantize"):
            found = shutil.which(name)
            if found:
                quant_bin = Path(found)
                break

    # С quantize: HF → f16 → Q4_K_M. Без него: сразу q8_0 (меньше RAM/диска, чем f16).
    if quant_bin and quant_bin.is_file():
        _log(f"Converting with {convert} → f16")
        subprocess.run(
            [
                sys.executable,
                str(convert),
                str(ckpt_dir),
                "--outfile",
                str(f16_path),
                "--outtype",
                "f16",
            ],
            check=True,
        )
        _log(f"Quantizing → Q4_K_M via {quant_bin}")
        subprocess.run(
            [str(quant_bin), str(f16_path), str(out_path), "Q4_K_M"],
            check=True,
        )
        try:
            f16_path.unlink()
        except OSError:
            pass
    else:
        q8_name = Path(out_name).name
        if "Q4_K_M" in q8_name:
            q8_name = q8_name.replace("Q4_K_M", "Q8_0")
        elif q8_name.endswith(".gguf"):
            q8_name = q8_name[:-5] + ".Q8_0.gguf"
        q8_path = models_dir / q8_name
        _log(f"Converting with {convert} → q8_0 (no llama-quantize)")
        subprocess.run(
            [
                sys.executable,
                str(convert),
                str(ckpt_dir),
                "--outfile",
                str(q8_path),
                "--outtype",
                "q8_0",
            ],
            check=True,
        )
        if q8_path.is_file():
            return {
                "ok": True,
                "gguf": q8_path.name,
                "hint": (
                    "Экспорт Q8_0 без llama-quantize. "
                    "Для Q4_K_M собери llama-quantize и задай ZIPKA_LLAMA_QUANTIZE."
                ),
                "checkpoint": str(ckpt_dir),
            }
        return {
            "ok": False,
            "gguf": "",
            "hint": "convert q8_0 прошёл, но выходной GGUF не найден",
            "checkpoint": str(ckpt_dir),
        }

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
    parser.add_argument(
        "--merge-only",
        action="store_true",
        help="Только merge уже сохранённого LoRA-адаптера → checkpoint (после OOM на merge)",
    )
    args = parser.parse_args(argv)
    job_path = Path(args.job)
    data_dir = Path(args.data_dir)
    job = json.loads(job_path.read_text(encoding="utf-8"))

    try:
        if args.merge_only:
            adapter = Path(job["adapter_dir"])
            ckpt = Path(job["checkpoint_dir"])
            train_meta = merge_adapter_to_checkpoint(
                adapter_dir=adapter,
                ckpt_dir=ckpt,
                data_dir=data_dir,
            )
            job["train"] = {**(job.get("train") or {}), **train_meta}
            export = export_gguf(job, data_dir, ckpt)
            job["export"] = export
            job["status"] = "succeeded"
            job.pop("error", None)
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
                    "error": None,
                },
            )
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
                        "error": None,
                    },
                )
                _log(f"Applied lineage: {meta}")
            except Exception as exc:
                _log(f"Lineage apply warning: {exc}")
                traceback.print_exc()
            return 0

        if args.export_only:
            ckpt = Path(job["checkpoint_dir"])
            if not ckpt.is_dir():
                raise RuntimeError(f"Нет checkpoint: {ckpt}")
            export = export_gguf(job, data_dir, ckpt)
            job["export"] = export
            if export.get("ok") and export.get("gguf"):
                job["export_gguf_name"] = export["gguf"]
                job["status"] = "succeeded"
                job.pop("error", None)
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
                    "error": None if job["status"] == "succeeded" else job.get("error"),
                },
            )
            if job["status"] == "succeeded":
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
                            "error": None,
                        },
                    )
                    _log(f"Applied lineage: {meta}")
                except Exception as exc:
                    _log(f"Lineage apply warning: {exc}")
                    traceback.print_exc()
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
                "error": None,
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
                    "error": None,
                },
            )
            _log(f"Applied lineage: {meta}")
        except Exception as exc:
            _log(f"Lineage apply warning: {exc}")
            traceback.print_exc()
        return 0
    except Exception as exc:
        traceback.print_exc()
        err = _exc_text(exc)
        job["status"] = "failed"
        job["error"] = err
        # если адаптер уже есть — подсказка дожать merge без переобучения
        adapter = Path(job.get("adapter_dir") or "")
        if (adapter / "adapter_config.json").is_file():
            job["error"] = (
                err
                + f"\nАдаптер уже сохранён ({adapter}). "
                "Дожми merge без переобучения:\n"
                f'  python -m zipka.evolve.finetune_worker --merge-only '
                f'--job "{job_path}" --data-dir "{data_dir}"'
            )
        from datetime import datetime, timezone

        _write_job(job_path, job)
        _write_status(
            data_dir,
            {
                "state": "failed",
                "phase": "error",
                "error": job["error"],
                "job_id": job.get("id"),
                "job_path": str(job_path),
                "started_at": job.get("started_at"),
                "finished_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
