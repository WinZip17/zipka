"""Ранние сообщения в консоль перед нагрузкой на GPU / модель ИИ."""

from __future__ import annotations

import logging
import sys
from typing import Any

_log = logging.getLogger("zipka.ai")


def announce_ai(action: str, *parts: Any) -> None:
    """Печатает в stdout (flush) до тяжёлой работы модели.

    Пример: announce_ai("чат", "роль=chat", "модель=foo.gguf")
    """
    detail = " | ".join(str(p) for p in parts if p is not None and str(p) != "")
    msg = f"[zipka.ai] {action}" if not detail else f"[zipka.ai] {action} | {detail}"
    try:
        # Windows-консоль часто не UTF-8 — пишем через буфер с заменой
        buf = getattr(sys.stdout, "buffer", None)
        if buf is not None:
            enc = getattr(sys.stdout, "encoding", None) or "utf-8"
            buf.write((msg + "\n").encode(enc, errors="replace"))
            buf.flush()
        else:
            print(msg, flush=True)
    except Exception:
        try:
            print(msg.encode("ascii", "replace").decode("ascii"), flush=True)
        except Exception:
            pass
    _log.info("%s", msg)
