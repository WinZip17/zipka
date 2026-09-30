from __future__ import annotations

import re
import time
from collections import Counter
from typing import Literal

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

# «Ты …» в женском роде → мужской (когда собеседник — мужчина).
# Не трогаем формы о самой Зипке («я …»).
_TY_FEM_TO_MASC: tuple[tuple[str, str], ...] = (
    (r"живая", "живой"),
    (r"жива", "жив"),
    (r"готова", "готов"),
    (r"уверена", "уверен"),
    (r"согласна", "согласен"),
    (r"рада", "рад"),
    (r"поняла", "понял"),
    (r"сделала", "сделал"),
    (r"устала", "устал"),
    (r"права", "прав"),
    (r"должна", "должен"),
    (r"сама", "сам"),
    (r"первая", "первый"),
    (r"хорошая", "хороший"),
    (r"умная", "умный"),
)

_TY_FEM_PAIRS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"(?i)\b(ты)\s+({fem})\b"), masc) for fem, masc in _TY_FEM_TO_MASC
]

_FILLER_CHARS = set("ХXхx·.•-_=~*#░▒▓█")
_INSTRUCTION_ECHO = (
    "не копируй длинные",
    "не цитируй длинные",
    "отвечай только текстом",
    "кратко: назначение",
    "комментарий/фокус пользователя",
    "это не мой стиль",
)

_gender_cache: tuple[float, str] | None = None
Gender = Literal["male", "female", ""]


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


def enforce_addressee_gender(text: str, gender: Gender | str) -> str:
    """К собеседнику-мужчине не обращаться в женском роде («ты живая» → «ты живой»)."""
    if not text or str(gender or "").lower() not in {"male", "m", "муж", "мужской"}:
        return text
    out = text
    for pattern, masc in _TY_FEM_PAIRS:
        out = pattern.sub(
            lambda m, f=masc: f"{m.group(1)} {_match_case(m.group(2), f)}",
            out,
        )
    return out


def load_addressee_gender() -> Gender:
    """Прочитать gender собеседника из user_profile (кэш ~20 с)."""
    global _gender_cache
    now = time.monotonic()
    if _gender_cache and now - _gender_cache[0] < 20.0:
        return _gender_cache[1]  # type: ignore[return-value]
    gender: Gender = ""
    try:
        from zipka.config import get_settings

        path = get_settings().data_dir / "memory" / "user_profile.json"
        if path.is_file():
            import json

            data = json.loads(path.read_text(encoding="utf-8"))
            ident = data.get("identity") or {}
            raw = str(ident.get("gender") or "").strip().lower()
            if raw in {"male", "m", "муж", "мужской", "man"}:
                gender = "male"
            elif raw in {"female", "f", "жен", "женский", "woman"}:
                gender = "female"
            elif not raw:
                gender = _infer_gender_from_profile(ident, data)
    except Exception:
        gender = ""
    _gender_cache = (now, gender)
    return gender


def _infer_gender_from_profile(ident: dict, data: dict) -> Gender:
    """Эвристика: типичные мужские имена / окончания черт характера."""
    name = str(ident.get("name") or ident.get("how_to_address") or "").strip().lower()
    male_names = {
        "юра",
        "юрий",
        "ура",
        "иван",
        "сергей",
        "алексей",
        "дмитрий",
        "андрей",
        "михаил",
        "павел",
        "николай",
        "максим",
        "артём",
        "артем",
        "кирилл",
        "егор",
        "олег",
        "роман",
        "виктор",
        "игорь",
        "денис",
        "антон",
        "владимир",
        "winzip",
    }
    if name in male_names:
        return "male"
    female_names = {
        "анна",
        "мария",
        "маша",
        "елена",
        "ольга",
        "наташа",
        "наталья",
        "екатерина",
        "катя",
        "ирина",
        "татьяна",
        "юлия",
        "даша",
        "дарья",
        "алина",
        "виктория",
    }
    if name in female_names:
        return "female"
    chars = data.get("character") or []
    masc_end = 0
    fem_end = 0
    for c in chars:
        s = str(c).strip().lower()
        if re.search(r"(ен|ан|ый|ий|ой)$", s):
            masc_end += 1
        if re.search(r"(на|ая|яя)$", s):
            fem_end += 1
    if masc_end >= 2 and masc_end > fem_end:
        return "male"
    if fem_end >= 2 and fem_end > masc_end:
        return "female"
    return ""


def is_degenerate_generation(text: str) -> bool:
    """XXXX/заполнители, повтор одного символа, эхо инструкции."""
    t = (text or "").strip()
    if len(t) < 12:
        return len(t) < 4
    low = t.lower()
    if any(p in low for p in _INSTRUCTION_ECHO) and len(t) < 120:
        # короткая отписка = эхо промпта
        if not re.search(r"[а-яё]{4,}", low):
            return True
        # целиком фраза из инструкции
        if sum(1 for p in _INSTRUCTION_ECHO if p in low) >= 1 and len(t) < 80:
            return True

    compact = re.sub(r"\s+", "", t)
    if not compact:
        return True
    if re.search(r"(.)\1{20,}", compact):
        return True
    ch, n = Counter(compact).most_common(1)[0]
    if n / len(compact) >= 0.45 and (ch in _FILLER_CHARS or not ch.isalnum()):
        return True
    # доля заполнителей
    fillers = sum(1 for c in compact if c in _FILLER_CHARS)
    if fillers / len(compact) >= 0.35 and len(compact) >= 40:
        return True
    # почти нет кириллических слов при «русском» задании
    letters = sum(1 for c in compact if c.isalpha())
    cyr = sum(1 for c in compact if "а" <= c.lower() <= "я" or c.lower() == "ё")
    if letters >= 40 and cyr / max(1, letters) < 0.15 and fillers > 10:
        return True
    return False


def strip_thinking(text: str) -> str:
    """Убрать блоки размышлений и поправить род в ответе модели."""
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = enforce_feminine(cleaned.strip())
    cleaned = enforce_addressee_gender(cleaned, load_addressee_gender())
    return cleaned
