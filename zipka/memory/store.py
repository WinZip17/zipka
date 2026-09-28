from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from zipka.config import Settings, ensure_data_dirs, get_settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        base = ensure_data_dirs(self.settings)
        self.memory_dir = base / "memory"
        self.notes_path = self.memory_dir / "notes.jsonl"
        self.skills_path = self.memory_dir / "skills.json"
        self.preferences_path = self.memory_dir / "preferences.json"
        self.evolve_log_path = self.memory_dir / "evolve_log.jsonl"
        self.chat_path = self.memory_dir / "chat.jsonl"
        self._ensure_defaults()

    def _ensure_defaults(self) -> None:
        if not self.skills_path.exists():
            self.write_json(
                self.skills_path,
                {
                    "skills": [
                        "диалог",
                        "чтение книг",
                        "изучение исходников",
                        "рефлексия",
                        "самообучение по сети",
                    ]
                },
            )
        if not self.preferences_path.exists():
            self.write_json(
                self.preferences_path,
                {"language": "ru", "tone": "ироничный", "verbosity": "средняя"},
            )

    @staticmethod
    def write_json(path: Path, data: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @staticmethod
    def read_json(path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))

    def append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def add_note(
        self, kind: str, text: str, meta: dict[str, Any] | None = None
    ) -> None:
        self.append_jsonl(
            self.notes_path,
            {"ts": _utc_now(), "kind": kind, "text": text, "meta": meta or {}},
        )

    def recent_notes(
        self, limit: int = 20, kind: str | None = None
    ) -> list[dict[str, Any]]:
        if not self.notes_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.notes_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if kind and row.get("kind") != kind:
                    continue
                rows.append(row)
        return rows[-limit:]

    def get_skills(self) -> list[str]:
        data = self.read_json(self.skills_path, {"skills": []})
        return list(data.get("skills", []))

    def set_skills(self, skills: list[str]) -> None:
        self.write_json(self.skills_path, {"skills": skills})

    def get_preferences(self) -> dict[str, Any]:
        return self.read_json(self.preferences_path, {})

    def set_preferences(self, prefs: dict[str, Any]) -> None:
        self.write_json(self.preferences_path, prefs)

    def log_evolve(self, kind: str, detail: dict[str, Any]) -> None:
        self.append_jsonl(
            self.evolve_log_path,
            {"ts": _utc_now(), "kind": kind, **detail},
        )

    def add_chat(self, role: str, content: str) -> None:
        self.append_jsonl(
            self.chat_path, {"ts": _utc_now(), "role": role, "content": content}
        )

    def recent_chat(self, limit: int = 20) -> list[dict[str, str]]:
        chunk = self.chat_history(limit=limit)
        return [
            {"role": m["role"], "content": m["content"]} for m in chunk["messages"]
        ]

    def chat_history(
        self, *, limit: int = 30, before: int | None = None
    ) -> dict[str, Any]:
        """Пагинация истории: последние `limit` или порция перед индексом `before`."""
        rows: list[dict[str, Any]] = []
        if self.chat_path.exists():
            with self.chat_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    rows.append(
                        {
                            "role": row.get("role", "assistant"),
                            "content": row.get("content", ""),
                            "ts": row.get("ts"),
                        }
                    )
        total = len(rows)
        if before is None:
            end = total
        else:
            end = max(0, min(before, total))
        start = max(0, end - max(1, limit))
        messages = [
            {
                "index": start + i,
                "role": row["role"],
                "content": row["content"],
                "ts": row.get("ts"),
            }
            for i, row in enumerate(rows[start:end])
        ]
        return {
            "messages": messages,
            "total": total,
            "start": start,
            "end": end,
            "has_more": start > 0,
            "oldest_index": start,
        }
