from __future__ import annotations

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError
from zipka.llm.gguf_client import GgufClient, resolve_gguf_path
from zipka.llm.ollama_client import OllamaClient


def create_llm_client(settings: Settings | None = None):
    """Выбрать бэкенд: GGUF из data/models или системная Ollama.

    ZIPKA_LLM_BACKEND=auto|gguf|ollama
    """
    settings = settings or get_settings()
    backend = (settings.zipka_llm_backend or "auto").strip().lower()
    models_dir = settings.data_dir / "models"
    gguf = resolve_gguf_path(models_dir, settings.zipka_gguf_model)

    if backend == "ollama":
        return OllamaClient(settings)

    if backend == "gguf":
        if not gguf:
            raise LlmError(
                f"Режим gguf, но в {models_dir} нет .gguf файлов. "
                "Положи модель (*.gguf) и перезапусти Зипку."
            )
        return GgufClient(settings, gguf)

    # auto: предпочесть локальный файл, иначе Ollama
    if gguf is not None:
        try:
            client = GgufClient(settings, gguf)
            if client.is_available():
                return client
        except LlmError:
            pass
        # файл есть, но нет llama-cpp-python — сообщим при первом chat;
        # пока пробуем Ollama, а status покажет подсказку
        try:
            import llama_cpp  # noqa: F401
        except ImportError:
            # вернём gguf-клиент всё равно — is_available=False, chat даст понятную ошибку
            return GgufClient(settings, gguf)

    return OllamaClient(settings)


def describe_backend(client) -> dict:
    if isinstance(client, GgufClient):
        return {
            "backend": "gguf",
            "model": client.model_name,
            "model_path": str(client.model_path),
            "available": client.is_available(),
        }
    return {
        "backend": "ollama",
        "model": getattr(client, "settings", get_settings()).ollama_model,
        "host": getattr(client, "base", ""),
        "available": client.is_available(),
    }
