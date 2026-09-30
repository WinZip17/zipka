"""Фасад агента Зипка: composition root + тонкие обёртки."""
from __future__ import annotations

import threading
from typing import Any

from zipka.books.reader import BookReader
from zipka.character.persona import Persona
from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.evolve.finetune import FinetuneEvolve
from zipka.evolve.hard import HardEvolve
from zipka.evolve.soft import SoftEvolve
from zipka.llm.factory import LlmRouter, create_llm_client
from zipka.llm.vision import VisionGgufClient
from zipka.memory.store import MemoryStore
from zipka.memory.user_profile import UserProfiler
from zipka.mind.goals import PseudoMind
from zipka.mind.proactive import ProactiveEngine
from zipka.net.learner import NetLearner
from zipka.news import NewsDesk
from zipka.safety.policy import SafetyPolicy
from zipka.sensors.ears import Ears
from zipka.sensors.eyes import Eyes

from . import books_intent, prompting, runtime, vision_intent
from .chat_pipeline import ChatCtx, run_chat_pipeline


class Zipka:
    FINETUNE_BUSY_MSG = (
        "Сейчас идёт дообучение модели. Подожди окончания "
        "или сбрось его в Настройки → Дообучение."
    )

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.llm = create_llm_client(self.settings)
        self.memory = MemoryStore(self.settings)
        self.persona = Persona(self.settings)
        self.soft = SoftEvolve(self.persona, self.memory, self.llm)
        self.hard = HardEvolve(self._code_llm(), self.memory, self.settings)
        self.finetune = FinetuneEvolve(self.memory, self.settings)
        self.books = BookReader(self.llm, self.memory, self.settings)
        self.eyes = Eyes(self.settings)
        self.ears = Ears(self.settings)
        self.user = UserProfiler(self.memory, self.llm, self.settings)
        self.mind = PseudoMind(
            self.persona, self.memory, self.llm, self.soft, self.settings
        )
        self.proactive = ProactiveEngine(
            self.llm, self.memory, self.mind, self.settings
        )
        self.net = NetLearner(self.llm, self.memory, self.settings)
        self.news = NewsDesk(self.llm, self.memory, self.settings)
        self.safety = SafetyPolicy()
        self.vision = VisionGgufClient(self.settings)
        self.uploads_dir = self.settings.data_dir / "books" / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._reset_pending = False
        self._chat_busy = False

    # --- busy / runtime ---

    def is_chat_busy(self) -> bool:
        return bool(self._chat_busy)

    def is_finetune_busy(self) -> bool:
        return runtime.is_finetune_busy(self)

    def unload_inference_models(self) -> None:
        runtime.unload_inference_models(self)

    def start_finetune_approved(self) -> dict[str, Any]:
        return runtime.start_finetune_approved(self)

    def _code_llm(self) -> Any:
        return runtime.code_llm(self)

    def reload_runtime(self) -> None:
        runtime.reload_runtime(self)

    def reset_learning(self, *, confirm: bool = False) -> dict[str, Any]:
        return runtime.reset_learning(self, confirm=confirm)

    def status(self) -> dict[str, Any]:
        return runtime.status(self)

    def _reload_llm(self) -> dict[str, Any]:
        return runtime.reload_llm(self)

    def set_compute(
        self,
        mode: str,
        *,
        gpu_layers: int | None = None,
    ) -> dict[str, Any]:
        return runtime.set_compute(self, mode, gpu_layers=gpu_layers)

    def set_chat_model(self, model_id: str) -> dict[str, Any]:
        return self.set_models(chat_gguf=model_id)

    def set_models(
        self,
        *,
        chat_gguf: str | None = None,
        code_gguf: str | None = None,
    ) -> dict[str, Any]:
        return runtime.set_models(self, chat_gguf=chat_gguf, code_gguf=code_gguf)

    # --- prompting / chat ---

    def build_messages(
        self,
        user_text: str,
        *,
        reply_context: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        return prompting.build_messages(
            self, user_text, reply_context=reply_context
        )

    def chat(
        self,
        user_text: str,
        *,
        auto_soft: bool = True,
        reply_to: dict[str, Any] | None = None,
        reply_chain: list[dict[str, Any]] | None = None,
    ) -> str:
        if self.is_finetune_busy():
            return self.FINETUNE_BUSY_MSG
        self._chat_busy = True
        try:
            return self._chat_inner(
                user_text,
                auto_soft=auto_soft,
                reply_to=reply_to,
                reply_chain=reply_chain,
            )
        finally:
            self._chat_busy = False
            try:
                if not self.is_finetune_busy():
                    self.news.on_chat_idle()
            except Exception:
                pass

    def _chat_inner(
        self,
        user_text: str,
        *,
        auto_soft: bool = True,
        reply_to: dict[str, Any] | None = None,
        reply_chain: list[dict[str, Any]] | None = None,
    ) -> str:
        text = user_text.strip()
        if not text:
            return "Пусто. Скажи что-нибудь."
        reply_context = prompting.normalize_reply_context(reply_chain, reply_to)
        return run_chat_pipeline(
            self,
            ChatCtx(text=text, auto_soft=auto_soft, reply_context=reply_context),
        )

    def _schedule_post_chat(
        self,
        user_text: str,
        reply: str,
        *,
        reflect: bool,
        observe: bool,
    ) -> None:
        def _job() -> None:
            try:
                if observe:
                    try:
                        self.user.observe_dialogue(user_text, reply)
                    except Exception:
                        pass
                    finally:
                        self.user._turn_alert = None
                elif self.user._turn_alert is not None:
                    self.user._turn_alert = None
                if reflect:
                    try:
                        self.mind.reflect()
                    except Exception:
                        pass
            except Exception:
                pass

        threading.Thread(target=_job, name="zipka-post-chat", daemon=True).start()

    def _after_code_role(self) -> None:
        """После патча заранее вернуть чатовую GGUF в память (фон)."""
        if not isinstance(self.llm, LlmRouter):
            return
        if self.llm.same_model():
            return

        def _preload() -> None:
            try:
                self.llm.preload_chat()
            except Exception:
                pass

        threading.Thread(
            target=_preload, name="zipka-preload-chat", daemon=True
        ).start()

    # --- books ---

    def try_read_url_from_message(self, text: str) -> str | None:
        return books_intent.try_read_url_from_message(self, text)

    def try_read_from_message(self, text: str) -> str | None:
        return books_intent.try_read_from_message(self, text)

    def ingest_uploaded_book(
        self,
        filename: str,
        content: bytes,
        *,
        member: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        return books_intent.ingest_uploaded_book(
            self, filename, content, member=member, comment=comment
        )

    @staticmethod
    def _extract_comment(text: str) -> str | None:
        return books_intent.extract_comment(text)

    @staticmethod
    def _extract_mode(text: str) -> str | None:
        return books_intent.extract_mode(text)

    @staticmethod
    def _extract_max_files(text: str) -> int | None:
        return books_intent.extract_max_files(text)

    @staticmethod
    def _extract_book_path(text: str):
        return books_intent.extract_book_path(text)

    # --- vision / proactive ---

    def greet(self, *, force: bool = False) -> str | None:
        if self.is_finetune_busy():
            return None
        return self.proactive.greeting(force=force)

    def rare_ping(self, *, force: bool = False) -> str | None:
        if self.is_finetune_busy():
            return None
        return self.proactive.maybe_rare_ping(force=force)

    def try_look_from_message(self, text: str) -> str | None:
        return vision_intent.try_look_from_message(self, text)

    def comment_eyes(self, description: str) -> str | None:
        return vision_intent.comment_eyes(self, description)

    def comment_ears(self, heard: str) -> str | None:
        return vision_intent.comment_ears(self, heard)

    def describe_image(self, image_b64: str, prompt: str = "Что ты видишь?") -> str:
        return vision_intent.describe_image(self, image_b64, prompt=prompt)

    def _remember_turn(
        self,
        user_text: str,
        reply: str,
        *,
        reply_to: dict[str, Any] | None = None,
    ) -> None:
        self.memory.add_chat("user", user_text, reply_to=reply_to)
        self.memory.add_chat("assistant", reply)

    @staticmethod
    def _normalize_reply_context(
        reply_chain: list[dict[str, Any]] | None,
        reply_to: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return prompting.normalize_reply_context(reply_chain, reply_to)
