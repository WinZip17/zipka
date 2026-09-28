from __future__ import annotations

from pathlib import Path
from typing import Any

from zipka.config import Settings, get_settings
from zipka.llm.gguf_client import find_gguf_files
from zipka.runtime_settings import load_runtime

# Два чатовых профиля под 8GB VRAM (4060 Laptop).
CHAT_PROFILES: dict[str, dict[str, Any]] = {
    "pathfinder": {
        "id": "pathfinder",
        "label": "Pathfinder RP 12B RU",
        "blurb": "личность / живой русский диалог",
        "filename": "Pathfinder-RP-12B-RU.Q4_K_M.gguf",
        "match": (
            "pathfinder-rp-12b-ru.q4_k_m",
            "pathfinder-rp-12b-ru-q4_k_m",
            "pathfinder_rp_12b_ru.q4_k_m",
        ),
        "hf_repo": "roleplaiapp/Pathfinder-RP-12B-RU-Q4_K_M-GGUF",
        "hf_file": "Pathfinder-RP-12B-RU.Q4_K_M.gguf",
        "url": (
            "https://huggingface.co/roleplaiapp/"
            "Pathfinder-RP-12B-RU-Q4_K_M-GGUF/resolve/main/"
            "Pathfinder-RP-12B-RU.Q4_K_M.gguf"
        ),
        "size_hint_gb": 7.5,
        "recommended_ctx": 8192,
    },
    "qwen25": {
        "id": "qwen25",
        "label": "Qwen2.5-7B-Instruct Q5_K_M",
        "blurb": "инструкции / JSON / запасной чат",
        "filename": "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
        "match": (
            "qwen2.5-7b-instruct-q5_k_m",
            "qwen2_5_7b_instruct-q5_k_m",
            "qwen2.5-7b-instruct.q5_k_m",
        ),
        "hf_repo": "bartowski/Qwen2.5-7B-Instruct-GGUF",
        "hf_file": "Qwen2.5-7B-Instruct-Q5_K_M.gguf",
        "url": (
            "https://huggingface.co/bartowski/Qwen2.5-7B-Instruct-GGUF/"
            "resolve/main/Qwen2.5-7B-Instruct-Q5_K_M.gguf"
        ),
        "size_hint_gb": 5.4,
        "recommended_ctx": 8192,
    },
}

DEFAULT_CHAT_MODEL_ID = "pathfinder"


def list_chat_profiles() -> list[dict[str, Any]]:
    return [dict(CHAT_PROFILES[k]) for k in ("pathfinder", "qwen25") if k in CHAT_PROFILES]


def get_profile(model_id: str | None) -> dict[str, Any] | None:
    if not model_id:
        return None
    return CHAT_PROFILES.get(str(model_id).strip().lower())


def active_chat_model_id(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    rt = load_runtime(settings)
    rid = str(rt.get("chat_model_id") or "").strip().lower()
    if rid in CHAT_PROFILES:
        return rid
    env = (settings.zipka_chat_model or "").strip().lower()
    if env in CHAT_PROFILES:
        return env
    # ZIPKA_GGUF_MODEL=имя файла → угадать профиль
    preferred = (settings.zipka_gguf_model or "").strip()
    if preferred:
        hit = match_profile_by_filename(preferred)
        if hit:
            return hit["id"]
    return DEFAULT_CHAT_MODEL_ID


def match_profile_by_filename(name: str) -> dict[str, Any] | None:
    low = Path(name).name.lower().replace(" ", "")
    for profile in CHAT_PROFILES.values():
        fname = str(profile["filename"]).lower()
        if low == fname or low.endswith(fname):
            return profile
        for token in profile.get("match") or ():
            if token in low:
                return profile
    return None


def find_profile_file(models_dir: Path, profile: dict[str, Any]) -> Path | None:
    files = find_gguf_files(models_dir)
    if not files:
        return None
    want = str(profile.get("filename") or "").lower()
    tokens = [t.lower() for t in (profile.get("match") or ())]
    # точное имя
    for p in files:
        if p.name.lower() == want:
            return p
    # по match-токенам
    for p in files:
        low = p.name.lower()
        if any(t in low for t in tokens):
            return p
    return None


def resolve_chat_gguf(
    settings: Settings | None = None,
    *,
    model_id: str | None = None,
) -> tuple[Path | None, dict[str, Any]]:
    """Путь к GGUF активного (или указанного) чатового профиля."""
    settings = settings or get_settings()
    mid = (model_id or active_chat_model_id(settings)).strip().lower()
    profile = get_profile(mid) or CHAT_PROFILES[DEFAULT_CHAT_MODEL_ID]
    models_dir = settings.data_dir / "models"
    path = find_profile_file(models_dir, profile)
    if path is None and settings.zipka_gguf_model:
        # явный файл из .env, если профиль ещё не скачан
        from zipka.llm.gguf_client import resolve_gguf_path

        path = resolve_gguf_path(models_dir, settings.zipka_gguf_model)
    return path, profile


def chat_models_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    models_dir = settings.data_dir / "models"
    active = active_chat_model_id(settings)
    profiles: list[dict[str, Any]] = []
    for profile in list_chat_profiles():
        path = find_profile_file(models_dir, profile)
        profiles.append(
            {
                "id": profile["id"],
                "label": profile["label"],
                "blurb": profile.get("blurb") or "",
                "filename": profile["filename"],
                "present": path is not None,
                "path": str(path) if path else None,
                "size_hint_gb": profile.get("size_hint_gb"),
                "hf_repo": profile.get("hf_repo"),
                "url": profile.get("url"),
                "active": profile["id"] == active,
            }
        )
    active_path, active_profile = resolve_chat_gguf(settings, model_id=active)
    return {
        "active_id": active,
        "active_label": active_profile.get("label"),
        "active_path": str(active_path) if active_path else None,
        "active_present": active_path is not None,
        "models_dir": str(models_dir),
        "profiles": profiles,
        "download_hint": (
            f"Скачай недостающие: python -m zipka.tools.download_chat_models "
            f"или zipka models download"
        ),
    }
