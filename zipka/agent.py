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
from zipka.evolve.hard import HardEvolve
from zipka.evolve.soft import SoftEvolve
from zipka.llm.ollama_client import OllamaClient, OllamaError
from zipka.memory.store import MemoryStore
from zipka.mind.goals import PseudoMind
from zipka.net.learner import NetLearner
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
    r"изучи|разбери|проанализируй|изучить|study|analyze|"
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
        self.net = NetLearner(self.llm, self.memory, self.settings)
        self.safety = SafetyPolicy()
        self.uploads_dir = self.settings.data_dir / "books" / "uploads"
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        ollama_ok = self.llm.is_available()
        models = []
        if ollama_ok:
            try:
                models = self.llm.list_models()
            except OllamaError:
                models = []
        return {
            "name": "Зипка",
            "ollama": ollama_ok,
            "models": models,
            "model": self.settings.ollama_model,
            "eyes": self.eyes.enabled,
            "ears": self.ears.enabled,
            "pending_patch": self.hard.has_pending(),
            "mind": self.mind.load(),
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

        book_reply = self.try_read_from_message(text)
        if book_reply is not None:
            self._remember_turn(text, book_reply)
            return book_reply

        if self.hard.is_approve(text):
            if not self.hard.has_pending():
                return "Нечего утверждать — патча нет."
            meta = self.hard.apply_pending()
            reply = (
                f"Патч {meta['id']} применён. Файлы: {', '.join(meta['files'])}. "
                f"Откат: `zipka rollback {meta['id']}`"
            )
            self._remember_turn(text, reply)
            return reply

        if self.hard.has_pending() and "патч" in text.lower():
            return self.hard.format_pending()

        if self.hard.wants_code_change(text):
            pending = self.hard.propose(text)
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

        try:
            if (
                path.is_file()
                and _LIST_INTENT.search(text)
                and path.suffix.lower() in ARCHIVE_SUFFIXES
            ):
                books = self.books.list_archive_books(path)
                listing = "\n".join(f"- {b}" for b in books) or "(пусто)"
                return f"В архиве `{path.name}`:\n{listing}"

            result = self.books.read(path, member=member)
            kind = result.get("kind") or "book"
            verb = "Изучила" if kind.startswith("code") else "Прочитала"
            inner = (
                f" (файл: {result['archive_member']})"
                if result.get("archive_member")
                else ""
            )
            files_line = ""
            if result.get("files"):
                files_line = f"Файлов: {len(result['files'])}.\n"
            digest_preview = (result.get("digest") or "")[:1500]
            return (
                f"{verb}{inner}: `{path}`\n"
                f"{files_line}"
                f"Фрагментов: {result['chunks']}. "
                f"Выжимка: `{result['digest_path']}`\n\n"
                f"{digest_preview}"
            )
        except Exception as exc:
            return f"Не смогла прочитать `{path}`: {exc}"

    def ingest_uploaded_book(
        self, filename: str, content: bytes, *, member: str | None = None
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
        result = self.books.read(dest, member=member)
        result["uploaded_path"] = str(dest)
        preview = (result.get("digest") or "")[:1500]
        kind = result.get("kind") or "book"
        label = "код" if kind.startswith("code") else "файл"
        reply = (
            f"{label.capitalize()} `{safe_name}` принят и изучен.\n"
            f"Фрагментов: {result['chunks']}. "
            f"Выжимка: `{result['digest_path']}`\n\n{preview}"
        )
        self._remember_turn(f"[upload] {safe_name}", reply)
        result["reply"] = reply
        return result

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
