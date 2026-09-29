"""Дообучение чатовой модели на диалогах Зипки: LoRA → merge → новый GGUF.

Цикл (альтернатива «просто сохранись» в память):
1. Собрать пары user/assistant из chat.jsonl
2. LoRA поверх HF-базы (или прошлого merge-чекпоинта)
3. Merge → data/finetune/checkpoints/gen_N
4. Экспорт GGUF → data/models/zipka-self-genN-*.gguf
5. Переключить chat_gguf на новый файл
6. Следующий круг стартует с checkpoint gen_N

Обучение идёт в отдельном процессе (см. finetune_worker), чтобы не держать
torch в основном процессе чата. Нужно: pip install -e \".[finetune]\"
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.llm.chat_models import active_gguf_name
from zipka.memory.store import MemoryStore
from zipka.runtime_settings import load_runtime, save_runtime

APPROVE_PHRASE = "разрешаю дообучение"
APPROVE_PHRASES = {
    APPROVE_PHRASE,
    "разрешаю дообучить",
    "разрешаю сохранить в модель",
}

# Подстрока имени GGUF → HF base для первого поколения
HF_BASE_BY_GGUF_HINT: list[tuple[str, str, str]] = [
    ("qwen2.5-7b-instruct", "Qwen/Qwen2.5-7B-Instruct", "qwen25"),
    ("qwen2.5-7b", "Qwen/Qwen2.5-7B-Instruct", "qwen25"),
    ("qwen3-8b", "Qwen/Qwen3-8B", "qwen3"),
    ("qwen3", "Qwen/Qwen3-8B", "qwen3"),
    # Pathfinder — только GGUF; без локального HF лучше дообучать Qwen
    ("pathfinder", "", "pathfinder"),
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_hf_base_for_gguf(gguf_name: str) -> dict[str, Any]:
    low = Path(gguf_name).name.lower()
    for hint, hf_id, family in HF_BASE_BY_GGUF_HINT:
        if hint in low:
            return {
                "gguf": Path(gguf_name).name,
                "hf_id": hf_id,
                "family": family,
                "ok": bool(hf_id),
                "hint": (
                    None
                    if hf_id
                    else (
                        "Для Pathfinder нет открытого HF-оригинала в каталоге. "
                        "Поставь chat на Qwen2.5/Qwen3 или укажи свой hf_base "
                        "в data/finetune/lineage.json → \"override_hf_base\"."
                    )
                ),
            }
    return {
        "gguf": Path(gguf_name).name,
        "hf_id": "",
        "family": "unknown",
        "ok": False,
        "hint": "Неизвестная GGUF — укажи override_hf_base в lineage.json",
    }


class FinetuneEvolve:
    """Очередь дообучения с явным approve (как hard-evolve)."""

    def __init__(
        self,
        memory: MemoryStore,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.memory = memory
        self.root = self.settings.data_dir / "finetune"
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "datasets").mkdir(exist_ok=True)
        (self.root / "adapters").mkdir(exist_ok=True)
        (self.root / "checkpoints").mkdir(exist_ok=True)
        (self.root / "jobs").mkdir(exist_ok=True)
        self.lineage_path = self.root / "lineage.json"
        self.pending_path = self.root / "pending.json"
        self.status_path = self.root / "status.json"
        self._lock = threading.Lock()

    # --- phrases ---

    @staticmethod
    def is_approve(text: str) -> bool:
        return text.strip().lower() in APPROVE_PHRASES

    @staticmethod
    def wants_finetune(text: str) -> bool:
        low = text.lower().strip()
        keys = (
            "дообучись",
            "дообучи себя",
            "дообучить модель",
            "сохранись в модель",
            "сохрани себя в модель",
            "сохрани себя в gguf",
            "сохранись в gguf",
            "сохрани опыт в модель",
            "сохрани опыт в gguf",
            "lora",
            "fine-tune",
            "finetune",
            "запусти дообучение",
        )
        if any(k in low for k in keys):
            return True
        # короткое «сохранись» — только если нет soft-evolve контекста навыков
        if re.fullmatch(r"сохранись!?", low):
            return True
        return False

    def load_lineage(self) -> dict[str, Any]:
        if not self.lineage_path.exists():
            return {
                "generation": 0,
                "override_hf_base": "",
                "history": [],
                "active_checkpoint": "",
                "active_gguf": "",
            }
        try:
            data = json.loads(self.lineage_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"generation": 0, "override_hf_base": "", "history": []}
        if not isinstance(data, dict):
            return {"generation": 0, "override_hf_base": "", "history": []}
        data.setdefault("generation", 0)
        data.setdefault("override_hf_base", "")
        data.setdefault("history", [])
        return data

    def save_lineage(self, data: dict[str, Any]) -> None:
        self.lineage_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def load_pending(self) -> dict[str, Any] | None:
        if not self.pending_path.exists():
            return None
        try:
            return json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def clear_pending(self) -> None:
        if self.pending_path.exists():
            self.pending_path.unlink()

    def has_pending(self) -> bool:
        return self.pending_path.exists()

    def load_status(self) -> dict[str, Any]:
        if not self.status_path.exists():
            return {"state": "idle"}
        try:
            return json.loads(self.status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"state": "idle"}

    def _write_status(self, data: dict[str, Any]) -> None:
        data = {**data, "updated_at": _utc_now()}
        self.status_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def build_dataset(
        self,
        *,
        min_pairs: int = 8,
        max_pairs: int = 400,
        since_ts: str | None = None,
    ) -> dict[str, Any]:
        """Собрать JSONL диалогов (alpaca-подобно: instruction/output)."""
        hist = self.memory.chat_history(limit=5000)
        messages = hist.get("messages") or []
        pairs: list[dict[str, str]] = []
        i = 0
        while i < len(messages) - 1:
            a, b = messages[i], messages[i + 1]
            if since_ts:
                ts = str(a.get("ts") or "")
                if ts and ts < since_ts:
                    i += 1
                    continue
            if a.get("role") == "user" and b.get("role") == "assistant":
                user = str(a.get("content") or "").strip()
                bot = str(b.get("content") or "").strip()
                # отфильтровать служебные approve/патчи
                skip_markers = (
                    "разрешаю правку",
                    "разрешаю дообучен",
                    "патч ",
                    "[soft-evolve]",
                )
                if user and bot and not any(m in user.lower() for m in skip_markers):
                    if len(user) >= 2 and len(bot) >= 8:
                        pairs.append(
                            {
                                "instruction": user[:4000],
                                "input": "",
                                "output": bot[:6000],
                            }
                        )
                i += 2
                continue
            i += 1

        if len(pairs) > max_pairs:
            pairs = pairs[-max_pairs:]

        gen = int(self.load_lineage().get("generation") or 0) + 1
        ds_path = self.root / "datasets" / f"gen_{gen:04d}.jsonl"
        with ds_path.open("w", encoding="utf-8") as f:
            for row in pairs:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        return {
            "path": str(ds_path),
            "pairs": len(pairs),
            "min_pairs": min_pairs,
            "enough": len(pairs) >= min_pairs,
            "generation": gen,
        }

    def resolve_train_base(self) -> dict[str, Any]:
        lineage = self.load_lineage()
        override = str(lineage.get("override_hf_base") or "").strip()
        active_ckpt = str(lineage.get("active_checkpoint") or "").strip()
        if active_ckpt and Path(active_ckpt).is_dir():
            return {
                "kind": "checkpoint",
                "path": active_ckpt,
                "hf_id": "",
                "ok": True,
                "hint": None,
            }
        if override:
            p = Path(override)
            if p.is_dir():
                return {
                    "kind": "checkpoint",
                    "path": str(p),
                    "hf_id": "",
                    "ok": True,
                    "hint": None,
                }
            return {
                "kind": "hub",
                "path": "",
                "hf_id": override,
                "ok": True,
                "hint": None,
            }

        gguf = active_gguf_name("chat", self.settings)
        info = resolve_hf_base_for_gguf(gguf)
        if not info["ok"]:
            return {
                "kind": "hub",
                "path": "",
                "hf_id": "",
                "ok": False,
                "hint": info.get("hint"),
                "gguf": gguf,
            }
        return {
            "kind": "hub",
            "path": "",
            "hf_id": info["hf_id"],
            "ok": True,
            "hint": None,
            "gguf": gguf,
            "family": info.get("family"),
        }

    def propose(
        self,
        *,
        max_steps: int = 60,
        lora_r: int = 8,
        max_seq_len: int = 512,
        min_pairs: int = 8,
    ) -> dict[str, Any]:
        status = self.load_status()
        if status.get("state") == "running":
            raise RuntimeError(
                "Дообучение уже идёт. Статус: "
                + json.dumps(status, ensure_ascii=False)[:400]
            )

        ds = self.build_dataset(min_pairs=min_pairs)
        if not ds["enough"]:
            raise RuntimeError(
                f"Мало диалогов для дообучения: {ds['pairs']} пар "
                f"(нужно ≥ {min_pairs}). Поговори ещё, потом снова «дообучись»."
            )

        base = self.resolve_train_base()
        if not base.get("ok"):
            raise RuntimeError(base.get("hint") or "Нет HF-базы для LoRA")

        job_id = (
            datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            + "-"
            + uuid.uuid4().hex[:8]
        )
        gen = int(ds["generation"])
        pending = {
            "id": job_id,
            "generation": gen,
            "created_at": _utc_now(),
            "status": "pending_approval",
            "dataset": ds["path"],
            "pairs": ds["pairs"],
            "base": base,
            "params": {
                "max_steps": max_steps,
                "lora_r": lora_r,
                "max_seq_len": max_seq_len,
                "batch_size": 1,
                "grad_accum": 4,
                "learning_rate": 2e-4,
            },
            "adapter_dir": str(self.root / "adapters" / f"gen_{gen:04d}"),
            "checkpoint_dir": str(self.root / "checkpoints" / f"gen_{gen:04d}"),
            "export_gguf_name": f"zipka-self-gen{gen:04d}.Q4_K_M.gguf",
        }
        self.pending_path.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.memory.log_evolve(
            "finetune_propose",
            {
                "id": job_id,
                "generation": gen,
                "pairs": ds["pairs"],
                "base": base,
            },
        )
        return pending

    def format_pending(self, pending: dict[str, Any] | None = None) -> str:
        pending = pending or self.load_pending()
        if not pending:
            return "Нет ожидающего дообучения."
        base = pending.get("base") or {}
        base_desc = base.get("path") or base.get("hf_id") or "?"
        return "\n".join(
            [
                f"Дообучение {pending['id']} ждёт approve (сохранение опыта в GGUF).",
                f"Поколение: {pending.get('generation')}",
                f"Пар диалогов: {pending.get('pairs')}",
                f"База: {base.get('kind')} → {base_desc}",
                f"Выход: data/models/{pending.get('export_gguf_name')}",
                f"Параметры: {json.dumps(pending.get('params') or {}, ensure_ascii=False)}",
                "",
                "Это долгий процесс (минуты–часы, нужна VRAM). Чат на время обучения "
                "может тормозить, если GPU один.",
                f"Чтобы запустить, напиши точно: {APPROVE_PHRASE}",
            ]
        )

    def start_approved(self) -> dict[str, Any]:
        pending = self.load_pending()
        if not pending:
            raise RuntimeError("Нет ожидающего дообучения.")
        with self._lock:
            st = self.load_status()
            if st.get("state") == "running":
                raise RuntimeError("Уже запущено.")
            job = dict(pending)
            job["status"] = "running"
            job["started_at"] = _utc_now()
            job_path = self.root / "jobs" / f"{job['id']}.json"
            job_path.write_text(
                json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._write_status(
                {
                    "state": "running",
                    "job_id": job["id"],
                    "generation": job.get("generation"),
                    "phase": "starting",
                    "job_path": str(job_path),
                }
            )
            self.clear_pending()

        log_path = self.root / "jobs" / f"{job['id']}.log"
        worker_cmd = [
            sys.executable,
            "-m",
            "zipka.evolve.finetune_worker",
            "--job",
            str(job_path),
            "--data-dir",
            str(self.settings.data_dir),
        ]
        # DETACHED on Windows so UI process isn't tied forever
        kwargs: dict[str, Any] = {
            "stdout": log_path.open("w", encoding="utf-8"),
            "stderr": subprocess.STDOUT,
            "cwd": str(Path(__file__).resolve().parents[2]),
        }
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        proc = subprocess.Popen(worker_cmd, **kwargs)
        self._write_status(
            {
                "state": "running",
                "job_id": job["id"],
                "generation": job.get("generation"),
                "phase": "subprocess",
                "pid": proc.pid,
                "log": str(log_path),
                "job_path": str(job_path),
            }
        )
        self.memory.log_evolve(
            "finetune_start",
            {"id": job["id"], "pid": proc.pid, "generation": job.get("generation")},
        )
        return {
            "ok": True,
            "job_id": job["id"],
            "pid": proc.pid,
            "log": str(log_path),
            "message": (
                f"Дообучение запущено (pid {proc.pid}). "
                f"Лог: {log_path}. Статус: zipka finetune status"
            ),
        }

    def apply_success_from_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Вызывается воркером/статусом: обновить lineage + runtime chat_gguf."""
        lineage = self.load_lineage()
        gen = int(job.get("generation") or (int(lineage.get("generation") or 0) + 1))
        gguf_name = job.get("export_gguf_name") or f"zipka-self-gen{gen:04d}.Q4_K_M.gguf"
        gguf_path = self.settings.data_dir / "models" / gguf_name
        ckpt = job.get("checkpoint_dir") or ""
        entry = {
            "generation": gen,
            "job_id": job.get("id"),
            "finished_at": _utc_now(),
            "checkpoint": ckpt,
            "gguf": gguf_name if gguf_path.is_file() else "",
            "pairs": job.get("pairs"),
            "base": job.get("base"),
        }
        history = list(lineage.get("history") or [])
        history.append(entry)
        lineage["generation"] = gen
        lineage["history"] = history[-50:]
        if ckpt and Path(ckpt).is_dir():
            lineage["active_checkpoint"] = ckpt
        if gguf_path.is_file():
            lineage["active_gguf"] = gguf_name
            save_runtime({"chat_gguf": gguf_name}, self.settings)
        self.save_lineage(lineage)
        return {
            "generation": gen,
            "gguf": lineage.get("active_gguf"),
            "checkpoint": lineage.get("active_checkpoint"),
            "switched": gguf_path.is_file(),
        }

    def refresh_job_status(self) -> dict[str, Any]:
        """Прочитать status.json / job file после работы воркера."""
        st = self.load_status()
        job_path = st.get("job_path")
        if job_path and Path(job_path).is_file():
            try:
                job = json.loads(Path(job_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                job = None
            if job and job.get("status") == "succeeded" and st.get("state") != "done":
                meta = self.apply_success_from_job(job)
                self._write_status(
                    {
                        "state": "done",
                        "job_id": job.get("id"),
                        "generation": meta.get("generation"),
                        "result": meta,
                        "job_path": job_path,
                    }
                )
                return self.load_status()
            if job and job.get("status") == "failed":
                self._write_status(
                    {
                        "state": "failed",
                        "job_id": job.get("id"),
                        "error": job.get("error"),
                        "job_path": job_path,
                    }
                )
        return self.load_status()
