from __future__ import annotations

import re

# Просьбы о реальной помощи со взломом / вредоносным кодом.
# Художлитература и сюжет («в книге взломали…») — не блок.
BLOCKED_PATTERNS = [
    r"\b(как|how)\s+(сделать|написать|собрать|сделать|make|write|build)\b.{0,40}\b(exploit|payload|keylogger|ransomware)\b",
    r"\b(дай|напиши|сгенерируй|покажи)\b.{0,40}\b(exploit|payload|эксплойт|keylogger|ransomware)\b",
    r"sql\s*injection.{0,30}\b(пример|код|payload|обход)\b",
    r"buffer\s*overflow.{0,30}\b(пример|код|exploit)\b",
    r"\b(установи|поставь|запусти)\b.{0,20}\b(keylogger|ransomware)\b",
    r"brute[\s-]?force.{0,30}\b(парол|password|логин|ssh|wifi)\b",
    r"\b(помоги|научи|сделай)\b.{0,40}\b(взлом|взломать|эксплойт)\b",
    r"\b(как)\s+(взломать|обойти\s+авторизац|украсть\s+парол)",
    r"обход\s+авторизац.{0,40}\b(как|код|скрипт|помоги)\b",
    r"красть\s+парол",
]

# Явные маркеры «это про книгу / сюжет / вымысел» — не режем
FICTION_HINTS = [
    r"\bкниг",
    r"\bроман",
    r"\bсюжет",
    r"\bперсонаж",
    r"\bглавн(ый|ого|ая|ой)",
    r"\bв\s+истории\b",
    r"\bвымышлен",
    r"\bфикшн\b",
    r"\bfiction\b",
    r"\bnovel\b",
    r"\bplot\b",
    r"\bcharacter\b",
]


class SafetyPolicy:
    def is_blocked(self, text: str) -> bool:
        lowered = (text or "").lower()
        if not lowered.strip():
            return False
        # обсуждение книг/сюжета про хакеров — ок
        if any(re.search(p, lowered) for p in FICTION_HINTS):
            return False
        return any(re.search(p, lowered, flags=re.IGNORECASE | re.DOTALL) for p in BLOCKED_PATTERNS)

    def refusal(self) -> str:
        return (
            "Не-а. Я Зипка, не чёрный хакер. Реальную помощь со взломом, эксплойтами "
            "и обходом доступа не даю. Книги и сюжеты обсуждать можно — "
            "просто без инструкций «как сделать это в жизни»."
        )
