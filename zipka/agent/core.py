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
from zipka.net.search import WebSearch
from zipka.news import NewsDesk
from zipka.safety.policy import SafetyPolicy
from zipka.sensors.ears import Ears
from zipka.sensors.eyes import Eyes

from . import books_intent, prompting, runtime, vision_intent
from .chat_pipeline import ChatCtx, run_chat_pipeline
from .pending_turn import PendingTurnTracker


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
        self.soft = SoftEvolve(
            self.persona, self.memory, self.llm, settings=self.settings
        )
        self.hard = HardEvolve(self._code_llm(), self.memory, self.settings)
        self.finetune = FinetuneEvolve(self.memory, self.settings)
        self.books = BookReader(self.llm, self.memory, self.settings)
        self.books.on_phase = self.set_chat_phase
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
        self.search = WebSearch(self.llm, self.memory, self.net, self.settings)
        self.news = NewsDesk(self.llm, self.memory, self.settings)
        self.safety = SafetyPolicy()
        self.vision = VisionGgufClient(self.settings)
        self.uploads_dir = self.settings.data_dir / "books" / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._reset_pending = False
        self._chat_busy = False
        self.pending_turn = PendingTurnTracker(
            self.settings.data_dir / "mind" / "chat_pending.json"
        )
        # После рестарта процесса старый pending с диска неактуален
        self.pending_turn.clear()

    # --- busy / runtime ---

    def is_chat_busy(self) -> bool:
        return bool(self._chat_busy) or self.pending_turn.active()

    def set_chat_phase(self, phase: str, label: str | None = None) -> None:
        self.pending_turn.set_phase(phase, label)

    def chat_pending_status(self) -> dict[str, Any] | None:
        return self.pending_turn.snapshot()

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

    def reset_finetune(self, *, confirm_phrase: str) -> dict[str, Any]:
        return runtime.reset_finetune(self, confirm_phrase=confirm_phrase)

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

    def set_soft_evolve_from_dialogue(self, enabled: bool) -> dict[str, Any]:
        return runtime.set_soft_evolve_from_dialogue(self, enabled)

    def set_sensors_enabled(self, enabled: bool) -> dict[str, Any]:
        return runtime.set_sensors_enabled(self, enabled)

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
        if self.pending_turn.active() or self._chat_busy:
            return (
                "Я ещё отвечаю на предыдущее сообщение. "
                "Подожди или обнови ленту — ответ появится сам."
            )
        text = user_text.strip()
        if not text:
            return "Пусто. Скажи что-нибудь."

        reply_context = prompting.normalize_reply_context(reply_chain, reply_to)
        reply_to_last = reply_context[-1] if reply_context else None

        # Сразу в историю + pending (файл): F5 не должен съесть вопрос/статус
        self.pending_turn.begin(
            user_text=text,
            phase="replying",
            kind="chat",
            reply_to=reply_to_last,
        )
        self.memory.add_chat("user", text, reply_to=reply_to_last)
        self.pending_turn.mark_user_saved()
        try:
            self.proactive.note_user_activity()
        except Exception:
            pass
        self._chat_busy = True
        self._last_chat_reply: str | None = None

        done = threading.Event()

        def _worker() -> None:
            try:
                reply = run_chat_pipeline(
                    self,
                    ChatCtx(
                        text=text,
                        auto_soft=auto_soft,
                        reply_context=reply_context,
                    ),
                )
                self._ensure_assistant_saved(reply)
                self._last_chat_reply = reply
            except Exception as exc:
                err = f"Не смогла ответить: {exc}"
                self._ensure_assistant_saved(err)
                self._last_chat_reply = err
            finally:
                self._chat_busy = False
                self.pending_turn.clear()
                done.set()
                try:
                    if not self.is_finetune_busy():
                        self.news.on_chat_idle()
                except Exception:
                    pass

        # Отдельный поток: обрыв HTTP (F5) не отменяет генерацию и не сбрасывает pending
        threading.Thread(
            target=_worker, name="zipka-chat-turn", daemon=True
        ).start()
        done.wait()
        return self._last_chat_reply or ""

    def _chat_inner(
        self,
        user_text: str,
        *,
        auto_soft: bool = True,
        reply_to: dict[str, Any] | None = None,
        reply_chain: list[dict[str, Any]] | None = None,
    ) -> str:
        """Совместимость: прямой вызов без pending (редко). Предпочтителен chat()."""
        text = user_text.strip()
        if not text:
            return "Пусто. Скажи что-нибудь."
        reply_context = prompting.normalize_reply_context(reply_chain, reply_to)
        return run_chat_pipeline(
            self,
            ChatCtx(text=text, auto_soft=auto_soft, reply_context=reply_context),
        )

    def _ensure_assistant_saved(self, reply: str) -> None:
        """Если хендлер не вызвал _remember_turn — дописать ответ сами."""
        if self.pending_turn.assistant_saved():
            return
        if not self.pending_turn.user_saved():
            return
        self.memory.add_chat("assistant", reply)
        self.pending_turn.mark_assistant_saved()

    def run_with_pending(
        self,
        *,
        user_text: str,
        phase: str,
        kind: str,
        label: str | None = None,
        reply_to: dict[str, Any] | None = None,
        save_user: bool = True,
    ):
        """Контекст для upload/learn: pending + опционально user в историю."""
        from contextlib import contextmanager

        @contextmanager
        def _cm():
            self.pending_turn.begin(
                user_text=user_text,
                phase=phase,
                label=label,
                kind=kind,
                reply_to=reply_to,
            )
            if save_user:
                self.memory.add_chat("user", user_text, reply_to=reply_to)
                self.pending_turn.mark_user_saved()
            self._chat_busy = True
            try:
                yield self
            finally:
                self._chat_busy = False
                self.pending_turn.clear()

        return _cm()

    def _schedule_post_chat(
        self,
        user_text: str,
        reply: str,
        *,
        reflect: bool,
        observe: bool,
        soft_dialogue: bool = True,
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
                if soft_dialogue:
                    try:
                        self.soft.maybe_propose_from_dialogue(user_text, reply)
                    except Exception:
                        pass
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
        return self.proactive.maybe_rare_ping(
            force=force,
            restudy=self._restudy_note_for_ping,
        )

    def _restudy_note_for_ping(self, note: dict[str, Any]) -> dict[str, Any]:
        """Перечитать исходник заметки (URL/файл), иначе выжимку/текст заметки."""
        from pathlib import Path

        meta = dict(note.get("meta") or {})
        kind = str(note.get("kind") or "book")
        note_text = str(note.get("text") or "").strip()
        source_label = str(
            meta.get("title")
            or meta.get("source")
            or meta.get("url")
            or meta.get("path")
            or kind
        )

        def _summarize_raw(raw: str, *, label: str) -> str:
            raw = (raw or "").strip()
            if len(raw) < 40:
                return ""
            if not self.llm.is_available():
                return raw[:3000]
            instruction = (
                "Перечитай материал и сделай свежую краткую выжимку для Зипки: "
                "ключевые факты, термины, спорные места. Без воды, по-русски."
            )
            try:
                return self.llm.summarize(raw[:12_000], instruction=instruction)
            except Exception:
                return raw[:3000]

        # 1) URL
        url = meta.get("url") or meta.get("source_url")
        if not url and kind == "net_search":
            urls = meta.get("urls") or []
            if isinstance(urls, list) and urls:
                url = urls[0]
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            try:
                self.net._assert_safe_url(url)
                raw = self.net._fetch_text(url)
                digest = _summarize_raw(raw, label=url)
                if digest:
                    return {"source": url, "digest": digest, "kind": kind}
            except Exception:
                pass

        # 2) Локальный файл
        path_raw = meta.get("path") or meta.get("source")
        if isinstance(path_raw, str) and path_raw.strip():
            path = Path(path_raw)
            try:
                if path.is_file():
                    load = getattr(self.books, "_load_text", None)
                    raw = load(path) if callable(load) else path.read_text(
                        encoding="utf-8", errors="ignore"
                    )
                    digest = _summarize_raw(str(raw), label=str(path))
                    if digest:
                        return {
                            "source": str(path),
                            "digest": digest,
                            "kind": kind,
                        }
            except Exception:
                pass

        # 3) Сохранённая выжимка books/notes
        digest_path = meta.get("digest_path")
        if isinstance(digest_path, str) and digest_path.strip():
            dp = Path(digest_path)
            try:
                if dp.is_file():
                    body = dp.read_text(encoding="utf-8", errors="ignore")
                    if body.strip():
                        return {
                            "source": str(dp),
                            "digest": body[:8000],
                            "kind": kind,
                        }
            except Exception:
                pass

        # 4) Текст заметки
        return {
            "source": source_label,
            "digest": note_text,
            "kind": kind,
        }

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
        # User уже записан в chat() / run_with_pending — только ответ
        if self.pending_turn.user_saved() and not self.pending_turn.assistant_saved():
            self.memory.add_chat("assistant", reply)
            self.pending_turn.mark_assistant_saved()
            return
        if self.pending_turn.assistant_saved():
            return
        self.memory.add_chat("user", user_text, reply_to=reply_to)
        self.memory.add_chat("assistant", reply)

    @staticmethod
    def _normalize_reply_context(
        reply_chain: list[dict[str, Any]] | None,
        reply_to: dict[str, Any] | None,
    ) -> list[dict[str, Any]]:
        return prompting.normalize_reply_context(reply_chain, reply_to)
