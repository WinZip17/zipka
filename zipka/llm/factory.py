from __future__ import annotations

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError
from zipka.llm.gguf_client import GgufClient, probe_llama_cpp, resolve_gguf_path
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
        # иначе тихо уходим на Ollama (статус/чат подскажут при нужде)

    return OllamaClient(settings)


def describe_backend(client) -> dict:
    if isinstance(client, GgufClient):
        ok = client.is_available()
        info = {
            "backend": "gguf",
            "model": client.model_name,
            "model_path": str(client.model_path),
            "available": ok,
        }
        if not ok:
            info["error"] = client.load_error()
        return info
    return {
        "backend": "ollama",
        "model": getattr(client, "settings", get_settings()).ollama_model,
        "host": getattr(client, "base", ""),
        "available": client.is_available(),
    }
