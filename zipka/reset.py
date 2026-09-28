from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from zipka.config import Settings, ensure_data_dirs, get_settings

CONFIRM_PHRASE = "подтверждаю сброс обучения"
CONFIRM_PHRASES = {
    CONFIRM_PHRASE,
    "подтверждаю сброс обучения.",
    "confirm reset learning",
    "confirm factory reset",
}

# Runtime dirs/files to wipe (keep persona.example.yaml and README.md)
WIPE_SUBDIRS = (
    "memory",
    "mind",
    "snapshots",
    "patches",
    "books/notes",
    "books/extracted",
    "books/uploads",
)
WIPE_FILES = (
    "persona/persona.yaml",
)


def reset_learning_data(
    settings: Settings | None = None,
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    """Полная очистка data/ до состояния «с нуля». Требует confirm=True."""
    if not confirm:
        raise PermissionError(
            f"Сброс без подтверждения запрещён. Нужно: confirm=True "
            f"и фраза «{CONFIRM_PHRASE}»."
        )

    settings = settings or get_settings()
    base = settings.data_dir
    removed: list[str] = []
    errors: list[str] = []

    for sub in WIPE_SUBDIRS:
        target = base / sub
        if target.exists():
            try:
                shutil.rmtree(target)
                removed.append(str(target))
            except OSError as exc:
                errors.append(f"{target}: {exc}")

    for rel in WIPE_FILES:
        target = base / rel
        if target.exists():
            try:
                target.unlink()
                removed.append(str(target))
            except OSError as exc:
                errors.append(f"{target}: {exc}")

    # recreate empty structure
    ensure_data_dirs(settings)
    for sub in ("books/notes", "books/extracted", "books/uploads"):
        (base / sub).mkdir(parents=True, exist_ok=True)

    return {
        "ok": not errors,
        "removed": removed,
        "errors": errors,
        "data_dir": str(base),
    }


def is_reset_request(text: str) -> bool:
    lowered = text.strip().lower()
    keys = (
        "сбрось обучение",
        "сбросить обучение",
        "очисти обучение",
        "очистить обучение",
        "сброс обучения",
        "factory reset",
        "reset learning",
        "wipe memory",
        "очисти память",
        "забудь всё",
        "обнули data",
    )
    return any(k in lowered for k in keys)


def is_reset_confirm(text: str) -> bool:
    return text.strip().lower() in CONFIRM_PHRASES
