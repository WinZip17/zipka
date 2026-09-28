from __future__ import annotations

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError
from zipka.llm.chat_models import (
    active_chat_model_id,
    chat_models_status,
    resolve_chat_gguf,
)
from zipka.llm.gguf_client import GgufClient, find_gguf_files, probe_llama_cpp
from zipka.llm.ollama_client import OllamaClient


def create_llm_client(settings: Settings | None = None):
    """Выбрать бэкенд: GGUF из data/models или системная Ollama.

    ZIPKA_LLM_BACKEND=auto|gguf|ollama
    Активный чатовый GGUF задаётся профилем pathfinder|qwen25
    (runtime chat_model_id / ZIPKA_CHAT_MODEL).
    """
    settings = settings or get_settings()
    backend = (settings.zipka_llm_backend or "auto").strip().lower()
    models_dir = settings.data_dir / "models"
    gguf, profile = resolve_chat_gguf(settings)
    any_gguf = bool(find_gguf_files(models_dir))

    if backend == "ollama":
        return OllamaClient(settings)

    if backend == "gguf":
        if not gguf:
            label = profile.get("label") or profile.get("id")
            fname = profile.get("filename")
            raise LlmError(
                f"Режим gguf, но нет файла для «{label}» ({fname}). "
                f"Скачай в {models_dir}: python -m zipka.tools.download_chat_models "
                f"--id {profile.get('id')}"
            )
        ok, err = probe_llama_cpp()
        if not ok:
            raise LlmError(err or "GGUF недоступен.")
        return GgufClient(settings, gguf)

    # auto: GGUF только если библиотека реально грузится
    if gguf is not None:
        ok, _err = probe_llama_cpp()
        if ok:
            try:
                client = GgufClient(settings, gguf)
                if client.is_available():
                    return client
            except LlmError:
                pass
    elif any_gguf:
        # профиль не скачан, но другие .gguf есть — всё равно сообщим в статусе
        pass

    return OllamaClient(settings)


def describe_backend(client) -> dict:
    settings = get_settings()
    chat = chat_models_status(settings)
    if isinstance(client, GgufClient):
        ok = client.is_available()
        info = {
            "backend": "gguf",
            "model": client.model_name,
            "model_path": str(client.model_path),
            "available": ok,
            "chat_model_id": active_chat_model_id(settings),
            "chat_model_label": chat.get("active_label"),
            "load": client.load_info(),
        }
        if not ok:
            info["error"] = client.load_error()
        return info
    return {
        "backend": "ollama",
        "model": getattr(client, "settings", settings).ollama_model,
        "host": getattr(client, "base", ""),
        "available": client.is_available(),
        "chat_model_id": active_chat_model_id(settings),
        "chat_model_label": chat.get("active_label"),
    }
