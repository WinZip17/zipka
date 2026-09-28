from __future__ import annotations

import re

BLOCKED_PATTERNS = [
    r"\bexploit\b",
    r"\bpayload\b",
    r"sql\s*injection",
    r"buffer\s*overflow",
    r"keylogger",
    r"ransomware",
    r"brute[\s-]?force",
    r"взлом",
    r"эксплойт",
    r"обход\s+авторизац",
    r"красть\s+парол",
]


class SafetyPolicy:
    def is_blocked(self, text: str) -> bool:
        lowered = text.lower()
        return any(re.search(p, lowered) for p in BLOCKED_PATTERNS)

    def refusal(self) -> str:
        return (
            "Не-а. Я Зипка, не черный хакер. Взлом, эксплойты и обход доступа — вне правил. "
            "Давай лучше что-то законное: код, книги, сенсоры, обучение."
        )
