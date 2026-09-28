from __future__ import annotations

from pathlib import Path
from typing import Any

from zipka.config import Settings, get_settings
from zipka.llm.base import LlmError
from zipka.llm.sanitize import strip_thinking
from zipka.runtime_settings import resolve_gpu_layers


def probe_llama_cpp() -> tuple[bool, str]:
    """Проверить, что llama_cpp реально грузится (не только установлен).

    CUDA-колесо без DLL CUDA даёт RuntimeError/OSError на import — это не ImportError.
    """
    try:
        import llama_cpp  # noqa: F401
    except ImportError as exc:
        return False, f"llama-cpp-python не установлен: {exc}"
    except Exception as exc:
        return False, (
            f"llama-cpp-python не загружается ({type(exc).__name__}: {exc}). "
            "Часто это CUDA-колесо без CUDA DLL. Верни CPU-сборку:\n"
            "  pip uninstall llama-cpp-python -y\n"
            "  pip install llama-cpp-python --only-binary=:all: "
            "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu"
        )
    return True, ""


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
        self._loaded_ctx: int | None = None
        self._loaded_gpu: int | None = None
        self._n_layer: int | None = None
        self._n_threads: int | None = None

    @property
    def backend(self) -> str:
        return "gguf"

    def unload(self) -> None:
        llm = self._llm
        self._llm = None
        self._loaded_ctx = None
        self._loaded_gpu = None
        self._n_layer = None
        self._n_threads = None
        if llm is not None:
            close = getattr(llm, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def is_available(self) -> bool:
        if self.model_path is None or not self.model_path.is_file():
            return False
        ok, _ = probe_llama_cpp()
        return ok

    def load_error(self) -> str:
        ok, err = probe_llama_cpp()
        return "" if ok else err

    def list_models(self) -> list[str]:
        return [p.name for p in find_gguf_files(self.models_dir)]

    def load_info(self) -> dict[str, Any]:
        """Фактические параметры загруженной (или желаемой) модели."""
        want_gpu = int(resolve_gpu_layers(self.settings))
        n_layer = self._n_layer
        gpu_eff = want_gpu
        if want_gpu < 0:
            gpu_eff = n_layer if n_layer else -1
        elif n_layer is not None:
            gpu_eff = min(want_gpu, n_layer)
        cpu_layers = None
        if n_layer is not None and gpu_eff is not None and gpu_eff >= 0:
            cpu_layers = max(0, n_layer - int(gpu_eff))
        return {
            "n_layer": n_layer,
            "n_gpu_layers_requested": want_gpu,
            "n_gpu_layers_effective": gpu_eff if self._llm is not None else None,
            "n_cpu_layers": cpu_layers if self._llm is not None else None,
            "n_threads": self._n_threads,
            "loaded": self._llm is not None,
        }

    def _desired_ctx(self) -> int:
        return max(2048, int(self.settings.zipka_gguf_ctx))

    @staticmethod
    def _resolve_threads(settings: Settings) -> int:
        import os

        configured = int(settings.zipka_gguf_threads or 0)
        if configured > 0:
            return configured
        return max(1, os.cpu_count() or 4)

    @staticmethod
    def _read_n_layer(llm: Any) -> int | None:
        meta = getattr(llm, "metadata", None) or {}
        for key in (
            "llama.block_count",
            "qwen2.block_count",
            "qwen3.block_count",
            "gemma.block_count",
            "gemma2.block_count",
        ):
            raw = meta.get(key)
            if raw is None:
                continue
            try:
                return int(raw)
            except (TypeError, ValueError):
                continue
        # fallback: любое *.block_count
        for key, raw in meta.items():
            if str(key).endswith(".block_count"):
                try:
                    return int(raw)
                except (TypeError, ValueError):
                    continue
        return None

    def _ensure_loaded(self) -> Any:
        want_ctx = self._desired_ctx()
        want_gpu = int(resolve_gpu_layers(self.settings))
        want_threads = self._resolve_threads(self.settings)
        if (
            self._llm is not None
            and self._loaded_ctx == want_ctx
            and self._loaded_gpu == want_gpu
            and self._n_threads == want_threads
        ):
            return self._llm
        try:
            from llama_cpp import Llama
        except ImportError as exc:
            raise LlmError(
                "Для локальных GGUF нужен пакет llama-cpp-python:\n"
                "  pip install llama-cpp-python --only-binary=:all: "
                "--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu"
            ) from exc

        self.unload()
        kwargs: dict[str, Any] = {
            "model_path": str(self.model_path),
            "n_ctx": want_ctx,
            "n_gpu_layers": want_gpu,
            "n_threads": want_threads,
            "n_threads_batch": want_threads,
            "verbose": False,
        }
        try:
            self._llm = Llama(**kwargs)
        except TypeError:
            kwargs.pop("n_threads_batch", None)
            self._llm = Llama(**kwargs)
        self._loaded_ctx = want_ctx
        self._loaded_gpu = want_gpu
        self._n_threads = want_threads
        self._n_layer = self._read_n_layer(self._llm)
        return self._llm

    def _estimate_tokens(self, llm: Any, messages: list[dict[str, str]]) -> int:
        """Грубая/точная оценка токенов промпта."""
        blob = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content') or ''}" for m in messages
        )
        try:
            # llama.cpp tokenizer
            return len(llm.tokenize(blob.encode("utf-8"), add_bos=True))
        except Exception:
            # кириллица ~2–3 символа/токен; с запасом
            return max(32, len(blob) // 2 + 16 * len(messages))

    def _fit_messages(
        self,
        llm: Any,
        messages: list[dict[str, str]],
        *,
        n_ctx: int,
        max_out: int,
    ) -> tuple[list[dict[str, str]], int]:
        """Урезает историю/system так, чтобы prompt + max_out влезли в n_ctx."""
        reserve = max(128, int(max_out)) + 64
        budget = max(512, n_ctx - reserve)

        fitted = [dict(m) for m in messages]
        # сначала укорачиваем system
        for m in fitted:
            if m.get("role") == "system" and len(m.get("content") or "") > 6000:
                m["content"] = (m["content"] or "")[:6000] + "\n…"

        def fits(msgs: list[dict[str, str]]) -> bool:
            return self._estimate_tokens(llm, msgs) <= budget

        # выкидываем старые реплики истории (оставляем system + последний user)
        while len(fitted) > 2 and not fits(fitted):
            # индекс 1 — первая после system
            if fitted[0].get("role") == "system":
                del fitted[1]
            else:
                del fitted[0]

        # ещё режем system / последний user
        if not fits(fitted):
            for m in fitted:
                content = m.get("content") or ""
                if len(content) > 2500:
                    m["content"] = content[:2500] + "\n…"
        if not fits(fitted):
            for m in fitted:
                content = m.get("content") or ""
                if len(content) > 1200:
                    m["content"] = content[:1200] + "\n…"

        prompt_tokens = self._estimate_tokens(llm, fitted)
        # max_tokens не должен выталкивать за ctx
        allowed_out = max(64, min(max_out, n_ctx - prompt_tokens - 32))
        if prompt_tokens >= n_ctx - 64:
            raise LlmError(
                f"Промпт (~{prompt_tokens} tok) не влезает в ctx={n_ctx}. "
                f"Увеличь ZIPKA_GGUF_CTX в .env (сейчас {self.settings.zipka_gguf_ctx}) "
                "и перезапусти Зипку."
            )
        return fitted, allowed_out

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        model: str | None = None,
        stream: bool = False,
        images: list[str] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if images:
            raise LlmError(
                "Vision/картинки в GGUF-режиме пока не поддерживаются. "
                "Для глаз нужен Ollama с vision-моделью."
            )
        if stream:
            pass
        if model and model != self.model_name:
            alt = resolve_gguf_path(self.models_dir, model)
            if alt and alt != self.model_path:
                self.model_path = alt
                self.model_name = alt.name
                self._llm = None
                self._loaded_ctx = None

        llm = self._ensure_loaded()
        clean = [
            {"role": str(m.get("role") or "user"), "content": m.get("content") or ""}
            for m in messages
        ]
        temp = 0.7 if temperature is None else float(temperature)
        want_out = (
            int(max_tokens)
            if max_tokens is not None
            else int(self.settings.zipka_gguf_max_tokens)
        )
        want_out = max(64, min(want_out, 2048))
        n_ctx = int(getattr(llm, "n_ctx", lambda: self._desired_ctx())())
        fitted, out_tokens = self._fit_messages(
            llm, clean, n_ctx=n_ctx, max_out=want_out
        )
        try:
            kwargs: dict[str, Any] = {
                "messages": fitted,
                "temperature": temp,
                "max_tokens": out_tokens,
            }
            # Qwen3: по возможности сразу без thinking-блоков
            try:
                result = llm.create_chat_completion(
                    **kwargs,
                    chat_template_kwargs={"enable_thinking": False},
                )
            except TypeError:
                result = llm.create_chat_completion(**kwargs)
        except Exception as exc:
            msg = str(exc)
            if "exceed context" in msg.lower() or "context window" in msg.lower():
                raise LlmError(
                    f"Контекст переполнен ({self.model_name}): {msg}. "
                    f"Поставь ZIPKA_GGUF_CTX=8192 (или больше) в .env и перезапусти."
                ) from exc
            raise LlmError(f"Ошибка GGUF chat ({self.model_name}): {exc}") from exc

        choice = (result.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        return strip_thinking(message.get("content") or "")

    def summarize(self, text: str, *, instruction: str) -> str:
        messages = [
            {
                "role": "system",
                "content": "Ты Зипка. Кратко и по делу. Отвечай на русском.",
            },
            {
                "role": "user",
                "content": f"{instruction}\n\n---\n{text[:8000]}",
            },
        ]
        return self.chat(messages, max_tokens=1024)
