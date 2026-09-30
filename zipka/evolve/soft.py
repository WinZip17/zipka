"""Мягкая самоэволюция: persona / skills / preferences / notes."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from zipka.character.persona import Persona
from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.memory.store import MemoryStore
from zipka.runtime_settings import load_runtime

SOFT_MARKER = "[[SOFT_EVOLVE]]"
APPROVE_PHRASE = "запомни это"
APPROVE_PHRASES = {
    APPROVE_PHRASE,
    "запомни это.",
    "разрешаю soft-evolve",
    "разрешаю soft evolve",
    "да, запомни",
    "да запомни",
    "ок, запомни",
    "ок запомни",
    "хорошо, запомни",
}
DECLINE_PHRASES = {
    "не запоминай",
    "не надо soft",
    "отмена soft",
    "отмени soft",
    "не сохраняй soft",
}

# не чаще раза в N ходов чата
DIALOGUE_EVERY_TURNS = 6
MIN_USER_CHARS = 36
MIN_REPLY_CHARS = 40


class SoftEvolve:
    """Мягкая самоэволюция: persona / skills / preferences / notes."""

    def __init__(
        self,
        persona: Persona,
        memory: MemoryStore,
        llm: Any,
        settings: Settings | None = None,
    ) -> None:
        self.persona = persona
        self.memory = memory
        self.llm = llm
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.pending_path = self.settings.data_dir / "mind" / "soft_pending.json"
        self._turns_since_propose = 0

    def dialogue_enabled(self) -> bool:
        try:
            return bool(load_runtime(self.settings).get("soft_evolve_from_dialogue"))
        except Exception:
            return False

    def is_approve(self, text: str) -> bool:
        return text.strip().lower() in APPROVE_PHRASES

    def is_decline(self, text: str) -> bool:
        low = text.strip().lower()
        return low in DECLINE_PHRASES or low.startswith("не запоминай")

    def has_pending(self) -> bool:
        return self.pending_path.is_file()

    def load_pending(self) -> dict[str, Any] | None:
        if not self.pending_path.is_file():
            return None
        try:
            data = json.loads(self.pending_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def clear_pending(self) -> None:
        try:
            self.pending_path.unlink(missing_ok=True)
        except OSError:
            pass

    def save_pending(self, change: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "change": change,
        }
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return payload

    def format_pending(self, pending: dict[str, Any] | None = None) -> str:
        pending = pending or self.load_pending()
        if not pending:
            return "Нет предложения soft-evolve."
        change = pending.get("change") or {}
        reason = str(change.get("reason") or "уточнить себя по диалогу").strip()
        bits: list[str] = []
        if change.get("persona_patch"):
            bits.append(f"persona: {change['persona_patch']}")
        if change.get("skills_add"):
            bits.append("навыки: " + ", ".join(str(s) for s in change["skills_add"]))
        if change.get("preferences_patch"):
            bits.append(f"предпочтения: {change['preferences_patch']}")
        if change.get("note"):
            bits.append(f"заметка: {change['note']}")
        detail = "; ".join(bits) if bits else "(без деталей)"
        return (
            f"Могу запомнить из диалога: {reason}\n"
            f"{detail}\n"
            f"Если ок — напиши «{APPROVE_PHRASE}». "
            "Если не нужно — «не запоминай»."
        )

    def mark_pending_shown(self) -> None:
        pending = self.load_pending()
        if not pending or pending.get("shown"):
            return
        pending["shown"] = True
        try:
            self.pending_path.write_text(
                json.dumps(pending, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def pending_offer_once(self) -> str | None:
        """Текст предложения для следующего ответа (один раз)."""
        pending = self.load_pending()
        if not pending or pending.get("shown"):
            return None
        text = self.format_pending(pending)
        self.mark_pending_shown()
        return text

    def apply_pending(self) -> dict[str, Any]:
        pending = self.load_pending()
        if not pending:
            raise RuntimeError("Нет pending soft-evolve")
        change = dict(pending.get("change") or {})
        change["apply"] = True
        applied = self.apply(change)
        self.clear_pending()
        return applied

    def should_consider_dialogue(
        self,
        user_text: str,
        assistant_text: str,
        *,
        skip: bool = False,
    ) -> bool:
        if skip or not self.dialogue_enabled():
            return False
        if self.has_pending():
            return False
        if not getattr(self.llm, "is_available", lambda: False)():
            return False
        user = (user_text or "").strip()
        reply = (assistant_text or "").strip()
        if len(user) < MIN_USER_CHARS or len(reply) < MIN_REPLY_CHARS:
            return False
        # служебные / слишком короткие команды не анализируем
        low = user.lower()
        if any(
            k in low
            for k in (
                "разрешаю правку",
                "разрешаю дообуч",
                "обнови новости",
                "запомни это",
                "не запоминай",
            )
        ):
            return False
        self._turns_since_propose += 1
        if self._turns_since_propose < DIALOGUE_EVERY_TURNS:
            return False
        return True

    def propose_from_dialogue(
        self, user_text: str, assistant_text: str
    ) -> dict[str, Any] | None:
        """Анализ диалога → pending (без apply). None если менять нечего."""
        prompt = (
            "Проанализируй диалог. Если Зипке полезно обновить характер, навыки "
            "или предпочтения — верни ТОЛЬКО JSON вида:\n"
            '{"apply": true, "reason": "...", "persona_patch": {}, '
            '"skills_add": [], "preferences_patch": {}, "note": ""}\n'
            "Если менять нечего: {\"apply\": false}\n"
            "Не предлагай правки кода. persona_patch — только осмысленные поля "
            "(traits/style/summary/taboos), без мусора.\n"
            f"USER: {user_text}\nZIPKA: {assistant_text}"
        )
        try:
            raw = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": "Ты модуль soft-evolve. Отвечай только JSON.",
                    },
                    {"role": "user", "content": prompt},
                ]
            )
        except Exception:
            return None
        data = _extract_json(raw)
        self._turns_since_propose = 0
        if not data or not data.get("apply"):
            return None
        # пустой apply без содержания — игнор
        if not any(
            [
                data.get("persona_patch"),
                data.get("skills_add"),
                data.get("preferences_patch"),
                data.get("note"),
            ]
        ):
            return None
        return self.save_pending(data)

    def maybe_propose_from_dialogue(
        self,
        user_text: str,
        assistant_text: str,
        *,
        skip: bool = False,
    ) -> dict[str, Any] | None:
        if not self.should_consider_dialogue(
            user_text, assistant_text, skip=skip
        ):
            return None
        return self.propose_from_dialogue(user_text, assistant_text)

    def apply(self, change: dict[str, Any]) -> dict[str, Any]:
        applied: dict[str, Any] = {"reason": change.get("reason", "")}
        if change.get("persona_patch"):
            self.persona.update(change["persona_patch"])
            applied["persona_patch"] = change["persona_patch"]
        if change.get("skills_add"):
            skills = self.memory.get_skills()
            for s in change["skills_add"]:
                if s not in skills:
                    skills.append(s)
            self.memory.set_skills(skills)
            applied["skills_add"] = change["skills_add"]
        if change.get("preferences_patch"):
            prefs = self.memory.get_preferences()
            prefs.update(change["preferences_patch"])
            self.memory.set_preferences(prefs)
            applied["preferences_patch"] = change["preferences_patch"]
        if change.get("note"):
            self.memory.add_note("soft_evolve", change["note"])
            applied["note"] = change["note"]
        self.memory.log_evolve("soft", applied)
        return applied

    def apply_user_request(self, request: str) -> dict[str, Any]:
        raw = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Преобразуй запрос пользователя в JSON soft-evolve:\n"
                        '{"apply": true, "reason": "...", "persona_patch": {}, '
                        '"skills_add": [], "preferences_patch": {}, "note": ""}'
                    ),
                },
                {"role": "user", "content": request},
            ]
        )
        data = _extract_json(raw) or {
            "apply": True,
            "reason": "запрос пользователя",
            "note": request,
        }
        data["apply"] = True
        self.clear_pending()
        return self.apply(data)


def _extract_json(text: str) -> dict[str, Any] | None:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
