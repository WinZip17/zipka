"""Regex и извлечение пути/комментария/режима из текста чата."""
from __future__ import annotations

import re
from pathlib import Path

from zipka.books.reader import ARCHIVE_SUFFIXES, READABLE_SUFFIXES

_FILE_EXTS = "|".join(
    re.escape(ext.lstrip(".")) for ext in sorted(READABLE_SUFFIXES | ARCHIVE_SUFFIXES)
)
PATH_RE = re.compile(
    rf'(?P<q>["\'])(?P<p1>[^"\']+\.(?:{_FILE_EXTS})(?![A-Za-z0-9]))(?P=q)'
    rf'|(?P<p2>(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?!/)|\\)'
    rf'[^\s"\']+\.(?:{_FILE_EXTS})(?![A-Za-z0-9]))',
    re.IGNORECASE,
)
DIR_PATH_RE = re.compile(
    rf'(?P<q>["\'])(?P<d1>(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?!/)|\\)[^"\']+)(?P=q)'
    rf'|(?P<d2>(?:(?<![A-Za-z0-9])[A-Za-z]:[\\/]|/(?!/)|\\)[^\s"\']+)',
    re.IGNORECASE,
)
READ_INTENT = re.compile(
    r"(прочитай|прочти|прочесть|прочитать|читай|открой\s+(?:книг|стать|ссылк|url|страниц)|"
    r"прочитай\s+(?:книг|стать|ссылк|url)|read\s+(?:the\s+)?(?:book|article|page|url|link)|"
    r"изучи(?:\s+папк\w*|те)?|разбери|проанализируй|изучить|study|analyze|"
    r"обучись\s+на|обуч\w*\s+по\s+папк|"
    r"посмотр\w*|взглян\w*|глянь|"
    r"что\s+(?:ты\s+)?думаешь\s+о\s+(?:этом\s+)?(?:проект|папк|код|репо)|"
    r"оцен\w*\s+проект|разбор\s+проект|"
    r"что\s+в\s+архиве|список\s+(?:файлов\s+)?(?:в\s+)?архиве|"
    r"list\s+archive)",
    re.IGNORECASE,
)
LIST_INTENT = re.compile(
    r"(что\s+в\s+архиве|список\s+(?:файлов\s+)?(?:в\s+)?архиве|list\s+archive|--list)",
    re.IGNORECASE,
)
MEMBER_RE = re.compile(
    rf"(?:внутри|файл(?:ом)?|member|-m)\s+(?P<q>['\"])?(?P<name>[^\s'\"]+\.(?:{_FILE_EXTS}))(?P=q)?",
    re.IGNORECASE,
)
COMMENT_RE = re.compile(
    r"(?:комментарий|учти|с\s+комментарием|фокус|note|comment)\s*[:\-–—]\s*(?P<c>.+)$",
    re.IGNORECASE | re.DOTALL,
)
OPINION_RE = re.compile(
    r"(?:"
    r"что\s+(?:ты\s+)?(?:о\s+(?:н[её]м|ней|этом|этой|данном?\w*)\s+)?"
    r"(?:проект\w*|папк\w*|код\w*|репо\w*|архив\w*)?\s*думаешь|"
    r"что\s+(?:ты\s+)?думаешь|"
    r"тво[её]\s+мнение|"
    r"как\s+(?:тебе|оцен\w*)|"
    r"оцен\w*\s+(?:проект|папк|код|репо)|"
    r"впечатлени\w*"
    r")",
    re.IGNORECASE,
)
MODE_RE = re.compile(
    r"(?:mode|режим|только)\s*[:\s]+(?P<m>books?|code|код|книг\w*|auto|вс[её])",
    re.IGNORECASE,
)
EDITS_RE = re.compile(
    r"(предложи\s+правк|с\s+правкам|и\s+правк|propose\s+edits|--edits)",
    re.IGNORECASE,
)
MAX_FILES_RE = re.compile(
    r"(?:макс(?:имум)?|max(?:[_-]?files)?|файлов)\s*[=:]?\s*(?P<n>\d+)",
    re.IGNORECASE,
)


def extract_comment(text: str) -> str | None:
    """Явный «комментарий: …» или свободный хвост после пути («…, что думаешь?»)."""
    match = COMMENT_RE.search(text or "")
    if match:
        comment = match.group("c").strip().strip("\"'")
        return comment or None

    scrubbed = re.sub(
        r"https?://[^\s<>\"')\]]+",
        " ",
        text or "",
        flags=re.IGNORECASE,
    )
    # вырезать путь к файлу/папке
    scrubbed = PATH_RE.sub(" ", scrubbed)
    scrubbed = DIR_PATH_RE.sub(" ", scrubbed)
    # вырезать служебные куски
    scrubbed = MEMBER_RE.sub(" ", scrubbed)
    scrubbed = MODE_RE.sub(" ", scrubbed)
    scrubbed = MAX_FILES_RE.sub(" ", scrubbed)
    scrubbed = EDITS_RE.sub(" ", scrubbed)
    scrubbed = READ_INTENT.sub(" ", scrubbed)
    scrubbed = LIST_INTENT.sub(" ", scrubbed)
    scrubbed = re.sub(
        r"\b(?:проект|папк\w*|репозитори\w*|репо|код|книг\w*|архив\w*)\b",
        " ",
        scrubbed,
        flags=re.IGNORECASE,
    )
    scrubbed = re.sub(r"\s+", " ", scrubbed).strip(" \t\r\n\"'.,;:!?—–-")
    if len(scrubbed) < 3:
        return None
    # слишком общее («пожалуйста») — не фокус
    if scrubbed.lower() in {"пожалуйста", "pls", "please", "спасибо"}:
        return None
    return scrubbed


def wants_opinion(text: str) -> bool:
    return bool(OPINION_RE.search(text or ""))


def extract_mode(text: str) -> str | None:
    match = MODE_RE.search(text)
    if not match:
        return None
    raw = match.group("m").lower()
    if raw.startswith("book") or raw.startswith("книг"):
        return "books"
    if raw.startswith("code") or raw.startswith("код"):
        return "code"
    return "auto"


def extract_max_files(text: str) -> int | None:
    match = MAX_FILES_RE.search(text)
    if not match:
        return None
    try:
        n = int(match.group("n"))
    except ValueError:
        return None
    return max(1, min(n, 80))


def extract_book_path(text: str) -> Path | None:
    scrubbed = re.sub(
        r"https?://[^\s<>\"')\]]+",
        " ",
        text or "",
        flags=re.IGNORECASE,
    )
    match = PATH_RE.search(scrubbed)
    if match:
        raw = match.group("p1") or match.group("p2")
        return Path(raw).expanduser()

    stripped = scrubbed.strip().strip("\"'")
    candidate = Path(stripped).expanduser()
    if candidate.suffix.lower() in (READABLE_SUFFIXES | ARCHIVE_SUFFIXES):
        return candidate
    if candidate.exists() and candidate.is_dir() and READ_INTENT.search(text):
        return candidate

    if READ_INTENT.search(text):
        for m in DIR_PATH_RE.finditer(scrubbed):
            raw = m.group("d1") or m.group("d2")
            if not raw:
                continue
            raw = raw.rstrip(".,;:!?")
            p = Path(raw).expanduser()
            try:
                if p.exists() and p.is_dir():
                    return p
            except OSError:
                continue
    return None
