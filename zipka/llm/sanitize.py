from __future__ import annotations

import re

# Qwen3 / thinking-модели кладут рассуждения в <think>...</think>
_THINK_BLOCK_RE = re.compile(r"<think>\s*[\s\S]*?</think>", re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</?think>", re.IGNORECASE)


def strip_thinking(text: str) -> str:
    """Убрать блоки размышлений из ответа модели."""
    if not text:
        return ""
    cleaned = _THINK_BLOCK_RE.sub("", text)
    cleaned = _THINK_TAG_RE.sub("", cleaned)
    # частые артефакты после вырезания
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
