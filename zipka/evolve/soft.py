from __future__ import annotations

import re
from typing import Any

from zipka.character.persona import Persona
from zipka.llm.ollama_client import OllamaClient
from zipka.memory.store import MemoryStore


SOFT_MARKER = "[[SOFT_EVOLVE]]"


class SoftEvolve:
    """Мягкая самоэволюция: persona / skills / preferences / notes."""

    def __init__(
        self,
        persona: Persona,
        memory: MemoryStore,
        llm: OllamaClient,
    ) -> None:
        self.persona = persona
        self.memory = memory
        self.llm = llm

    def propose_from_dialogue(self, user_text: str, assistant_text: str) -> dict[str, Any] | None:
        prompt = (
            "Проанализируй диалог. Если Зипке полезно обновить характер, навыки "
            "или предпочтения — верни ТОЛЬКО JSON вида:\n"
            '{"apply": true, "reason": "...", "persona_patch": {}, '
            '"skills_add": [], "preferences_patch": {}, "note": ""}\n'
            "Если менять нечего: {\"apply\": false}\n"
            f"USER: {user_text}\nZIPKA: {assistant_text}"
        )
        raw = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": "Ты модуль soft-evolve. Отвечай только JSON.",
                },
                {"role": "user", "content": prompt},
            ]
        )
        data = _extract_json(raw)
        if not data or not data.get("apply"):
            return None
        return self.apply(data)

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
        return self.apply(data)


def _extract_json(text: str) -> dict[str, Any] | None:
    import json

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
