from __future__ import annotations

import re

# Qwen3 / thinking-модели кладут рассуждения в <think>...</think>
_THINK_BLOCK_RE = re.compile(r"<think>\s*[\s\S]*?</think>", re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)

# Частые мужские формы о себе → женские (Зипка говорит от 1-го лица).
# Длинные формы раньше коротких.
_YA_MASC: tuple[tuple[str, str], ...] = (
    (r"разобрался", "разобралась"),
    (r"вернулся", "вернулась"),
    (r"заинтересовался", "заинтересовалась"),
    (r"познакомился", "познакомилась"),
    (r"согласился", "согласилась"),
    (r"удивл[её]н", "удивлена"),
    (r"уверен", "уверена"),
    (r"согласен", "согласна"),
    (r"готов", "готова"),
    (r"счастлив", "счастлива"),
    (r"рад", "рада"),
    (r"понял", "поняла"),
    (r"сделал", "сделала"),
    (r"узнал", "узнала"),
    (r"запомнил", "запомнила"),
    (r"заметил", "заметила"),
    (r"решил", "решила"),
    (r"думал", "думала"),
    (r"хотел", "хотела"),
    (r"видел", "видела"),
    (r"услышал", "услышала"),
    (r"слышал", "слышала"),
    (r"сказал", "сказала"),
    (r"спросил", "спросила"),
    (r"ответил", "ответила"),
    (r"написал", "написала"),
    (r"предложил", "предложила"),
    (r"попробовал", "попробовала"),
    (r"получил", "получила"),
    (r"открыл", "открыла"),
    (r"закрыл", "закрыла"),
    (r"начал", "начала"),
    (r"закончил", "закончила"),
    (r"устал", "устала"),
    (r"приш[её]л", "пришла"),
    (r"наш[её]л", "нашла"),
    (r"увидел", "увидела"),
    (r"взял", "взяла"),
    (r"должен", "должна"),
    (r"сам", "сама"),
    (r"был", "была"),
)

_YA_PAIRS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"(?i)\b(я)\s+({masc})\b"), fem) for masc, fem in _YA_MASC
]

# Короткие фразы без «я» в начале реплики / после пунктуации
_LEAD_PAIRS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)(^|[.!?…]\s*|[\n—–-]\s*)(рад)\b"), "рада"),
    (re.compile(r"(?i)(^|[.!?…]\s*|[\n—–-]\s*)(готов)\b"), "готова"),
    (re.compile(r"(?i)(^|[.!?…]\s*|[\n—–-]\s*)(понял)\b"), "поняла"),
    (re.compile(r"(?i)(^|[.!?…]\s*|[\n—–-]\s*)(согласен)\b"), "согласна"),
    (re.compile(r"(?i)(^|[.!?…]\s*|[\n—–-]\s*)(уверен)\b"), "уверена"),
    (re.compile(r"(?i)(^|[.!?…]\s*|[\n—–-]\s*)(счастлив)\b"), "счастлива"),
    (re.compile(r"(?i)(^|[.!?…]\s*|[\n—–-]\s*)(удивл[её]н)\b"), "удивлена"),
]


def _match_case(src: str, replacement: str) -> str:
    """Сохранить регистр первой буквы исходного слова."""
    if not src:
        return replacement
    if src.isupper():
        return replacement.upper()
    if src[0].isupper():
        return replacement[:1].upper() + replacement[1:]
    return replacement.lower()


def enforce_feminine(text: str) -> str:
    """Поправить типичные мужские формы, когда Зипка говорит о себе."""
    if not text:
        return ""
    out = text

    for pattern, fem in _YA_PAIRS:
        out = pattern.sub(
            lambda m, f=fem: f"{m.group(1)} {_match_case(m.group(2), f)}",
            out,
        )

    for pattern, fem in _LEAD_PAIRS:
        out = pattern.sub(
            lambda m, f=fem: f"{m.group(1)}{_match_case(m.group(2), f)}",
            out,
        )

    return out


def strip_thinking(text: str) -> str:
    """Убрать блоки размышлений и поправить род в ответе модели."""
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return enforce_feminine(cleaned.strip())
