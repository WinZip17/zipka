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
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError):
            return default

    @staticmethod
    def iter_jsonl(path: Path) -> list[dict[str, Any]]:
        """Прочитать JSONL: одна запись на строку; битые строки пропускаем.

        Также терпит pretty-printed объекты (несколько строк на запись).
        """
        if not path.exists():
            return []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        # быстрый путь: классический JSONL
        line_ok = True
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                line_ok = False
                break
            if isinstance(row, dict):
                rows.append(row)
        if line_ok:
            return rows

        # fallback: поток JSON-объектов (pretty-print / ручное редактирование)
        rows = []
        dec = json.JSONDecoder()
        idx = 0
        while idx < len(text):
            while idx < len(text) and text[idx].isspace():
                idx += 1
            if idx >= len(text):
                break
            try:
                obj, end = dec.raw_decode(text, idx)
            except json.JSONDecodeError:
                # пропустить до следующей '{'
                nxt = text.find("{", idx + 1)
                if nxt < 0:
                    break
                idx = nxt
                continue
            if isinstance(obj, dict):
                rows.append(obj)
            idx = end
        return rows

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
        rows = self.iter_jsonl(self.notes_path)
        if kind:
            rows = [row for row in rows if row.get("kind") == kind]
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

    def add_chat(
        self,
        role: str,
        content: str,
        *,
        reply_to: dict[str, Any] | None = None,
    ) -> None:
        row: dict[str, Any] = {
            "ts": _utc_now(),
            "role": role,
            "content": content,
        }
        if reply_to:
            row["reply_to"] = {
                "role": reply_to.get("role"),
                "content": str(reply_to.get("content") or "")[:4000],
            }
            if reply_to.get("ts"):
                row["reply_to"]["ts"] = reply_to["ts"]
        self.append_jsonl(self.chat_path, row)

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
        for row in self.iter_jsonl(self.chat_path):
            item: dict[str, Any] = {
                "role": row.get("role", "assistant"),
                "content": row.get("content", ""),
                "ts": row.get("ts"),
            }
            if isinstance(row.get("reply_to"), dict):
                item["reply_to"] = row["reply_to"]
            rows.append(item)
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
                **({"reply_to": row["reply_to"]} if row.get("reply_to") else {}),
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
