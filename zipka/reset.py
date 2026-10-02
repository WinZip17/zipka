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

# Каталоги целиком (scaffolding вроде README/example не кладём сюда)
WIPE_SUBDIRS = (
    "memory",
    "mind",
    "snapshots",
    "patches",
    "books/notes",
    "books/extracted",
    "books/uploads",
    "books/rag",
)

# Файлы runtime (дублируют WIPE_DIR_KEEP/SUBDIRS — на случай остатков после lock)
WIPE_FILES = (
    "persona/persona.yaml",
    "news/sources.json",
    "news/items.jsonl",
    "news/items.jsonl.migrated",
    "news/news.sqlite",
    "news/news.sqlite-wal",
    "news/news.sqlite-shm",
)

# В этих каталогах снести всё, кроме keep-имён (защита scaffolding в git)
WIPE_DIR_KEEP: dict[str, frozenset[str]] = {
    "news": frozenset({"README.md", "sources.example.json"}),
}


def _wipe_dir_keeping(target: Path, keep: frozenset[str]) -> list[str]:
    """Удалить содержимое каталога, сохранив keep-файлы. Вернуть список путей."""
    removed: list[str] = []
    if not target.is_dir():
        return removed
    for child in target.iterdir():
        if child.name in keep:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed.append(str(child))
    return removed


def _reseed_persona(settings: Settings) -> str | None:
    """Создать persona.yaml из example/default после сброса. Путь или None."""
    from zipka.character.persona import Persona

    path = settings.data_dir / "persona" / "persona.yaml"
    if path.exists():
        try:
            path.unlink()
        except OSError:
            pass
    # Persona.__init__ сам сидирует файл, если его нет
    Persona(settings)
    return str(path) if path.exists() else None


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

    for rel, keep in WIPE_DIR_KEEP.items():
        target = base / rel
        if not target.exists():
            continue
        try:
            removed.extend(_wipe_dir_keeping(target, keep))
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
    for sub in (
        "books/notes",
        "books/extracted",
        "books/uploads",
        "books/rag",
        "news",
    ):
        (base / sub).mkdir(parents=True, exist_ok=True)

    seeded: str | None = None
    try:
        seeded = _reseed_persona(settings)
    except Exception as exc:
        errors.append(f"persona.yaml: {exc}")

    return {
        "ok": not errors,
        "removed": removed,
        "errors": errors,
        "data_dir": str(base),
        "persona_seeded": seeded,
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
