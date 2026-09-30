"""Диалог о новостях: выборки, обсуждение, мнение (не literal keyword dump)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Any, TYPE_CHECKING

from zipka.character.persona import Persona
from zipka.llm.base import LlmError

if TYPE_CHECKING:
    from zipka.news.reader import NewsDesk

# «о»/«про» только как отдельные слова — иначе «было»/«интересного» дают ложный topic
_TOPIC_PREP_RE = re.compile(
    r"(?i)(?<![A-Za-zА-Яа-яЁё0-9])(?:про|о|об|насчёт|насчет)"
    r"(?![A-Za-zА-Яа-яЁё0-9])\s+[«\"]?"
    r"([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-.&]{1,48})"
    r"[»\"]?",
)
_MENTION_RE = re.compile(
    r"(?i)упоминал\w*\s+(?:(?:ли|про|о|об)\s+)*"
    r"[«\"]?([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-.&]{1,40})[»\"]?",
)
_SOURCE_RE = re.compile(
    r"(?i)(?:из|в|у|канал(?:е|а)?|источник(?:е|а)?)\s+"
    r"(?:@|https?://t\.me/(?:s/)?)?([A-Za-z0-9_]{3,64})"
    r"|(?:@([A-Za-z0-9_]{3,64}))",
)
_OPINION_RE = re.compile(
    r"(?i)("
    r"что\s+думаешь|как\s+тебе|тво[её]\s+мнени|как\s+относишься|"
    r"оценка|кажется\s+ли|интересн\w*\s+ли\s+тебе|ваше?\s+мнени|"
    r"прокомментируй|что\s+об\s+этом\s+дума"
    r")",
)
_DISCUSS_RE = re.compile(
    r"(?i)("
    r"обсуд|поговорим|разберём|разберем|подробнее\s+про\s+новост|"
    r"эта\s+новость|конкретн\w*\s+новост|расскажи\s+про\s+новост|"
    r"что\s+за\s+новость|поясни\s+новост"
    r")",
)
_SEARCH_RE = re.compile(
    r"(?i)("
    r"упоминал|упоминани|были\s+ли|есть\s+ли\s+(?:что|новост)|"
    r"найди|поищи|выбери|отфильтр|только\s+про|"
    r"новост\w*\s+про\b|про\s+\S+\s+в\s+новост"
    r")",
)
_BROWSE_RE = re.compile(
    r"(?i)("
    r"что\s+(?:было\s+)?интересн|что\s+нового|обзор|"
    r"последн\w*\s+новост|свеж\w*\s+новост|что\s+в\s+(?:ленте|новост)|"
    r"какие\s+новост|расскажи\s+(?:про\s+)?новост|новост\w*\s+за\s+|"
    r"главн\w*\s+новост|важн\w*\s+новост|кратко\s+по\s+новост"
    r")",
)
_QUOTED_RE = re.compile(r"[«\"]([^»\"]{4,80})[»\"]")


class NewsIntent(str, Enum):
    BROWSE = "browse"
    SEARCH = "search"
    DISCUSS = "discuss"
    OPINION = "opinion"


@dataclass
class NewsFilters:
    days: int = 7
    topic: str | None = None
    source: str | None = None
    limit: int = 10


_TOPIC_STOP = {
    "новостях",
    "новости",
    "новость",
    "ленте",
    "канале",
    "этом",
    "том",
    "чём",
    "чем",
    "последних",
    "последние",
    "свежих",
    "сегодня",
    "неделе",
}


def extract_topic(text: str) -> str | None:
    m = _TOPIC_PREP_RE.search(text)
    if m:
        topic = m.group(1).strip(" .,!?:;")
        if topic.lower() not in _TOPIC_STOP:
            return topic
    m2 = _MENTION_RE.search(text)
    if m2:
        topic = m2.group(1).strip(" .,!?:;")
        if topic.lower() not in _TOPIC_STOP | {"ли", "в", "на"}:
            return topic
    q = _QUOTED_RE.search(text)
    if q:
        return q.group(1).strip()
    return None


def extract_source(text: str) -> str | None:
    m = _SOURCE_RE.search(text)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").lstrip("@").lower() or None


def classify_intent(text: str) -> NewsIntent | None:
    """None — не новостной вопрос (команды ingest обрабатывает caller)."""
    low = text.lower()
    newsish = bool(re.search(r"(?i)новост|лент[аы]|rss|телеграм|выдержк", low))
    if not newsish:
        if not (_OPINION_RE.search(text) or _DISCUSS_RE.search(text)):
            return None
        return None

    topic = extract_topic(text)
    if _OPINION_RE.search(text):
        return NewsIntent.OPINION
    if _DISCUSS_RE.search(text):
        return NewsIntent.DISCUSS
    if _SEARCH_RE.search(text) or (
        topic and re.search(r"(?i)упоминал|были\s+ли|найди|поищи|есть\s+ли", low)
    ):
        if topic or _SEARCH_RE.search(text):
            return NewsIntent.SEARCH if topic else NewsIntent.BROWSE
    if _BROWSE_RE.search(text):
        return NewsIntent.BROWSE
    if topic:
        return NewsIntent.DISCUSS
    if re.search(r"(?i)новост", low):
        return NewsIntent.BROWSE
    return None


def _item_time(row: dict[str, Any]):
    from zipka.news.reader import _parse_dt, _utc_now

    return _parse_dt(row.get("published_at")) or _parse_dt(row.get("fetched_at")) or _utc_now()


def filter_items(
    desk: NewsDesk,
    filters: NewsFilters,
) -> list[dict[str, Any]]:
    from zipka.news.reader import _utc_now

    since = _utc_now() - timedelta(days=max(1, filters.days))
    topic_l = (filters.topic or "").lower().strip()
    source_l = (filters.source or "").lower().strip()

    if topic_l:
        rows = desk.search(topic_l, days=filters.days, limit=max(filters.limit * 3, 30))
    else:
        rows = desk.load_items(limit=400)

    out: list[dict[str, Any]] = []
    for row in rows:
        when = _item_time(row)
        if when < since:
            continue
        if source_l:
            blob_src = " ".join(
                [
                    str(row.get("source") or ""),
                    str(row.get("url") or ""),
                    str(row.get("source_url") or ""),
                ]
            ).lower()
            if source_l not in blob_src and f"@{source_l}" not in blob_src:
                continue
        out.append(row)

    out.sort(key=_item_time, reverse=True)
    return out[: max(1, filters.limit)]


def match_specific_item(
    desk: NewsDesk, text: str, pool: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Найти конкретную новость по кавычкам / фрагменту заголовка."""
    quoted = _QUOTED_RE.findall(text)
    candidates = pool or desk.load_items(limit=200)
    for frag in quoted:
        fl = frag.lower()
        for row in candidates:
            title = str(row.get("title") or "").lower()
            summary = str(row.get("summary") or "").lower()
            if fl in title or fl in summary or title in fl:
                return row
    # значимые слова (≥4) из запроса vs заголовки
    words = [
        w
        for w in re.findall(r"[A-Za-zА-Яа-яЁё0-9]{4,}", text.lower())
        if w
        not in {
            "новость",
            "новости",
            "новостях",
            "расскажи",
            "обсудим",
            "подумать",
            "думаешь",
            "последних",
            "интересного",
            "интересные",
        }
    ]
    if len(words) < 2:
        return None
    best: dict[str, Any] | None = None
    best_score = 0
    for row in candidates[:80]:
        title = str(row.get("title") or "").lower()
        score = sum(1 for w in words if w in title)
        if score > best_score:
            best_score = score
            best = row
    if best_score >= 2:
        return best
    return None


def _context_block(desk: NewsDesk, items: list[dict[str, Any]]) -> str:
    from zipka.news.reader import sanitize_news_summary

    lines: list[str] = []
    for i, h in enumerate(items, 1):
        when = (h.get("published_at") or h.get("fetched_at") or "")[:16]
        src = h.get("source") or ""
        title = h.get("title") or "Без заголовка"
        body = str(h.get("text") or "")
        summary = sanitize_news_summary(
            str(h.get("summary") or ""),
            fallback=body[:420] if body else title,
        )
        url = desk.item_source_url(h)
        lines.append(f"{i}. [{when}] {src}: {title}")
        if summary and summary.strip() != str(title).strip():
            lines.append(f"   {summary[:420]}")
        if url:
            lines.append(f"   URL: {url}")
    return "\n".join(lines) if lines else "(пусто)"


def _looks_like_bad_llm_reply(text: str, user_text: str = "") -> bool:
    raw = (text or "").strip()
    low = raw.lower()
    if len(raw) < 60:
        return True
    markers = (
        "не здоровайся",
        "в ответе обязательно",
        "опирайся только на блок",
        "блок «выдержки»",
        "пользователь ждёт именно",
        "напиши ответ пользователю",
        "единственный источник фактов",
    )
    if sum(1 for m in markers if m in low) >= 1:
        return True
    u = (user_text or "").strip().lower()
    if u and (low == u or u in low or low in u):
        return True
    # эхо «Привет, Зипка. <тот же вопрос>»
    if u and low.endswith(u) and len(raw) < len(user_text) + 40:
        return True
    return False


def _llm_news_reply(
    desk: NewsDesk,
    *,
    intent: NewsIntent,
    user_text: str,
    items: list[dict[str, Any]],
    filters: NewsFilters,
) -> str | None:
    if not items:
        return None
    if not getattr(desk.llm, "is_available", lambda: False)():
        return None

    persona = Persona(desk.settings)
    system = persona.system_prompt(
        skills=desk.memory.get_skills() if hasattr(desk.memory, "get_skills") else None,
        preferences=(
            desk.memory.get_preferences()
            if hasattr(desk.memory, "get_preferences")
            else None
        ),
    )
    task = {
        NewsIntent.OPINION: (
            "Дай своё живое мнение по этим новостям: что цепляет, что раздражает, "
            "где шум. Факты только из выдержек."
        ),
        NewsIntent.DISCUSS: (
            "Обсуди тему/новость с характером: разбери суть, можно усомниться, "
            "не будь дайджест-ботом."
        ),
        NewsIntent.BROWSE: (
            "Короткий обзор ленты: 3–5 акцентов своими словами + лёгкая оценка. "
            "Не здоровайся и не предлагай обновить ленту."
        ),
        NewsIntent.SEARCH: (
            "По найденным упоминаниям темы ответь по делу; если слабо релевантно — скажи честно."
        ),
    }[intent]

    filt_bits = [f"период≈{filters.days}д"]
    if filters.topic:
        filt_bits.append(f"тема≈{filters.topic}")
    if filters.source:
        filt_bits.append(f"источник≈@{filters.source}")
    user_block = (
        f"Задача: {task}\n"
        f"Сообщение пользователя: {user_text}\n"
        f"Фильтр: {', '.join(filt_bits)}; выдержек: {len(items)}\n\n"
        f"Выдержки (единственный источник фактов):\n{_context_block(desk, items)}\n\n"
        "Напиши ответ пользователю от лица Зипки. "
        "Сошлись минимум на два пункта из выдержек. "
        "Не цитируй и не пересказывай эти инструкции."
    )
    try:
        raw = desk.llm.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_block},
            ]
        ).strip()
    except (LlmError, Exception):
        return None
    if not raw or _looks_like_bad_llm_reply(raw, user_text):
        return None
    return raw


def answer_news_dialogue(desk: NewsDesk, text: str) -> str | None:
    """Ответ на вопрос о новостях или None, если это не news-dialogue."""
    from zipka.news.reader import _NEWS_UPDATE_RE

    if not _NEWS_UPDATE_RE.search(text) and not classify_intent(text):
        return None

    # ingest / источники — не сюда
    low = text.lower()
    if any(
        k in low
        for k in (
            "обнови новости",
            "прочитай новости",
            "изучи новости",
            "подтянуть новости",
            "собери новости",
            "добавь rss",
            "добавь телеграм",
            "добавь telegram",
            "добавь тг",
            "покажи источники",
            "источники новостей",
        )
    ):
        return None

    intent = classify_intent(text)
    if intent is None and _NEWS_UPDATE_RE.search(text):
        intent = NewsIntent.BROWSE
    if intent is None:
        return None

    days = desk.extract_days(text, default=7)
    topic = extract_topic(text)
    source = extract_source(text)
    limit = 8 if intent in {NewsIntent.BROWSE, NewsIntent.OPINION} else 12
    filters = NewsFilters(days=days, topic=topic, source=source, limit=limit)

    # конкретная новость
    pool = filter_items(desk, NewsFilters(days=days, source=source, limit=80))
    specific = match_specific_item(desk, text, pool)
    if specific and intent in {
        NewsIntent.DISCUSS,
        NewsIntent.OPINION,
        NewsIntent.BROWSE,
    }:
        items = [specific]
        intent = (
            NewsIntent.OPINION if intent == NewsIntent.OPINION else NewsIntent.DISCUSS
        )
    elif intent == NewsIntent.SEARCH and topic:
        items = desk.search(topic, days=days, limit=limit)
        if source:
            sl = source.lower()
            items = [
                h
                for h in items
                if sl in str(h.get("source") or "").lower()
                or sl in str(h.get("url") or "").lower()
            ]
    else:
        # browse / discuss / opinion — topic как мягкий фильтр
        items = filter_items(desk, filters)
        if not items and topic:
            items = desk.search(topic, days=days, limit=limit)

    if not items:
        hint = ""
        if topic:
            hint = f" по «{topic}»"
        return (
            f"За последние {days} дн.{hint} в сохранённых новостях пусто. "
            "Можешь сказать «обнови новости» — подтяну свежие выдержки."
        )

    llm_reply = _llm_news_reply(
        desk,
        intent=intent,
        user_text=text,
        items=items[:limit],
        filters=filters,
    )
    if llm_reply:
        return llm_reply

    # fallback без LLM / при плохом ответе модели
    if intent == NewsIntent.SEARCH and topic:
        return desk.format_search_answer(topic=topic, days=days, hits=items)
    head = {
        NewsIntent.OPINION: f"Мой взгляд на ленту за {days} дн.",
        NewsIntent.DISCUSS: f"Давай по делу за {days} дн.",
        NewsIntent.BROWSE: f"Что цепляет за {days} дн.",
    }.get(intent, f"За {days} дн.")
    title = f"{head} ({len(items)} выдержек"
    if topic:
        title += f", тема «{topic}»"
    if source:
        title += f", @{source}"
    title += "):"
    lines = [title, ""]
    for h in items[:8]:
        lines.append(desk.format_hit_block(h))
        lines.append("")
    if intent in {NewsIntent.OPINION, NewsIntent.DISCUSS, NewsIntent.BROWSE}:
        lines.append(
            "Могу разобрать одну подробнее или сказать, что думаю — "
            "ткни в заголовок или источник."
        )
    return "\n".join(lines).rstrip()
