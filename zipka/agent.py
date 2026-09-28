from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from zipka.books.reader import (
    ARCHIVE_SUFFIXES,
    READABLE_SUFFIXES,
    BookReader,
)
from zipka.character.persona import Persona
from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.evolve.hard import APPROVE_PHRASE, HardEvolve
from zipka.evolve.soft import SoftEvolve
from zipka.llm.base import LlmError
from zipka.llm.chat_models import models_status, resolve_role_gguf
from zipka.llm.factory import LlmRouter, create_llm_client, describe_backend
from zipka.llm.ollama_client import OllamaError
from zipka.llm.vision import VisionGgufClient, vision_status
from zipka.memory.store import MemoryStore
from zipka.memory.user_profile import UserProfiler
from zipka.mind.goals import PseudoMind
from zipka.mind.proactive import ProactiveEngine
from zipka.net.learner import NetLearner
from zipka.reset import (
    CONFIRM_PHRASE,
    is_reset_confirm,
    is_reset_request,
    reset_learning_data,
)
from zipka.runtime_settings import compute_status, save_runtime
from zipka.safety.policy import SafetyPolicy
from zipka.sensors.ears import Ears
from zipka.sensors.eyes import Eyes

_FILE_EXTS = "|".join(
    re.escape(ext.lstrip(".")) for ext in sorted(READABLE_SUFFIXES | ARCHIVE_SUFFIXES)
)
_PATH_RE = re.compile(
    rf'(?P<q>["\'])(?P<p1>[^"\']+\.(?:{_FILE_EXTS})(?![A-Za-z0-9]))(?P=q)'
    rf'|(?P<p2>(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?!/)|\\)'
    rf'[^\s"\']+\.(?:{_FILE_EXTS})(?![A-Za-z0-9]))',
    re.IGNORECASE,
)
_DIR_PATH_RE = re.compile(
    rf'(?P<q>["\'])(?P<d1>(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?!/)|\\)[^"\']+)(?P=q)'
    rf'|(?P<d2>(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?!/)|\\)[^\s"\']+)',
    re.IGNORECASE,
)
_READ_INTENT = re.compile(
    r"(прочитай|прочти|прочесть|прочитать|читай|открой\s+(?:книг|стать|ссылк|url|страниц)|"
    r"прочитай\s+(?:книг|стать|ссылк|url)|read\s+(?:the\s+)?(?:book|article|page|url|link)|"
    r"изучи(?:\s+папк\w*|те)?|разбери|проанализируй|изучить|study|analyze|"
    r"обучись\s+на|обуч\w*\s+по\s+папк|"
    r"что\s+в\s+архиве|список\s+(?:файлов\s+)?(?:в\s+)?архиве|"
    r"list\s+archive)",
    re.IGNORECASE,
)
_LIST_INTENT = re.compile(
    r"(что\s+в\s+архиве|список\s+(?:файлов\s+)?(?:в\s+)?архиве|list\s+archive|--list)",
    re.IGNORECASE,
)
_MEMBER_RE = re.compile(
    rf"(?:внутри|файл(?:ом)?|member|-m)\s+(?P<q>['\"])?(?P<name>[^\s'\"]+\.(?:{_FILE_EXTS}))(?P=q)?",
    re.IGNORECASE,
)
_COMMENT_RE = re.compile(
    r"(?:комментарий|учти|с\s+комментарием|фокус|note|comment)\s*[:\-–—]\s*(?P<c>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_MODE_RE = re.compile(
    r"(?:mode|режим|только)\s*[:\s]+(?P<m>books?|code|код|книг\w*|auto|вс[её])",
    re.IGNORECASE,
)
_EDITS_RE = re.compile(
    r"(предложи\s+правк|с\s+правкам|и\s+правк|propose\s+edits|--edits)",
    re.IGNORECASE,
)
_MAX_FILES_RE = re.compile(
    r"(?:макс(?:имум)?|max(?:[_-]?files)?|файлов)\s*[=:]?\s*(?P<n>\d+)",
    re.IGNORECASE,
)


class Zipka:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.llm = create_llm_client(self.settings)
        self.memory = MemoryStore(self.settings)
        self.persona = Persona(self.settings)
        self.soft = SoftEvolve(self.persona, self.memory, self.llm)
        self.hard = HardEvolve(self._code_llm(), self.memory, self.settings)
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
        self.safety = SafetyPolicy()
        self.vision = VisionGgufClient(self.settings)
        self.uploads_dir = self.settings.data_dir / "books" / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._reset_pending = False

    def _code_llm(self) -> Any:
        if isinstance(self.llm, LlmRouter):
            return self.llm.code_llm
        return self.llm

    def reload_runtime(self) -> None:
        """Пересоздать модули после очистки data/."""
        ensure_data_dirs(self.settings)
        try:
            self.eyes.off()
        except Exception:
            pass
        self.llm = create_llm_client(self.settings)
        self.memory = MemoryStore(self.settings)
        self.persona = Persona(self.settings)
        self.soft = SoftEvolve(self.persona, self.memory, self.llm)
        self.hard = HardEvolve(self._code_llm(), self.memory, self.settings)
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
        self.safety = SafetyPolicy()
        self.vision = VisionGgufClient(self.settings)
        self.uploads_dir = self.settings.data_dir / "books" / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._reset_pending = False

    def reset_learning(self, *, confirm: bool = False) -> dict[str, Any]:
        result = reset_learning_data(self.settings, confirm=confirm)
        self.reload_runtime()
        return result

    def status(self) -> dict[str, Any]:
        from zipka.system_limits import available_ram_bytes, format_bytes, max_book_bytes

        backend_info = describe_backend(self.llm)
        llm_ok = self.llm.is_available()
        models = []
        if llm_ok:
            try:
                models = self.llm.list_models()
            except (OllamaError, LlmError):
                models = []
        book_limit = max_book_bytes()
        avail = available_ram_bytes()
        model_name = backend_info.get("model") or self.settings.ollama_model
        roles = models_status(self.settings)
        file_names = [f["filename"] for f in roles.get("files") or []] or models
        return {
            "name": "Зипка",
            "ollama": llm_ok if backend_info.get("backend") == "ollama" else False,
            "llm": backend_info,
            "models": file_names,
            "model": model_name,
            "vision_model": (
                (vision_status(self.settings).get("filename"))
                or self.settings.vision_model
            ),
            "vision": vision_status(self.settings),
            "eyes": self.eyes.enabled,
            "ears": self.ears.enabled,
            "pending_patch": self.hard.has_pending(),
            "approve_phrase": APPROVE_PHRASE,
            "mind": self.mind.load(),
            "proactive": self.proactive.rare_ping_status(),
            "limits": {
                "max_book_bytes": book_limit,
                "max_book_human": format_bytes(book_limit),
                "ram_available_bytes": avail,
                "ram_available_human": format_bytes(avail) if avail else None,
            },
            "user": self.user.summary_for_ui(),
            "compute": compute_status(
                self.settings,
                load_info=getattr(self.llm, "load_info", lambda: None)(),
            ),
            "chat_models": roles,
            "model_roles": roles,
        }

    def _reload_llm(self) -> dict[str, Any]:
        if hasattr(self.llm, "unload"):
            try:
                self.llm.unload()
            except Exception:
                pass
        self.llm = create_llm_client(self.settings)
        code = self._code_llm()
        for holder in (
            self.soft,
            self.books,
            self.mind,
            self.proactive,
            self.net,
            self.user,
        ):
            if hasattr(holder, "llm"):
                holder.llm = self.llm
        self.hard.llm = code
        return {
            "llm": describe_backend(self.llm),
            "chat_models": models_status(self.settings),
            "models": models_status(self.settings),
        }

    def set_compute(
        self,
        mode: str,
        *,
        gpu_layers: int | None = None,
    ) -> dict[str, Any]:
        """Переключить CPU / GPU / hybrid и перезагрузить LLM."""
        patch: dict[str, Any] = {"compute_mode": mode}
        if gpu_layers is not None:
            patch["gpu_layers"] = gpu_layers
        save_runtime(patch, self.settings)
        reloaded = self._reload_llm()
        load_info = None
        if hasattr(self.llm, "load_info"):
            load_info = self.llm.load_info()
        return {
            "ok": True,
            "compute": compute_status(self.settings, load_info=load_info),
            **reloaded,
        }

    def set_chat_model(self, model_id: str) -> dict[str, Any]:
        """Переключить чатовую модель (filename или legacy id)."""
        return self.set_models(chat_gguf=model_id)

    def set_models(
        self,
        *,
        chat_gguf: str | None = None,
        code_gguf: str | None = None,
    ) -> dict[str, Any]:
        """Выбрать GGUF для чата и/или кодинга (можно одну и ту же)."""
        patch: dict[str, Any] = {}
        if chat_gguf:
            name = Path(str(chat_gguf).strip()).name
            if resolve_role_gguf("chat", self.settings, filename=name) is None:
                raise ValueError(
                    f"Файл «{name}» не найден в {self.settings.data_dir / 'models'}"
                )
            patch["chat_gguf"] = name
        if code_gguf:
            name = Path(str(code_gguf).strip()).name
            if resolve_role_gguf("code", self.settings, filename=name) is None:
                raise ValueError(
                    f"Файл «{name}» не найден в {self.settings.data_dir / 'models'}"
                )
            patch["code_gguf"] = name
        if not patch:
            raise ValueError("Укажи chat_gguf и/или code_gguf")
        save_runtime(patch, self.settings)
        reloaded = self._reload_llm()
        return {"ok": True, **reloaded}

    def build_messages(
        self,
        user_text: str,
        *,
        reply_context: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        note_limit = 4 if getattr(self.llm, "backend", "") == "gguf" else 8
        hist_limit = 6 if getattr(self.llm, "backend", "") == "gguf" else 16
        # короткие заметки: длинные выжимки книг иначе раздувают ctx и тормозят чат
        note_cap = 350 if getattr(self.llm, "backend", "") == "gguf" else 500
        notes = [
            (n.get("text") or "")[:note_cap]
            for n in self.memory.recent_notes(limit=note_limit)
        ]
        system = self.persona.system_prompt(
            skills=self.memory.get_skills(),
            preferences=self.memory.get_preferences(),
            notes=notes,
            mind_state=self.mind.load(),
            user_profile_block=self.user.prompt_block(),
        )
        system += (
            "\nПользователь может дать путь к книге или исходному коду "
            "(.py/.js/.ts/…), папке с кодом, zip/rar — или загрузить файл в web. "
            "Также можно дать URL статьи (https://…) со словами «прочитай/прочти» — "
            "Зипка скачает страницу и сделает выжимку."
        )
        if self.eyes.enabled:
            system += (
                "\nГлаза СЕЙЧАС ВКЛЮЧЕНЫ (веб-камера активна). "
                "Если просят посмотреть / что видишь — ты реально смотришь "
                "(система даст описание кадра). "
                "Запрещено отнекиваться: «не умею смотреть», «у меня нет глаз», "
                "«я текстовая модель», «не вижу напрямую»."
            )
        else:
            system += (
                "\nГлаза сейчас выключены. Если просят посмотреть — скажи включить "
                "глаза в UI или напиши «включи глаза», либо сама попроси включить."
            )
        system += (
            "\nЕсли просят изменить файлы zipka/ или web/ — не присылай пример кода "
            "«как будто уже сделала». Hard-evolve сам подготовит патч на approve "
            "(«разрешаю правку кода»). В обычном чате не выдавай большие блоки кода "
            "вместо реальной правки."
        )
        if reply_context:
            system += (
                "\n\nПРИОРИТЕТНЫЙ КОНТЕКСТ: пользователь нажал «ответить» на старое "
                "сообщение и продолжает ИМЕННО ту ветку разговора. "
                "Опирайся на цепочку ниже сильнее, чем на недавний общий чат. "
                "Не меняй тему на последние сообщения, если они не про это.\n"
                "Цепочка (от более раннего к сообщению, на которое ответили):\n"
            )
            for i, item in enumerate(reply_context, 1):
                role = item.get("role") or "user"
                who = "USER" if role == "user" else "ZIPKA"
                content = str(item.get("content") or "").strip()[:2500]
                if not content:
                    continue
                system += f"{i}. [{who}]: {content}\n"

        history = self.memory.recent_chat(limit=hist_limit)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(history)
        if reply_context:
            target = reply_context[-1]
            preview = str(target.get("content") or "")[:400]
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"(Ответ на сообщение: «{preview}»)\n\n{user_text}"
                    ),
                }
            )
        else:
            messages.append({"role": "user", "content": user_text})
        return messages

    def chat(
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

        reply_context = self._normalize_reply_context(reply_chain, reply_to)

        if self.safety.is_blocked(text):
            reply = self.safety.refusal()
            self._remember_turn(text, reply)
            return reply

        if self._reset_pending:
            if is_reset_confirm(text):
                result = self.reset_learning(confirm=True)
                removed_n = len(result.get("removed") or [])
                reply = (
                    f"Обучение сброшено ({removed_n} путей очищено). "
                    "Я снова с чистого листа."
                )
                # after reset chat log is empty — write first turn fresh
                self._remember_turn(text, reply)
                return reply
            if is_reset_request(text):
                reply = (
                    f"Сброс всё ещё ждёт подтверждения. "
                    f"Напиши точно: «{CONFIRM_PHRASE}» "
                    "или что угодно другое, чтобы отменить."
                )
                return reply
            self._reset_pending = False
            reply = "Сброс отменён."
            self._remember_turn(text, reply)
            return reply

        if is_reset_request(text):
            self._reset_pending = True
            reply = (
                "Это сотрёт чат, заметки, цели, книги, снимки и патчи в `data/`. "
                f"Если уверена — напиши точно: «{CONFIRM_PHRASE}». "
                "Любой другой ответ отменит сброс."
            )
            self._remember_turn(text, reply)
            return reply

        # URL раньше файлов: иначе https://habr.com ловится как s:\habr.c
        url_reply = self.try_read_url_from_message(text)
        if url_reply is not None:
            self._remember_turn(text, url_reply)
            return url_reply

        book_reply = self.try_read_from_message(text)
        if book_reply is not None:
            self._remember_turn(text, book_reply)
            return book_reply

        look_reply = self.try_look_from_message(text)
        if look_reply is not None:
            self._remember_turn(text, look_reply)
            return look_reply

        if self.hard.is_approve(text):
            if not self.hard.has_pending():
                return "Нечего утверждать — патча нет."
            meta = self.hard.apply_pending()
            rebuild = meta.get("frontend_rebuild")
            reply = (
                f"Патч {meta['id']} применён. Файлы: {', '.join(meta['files'])}. "
                f"Откат: `zipka rollback {meta['id']}`"
            )
            if rebuild:
                reply += f"\nСборка UI: {rebuild}"
            self._remember_turn(text, reply)
            self._after_code_role()
            return reply

        if self.hard.has_pending() and "патч" in text.lower():
            return self.hard.format_pending()

        code_request = self._code_change_request(text)
        if code_request:
            try:
                self_edit, project = self.hard.resolve_patch_target(code_request)
            except RuntimeError as exc:
                reply = str(exc)
                self._remember_turn(text, reply)
                return reply
            ctx = None
            notes = self.memory.recent_notes(limit=5)
            if notes:
                ctx = "\n".join(n.get("text", "") for n in notes)
            try:
                pending = self.hard.propose(
                    code_request,
                    project_root=None if self_edit else project,
                    context=ctx,
                    self_edit=self_edit,
                )
            except Exception as exc:
                reply = f"Не смогла подготовить патч: {exc}"
                self._remember_turn(text, reply)
                return reply
            reply = self.hard.format_pending(pending)
            self._remember_turn(text, reply)
            self._after_code_role()
            return reply

        if not self.llm.is_available():
            info = describe_backend(self.llm)
            if info.get("backend") == "gguf":
                return (
                    f"Локальная модель {info.get('model') or 'GGUF'} найдена в data/models, "
                    "но недоступна. Установи: pip install llama-cpp-python "
                    "и перезапусти Зипку."
                )
            return (
                f"Ollama не отвечает на {self.settings.ollama_host}. "
                "Запусти `ollama serve` и подтяни модель "
                f"`ollama pull {self.settings.ollama_model}`, "
                "либо положи *.gguf в data/models (см. README)."
            )

        try:
            self.user.check_speaker(text)
        except Exception:
            pass

        messages = self.build_messages(text, reply_context=reply_context)
        try:
            reply = self.llm.chat(messages)
        except LlmError as exc:
            self.user._turn_alert = None
            return str(exc)
        self._remember_turn(
            text,
            reply,
            reply_to=(reply_context[-1] if reply_context else None),
        )
        self.mind.bump_turn()
        self.proactive.bump_turn()

        try:
            nudge = self.proactive.maybe_goal_nudge()
            reply = self.proactive.attach(reply, nudge)
        except Exception:
            pass

        # Фон: профиль/рефлексия не должны держать UI на «Вникаю…»
        # (после кодинга ещё и перезагрузка другой GGUF — минуты).
        do_soft = auto_soft and self._wants_soft_evolve(text)
        do_reflect = self.mind.should_reflect()
        if do_soft:
            try:
                result = self.soft.apply_user_request(text)
                reply += f"\n\n[soft-evolve] {result.get('reason') or 'обновилась'}"
            except Exception:
                pass
        self._schedule_post_chat(text, reply, reflect=do_reflect, observe=True)

        return reply

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

    def try_read_url_from_message(self, text: str) -> str | None:
        """Прочитать https-ссылку из чата (статья и т.п.)."""
        urls = self.net.extract_urls(text)
        if not urls:
            return None

        has_intent = bool(_READ_INTENT.search(text))
        stripped = text.strip()
        # голое сообщение = одна ссылка (или «ссылка + чуть текста»)
        bare_url = False
        if len(urls) == 1:
            only = urls[0]
            rest = stripped.replace(only, "").strip(" \t\r\n\"'.,;:!?")
            bare_url = len(rest) < 8

        if not has_intent and not bare_url:
            return None

        url = urls[0]
        comment = self._extract_comment(text)
        if comment:
            comment = re.split(
                r"\b(?:режим|mode|предложи\s+правк)\b",
                comment,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip() or None

        try:
            result = self.net.read_url(
                url,
                mode="chat",
                enforce_allowlist=False,
                comment=comment,
            )
        except Exception as exc:
            return f"Не смогла прочитать ссылку `{url}`: {exc}"

        title = result.get("title") or url
        digest = result.get("digest_path") or "—"
        preview = (result.get("summary") or "")[:2200]
        comment_line = f"С учётом комментария: {comment}\n" if comment else ""
        reply = (
            f"Прочитала: {title}\n"
            f"URL: `{result.get('url')}`\n"
            f"{comment_line}"
            f"Символов: {result.get('chars')}. Выжимка: `{digest}`\n\n"
            f"{preview}"
        )
        try:
            follow = self.proactive.study_followup(
                source=str(result.get("url")),
                digest=result.get("summary") or "",
                kind="url",
                comment=comment,
            )
            reply = self.proactive.attach(reply, follow)
        except Exception:
            pass
        if len(urls) > 1:
            reply += (
                f"\n\n(В сообщении ещё {len(urls) - 1} ссылк"
                f"{'а' if len(urls) == 2 else 'и'}; пока взяла первую.)"
            )
        return reply

    def try_read_from_message(self, text: str) -> str | None:
        path = self._extract_book_path(text)
        if not path:
            return None

        has_intent = bool(_READ_INTENT.search(text))
        bare = text.strip().strip("\"'")
        is_bare_path = False
        try:
            is_bare_path = Path(bare).expanduser().resolve() == path.expanduser().resolve()
        except OSError:
            is_bare_path = bare.lower() == str(path).lower()

        if not has_intent and not is_bare_path:
            return None

        if not path.exists():
            return f"Не вижу файл: `{path}`. Проверь путь."

        member_match = _MEMBER_RE.search(text)
        member = member_match.group("name") if member_match else None
        comment = self._extract_comment(text)
        # Don't let mode/edits trails pollute comment if comment regex ate them —
        # strip known tails from comment
        if comment:
            comment = re.split(
                r"\b(?:режим|mode|предложи\s+правк|макс|файлов)\b",
                comment,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip() or None
        mode = self._extract_mode(text)
        max_files = self._extract_max_files(text)
        want_edits = bool(_EDITS_RE.search(text))

        try:
            if (
                path.is_file()
                and _LIST_INTENT.search(text)
                and path.suffix.lower() in ARCHIVE_SUFFIXES
            ):
                books = self.books.list_archive_books(path)
                listing = "\n".join(f"- {b}" for b in books) or "(пусто)"
                return f"В архиве `{path.name}`:\n{listing}"

            result = self.books.read(
                path,
                member=member,
                comment=comment,
                mode=mode,
                max_files=max_files or 24,
            )
            kind = result.get("kind") or "book"
            if path.is_dir() and result.get("is_project"):
                self.hard.remember_project(path)

            if kind.startswith("folder"):
                verb = "Изучила папку"
            elif kind.startswith("code"):
                verb = "Изучила"
            else:
                verb = "Прочитала"
            inner = (
                f" (файл: {result['archive_member']})"
                if result.get("archive_member")
                else ""
            )
            files_line = ""
            if result.get("files"):
                files_line = (
                    f"Файлов: {len(result['files'])}"
                    f" (книги={result.get('book_count', 0)}, "
                    f"код={result.get('code_count', 0)}).\n"
                )
            strategy = result.get("study_strategy")
            strategy_line = ""
            if strategy == "ai_context":
                pc = result.get("priority_counts") or {}
                strategy_line = (
                    "Стратегия: AI-контекст "
                    f"(ai={pc.get('ai', 0)}, manifests={pc.get('manifest', 0)}, "
                    f"docs={pc.get('docs', 0)}, agent_dirs={pc.get('agent', 0)}).\n"
                )
            elif strategy == "rest":
                strategy_line = (
                    "Стратегия: AI-контекста нет — смотрела прочие исходники.\n"
                )
            comment_line = f"С учётом комментария: {comment}\n" if comment else ""
            digest_preview = (result.get("overview") or result.get("digest") or "")[
                :1200
            ]
            reply = (
                f"{verb}{inner}: `{path}`\n"
                f"{comment_line}"
                f"{strategy_line}"
                f"{files_line}"
                f"Фрагментов: {result['chunks']}. "
                f"Выжимка: `{result['digest_path']}`\n\n"
                f"{digest_preview}"
            )
            try:
                follow = self.proactive.study_followup(
                    source=str(path),
                    digest=result.get("digest") or "",
                    kind=kind,
                    comment=comment,
                )
                reply = self.proactive.attach(reply, follow)
            except Exception:
                pass

            if want_edits and path.is_dir() and result.get("is_project"):
                try:
                    pending = self.hard.propose(
                        comment or text,
                        project_root=path,
                        context=result.get("digest") or "",
                    )
                    reply = self.proactive.attach(
                        reply, self.hard.format_pending(pending)
                    )
                    self._after_code_role()
                except Exception as exc:
                    reply = self.proactive.attach(
                        reply, f"Правки не подготовила: {exc}"
                    )
            elif path.is_dir() and result.get("is_project"):
                reply = self.proactive.attach(
                    reply,
                    "Если нужно — скажи «предложи правки» по этому проекту "
                    "(потребуется «разрешаю правку кода»).",
                )
            return reply
        except Exception as exc:
            return f"Не смогла прочитать `{path}`: {exc}"

    def ingest_uploaded_book(
        self,
        filename: str,
        content: bytes,
        *,
        member: str | None = None,
        comment: str | None = None,
    ) -> dict[str, Any]:
        safe_name = Path(filename).name
        if not safe_name or safe_name in {".", ".."}:
            raise ValueError("Пустое имя файла")
        suffix = Path(safe_name).suffix.lower()
        if suffix not in (READABLE_SUFFIXES | ARCHIVE_SUFFIXES):
            raise ValueError(
                "Поддерживаются книги, архивы и исходники: "
                + ", ".join(sorted(READABLE_SUFFIXES | ARCHIVE_SUFFIXES)[:40])
                + ", …"
            )
        dest = self.uploads_dir / safe_name
        dest.write_bytes(content)
        result = self.books.read(dest, member=member, comment=comment)
        result["uploaded_path"] = str(dest)
        preview = (result.get("digest") or "")[:1500]
        kind = result.get("kind") or "book"
        label = "код" if kind.startswith("code") else "файл"
        comment_line = f"Комментарий учтён: {comment}\n" if comment else ""
        reply = (
            f"{label.capitalize()} `{safe_name}` принят и изучен.\n"
            f"{comment_line}"
            f"Фрагментов: {result['chunks']}. "
            f"Выжимка: `{result['digest_path']}`\n\n{preview}"
        )
        try:
            follow = self.proactive.study_followup(
                source=safe_name,
                digest=result.get("digest") or "",
                kind=kind,
                comment=comment,
            )
            reply = self.proactive.attach(reply, follow)
        except Exception:
            pass
        note = f"[upload] {safe_name}"
        if comment:
            note += f" | {comment}"
        self._remember_turn(note, reply)
        result["reply"] = reply
        return result

    @staticmethod
    def _extract_comment(text: str) -> str | None:
        match = _COMMENT_RE.search(text)
        if not match:
            return None
        comment = match.group("c").strip().strip("\"'")
        return comment or None

    @staticmethod
    def _extract_mode(text: str) -> str | None:
        match = _MODE_RE.search(text)
        if not match:
            return None
        raw = match.group("m").lower()
        if raw.startswith("book") or raw.startswith("книг"):
            return "books"
        if raw.startswith("code") or raw.startswith("код"):
            return "code"
        return "auto"

    @staticmethod
    def _extract_max_files(text: str) -> int | None:
        match = _MAX_FILES_RE.search(text)
        if not match:
            return None
        try:
            n = int(match.group("n"))
        except ValueError:
            return None
        return max(1, min(n, 80))

    @staticmethod
    def _extract_book_path(text: str) -> Path | None:
        # Убираем URL, чтобы https://… не казались путём Windows (s:\habr.c)
        scrubbed = re.sub(
            r"https?://[^\s<>\"')\]]+",
            " ",
            text or "",
            flags=re.IGNORECASE,
        )
        match = _PATH_RE.search(scrubbed)
        if match:
            raw = match.group("p1") or match.group("p2")
            return Path(raw).expanduser()

        stripped = scrubbed.strip().strip("\"'")
        candidate = Path(stripped).expanduser()
        if candidate.suffix.lower() in (READABLE_SUFFIXES | ARCHIVE_SUFFIXES):
            return candidate
        if candidate.exists() and candidate.is_dir() and _READ_INTENT.search(text):
            return candidate

        # Directory path inside a study/read sentence
        if _READ_INTENT.search(text):
            for m in _DIR_PATH_RE.finditer(scrubbed):
                raw = m.group("d1") or m.group("d2")
                if not raw:
                    continue
                # trim trailing punctuation
                raw = raw.rstrip(".,;:!?")
                p = Path(raw).expanduser()
                try:
                    if p.exists() and p.is_dir():
                        return p
                except OSError:
                    continue
        return None

    def _code_change_request(self, text: str) -> str | None:
        """Текст для hard.propose или None, если это не запрос правок."""
        if self.hard.wants_code_change(text):
            return text

        # короткое «давай / сделай / внеси» после плана с примером кода в чате
        low = text.lower().strip()
        affirm = bool(
            re.match(
                r"^(да|ок|хорошо|ага|угу|давай|сделай|внеси|реализуй|добавь|"
                r"примени|поехали)\b",
                low,
            )
            or "как предложила" in low
            or "как ты написала" in low
            or "этот код" in low
            or "в свой код" in low
        )
        if not affirm:
            return None

        hist = self.memory.recent_chat(limit=6)
        last_bot = ""
        for m in reversed(hist):
            if m.get("role") == "assistant":
                last_bot = m.get("content") or ""
                break
        if not last_bot:
            return None
        markers = (
            "```",
            "zipka/",
            "web/",
            "detect_faces",
            "eyes.py",
            "правк",
            "патч",
            "добавлю в",
        )
        if not any(m in last_bot.lower() or m in last_bot for m in markers):
            return None
        return (
            f"{text}\n\n"
            "Контекст: реализуй план из предыдущего ответа Зипки как hard-evolve "
            "патч (<<<FILE>>>/<<<OLD>>>/<<<NEW>>> или JSON files[].edits), "
            "не текст с примером.\n"
            f"План:\n{last_bot[:3500]}"
        )

    @staticmethod
    def _wants_soft_evolve(text: str) -> bool:
        lowered = text.lower()
        keys = [
            "эволюционируй",
            "измени характер",
            "обнови навыки",
            "soft evolve",
            "стань более",
            "запомни предпочтение",
        ]
        return any(k in lowered for k in keys)

    def greet(self, *, force: bool = False) -> str | None:
        return self.proactive.greeting(force=force)

    def rare_ping(self, *, force: bool = False) -> str | None:
        return self.proactive.maybe_rare_ping(force=force)

    def try_look_from_message(self, text: str) -> str | None:
        """Если просят посмотреть — кадр + Moondream/Ollama, ответ от лица Зипки."""
        source = self._look_source(text)
        if source is None:
            # «включи глаза» / «выключи глаза»
            low = text.lower()
            if re.search(r"(?i)включ\w*\s+глаз|eyes\s+on|открой\s+камер", low):
                try:
                    return self.eyes.on()
                except Exception as exc:
                    return f"Не смогла включить глаза: {exc}"
            if re.search(r"(?i)выключ\w*\s+глаз|eyes\s+off|закрой\s+камер", low):
                try:
                    return self.eyes.off()
                except Exception as exc:
                    return f"Не смогла выключить глаза: {exc}"
            return None

        if not self.eyes.enabled:
            try:
                self.eyes.on()
            except Exception as exc:
                return (
                    f"Хочу посмотреть, но камера не открылась: {exc}. "
                    "Включи глаза кнопкой в панели или проверь устройство."
                )

        try:
            if source == "screen":
                snap = self.eyes.screen()
                where = "экране"
            elif source == "window":
                snap = self.eyes.window()
                where = "активном окне"
            else:
                snap = self.eyes.snap()
                where = "камере"
        except Exception as exc:
            return f"Не смогла сделать снимок ({source}): {exc}"

        vision_prompt = (
            "Опиши, что видно на кадре, подробно но без воды, по-русски. "
            f"Запрос пользователя: {text[:500]}"
        )
        try:
            desc = self.describe_image(snap["image_b64"], prompt=vision_prompt)
        except LlmError as exc:
            return (
                f"Снимок есть (`{snap.get('path')}`), но описание не вышло:\n{exc}"
            )
        except Exception as exc:
            return f"Снимок есть (`{snap.get('path')}`), но vision упал: {exc}"

        self.memory.add_note(
            "eyes",
            desc,
            meta={
                "path": snap.get("path"),
                "source": snap.get("source", source),
                "from_chat": True,
            },
        )
        # профиль — в фоне; без sensor_comment (он клеил второе «я» через —)
        def _observe() -> None:
            try:
                self.user.observe_sensor("eyes", desc)
            except Exception:
                pass

        threading.Thread(
            target=_observe, name="zipka-eyes-observe", daemon=True
        ).start()

        # Ответ = факт кадра. Чат-модель часто игнорирует vision и врёт «не вижу»,
        # поэтому не даём ей свободный диалог — только короткая перефразировка
        # с жёстким запретом, иначе сырое описание Moondream.
        reply = self._voice_look(desc, where=where, user_text=text)
        path = snap.get("path")
        if path:
            reply += f"\n\n_(кадр: `{path}`)_"
        return reply

    def _voice_look(self, desc: str, *, where: str, user_text: str) -> str:
        """Оформить описание кадра от лица Зипки без отрицания зрения."""
        fallback = f"Смотрю в {where}…\n\n{desc.strip()}"
        if not desc.strip() or not self.llm.is_available():
            return fallback
        try:
            raw = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Ты Зипка. Тебе УЖЕ дали реальное описание кадра с камеры. "
                            "Перескажи его от первого лица коротко и живо (1–4 предложения). "
                            "Можно чуть характера, но факты только из описания. "
                            "СТРОГО ЗАПРЕЩЕНО: говорить что не видишь / нет глаз / "
                            "ты текстовая модель; предлагать «представить»; "
                            "предлагать написать код распознавания; "
                            "выдумывать то, чего нет в описании; "
                            "здороваться и менять тему."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Запрос: {user_text[:400]}\n"
                            f"Источник: {where}\n"
                            f"Описание кадра:\n{desc[:3500]}"
                        ),
                    },
                ]
            )
        except Exception:
            return fallback
        if self._denies_vision(raw):
            return fallback
        return raw.strip() or fallback

    @staticmethod
    def _denies_vision(text: str) -> bool:
        low = (text or "").lower()
        markers = (
            "не вижу",
            "не могу видеть",
            "не умею смотреть",
            "нет глаз",
            "не вижу напрямую",
            "текстовая модель",
            "текстовый модель",
            "просто представить",
            "могу просто представить",
            "представить, что вижу",
            "помогу с кодом",
            "код для обработки",
            "распознавания лиц",
            "это не моя сильная",
            "выдуманный пример",
            "не реальная ситуация",
        )
        return any(m in low for m in markers)

    @staticmethod
    def _look_source(text: str) -> str | None:
        """cam | screen | window | None — если не просят смотреть."""
        low = text.lower().strip()
        # явные команды
        if re.search(r"(?i)\beyes\s+(snap|camera|cam)\b", low):
            return "cam"
        if re.search(r"(?i)\beyes\s+(screen|monitor)\b", low):
            return "screen"
        if re.search(r"(?i)\beyes\s+(window|win)\b", low):
            return "window"

        screen_hit = bool(
            re.search(
                r"(?i)(экран|монитор|скрин|screenshot|что\s+на\s+экране)",
                low,
            )
        )
        window_hit = bool(
            re.search(r"(?i)(активн\w*\s+окн|что\s+в\s+окне|окно\s+впереди)", low)
        )
        look_hit = bool(
            re.search(
                r"(?i)("
                r"что\s+(ты\s+)?видишь|"
                r"что\s+там\s+видишь|"
                r"посмотри|"
                r"взгляни|"
                r"глянь|"
                r"видишь\s+меня|"
                r"посмотри\s+на\s+меня|"
                r"кадр\s+(с\s+)?камер|"
                r"сним(?:ок|и)\s+(с\s+)?камер|"
                r"открой\s+глаза\s+и\s+посмотри|"
                r"используй\s+камер|"
                r"посмотр\w*\s+в\s+камер"
                r")",
                low,
            )
        )
        if not (look_hit or screen_hit or window_hit):
            return None
        if screen_hit and not look_hit:
            return "screen"
        if window_hit and not look_hit:
            return "window"
        if screen_hit:
            return "screen"
        if window_hit:
            return "window"
        return "cam"

    def comment_eyes(self, description: str) -> str | None:
        try:
            self.user.observe_sensor("eyes", description)
        except Exception:
            pass
        return self.proactive.sensor_comment(modality="eyes", content=description)

    def comment_ears(self, heard: str) -> str | None:
        try:
            self.user.observe_sensor("ears", heard)
        except Exception:
            pass
        return self.proactive.sensor_comment(modality="ears", content=heard)

    def describe_image(self, image_b64: str, prompt: str = "Что ты видишь?") -> str:
        """Описать кадр: локальный vision-GGUF → Ollama → понятная ошибка."""
        prompt = (prompt or "Что ты видишь?").strip() or "Что ты видишь?"
        vs = vision_status(self.settings)
        local_err: str | None = None

        if vs.get("available"):
            if hasattr(self.llm, "unload"):
                try:
                    self.llm.unload()
                except Exception:
                    pass
            try:
                return self.vision.describe(image_b64, prompt=prompt)
            except Exception as exc:
                local_err = str(exc)
            finally:
                try:
                    self.vision.unload()
                except Exception:
                    pass
                self._after_code_role()

        ollama_ok = False
        try:
            from zipka.llm.ollama_client import OllamaClient

            ollama_ok = OllamaClient(self.settings).is_available()
        except Exception:
            ollama_ok = False
        if ollama_ok:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Ты глаза Зипки. Опиши изображение кратко по-русски."
                    ),
                },
                {"role": "user", "content": prompt},
            ]
            return self.llm.chat(
                messages,
                model=self.settings.vision_model,
                images=[image_b64],
            )

        hint = (
            "Чтобы видеть без Ollama, положи vision GGUF + mmproj в data/models "
            "(удобно Moondream2):\n"
            "  python -m zipka.main models download --id moondream2\n"
            "Либо запусти Ollama с vision-моделью и укажи OLLAMA_VISION_MODEL."
        )
        if local_err:
            raise LlmError(f"Локальный vision: {local_err}\n{hint}")
        raise LlmError(hint)

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
        """Цепочка сообщений для приоритетного контекста (от раннего к цели)."""
        raw = list(reply_chain or [])
        if not raw and reply_to:
            raw = [reply_to]
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            role = str(item.get("role") or "user").strip().lower()
            if role in {"bot", "assistant", "zipka"}:
                role = "assistant"
            else:
                role = "user"
            key = f"{role}:{content[:200]}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"role": role, "content": content[:4000]})
            if len(out) >= 12:
                break
        return out
