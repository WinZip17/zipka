from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError
from zipka.llm.chat_models import (
    active_gguf_name,
    models_status,
    resolve_role_gguf,
)
from zipka.llm.gguf_client import GgufClient, find_gguf_files, probe_llama_cpp
from zipka.llm.ollama_client import OllamaClient


class _RoleProxy:
    """Прокси к chat/code клиенту с выгрузкой другой модели (экономия VRAM)."""

    def __init__(self, router: "LlmRouter", role: str) -> None:
        self._router = router
        self._role = role

    @property
    def backend(self) -> str:
        return self._router._client(self._role).backend  # type: ignore[attr-defined]

    @property
    def model_name(self) -> str:
        c = self._router._client(self._role)
        return getattr(c, "model_name", "") or active_gguf_name(self._role)

    @property
    def model_path(self) -> Path | None:
        c = self._router._client(self._role)
        return getattr(c, "model_path", None)

    def is_available(self) -> bool:
        return self._router._client(self._role).is_available()

    def list_models(self) -> list[str]:
        return self._router.list_models()

    def load_info(self) -> dict[str, Any]:
        with self._router._lock:
            c = self._router._activate(self._role)
            if hasattr(c, "load_info"):
                return c.load_info()
            return {"loaded": False}

    def load_error(self) -> str:
        c = self._router._client(self._role)
        if hasattr(c, "load_error"):
            return c.load_error()
        return ""

    def unload(self) -> None:
        self._router.unload_role(self._role)

    def chat(self, *args: Any, **kwargs: Any) -> str:
        with self._router._lock:
            return self._router._activate(self._role).chat(*args, **kwargs)

    def summarize(self, text: str, *, instruction: str) -> str:
        with self._router._lock:
            return self._router._activate(self._role).summarize(
                text, instruction=instruction
            )


class LlmRouter:
    """Две роли (чат / кодинг) поверх GGUF или одна Ollama."""

    def __init__(
        self,
        settings: Settings,
        *,
        chat_client: Any,
        code_client: Any,
    ) -> None:
        self.settings = settings
        self._chat_client = chat_client
        self._code_client = code_client
        self._active_role: str | None = None
        self._lock = threading.RLock()
        self.chat_llm = _RoleProxy(self, "chat")
        self.code_llm = _RoleProxy(self, "code")

    @property
    def backend(self) -> str:
        return getattr(self._chat_client, "backend", "unknown")

    @property
    def model_name(self) -> str:
        return self.chat_llm.model_name

    @property
    def model_path(self) -> Path | None:
        return self.chat_llm.model_path

    def same_model(self) -> bool:
        cp = getattr(self._chat_client, "model_path", None)
        kp = getattr(self._code_client, "model_path", None)
        if cp is not None and kp is not None:
            try:
                return Path(cp).resolve() == Path(kp).resolve()
            except OSError:
                return str(cp) == str(kp)
        return self._chat_client is self._code_client

    def is_available(self) -> bool:
        return self._chat_client.is_available()

    def list_models(self) -> list[str]:
        return list(self._chat_client.list_models())

    def load_info(self) -> dict[str, Any]:
        return self.chat_llm.load_info()

    def load_error(self) -> str:
        return self.chat_llm.load_error()

    def unload(self) -> None:
        with self._lock:
            for c in {
                id(self._chat_client): self._chat_client,
                id(self._code_client): self._code_client,
            }.values():
                if hasattr(c, "unload"):
                    try:
                        c.unload()
                    except Exception:
                        pass
            self._active_role = None

    def unload_role(self, role: str) -> None:
        with self._lock:
            c = self._client(role)
            if hasattr(c, "unload"):
                try:
                    c.unload()
                except Exception:
                    pass
            if self._active_role == role:
                self._active_role = None

    def _client(self, role: str) -> Any:
        return self._chat_client if role == "chat" else self._code_client

    def _activate(self, role: str) -> Any:
        """Перед вызовом выгрузить другую GGUF, если это другой файл."""
        client = self._client(role)
        other_role = "code" if role == "chat" else "chat"
        other = self._client(other_role)
        if (
            client is not other
            and hasattr(other, "unload")
            and self._active_role == other_role
        ):
            try:
                other.unload()
            except Exception:
                pass
        self._active_role = role
        return client

    def chat(self, *args: Any, **kwargs: Any) -> str:
        return self.chat_llm.chat(*args, **kwargs)

    def summarize(self, text: str, *, instruction: str) -> str:
        return self.chat_llm.summarize(text, instruction=instruction)

    def preload_chat(self) -> None:
        """Фоновый прогрев чатовой модели после code-роли."""
        with self._lock:
            client = self._activate("chat")
            ensure = getattr(client, "_ensure_loaded", None)
            if callable(ensure):
                ensure()


def create_llm_client(settings: Settings | None = None) -> LlmRouter:
    """Собрать роутер: chat GGUF + code GGUF (или одна Ollama на обе роли)."""
    settings = settings or get_settings()
    backend = (settings.zipka_llm_backend or "auto").strip().lower()
    models_dir = settings.data_dir / "models"
    any_gguf = bool(find_gguf_files(models_dir))

    chat_path = resolve_role_gguf("chat", settings)
    code_path = resolve_role_gguf("code", settings)

    def _gguf_or_raise(path: Path | None, role: str) -> GgufClient:
        if path is None:
            name = active_gguf_name(role, settings)
            raise LlmError(
                f"Нет GGUF для роли «{role}»: {name}. "
                f"Положи файл в {models_dir}"
            )
        ok, err = probe_llama_cpp()
        if not ok:
            raise LlmError(err or "GGUF недоступен.")
        return GgufClient(settings, path)

    if backend == "ollama":
        ollama = OllamaClient(settings)
        return LlmRouter(settings, chat_client=ollama, code_client=ollama)

    if backend == "gguf":
        chat_c = _gguf_or_raise(chat_path, "chat")
        if code_path and chat_path and code_path.resolve() == chat_path.resolve():
            code_c = chat_c
        else:
            code_c = _gguf_or_raise(code_path, "code")
        return LlmRouter(settings, chat_client=chat_c, code_client=code_c)

    # auto
    if chat_path is not None:
        ok, _ = probe_llama_cpp()
        if ok:
            try:
                chat_c = GgufClient(settings, chat_path)
                if chat_c.is_available():
                    if (
                        code_path is None
                        or code_path.resolve() == chat_path.resolve()
                    ):
                        code_c = chat_c
                    else:
                        code_c = GgufClient(settings, code_path)
                    return LlmRouter(
                        settings, chat_client=chat_c, code_client=code_c
                    )
            except LlmError:
                pass
    elif any_gguf:
        pass

    ollama = OllamaClient(settings)
    return LlmRouter(settings, chat_client=ollama, code_client=ollama)


def describe_backend(client: Any) -> dict:
    settings = get_settings()
    status = models_status(settings)
    if isinstance(client, LlmRouter):
        chat_ok = client.chat_llm.is_available()
        info: dict[str, Any] = {
            "backend": client.backend,
            "model": client.chat_llm.model_name,
            "model_path": str(client.chat_llm.model_path)
            if client.chat_llm.model_path
            else None,
            "available": chat_ok,
            "chat": status.get("chat"),
            "code": status.get("code"),
            "same_model": client.same_model(),
            "chat_model_id": status["chat"]["filename"],
            "chat_model_label": status["chat"]["label"],
            "code_model": status["code"]["filename"],
            "code_model_label": status["code"]["label"],
            "load": client.chat_llm.load_info() if chat_ok else {},
        }
        if not chat_ok:
            info["error"] = client.chat_llm.load_error()
        return info
    if isinstance(client, GgufClient):
        ok = client.is_available()
        return {
            "backend": "gguf",
            "model": client.model_name,
            "model_path": str(client.model_path),
            "available": ok,
            "chat": status.get("chat"),
            "code": status.get("code"),
            "load": client.load_info() if ok else {},
            "error": client.load_error() if not ok else None,
        }
    return {
        "backend": "ollama",
        "model": getattr(client, "settings", settings).ollama_model,
        "host": getattr(client, "base", ""),
        "available": client.is_available(),
        "chat": status.get("chat"),
        "code": status.get("code"),
    }
