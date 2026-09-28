from __future__ import annotations

from pathlib import Path
from typing import Any

from zipka.config import Settings, get_settings
from zipka.llm.gguf_client import find_gguf_files, resolve_gguf_path
from zipka.runtime_settings import load_runtime

# Подсказки для UI / скачивания (не ограничивают выбор — в UI все *.gguf)
KNOWN_HINTS: dict[str, dict[str, Any]] = {
    "pathfinder-rp-12b-ru.q4_k_m.gguf": {
        "label": "Pathfinder RP 12B RU",
        "blurb": "личность / чат",
        "role_default": "chat",
    },
    "qwen2.5-7b-instruct-q5_k_m.gguf": {
        "label": "Qwen2.5-7B-Instruct Q5_K_M",
        "blurb": "кодинг / инструкции",
        "role_default": "code",
    },
    "qwen3-8b-q4_k_m.gguf": {
        "label": "Qwen3-8B Q4_K_M",
        "blurb": "универсальная",
        "role_default": None,
    },
}

DEFAULT_CHAT_GGUF = "Pathfinder-RP-12B-RU.Q4_K_M.gguf"
DEFAULT_CODE_GGUF = "Qwen2.5-7B-Instruct-Q5_K_M.gguf"

# Legacy id → filename (старый ZIPKA_CHAT_MODEL / chat_model_id)
LEGACY_IDS: dict[str, str] = {
    "pathfinder": DEFAULT_CHAT_GGUF,
    "qwen25": DEFAULT_CODE_GGUF,
    "qwen2.5": DEFAULT_CODE_GGUF,
    "qwen3": "Qwen3-8B-Q4_K_M.gguf",
}

# Сохраняем старые имена для download script
CHAT_PROFILES = {
    "pathfinder": {
        "id": "pathfinder",
        "label": "Pathfinder RP 12B RU",
        "blurb": "личность / живой русский диалог",
        "filename": DEFAULT_CHAT_GGUF,
        "match": ("pathfinder-rp-12b-ru.q4_k_m", "pathfinder-rp-12b-ru-q4_k_m"),
        "hf_repo": "roleplaiapp/Pathfinder-RP-12B-RU-Q4_K_M-GGUF",
        "hf_file": DEFAULT_CHAT_GGUF,
        "url": (
            "https://huggingface.co/roleplaiapp/"
            "Pathfinder-RP-12B-RU-Q4_K_M-GGUF/resolve/main/"
            + DEFAULT_CHAT_GGUF
        ),
        "size_hint_gb": 7.5,
    },
    "qwen25": {
        "id": "qwen25",
        "label": "Qwen2.5-7B-Instruct Q5_K_M",
        "blurb": "инструкции / JSON / кодинг",
        "filename": DEFAULT_CODE_GGUF,
        "match": ("qwen2.5-7b-instruct-q5_k_m", "qwen2_5_7b_instruct-q5_k_m"),
        "hf_repo": "bartowski/Qwen2.5-7B-Instruct-GGUF",
        "hf_file": DEFAULT_CODE_GGUF,
        "url": (
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/"
            "resolve/main/" + DEFAULT_CODE_GGUF
        ),
        "size_hint_gb": 5.4,
    },
}


def _hint_for(filename: str) -> dict[str, Any]:
    return dict(KNOWN_HINTS.get(filename.lower(), {}) or {})


def list_gguf_catalog(settings: Settings | None = None) -> list[dict[str, Any]]:
    settings = settings or get_settings()
    models_dir = settings.data_dir / "models"
    out: list[dict[str, Any]] = []
    for p in find_gguf_files(models_dir):
        hint = _hint_for(p.name)
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append(
            {
                "filename": p.name,
                "path": str(p),
                "size_bytes": size,
                "size_gb": round(size / (1024**3), 2) if size else None,
                "label": hint.get("label") or p.stem,
                "blurb": hint.get("blurb") or "",
            }
        )
    return out


def _normalize_name(name: str | None) -> str:
    return Path(str(name or "").strip()).name


def _legacy_to_filename(value: str) -> str:
    low = value.strip().lower()
    if low in LEGACY_IDS:
        return LEGACY_IDS[low]
    return _normalize_name(value)


def active_gguf_name(role: str, settings: Settings | None = None) -> str:
    """Имя файла GGUF для роли chat|code."""
    settings = settings or get_settings()
    rt = load_runtime(settings)
    key = "chat_gguf" if role == "chat" else "code_gguf"
    default = DEFAULT_CHAT_GGUF if role == "chat" else DEFAULT_CODE_GGUF
    raw = str(rt.get(key) or "").strip()
    if not raw:
        # legacy
        if role == "chat":
            raw = str(rt.get("chat_model_id") or settings.zipka_chat_model or "").strip()
            if raw:
                raw = _legacy_to_filename(raw)
        if not raw and role == "chat" and settings.zipka_gguf_model:
            raw = _normalize_name(settings.zipka_gguf_model)
    return _normalize_name(raw) or default


def resolve_role_gguf(
    role: str,
    settings: Settings | None = None,
    *,
    filename: str | None = None,
) -> Path | None:
    settings = settings or get_settings()
    models_dir = settings.data_dir / "models"
    want = _normalize_name(filename) if filename else active_gguf_name(role, settings)
    if not want:
        return None
    path = resolve_gguf_path(models_dir, want)
    if path is not None:
        return path
    # fuzzy: stem / substring
    low = want.lower()
    for p in find_gguf_files(models_dir):
        if p.name.lower() == low or p.stem.lower() == Path(low).stem.lower():
            return p
        if low.replace(".gguf", "") in p.name.lower():
            return p
    return None


def models_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    catalog = list_gguf_catalog(settings)
    chat_name = active_gguf_name("chat", settings)
    code_name = active_gguf_name("code", settings)
    chat_path = resolve_role_gguf("chat", settings)
    code_path = resolve_role_gguf("code", settings)
    same = bool(
        chat_path
        and code_path
        and chat_path.resolve() == code_path.resolve()
    ) or (chat_name.lower() == code_name.lower())

    def _role_block(name: str, path: Path | None) -> dict[str, Any]:
        hint = _hint_for(name)
        return {
            "filename": name,
            "label": hint.get("label") or Path(name).stem,
            "present": path is not None,
            "path": str(path) if path else None,
        }

    return {
        "models_dir": str(settings.data_dir / "models"),
        "files": catalog,
        "chat": _role_block(chat_name, chat_path),
        "code": _role_block(code_name, code_path),
        "same_model": same,
        "defaults": {
            "chat": DEFAULT_CHAT_GGUF,
            "code": DEFAULT_CODE_GGUF,
        },
        # совместимость со старым UI
        "active_id": chat_name,
        "active_label": _role_block(chat_name, chat_path)["label"],
        "active_path": str(chat_path) if chat_path else None,
        "active_present": chat_path is not None,
        "profiles": [
            {
                "id": f["filename"],
                "label": f["label"],
                "blurb": f.get("blurb") or "",
                "filename": f["filename"],
                "present": True,
                "path": f["path"],
                "active": f["filename"].lower() == chat_name.lower(),
            }
            for f in catalog
        ],
    }


# --- aliases for old imports ---
def list_chat_profiles() -> list[dict[str, Any]]:
    return [dict(CHAT_PROFILES[k]) for k in CHAT_PROFILES]


def get_profile(model_id: str | None) -> dict[str, Any] | None:
    if not model_id:
        return None
    mid = str(model_id).strip().lower()
    if mid in CHAT_PROFILES:
        return CHAT_PROFILES[mid]
    return None


def active_chat_model_id(settings: Settings | None = None) -> str:
    return active_gguf_name("chat", settings)


def match_profile_by_filename(name: str) -> dict[str, Any] | None:
    low = Path(name).name.lower()
    for profile in CHAT_PROFILES.values():
        if low == str(profile["filename"]).lower():
            return profile
        for token in profile.get("match") or ():
            if token in low:
                return profile
    return None


def find_profile_file(models_dir: Path, profile: dict[str, Any]) -> Path | None:
    return resolve_role_gguf(
        "chat",
        filename=str(profile.get("filename") or ""),
        settings=get_settings(),
    )


def resolve_chat_gguf(
    settings: Settings | None = None,
    *,
    model_id: str | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    settings = settings or get_settings()
    if model_id and model_id.lower() in CHAT_PROFILES:
        fname = CHAT_PROFILES[model_id.lower()]["filename"]
        path = resolve_role_gguf("chat", settings, filename=fname)
        return path, CHAT_PROFILES[model_id.lower()]
    path = resolve_role_gguf("chat", settings, filename=model_id)
    name = active_gguf_name("chat", settings) if not model_id else _normalize_name(model_id)
    hint = _hint_for(name)
    profile = {
        "id": name,
        "label": hint.get("label") or Path(name).stem,
        "filename": name,
        "blurb": hint.get("blurb") or "",
    }
    return path, profile


def chat_models_status(settings: Settings | None = None) -> dict[str, Any]:
    return models_status(settings)
