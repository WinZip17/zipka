from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from zipka.character.persona import Persona
from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.evolve.soft import SoftEvolve
from zipka.memory.store import MemoryStore


def goal_as_str(item: Any) -> str:
    """YAML с двоеточием даёт dict — склеиваем в читаемую строку."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        if len(item) == 1:
            k, v = next(iter(item.items()))
            k, v = str(k).strip(), str(v).strip()
            return f"{k}: {v}" if v else k
        parts = []
        for k, v in item.items():
            k, v = str(k).strip(), str(v).strip() if v is not None else ""
            parts.append(f"{k}: {v}" if v else k)
        return "; ".join(parts)
    if item is None:
        return ""
    return str(item).strip()


def normalize_goals(goals: Any) -> list[str]:
    if not isinstance(goals, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in goals:
        s = goal_as_str(item)
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


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
            seed_goals = normalize_goals(persona.load().get("goals_seed") or [])
            self.save(
                {
                    "goals": seed_goals,
                    "focus": "знакомство с миром",
                    "mood": "любопытная",
                    "last_reflection": None,
                    "insights": [],
                }
            )
        else:
            # починить goals после YAML-артефактов / старых снимков
            self._sanitize_goals()

    def _sanitize_goals(self) -> None:
        try:
            state = self.load()
        except Exception:
            return
        fixed = normalize_goals(state.get("goals"))
        if fixed != list(state.get("goals") or []):
            state["goals"] = fixed
            self.save(state)

    def load(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> None:
        if isinstance(state.get("goals"), list):
            state = {**state, "goals": normalize_goals(state["goals"])}
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
        state["goals"] = normalize_goals(
            data.get("goals") or state.get("goals") or []
        )
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
            # при режиме soft-from-dialogue не авто-применяем из reflect
            if self.soft.dialogue_enabled():
                if not self.soft.has_pending() and any(
                    soft_change.get(k)
                    for k in (
                        "persona_patch",
                        "skills_add",
                        "preferences_patch",
                        "note",
                    )
                ):
                    self.soft.save_pending(soft_change)
            else:
                self.soft.apply(soft_change)
        return state
