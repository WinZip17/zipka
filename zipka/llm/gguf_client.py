from __future__ import annotations

from pathlib import Path
from typing import Any

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError


def find_gguf_files(models_dir: Path) -> list[Path]:
    if not models_dir.is_dir():
        return []
    files = sorted(
        [
            p
            for p in models_dir.rglob("*.gguf")
            if p.is_file() and not p.name.startswith(".")
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return files


def resolve_gguf_path(models_dir: Path, preferred: str = "") -> Path | None:
    files = find_gguf_files(models_dir)
    if not files:
        return None
    if preferred:
        name = preferred.strip()
        for p in files:
            if p.name == name or p.stem == name or str(p).endswith(name):
                return p
        # allow relative path under models_dir
        candidate = (models_dir / name).resolve()
        try:
            candidate.relative_to(models_dir.resolve())
        except ValueError:
            return files[0]
        if candidate.is_file():
            return candidate
    return files[0]


class GgufClient:
    """Локальный LLM из файла .gguf в data/models (llama-cpp-python)."""

    def __init__(
        self,
        settings: Settings | None = None,
        model_path: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.models_dir = self.settings.data_dir / "models"
        self.model_path = model_path or resolve_gguf_path(
            self.models_dir, self.settings.zipka_gguf_model
        )
        if self.model_path is None:
            raise LlmError(
                f"В {self.models_dir} нет файлов .gguf. "
                "Скачай GGUF-модель и положи её туда."
            )
        self.model_name = self.model_path.name
        self._llm: Any = None

    @property
    def backend(self) -> str:
        return "gguf"

    def is_available(self) -> bool:
        if self.model_path is None or not self.model_path.is_file():
            return False
        try:
            import llama_cpp  # noqa: F401
        except ImportError:
            return False
        return True

    def list_models(self) -> list[str]:
        return [p.name for p in find_gguf_files(self.models_dir)]

    def _ensure_loaded(self) -> Any:
        if self._llm is not None:
            return self._llm
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise LlmError(
                "Для локальных GGUF нужен пакет llama-cpp-python:\n"
                "  pip install llama-cpp-python\n"
                "На Windows удобнее CPU-колесо с PyPI; для GPU см. docs llama-cpp-python."
            ) from exc

        n_ctx = max(512, int(self.settings.zipka_gguf_ctx))
        n_gpu = int(self.settings.zipka_gguf_gpu_layers)
        n_threads = int(self.settings.zipka_gguf_threads) or None
        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu,
            n_threads=n_threads,
            verbose=False,
        )
        return self._llm

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        images: list[str] | None = None,
    ) -> str:
        if images:
            raise LlmError(
                "Vision/картинки в GGUF-режиме пока не поддерживаются. "
                "Для глаз нужен Ollama с vision-моделью."
            )
        if stream:
            # простой non-stream ответ; стрим можно добавить позже
            pass
        if model and model != self.model_name:
            # переключение по имени файла из data/models
            alt = resolve_gguf_path(self.models_dir, model)
            if alt and alt != self.model_path:
                self.model_path = alt
                self.model_name = alt.name
                self._llm = None

        llm = self._ensure_loaded()
        # llama.cpp ждёт messages без лишних полей
        clean = [{"role": m["role"], "content": m.get("content") or ""} for m in messages]
        try:
            result = llm.create_chat_completion(
                messages=clean,
                temperature=0.7,
                max_tokens=max(256, int(self.settings.zipka_gguf_max_tokens)),
            )
        except Exception as exc:
            raise LlmError(f"Ошибка GGUF chat ({self.model_name}): {exc}") from exc

        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return (message.get("content") or "").strip()

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
