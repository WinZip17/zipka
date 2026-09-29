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
import os
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


def _is_pid_alive(pid: Any) -> bool:
    """Проверка, жив ли процесс (без сигнала kill)."""
    try:
        pid_i = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_i <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid_i)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        kernel32.CloseHandle(handle)
        if not ok:
            return False
        # STILL_ACTIVE = 259
        return int(exit_code.value) == 259
    try:
        os.kill(pid_i, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _tail_text(path: Path | str | None, *, max_chars: int = 2500) -> str:
    if not path:
        return ""
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    raw = raw.strip()
    if len(raw) <= max_chars:
        return raw
    return raw[-max_chars:]


def _crash_message_from_log(log_path: Any, *, pid: Any = None) -> str:
    """Человекочитаемая причина, если воркер умер без status=failed (OOM/abort)."""
    tail = _tail_text(log_path)
    low = tail.lower()
    pid_s = f" (pid {pid})" if pid is not None else ""
    if any(
        x in low
        for x in (
            "memory allocation",
            "out of memory",
            "oom",
            "cuda out of memory",
            "not enough memory",
            "std::bad_alloc",
        )
    ):
        return (
            f"Воркер дообучения упал из-за нехватки памяти{pid_s}. "
            "Qwen3-8B на CPU без 4-bit нужен большой запас RAM; "
            "лучше GPU + bitsandbytes, либо меньшая HF-база / освободить память. "
            "Можно снова «Подготовить»."
            + (f"\n\nЛог:\n{tail[-900:]}" if tail else "")
        )
    if tail:
        last_lines = "\n".join(tail.splitlines()[-12:])
        return (
            f"Воркер дообучения завершился аварийно{pid_s}. "
            "Можно снова «Подготовить»."
            f"\n\nХвост лога:\n{last_lines}"
        )
    return (
        f"Процесс дообучения прерван{pid_s}: pid не найден. "
        "Можно снова нажать «Подготовить»."
    )


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

    def is_running(self) -> bool:
        """True, пока статус job = running (даже если процесс уже убит — до refresh)."""
        return self.load_status().get("state") == "running"

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

    def _identity_examples(self) -> list[dict[str, str]]:
        """Синтетические пары из persona / skills / preferences."""
        from zipka.character.persona import Persona

        examples: list[dict[str, str]] = []
        try:
            persona = Persona(self.settings).load()
        except Exception:
            persona = {}

        skills = self.memory.get_skills()
        prefs = self.memory.get_preferences() or {}

        name = str(persona.get("name") or "Зипка")
        name_en = str(persona.get("name_en") or "Zipka")
        summary = str(persona.get("summary") or "").strip()
        traits = [str(t) for t in (persona.get("traits") or []) if str(t).strip()]
        style = [str(s) for s in (persona.get("style") or []) if str(s).strip()]
        taboos = [str(t) for t in (persona.get("taboos") or []) if str(t).strip()]
        goals = [str(g) for g in (persona.get("goals_seed") or []) if str(g).strip()]

        if summary:
            examples.append(
                {
                    "instruction": "Кто ты? Расскажи о себе коротко.",
                    "input": "",
                    "output": (
                        f"Я — {name} ({name_en}). {summary}"
                    )[:6000],
                }
            )
        if traits:
            examples.append(
                {
                    "instruction": "Какие у тебя черты характера?",
                    "input": "",
                    "output": (
                        f"Мои черты: {', '.join(traits)}. "
                        f"Я остаюсь собой — {name}, не сервильный ассистент."
                    )[:6000],
                }
            )
        if style:
            style_body = "\n".join(f"- {s}" for s in style[:12])
            examples.append(
                {
                    "instruction": "Как ты обычно отвечаешь? Какой у тебя стиль?",
                    "input": "",
                    "output": (
                        f"Держусь такого стиля:\n{style_body}"
                    )[:6000],
                }
            )
        if taboos:
            taboo_body = "\n".join(f"- {t}" for t in taboos[:10])
            examples.append(
                {
                    "instruction": "Чего ты принципиально не делаешь?",
                    "input": "",
                    "output": (
                        f"Табу для меня:\n{taboo_body}"
                    )[:6000],
                }
            )
        if goals:
            examples.append(
                {
                    "instruction": "Какие у тебя цели?",
                    "input": "",
                    "output": (
                        "Мои цели: " + "; ".join(goals[:10])
                    )[:6000],
                }
            )

        # закрепление женского рода
        examples.append(
            {
                "instruction": "Ты рад меня видеть?",
                "input": "",
                "output": (
                    f"Рада! Я — {name}, говорю о себе только в женском роде: "
                    "рада, поняла, сделала, готова — не «рад/понял/сделал»."
                ),
            }
        )

        if skills:
            skill_list = ", ".join(str(s) for s in skills if str(s).strip())
            if skill_list:
                examples.append(
                    {
                        "instruction": "Какие у тебя навыки?",
                        "input": "",
                        "output": (
                            f"Мои навыки: {skill_list}. "
                            "Могу развивать их через soft-evolve и практику."
                        )[:6000],
                    }
                )
                examples.append(
                    {
                        "instruction": "Что ты умеешь делать?",
                        "input": "",
                        "output": (
                            f"Умею: {skill_list}. "
                            "Если чего-то не хватает — учусь и запоминаю."
                        )[:6000],
                    }
                )

        if prefs:
            pref_bits = [
                f"{k}={v}" for k, v in prefs.items() if v is not None and str(v).strip()
            ]
            if pref_bits:
                pref_line = ", ".join(pref_bits)
                examples.append(
                    {
                        "instruction": "Какие у тебя предпочтения в общении?",
                        "input": "",
                        "output": (
                            f"Мои предпочтения: {pref_line}. "
                            "Стараюсь держать этот тон в ответах."
                        )[:6000],
                    }
                )
                # отдельный вопрос по тону, если есть
                tone = prefs.get("tone") or prefs.get("language")
                if tone:
                    examples.append(
                        {
                            "instruction": "В каком тоне лучше со мной говорить?",
                            "input": "",
                            "output": (
                                f"Ориентируюсь на предпочтения: {pref_line}."
                            )[:6000],
                        }
                    )

        return examples

    def build_dataset(
        self,
        *,
        min_pairs: int = 8,
        max_pairs: int = 400,
        since_ts: str | None = None,
    ) -> dict[str, Any]:
        """Собрать JSONL: чат + persona/skills/preferences."""
        hist = self.memory.chat_history(limit=5000)
        messages = hist.get("messages") or []
        chat_pairs: list[dict[str, str]] = []
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
                        chat_pairs.append(
                            {
                                "instruction": user[:4000],
                                "input": "",
                                "output": bot[:6000],
                            }
                        )
                i += 2
                continue
            i += 1

        if len(chat_pairs) > max_pairs:
            chat_pairs = chat_pairs[-max_pairs:]

        identity = self._identity_examples()
        # identity в начале — сильнее якорь личности, затем диалоги
        pairs = [*identity, *chat_pairs]

        gen = int(self.load_lineage().get("generation") or 0) + 1
        ds_path = self.root / "datasets" / f"gen_{gen:04d}.jsonl"
        with ds_path.open("w", encoding="utf-8") as f:
            for row in pairs:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

        return {
            "path": str(ds_path),
            "pairs": len(pairs),
            "chat_pairs": len(chat_pairs),
            "identity_pairs": len(identity),
            "min_pairs": min_pairs,
            "enough": len(chat_pairs) >= min_pairs,
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
                f"Мало диалогов для дообучения: {ds['chat_pairs']} пар чата "
                f"(нужно ≥ {min_pairs}; persona/skills/prefs дают ещё "
                f"{ds.get('identity_pairs', 0)} примеров). "
                "Поговори ещё, потом снова «дообучись»."
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
            "chat_pairs": ds.get("chat_pairs"),
            "identity_pairs": ds.get("identity_pairs"),
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
                (
                    f"Примеров: {pending.get('pairs')} "
                    f"(чат {pending.get('chat_pairs', '?')} + "
                    f"persona/skills/prefs {pending.get('identity_pairs', '?')})"
                ),
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
                    "started_at": job["started_at"],
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
                "started_at": job["started_at"],
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
        """Прочитать status.json / job file после работы воркера.

        Если state=running, а pid мёртв — пометить interrupted (после Ctrl+C / kill).
        """
        st = self.load_status()
        job_path = st.get("job_path")
        job: dict[str, Any] | None = None
        if job_path and Path(job_path).is_file():
            try:
                job = json.loads(Path(job_path).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                job = None

        if job and job.get("status") == "succeeded" and st.get("state") != "done":
            meta = self.apply_success_from_job(job)
            finished = job.get("finished_at") or _utc_now()
            self._write_status(
                {
                    "state": "done",
                    "job_id": job.get("id"),
                    "generation": meta.get("generation"),
                    "result": meta,
                    "job_path": job_path,
                    "started_at": st.get("started_at") or job.get("started_at"),
                    "finished_at": finished,
                    "phase": st.get("phase") or "finished",
                    "log": st.get("log"),
                }
            )
            return self.load_status()

        if job and job.get("status") == "failed" and st.get("state") == "running":
            finished = job.get("finished_at") or _utc_now()
            self._write_status(
                {
                    "state": "failed",
                    "job_id": job.get("id"),
                    "error": job.get("error"),
                    "job_path": job_path,
                    "phase": st.get("phase"),
                    "started_at": st.get("started_at") or job.get("started_at"),
                    "finished_at": finished,
                    "log": st.get("log"),
                    "pid": st.get("pid"),
                }
            )
            return self.load_status()

        if st.get("state") == "running":
            # подтянуть started_at из job, если в status нет (старые запуски)
            if not st.get("started_at") and job and job.get("started_at"):
                st = {**st, "started_at": job["started_at"]}
                self._write_status(
                    {
                        **{k: v for k, v in st.items() if k != "updated_at"},
                        "started_at": job["started_at"],
                    }
                )
                st = self.load_status()
            pid = st.get("pid")
            if pid is not None and not _is_pid_alive(pid):
                return self._mark_interrupted(
                    st,
                    job=job,
                    error=_crash_message_from_log(st.get("log"), pid=pid),
                    state="failed",
                )
            if pid is None and (not job or job.get("status") == "running"):
                # зависший статус без pid / без финала
                return self._mark_interrupted(
                    st,
                    job=job,
                    error=_crash_message_from_log(st.get("log"), pid=None),
                    state="failed",
                )

        return self.load_status()

    def _mark_interrupted(
        self,
        st: dict[str, Any],
        *,
        job: dict[str, Any] | None,
        error: str,
        state: str = "interrupted",
    ) -> dict[str, Any]:
        job_path = st.get("job_path")
        finished = _utc_now()
        if job and job_path and Path(str(job_path)).is_file():
            if job.get("status") == "running":
                job = dict(job)
                job["status"] = "failed"
                job["error"] = error
                job["finished_at"] = finished
                try:
                    Path(str(job_path)).write_text(
                        json.dumps(job, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                except OSError:
                    pass
        self._write_status(
            {
                "state": state,
                "job_id": st.get("job_id"),
                "generation": st.get("generation"),
                "phase": st.get("phase"),
                "pid": st.get("pid"),
                "log": st.get("log"),
                "job_path": job_path,
                "error": error,
                "started_at": st.get("started_at")
                or (job or {}).get("started_at"),
                "finished_at": finished,
            }
        )
        return self.load_status()

    def abort_running(self, *, kill: bool = True) -> dict[str, Any]:
        """Прервать/сбросить зависшее или идущее дообучение."""
        with self._lock:
            st = self.refresh_job_status()
            if st.get("state") != "running":
                # уже не running после refresh (interrupted/failed/done)
                return {
                    "ok": True,
                    "status": st,
                    "message": (
                        f"Сейчас state={st.get('state')}. "
                        + (str(st.get("error") or "")).strip()
                    ).strip(),
                }
            pid = st.get("pid")
            killed = False
            if kill and pid is not None and _is_pid_alive(pid):
                try:
                    if sys.platform == "win32":
                        subprocess.run(
                            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
                            check=False,
                            capture_output=True,
                            text=True,
                        )
                    else:
                        os.kill(int(pid), 15)
                    killed = True
                except OSError as exc:
                    return {
                        "ok": False,
                        "status": st,
                        "message": f"Не удалось остановить pid {pid}: {exc}",
                    }
            job = None
            job_path = st.get("job_path")
            if job_path and Path(str(job_path)).is_file():
                try:
                    job = json.loads(Path(str(job_path)).read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    job = None
            st2 = self._mark_interrupted(
                st,
                job=job,
                error=(
                    f"Дообучение прервано вручную"
                    + (f" (pid {pid})" if pid else "")
                    + ("." if killed or not pid else " — процесс уже не работал.")
                ),
                state="interrupted",
            )
            return {
                "ok": True,
                "killed": killed,
                "status": st2,
                "message": st2.get("error") or "Сброшено.",
            }
