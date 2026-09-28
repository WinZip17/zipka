from __future__ import annotations

from typing import Any, Protocol


class LlmClient(Protocol):
    """Общий контракт локального LLM (Ollama или GGUF)."""

    def is_available(self) -> bool: ...

    def list_models(self) -> list[str]: ...

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        images: list[str] | None = None,
    ) -> str: ...

    def summarize(self, text: str, *, instruction: str) -> str: ...


class LlmError(RuntimeError):
    pass
