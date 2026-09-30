"""Чтение URL / файлов / папок / upload из текста чата."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from zipka.books.reader import ARCHIVE_SUFFIXES, READABLE_SUFFIXES

from .books_parse import (
    DEFAULT_MAX_FILES,
    EDITS_RE,
    LIST_INTENT,
    MEMBER_RE,
    READ_INTENT,
    extract_book_path,
    extract_comment,
    extract_max_files,
    extract_mode,
    wants_opinion,
)

# re-export for Zipka thin wrappers / tests
__all__ = [
    "DEFAULT_MAX_FILES",
    "extract_book_path",
    "extract_comment",
    "extract_max_files",
    "extract_mode",
    "ingest_uploaded_book",
    "try_read_from_message",
    "try_read_url_from_message",
    "wants_opinion",
]


def try_read_url_from_message(agent: Any, text: str) -> str | None:
    """Прочитать https-ссылку из чата (статья и т.п.)."""
    urls = agent.net.extract_urls(text)
    if not urls:
        return None

    has_intent = bool(READ_INTENT.search(text))
    stripped = text.strip()
    bare_url = False
    if len(urls) == 1:
        only = urls[0]
        rest = stripped.replace(only, "").strip(" \t\r\n\"'.,;:!?")
        bare_url = len(rest) < 8

    if not has_intent and not bare_url:
        return None

    url = urls[0]
    comment = extract_comment(text)
    if comment:
        comment = re.split(
            r"\b(?:режим|mode|предложи\s+правк)\b",
            comment,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip() or None

    try:
        result = agent.net.read_url(
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
    from zipka.llm.sanitize import is_degenerate_generation

    if is_degenerate_generation(preview):
        preview = "(Выжимка статьи не удалась — попробуй ещё раз или открой файл выжимки.)"
    comment_line = f"С учётом комментария: {comment}\n" if comment else ""
    reply = (
        f"Прочитала: {title}\n"
        f"URL: `{result.get('url')}`\n"
        f"{comment_line}"
        f"Символов: {result.get('chars')}. Выжимка: `{digest}`\n\n"
        f"{preview}"
    )
    try:
        ask_opinion = wants_opinion(text) or (
            bool(comment) and wants_opinion(comment)
        )
        if ask_opinion:
            follow = agent.proactive.study_opinion(
                source=str(result.get("url")),
                digest=result.get("summary") or "",
                kind="url",
                comment=comment,
            )
        else:
            follow = agent.proactive.study_followup(
                source=str(result.get("url")),
                digest=result.get("summary") or "",
                kind="url",
                comment=comment,
            )
        reply = agent.proactive.attach(reply, follow)
    except Exception:
        pass
    if len(urls) > 1:
        reply += (
            f"\n\n(В сообщении ещё {len(urls) - 1} ссылк"
            f"{'а' if len(urls) == 2 else 'и'}; пока взяла первую.)"
        )
    return reply


def try_read_from_message(agent: Any, text: str) -> str | None:
    path = extract_book_path(text)
    if not path:
        return None

    has_intent = bool(READ_INTENT.search(text))
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

    member_match = MEMBER_RE.search(text)
    member = member_match.group("name") if member_match else None
    comment = extract_comment(text)
    if comment:
        comment = re.split(
            r"\b(?:режим|mode|предложи\s+правк|макс|файлов)\b",
            comment,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip() or None
    mode = extract_mode(text)
    requested_max = extract_max_files(text)
    max_files = requested_max if requested_max is not None else DEFAULT_MAX_FILES
    want_edits = bool(EDITS_RE.search(text))

    try:
        if (
            path.is_file()
            and LIST_INTENT.search(text)
            and path.suffix.lower() in ARCHIVE_SUFFIXES
        ):
            books = agent.books.list_archive_books(path)
            listing = "\n".join(f"- {b}" for b in books) or "(пусто)"
            return f"В архиве `{path.name}`:\n{listing}"

        result = agent.books.read(
            path,
            member=member,
            comment=comment,
            mode=mode,
            max_files=max_files,
        )
        kind = result.get("kind") or "book"
        if path.is_dir() and result.get("is_project"):
            agent.hard.remember_project(path)

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
            limit_note = (
                f"лимит {max_files}"
                + (
                    " (задан в запросе)"
                    if requested_max is not None
                    else f" (дефолт {DEFAULT_MAX_FILES})"
                )
            )
            files_line = (
                f"Файлов: {len(result['files'])}"
                f" (книги={result.get('book_count', 0)}, "
                f"код={result.get('code_count', 0)}; {limit_note}).\n"
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
        from zipka.llm.sanitize import is_degenerate_generation

        if is_degenerate_generation(digest_preview):
            digest_preview = (
                "(Выжимка частично не удалась — модель выдала мусор. "
                f"Смотри файл `{result.get('digest_path')}` или попроси пересказ.)"
            )
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
            ask_opinion = wants_opinion(text) or (
                bool(comment) and wants_opinion(comment)
            )
            if ask_opinion:
                follow = agent.proactive.study_opinion(
                    source=str(path),
                    digest=result.get("digest") or result.get("overview") or "",
                    kind=kind,
                    comment=comment,
                )
            else:
                follow = agent.proactive.study_followup(
                    source=str(path),
                    digest=result.get("digest") or "",
                    kind=kind,
                    comment=comment,
                )
            reply = agent.proactive.attach(reply, follow)
        except Exception:
            pass

        if want_edits and path.is_dir() and result.get("is_project"):
            try:
                pending = agent.hard.propose(
                    comment or text,
                    project_root=path,
                    context=result.get("digest") or "",
                )
                reply = agent.proactive.attach(
                    reply, agent.hard.format_pending(pending)
                )
                agent._after_code_role()
            except Exception as exc:
                reply = agent.proactive.attach(
                    reply, f"Правки не подготовила: {exc}"
                )
        elif path.is_dir() and result.get("is_project"):
            reply = agent.proactive.attach(
                reply,
                "Если нужно — скажи «предложи правки» по этому проекту "
                "(потребуется «разрешаю правку кода»).",
            )
        return reply
    except Exception as exc:
        return f"Не смогла прочитать `{path}`: {exc}"


def ingest_uploaded_book(
    agent: Any,
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
    note = f"[upload] {safe_name}"
    if comment:
        note += f" | {comment}"

    with agent.run_with_pending(
        user_text=note,
        phase="studying",
        kind="upload",
        label="Изучаю…",
        save_user=True,
    ):
        try:
            dest = agent.uploads_dir / safe_name
            dest.write_bytes(content)
            result = agent.books.read(dest, member=member, comment=comment)
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
                follow = agent.proactive.study_followup(
                    source=safe_name,
                    digest=result.get("digest") or "",
                    kind=kind,
                    comment=comment,
                )
                reply = agent.proactive.attach(reply, follow)
            except Exception:
                pass
            agent._remember_turn(note, reply)
            agent._ensure_assistant_saved(reply)
            result["reply"] = reply
            return result
        except Exception as exc:
            err = f"Не смогла прочитать `{safe_name}`: {exc}"
            agent._ensure_assistant_saved(err)
            raise
