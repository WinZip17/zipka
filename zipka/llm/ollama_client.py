from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

import httpx

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError


@dataclass
class ChatMessage:
    role: str
    content: str


class OllamaError(LlmError):
    pass


class OllamaClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base = self.settings.ollama_host.rstrip("/")

    @property
    def backend(self) -> str:
        return "ollama"

    def is_available(self) -> bool:
        try:
            with httpx.Client(timeout=3.0) as client:
                r = client.get(f"{self.base}/api/tags")
                return r.status_code == 200
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[str]:
        try:
            with httpx.Client(timeout=10.0) as client:
                r = client.get(f"{self.base}/api/tags")
                r.raise_for_status()
                data = r.json()
                return [m.get("name", "") for m in data.get("models", [])]
        except httpx.HTTPError as exc:
            raise OllamaError(
                f"Ollama недоступна на {self.base}. "
                "Установи Ollama и запусти `ollama serve`."
            ) from exc

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        images: list[str] | None = None,
    ) -> str:
        model = model or self.settings.ollama_model
        payload_messages = list(messages)
        if images and payload_messages:
            last = dict(payload_messages[-1])
            last["images"] = images
            payload_messages[-1] = last

        payload = {
            "model": model,
            "messages": payload_messages,
            "stream": stream,
        }
        try:
            with httpx.Client(timeout=180.0) as client:
                if stream:
                    return "".join(self._stream_chat(client, payload))
                r = client.post(f"{self.base}/api/chat", json=payload)
                r.raise_for_status()
                data = r.json()
                return data.get("message", {}).get("content", "")
        except httpx.HTTPError as exc:
            raise OllamaError(f"Ошибка Ollama chat: {exc}") from exc

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
    ) -> Iterator[str]:
        model = model or self.settings.ollama_model
        payload = {"model": model, "messages": messages, "stream": True}
        with httpx.Client(timeout=180.0) as client:
            yield from self._stream_chat(client, payload)

    def _stream_chat(
        self, client: httpx.Client, payload: dict[str, Any]
    ) -> Iterator[str]:
        import json

        with client.stream("POST", f"{self.base}/api/chat", json=payload) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("done"):
                    break
                chunk = data.get("message", {}).get("content", "")
                if chunk:
                    yield chunk

    def summarize(self, text: str, *, instruction: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "Ты Зипка. Кратко и по делу. Отвечай на русском.",
            },
            {
                "role": "user",
                "content": f"{instruction}\n\n---\n{text[:12000]}",
            },
        ]
        return self.chat(messages)
