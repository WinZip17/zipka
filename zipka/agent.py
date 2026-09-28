from __future__ import annotations

import re
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
from zipka.llm.ollama_client import OllamaClient, OllamaError
from zipka.memory.store import MemoryStore
from zipka.mind.goals import PseudoMind
from zipka.mind.proactive import ProactiveEngine
from zipka.net.learner import NetLearner
from zipka.reset import (
    CONFIRM_PHRASE,
    is_reset_confirm,
    is_reset_request,
    reset_learning_data,
)
from zipka.safety.policy import SafetyPolicy
from zipka.sensors.ears import Ears
from zipka.sensors.eyes import Eyes

_FILE_EXTS = "|".join(
    re.escape(ext.lstrip(".")) for ext in sorted(READABLE_SUFFIXES | ARCHIVE_SUFFIXES)
)
_PATH_RE = re.compile(
    rf'(?P<q>["\'])(?P<p1>[^"\']+\.(?:{_FILE_EXTS}))(?P=q)'
    rf'|(?P<p2>(?:[A-Za-z]:[\\/]|[\\/])[^\s"\']+\.(?:{_FILE_EXTS}))',
    re.IGNORECASE,
)
_DIR_PATH_RE = re.compile(
    rf'(?P<q>["\'])(?P<d1>(?:[A-Za-z]:[\\/]|[\\/])[^"\']+)(?P=q)'
    rf'|(?P<d2>(?:[A-Za-z]:[\\/]|[\\/])[^\s"\']+)',
    re.IGNORECASE,
)
_READ_INTENT = re.compile(
    r"(прочитай|прочти|прочесть|прочитать|читай|открой\s+книг|"
    r"прочитай\s+книг|read\s+(?:the\s+)?book|read\s+file|"
    r"изучи(?:\s+папк\w*)?|разбери|проанализируй|изучить|study|analyze|"
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
        self.llm = OllamaClient(self.settings)
        self.memory = MemoryStore(self.settings)
        self.persona = Persona(self.settings)
        self.soft = SoftEvolve(self.persona, self.memory, self.llm)
        self.hard = HardEvolve(self.llm, self.memory, self.settings)
        self.books = BookReader(self.llm, self.memory, self.settings)
        self.eyes = Eyes(self.settings)
        self.ears = Ears(self.settings)
        self.mind = PseudoMind(
            self.persona, self.memory, self.llm, self.soft, self.settings
        )
        self.proactive = ProactiveEngine(
            self.llm, self.memory, self.mind, self.settings
        )
        self.net = NetLearner(self.llm, self.memory, self.settings)
        self.safety = SafetyPolicy()
        self.uploads_dir = self.settings.data_dir / "books" / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._reset_pending = False

    def reload_runtime(self) -> None:
        """Пересоздать модули после очистки data/."""
        ensure_data_dirs(self.settings)
        self.memory = MemoryStore(self.settings)
        self.persona = Persona(self.settings)
        self.soft = SoftEvolve(self.persona, self.memory, self.llm)
        self.hard = HardEvolve(self.llm, self.memory, self.settings)
        self.books = BookReader(self.llm, self.memory, self.settings)
        self.eyes = Eyes(self.settings)
        self.ears = Ears(self.settings)
        self.mind = PseudoMind(
            self.persona, self.memory, self.llm, self.soft, self.settings
        )
        self.proactive = ProactiveEngine(
            self.llm, self.memory, self.mind, self.settings
        )
        self.net = NetLearner(self.llm, self.memory, self.settings)
        self.uploads_dir = self.settings.data_dir / "books" / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self._reset_pending = False

    def reset_learning(self, *, confirm: bool = False) -> dict[str, Any]:
        result = reset_learning_data(self.settings, confirm=confirm)
        self.reload_runtime()
        return result

    def status(self) -> dict[str, Any]:
        from zipka.system_limits import available_ram_bytes, format_bytes, max_book_bytes

        ollama_ok = self.llm.is_available()
        models = []
        if ollama_ok:
            try:
                models = self.llm.list_models()
            except OllamaError:
                models = []
        book_limit = max_book_bytes()
        avail = available_ram_bytes()
        return {
            "name": "Зипка",
            "ollama": ollama_ok,
            "models": models,
            "model": self.settings.ollama_model,
            "vision_model": self.settings.vision_model,
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
        }

    def build_messages(self, user_text: str) -> list[dict[str, str]]:
        notes = [n["text"] for n in self.memory.recent_notes(limit=8)]
        system = self.persona.system_prompt(
            skills=self.memory.get_skills(),
            preferences=self.memory.get_preferences(),
            notes=notes,
            mind_state=self.mind.load(),
        )
        system += (
            "\nПользователь может дать путь к книге или исходному коду "
            "(.py/.js/.ts/…), папке с кодом, zip/rar — или загрузить файл в web."
        )
        history = self.memory.recent_chat(limit=16)
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_text})
        return messages

    def chat(self, user_text: str, *, auto_soft: bool = True) -> str:
        text = user_text.strip()
        if not text:
            return "Пусто. Скажи что-нибудь."

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

        book_reply = self.try_read_from_message(text)
        if book_reply is not None:
            self._remember_turn(text, book_reply)
            return book_reply

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
            return reply

        if self.hard.has_pending() and "патч" in text.lower():
            return self.hard.format_pending()

        if self.hard.wants_code_change(text):
            self_edit = self.hard.wants_self_edit(text)
            project = None if self_edit else self.hard.last_project()
            ctx = None
            notes = self.memory.recent_notes(limit=5)
            if notes:
                ctx = "\n".join(n.get("text", "") for n in notes)
            try:
                pending = self.hard.propose(
                    text,
                    project_root=project,
                    context=ctx,
                    self_edit=self_edit or project is None,
                )
            except Exception as exc:
                reply = f"Не смогла подготовить патч: {exc}"
                self._remember_turn(text, reply)
                return reply
            reply = self.hard.format_pending(pending)
            self._remember_turn(text, reply)
            return reply

        if not self.llm.is_available():
            return (
                f"Ollama не отвечает на {self.settings.ollama_host}. "
                "Запусти `ollama serve` и подтяни модель "
                f"`ollama pull {self.settings.ollama_model}`."
            )

        messages = self.build_messages(text)
        reply = self.llm.chat(messages)
        self._remember_turn(text, reply)
        self.mind.bump_turn()
        self.proactive.bump_turn()

        if auto_soft and self._wants_soft_evolve(text):
            try:
                result = self.soft.apply_user_request(text)
                reply += f"\n\n[soft-evolve] {result.get('reason') or 'обновилась'}"
            except Exception:
                pass

        if self.mind.should_reflect():
            try:
                state = self.mind.reflect()
                reply += (
                    f"\n\n[рефлексия] фокус: {state.get('focus')}; "
                    f"настроение: {state.get('mood')}"
                )
            except Exception:
                pass

        try:
            nudge = self.proactive.maybe_goal_nudge()
            reply = self.proactive.attach(reply, nudge)
        except Exception:
            pass

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
            comment_line = f"С учётом комментария: {comment}\n" if comment else ""
            digest_preview = (result.get("overview") or result.get("digest") or "")[
                :1800
            ]
            reply = (
                f"{verb}{inner}: `{path}`\n"
                f"{comment_line}"
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
        match = _PATH_RE.search(text)
        if match:
            raw = match.group("p1") or match.group("p2")
            return Path(raw).expanduser()

        stripped = text.strip().strip("\"'")
        candidate = Path(stripped).expanduser()
        if candidate.suffix.lower() in (READABLE_SUFFIXES | ARCHIVE_SUFFIXES):
            return candidate
        if candidate.exists() and candidate.is_dir() and _READ_INTENT.search(text):
            return candidate

        # Directory path inside a study/read sentence
        if _READ_INTENT.search(text):
            for m in _DIR_PATH_RE.finditer(text):
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

    def comment_eyes(self, description: str) -> str | None:
        return self.proactive.sensor_comment(modality="eyes", content=description)

    def comment_ears(self, heard: str) -> str | None:
        return self.proactive.sensor_comment(modality="ears", content=heard)

    def describe_image(self, image_b64: str, prompt: str = "Что ты видишь?") -> str:
        messages = self.build_messages(prompt)
        return self.llm.chat(
            messages,
            model=self.settings.vision_model,
            images=[image_b64],
        )

    def _remember_turn(self, user_text: str, reply: str) -> None:
        self.memory.add_chat("user", user_text)
        self.memory.add_chat("assistant", reply)
