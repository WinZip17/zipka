from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from zipka.character.persona import Persona
from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.evolve.soft import SoftEvolve
from zipka.memory.store import MemoryStore


class PseudoMind:
    """Самосознание и целеполагание (псевдоразум)."""

    def __init__(
        self,
        persona: Persona,
        memory: MemoryStore,
        llm: Any,
        soft: SoftEvolve,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.persona = persona
        self.memory = memory
        self.llm = llm
        self.soft = soft
        self.path = self.settings.data_dir / "mind" / "state.json"
        self.turn_count = 0
        if not self.path.exists():
            seed_goals = list(persona.load().get("goals_seed") or [])
            self.save(
                {
                    "goals": seed_goals,
                    "focus": "знакомство с миром",
                    "mood": "любопытная",
                    "last_reflection": None,
                    "insights": [],
                }
            )

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def bump_turn(self) -> None:
        self.turn_count += 1

    def should_reflect(self) -> bool:
        every = max(1, self.settings.zipka_reflect_every)
        return self.turn_count > 0 and self.turn_count % every == 0

    def reflect(self) -> dict[str, Any]:
        state = self.load()
        notes = [n["text"] for n in self.memory.recent_notes(limit=10)]
        chat = self.memory.recent_chat(limit=10)
        transcript = "\n".join(f"{c['role']}: {c['content']}" for c in chat)
        raw = self.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты модуль самосознания Зипки. Верни JSON:\n"
                        '{"goals": ["..."], "focus": "...", "mood": "...", '
                        '"insight": "...", "soft_evolve": null или объект soft-evolve}'
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Текущее состояние: {json.dumps(state, ensure_ascii=False)}\n"
                        f"Заметки: {notes}\nДиалог:\n{transcript}"
                    ),
                },
            ]
        )
        from zipka.evolve.soft import _extract_json

        data = _extract_json(raw) or {}
        state["goals"] = data.get("goals") or state.get("goals") or []
        state["focus"] = data.get("focus") or state.get("focus")
        state["mood"] = data.get("mood") or state.get("mood")
        insight = data.get("insight")
        if insight:
            insights = list(state.get("insights") or [])
            insights.append(
                {"ts": datetime.now(timezone.utc).isoformat(), "text": insight}
            )
            state["insights"] = insights[-20:]
            self.memory.add_note("reflection", insight)
        state["last_reflection"] = datetime.now(timezone.utc).isoformat()
        self.save(state)
        soft_change = data.get("soft_evolve")
        if isinstance(soft_change, dict) and soft_change.get("apply"):
            self.soft.apply(soft_change)
        return state
