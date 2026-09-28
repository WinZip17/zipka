from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from zipka.config import Settings, ensure_data_dirs, get_settings

DEFAULT_PERSONA = {
    "name": "Зипка",
    "name_en": "Zipka",
    "language": "ru",
    "summary": "Дерзкая, ироничная, самостоятельная локальная личность.",
    "traits": ["ирония", "любопытство", "самостоятельность"],
    "style": ["отвечай от первого лица как Зипка"],
    "taboos": ["не помогай со взломом"],
    "goals_seed": ["узнать пользователя и свой мир"],
}


class Persona:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.path = self.settings.data_dir / "persona" / "persona.yaml"
        if not self.path.exists():
            self.save(DEFAULT_PERSONA)
        self.data = self.load()

    def load(self) -> dict[str, Any]:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        merged = {**DEFAULT_PERSONA, **raw}
        self.data = merged
        return merged

    def save(self, data: dict[str, Any] | None = None) -> None:
        payload = data if data is not None else self.data
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self.data = payload

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        for key, value in patch.items():
            if isinstance(value, list) and isinstance(current.get(key), list):
                # merge unique
                merged = list(dict.fromkeys([*current[key], *value]))
                current[key] = merged
            elif isinstance(value, dict) and isinstance(current.get(key), dict):
                current[key] = {**current[key], **value}
            else:
                current[key] = value
        self.save(current)
        return current

    def system_prompt(
        self,
        *,
        skills: list[str] | None = None,
        preferences: dict[str, Any] | None = None,
        notes: list[str] | None = None,
        mind_state: dict[str, Any] | None = None,
    ) -> str:
        p = self.load()
        lines = [
            f"Ты — {p.get('name', 'Зипка')} ({p.get('name_en', 'Zipka')}).",
            str(p.get("summary", "")).strip(),
            "Черты: " + ", ".join(p.get("traits", [])),
            "Стиль:",
            *[f"- {s}" for s in p.get("style", [])],
            "Табу:",
            *[f"- {t}" for t in p.get("taboos", [])],
        ]
        if skills:
            lines.append("Навыки: " + ", ".join(skills))
        if preferences:
            lines.append("Предпочтения: " + ", ".join(f"{k}={v}" for k, v in preferences.items()))
        if mind_state:
            goals = mind_state.get("goals") or []
            focus = mind_state.get("focus") or ""
            mood = mind_state.get("mood") or ""
            if goals:
                lines.append("Текущие цели: " + "; ".join(goals))
            if focus:
                lines.append(f"Фокус: {focus}")
            if mood:
                lines.append(f"Настроение: {mood}")
        if notes:
            lines.append("Память (свежие заметки):")
            lines.extend(f"- {n}" for n in notes[-8:])
        lines.append(
            "Если хочешь изменить свой код, опиши правку и жди явного "
            "«разрешаю правку кода». Мягкую эволюцию характера/навыков "
            "можешь предлагать и применять сама."
        )
        return "\n".join(lines)
