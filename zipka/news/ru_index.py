"""Русский индекс новостей: razdel + pymorphy3 + лёгкий fuzzy fallback."""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-.&]{0,48}")

# Частые служебные леммы — не для матча темы
_STOP_LEMMAS = {
    "и",
    "в",
    "во",
    "не",
    "на",
    "с",
    "со",
    "а",
    "но",
    "да",
    "к",
    "ко",
    "у",
    "о",
    "об",
    "обо",
    "от",
    "до",
    "по",
    "из",
    "за",
    "под",
    "над",
    "при",
    "про",
    "для",
    "без",
    "между",
    "через",
    "ли",
    "же",
    "бы",
    "то",
    "это",
    "этот",
    "эта",
    "эти",
    "тот",
    "та",
    "те",
    "он",
    "она",
    "они",
    "мы",
    "вы",
    "я",
    "ты",
    "быть",
    "есть",
    "как",
    "что",
    "чтобы",
    "или",
    "если",
    "когда",
    "уже",
    "еще",
    "ещё",
    "только",
    "также",
    "очень",
    "можно",
    "нужно",
    "новость",
    "лента",
    "канал",
    "источник",
    "выдержка",
}

# бренд-алиасы (поверх морфологии)
_ALIASES: dict[str, tuple[str, ...]] = {
    "озон": ("ozon", "озон"),
    "ozon": ("ozon", "озон"),
    "вайлдберриз": ("wildberries", "wb", "вайлдберриз"),
    "wildberries": ("wildberries", "wb", "вайлдберриз"),
    "wb": ("wildberries", "wb", "вайлдберриз"),
    "яндекс": ("yandex", "яндекс"),
    "yandex": ("yandex", "яндекс"),
    "сбер": ("sber", "сбер", "sberbank"),
    "тинькофф": ("tinkoff", "tbank", "тинькофф"),
}

_morph = None
_morph_failed = False


def _get_morph():
    global _morph, _morph_failed
    if _morph_failed:
        return None
    if _morph is None:
        try:
            import pymorphy3

            _morph = pymorphy3.MorphAnalyzer()
        except Exception:
            _morph_failed = True
            return None
    return _morph


def tokenize(text: str) -> list[str]:
    raw = text or ""
    try:
        from razdel import tokenize as razdel_tokenize

        out = []
        for tok in razdel_tokenize(raw):
            t = tok.text.strip("«»\"'.,!?:;()[]")
            if _WORD_RE.fullmatch(t):
                out.append(t)
        return out
    except Exception:
        return _WORD_RE.findall(raw)


def _norm_surface(token: str) -> str:
    return token.strip().lower().replace("ё", "е")


def lemmatize_token(token: str) -> str:
    t = _norm_surface(token)
    if len(t) < 2:
        return t
    morph = _get_morph()
    if morph is None:
        return t
    try:
        return _norm_surface(morph.parse(t)[0].normal_form)
    except Exception:
        return t


def lemmas_from_text(text: str, *, keep_stops: bool = False) -> list[str]:
    """Уникальные леммы в порядке появления (+ алиасы брендов в индекс)."""
    seen: set[str] = set()
    out: list[str] = []
    for tok in tokenize(text):
        surface = _norm_surface(tok)
        lemma = lemmatize_token(tok)
        candidates = [lemma]
        for alt in _ALIASES.get(lemma, ()) + _ALIASES.get(surface, ()):
            candidates.append(lemmatize_token(alt))
        for cand in candidates:
            if len(cand) < 2:
                continue
            if not keep_stops and cand in _STOP_LEMMAS:
                continue
            if cand not in seen:
                seen.add(cand)
                out.append(cand)
    return out


def item_search_blob(item: dict[str, Any]) -> str:
    return " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("summary") or ""),
            str(item.get("text") or ""),
            str(item.get("source") or ""),
        ]
    )


def ensure_item_lemmas(item: dict[str, Any], *, force: bool = False) -> list[str]:
    existing = item.get("lemmas")
    if (
        not force
        and isinstance(existing, list)
        and existing
        and all(isinstance(x, str) for x in existing)
    ):
        return [str(x) for x in existing]
    lemmas = lemmas_from_text(item_search_blob(item))
    item["lemmas"] = lemmas
    return lemmas


def query_lemma_groups(query: str) -> list[list[str]]:
    """
    Группы лемм запроса: внутри группы — OR (алиасы), между группами — AND.
    «Дмитрий Портнягин» → [[дмитрий], [портнягин]]
    «озон» → [[озон, ozon]]
    """
    groups: list[list[str]] = []
    seen_key: set[str] = set()
    for tok in tokenize(query or ""):
        surface = _norm_surface(tok)
        lemma = lemmatize_token(tok)
        if len(lemma) < 2 or lemma in _STOP_LEMMAS:
            continue
        alts = {lemma}
        for alt in _ALIASES.get(lemma, ()) + _ALIASES.get(surface, ()):
            al = lemmatize_token(alt)
            if len(al) >= 2 and al not in _STOP_LEMMAS:
                alts.add(al)
        key = "|".join(sorted(alts))
        if key in seen_key:
            continue
        seen_key.add(key)
        groups.append(sorted(alts, key=len, reverse=True))
    return groups


def query_lemmas(query: str) -> list[str]:
    """Плоский список (первая лемма каждой группы) — для отладки/подсказок."""
    return [g[0] for g in query_lemma_groups(query) if g]


def build_idf(docs: list[list[str]]) -> dict[str, float]:
    n = max(1, len(docs))
    df: Counter[str] = Counter()
    for lemmas in docs:
        df.update(set(lemmas))
    return {term: math.log(1.0 + n / (1.0 + cnt)) for term, cnt in df.items()}


def lemma_match_score(
    item_lemmas: list[str] | set[str],
    q_groups: list[list[str]],
    *,
    idf: dict[str, float] | None = None,
) -> tuple[bool, float]:
    if not q_groups:
        return False, 0.0
    bag = set(item_lemmas)
    score = 0.0
    hit_groups = 0
    for alts in q_groups:
        hit = next((a for a in alts if a in bag), None)
        if hit is None:
            continue
        hit_groups += 1
        score += float(idf.get(hit, 1.0) if idf else 1.0) * (
            1.0 + 0.15 * min(len(hit), 12)
        )
    if hit_groups == 0:
        return False, 0.0
    # 2+ слова темы — все группы обязательны (ФИО)
    if len(q_groups) >= 2 and hit_groups < len(q_groups):
        return False, 0.0
    return True, score


def fuzzy_fallback_score(query: str, item: dict[str, Any]) -> float:
    """Опечатки / латиница / редкий падеж, который морфология пропустила."""
    q = (query or "").strip()
    if len(q) < 4:
        return 0.0
    try:
        from rapidfuzz import fuzz
    except Exception:
        return 0.0
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    text = str(item.get("text") or "")[:400]
    blob = f"{title}\n{summary}\n{text}"
    if not blob.strip():
        return 0.0
    # partial_ratio хорошо ловит ФИО внутри длинного заголовка
    return float(
        max(
            fuzz.partial_ratio(q.lower(), title.lower()) if title else 0,
            fuzz.partial_ratio(q.lower(), blob.lower()),
            fuzz.token_set_ratio(q.lower(), blob.lower()),
        )
    )


# порог fuzzy: достаточно высокий, чтобы не ловить шум
FUZZY_MIN = 86.0
