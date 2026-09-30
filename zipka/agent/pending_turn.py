"""Серверный статус незавершённого хода чата (для UI после reload)."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PHASE_LABELS: dict[str, str] = {
    "replying": "Вникаю…",
    "reading": "Читаю…",
    "studying": "Изучаю…",
    "looking": "Смотрю…",
    "listening": "Слушаю…",
    "learning": "Учусь…",
    "news": "Читаю новости…",
    "applying": "Применяю…",
}


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PendingTurnTracker:
    """In-memory + файл: статус виден после F5, пока жив процесс / идёт ход."""

    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._path = path
        self._state: dict[str, Any] | None = None
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if not self._path or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict) and data.get("id") and not data.get("assistant_saved"):
            self._state = data

    def _persist_unlocked(self) -> None:
        if not self._path:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            if self._state and not self._state.get("assistant_saved"):
                self._path.write_text(
                    json.dumps(self._state, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            elif self._path.exists():
                self._path.unlink(missing_ok=True)
        except OSError:
            pass

    def begin(
        self,
        *,
        user_text: str,
        phase: str = "replying",
        label: str | None = None,
        kind: str = "chat",
        reply_to: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            state = {
                "id": uuid.uuid4().hex[:12],
                "kind": kind,
                "phase": phase,
                "label": label or PHASE_LABELS.get(phase, "Думаю…"),
                "user_text": (user_text or "")[:2000],
                "reply_to": reply_to,
                "user_saved": False,
                "assistant_saved": False,
                "started_at": _utc_iso(),
            }
            self._state = state
            self._persist_unlocked()
            return {
                "id": state["id"],
                "kind": state["kind"],
                "phase": state["phase"],
                "label": state["label"],
            }

    def set_phase(self, phase: str, label: str | None = None) -> None:
        with self._lock:
            if not self._state:
                return
            self._state["phase"] = phase
            self._state["label"] = label or PHASE_LABELS.get(
                phase, self._state.get("label") or "Думаю…"
            )
            self._persist_unlocked()

    def mark_user_saved(self) -> None:
        with self._lock:
            if self._state:
                self._state["user_saved"] = True
                self._persist_unlocked()

    def mark_assistant_saved(self) -> None:
        with self._lock:
            if self._state:
                self._state["assistant_saved"] = True
                self._persist_unlocked()

    def user_saved(self) -> bool:
        with self._lock:
            return bool(self._state and self._state.get("user_saved"))

    def assistant_saved(self) -> bool:
        with self._lock:
            return bool(self._state and self._state.get("assistant_saved"))

    def active(self) -> bool:
        with self._lock:
            return self._state is not None and not self._state.get("assistant_saved")

    def snapshot(self) -> dict[str, Any] | None:
        with self._lock:
            # Перечитать диск: F5/другой поток мог опереться на файл
            if self._path and self._path.exists():
                try:
                    data = json.loads(self._path.read_text(encoding="utf-8"))
                    if (
                        isinstance(data, dict)
                        and data.get("id")
                        and not data.get("assistant_saved")
                    ):
                        self._state = data
                except (OSError, json.JSONDecodeError):
                    pass
            if not self._state or self._state.get("assistant_saved"):
                return None
            s = self._state
            return {
                "id": s["id"],
                "kind": s.get("kind") or "chat",
                "phase": s.get("phase") or "replying",
                "label": s.get("label") or "Думаю…",
                "user_text": s.get("user_text") or "",
                "started_at": s.get("started_at"),
                "user_saved": bool(s.get("user_saved")),
            }

    def clear(self) -> None:
        with self._lock:
            self._state = None
            self._persist_unlocked()
