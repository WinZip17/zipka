"""Ветки soft / hard / finetune в chat pipeline."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .chat_pipeline import ChatCtx


def wants_soft_evolve(text: str) -> bool:
    lowered = text.lower()
    keys = [
        "эволюционируй",
        "измени характер",
        "обнови навыки",
        "soft evolve",
        "стань более",
        "запомни предпочтение",
    ]
    return any(k in lowered for k in keys)


def code_change_request(agent: Any, text: str) -> str | None:
    """Текст для hard.propose или None, если это не запрос правок."""
    if agent.hard.wants_code_change(text):
        return text

    low = text.lower().strip()
    affirm = bool(
        re.match(
            r"^(да|ок|хорошо|ага|угу|давай|сделай|внеси|реализуй|добавь|"
            r"примени|поехали)\b",
            low,
        )
        or "как предложила" in low
        or "как ты написала" in low
        or "этот код" in low
        or "в свой код" in low
    )
    if not affirm:
        return None

    hist = agent.memory.recent_chat(limit=6)
    last_bot = ""
    for m in reversed(hist):
        if m.get("role") == "assistant":
            last_bot = m.get("content") or ""
            break
    if not last_bot:
        return None
    markers = (
        "```",
        "zipka/",
        "web/",
        "detect_faces",
        "eyes.py",
        "правк",
        "патч",
        "добавлю в",
    )
    if not any(m in last_bot.lower() or m in last_bot for m in markers):
        return None
    return (
        f"{text}\n\n"
        "Контекст: реализуй план из предыдущего ответа Зипки как hard-evolve "
        "патч (<<<FILE>>>/<<<OLD>>>/<<<NEW>>> или JSON files[].edits), "
        "не текст с примером.\n"
        f"План:\n{last_bot[:3500]}"
    )


def handle_soft_approve(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if not agent.soft.is_approve(text):
        return None
    if not agent.soft.has_pending():
        return "Нечего запоминать — предложения soft-evolve нет."
    try:
        applied = agent.soft.apply_pending()
    except Exception as exc:
        reply = f"Не смогла применить soft-evolve: {exc}"
        agent._remember_turn(text, reply)
        return reply
    reason = applied.get("reason") or "обновилась"
    reply = f"Запомнила. Soft-evolve: {reason}."
    agent._remember_turn(text, reply)
    return reply


def handle_soft_decline(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if not agent.soft.is_decline(text):
        return None
    if not agent.soft.has_pending():
        return "Отменять нечего — предложения soft-evolve нет."
    agent.soft.clear_pending()
    reply = "Ок, не запоминаю."
    agent._remember_turn(text, reply)
    return reply


def handle_soft_pending_hint(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if agent.soft.has_pending() and any(
        k in text.lower()
        for k in ("soft", "запомн", "характер", "навык", "предпочтен")
    ):
        return agent.soft.format_pending()
    return None


def handle_finetune_approve(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if not agent.finetune.is_approve(text):
        return None
    if not agent.finetune.has_pending():
        st = agent.finetune.refresh_job_status()
        if st.get("state") == "done":
            reply = (
                f"Дообучение уже завершено (gen {st.get('generation')}). "
                f"Результат: {st.get('result')}"
            )
            agent._remember_turn(text, reply)
            return reply
        return "Нечего утверждать — заявки на дообучение нет."
    try:
        started = agent.start_finetune_approved()
    except Exception as exc:
        reply = f"Не смогла запустить дообучение: {exc}"
        agent._remember_turn(text, reply)
        return reply
    reply = started.get("message") or str(started)
    agent._remember_turn(text, reply)
    return reply


def handle_hard_approve(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if not agent.hard.is_approve(text):
        return None
    if not agent.hard.has_pending():
        return "Нечего утверждать — патча нет."
    meta = agent.hard.apply_pending()
    rebuild = meta.get("frontend_rebuild")
    reply = (
        f"Патч {meta['id']} применён. Файлы: {', '.join(meta['files'])}. "
        f"Откат: `zipka rollback {meta['id']}`"
    )
    if rebuild:
        reply += f"\nСборка UI: {rebuild}"
    agent._remember_turn(text, reply)
    agent._after_code_role()
    return reply


def handle_finetune_pending_hint(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if agent.finetune.has_pending() and any(
        k in text.lower()
        for k in ("дообуч", "gguf", "lora", "fine-tune", "finetune")
    ):
        return agent.finetune.format_pending()
    return None


def handle_hard_pending_hint(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if agent.hard.has_pending() and "патч" in text.lower():
        return agent.hard.format_pending()
    return None


def handle_finetune_propose(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if not agent.finetune.wants_finetune(text):
        return None
    try:
        pending = agent.finetune.propose()
    except Exception as exc:
        reply = f"Не смогла подготовить дообучение: {exc}"
        agent._remember_turn(text, reply)
        return reply
    reply = agent.finetune.format_pending(pending)
    agent._remember_turn(text, reply)
    return reply


def handle_hard_propose(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    code_request = code_change_request(agent, text)
    if not code_request:
        return None
    try:
        self_edit, project = agent.hard.resolve_patch_target(code_request)
    except RuntimeError as exc:
        reply = str(exc)
        agent._remember_turn(text, reply)
        return reply
    ctx_notes = None
    notes = agent.memory.recent_notes(limit=5)
    if notes:
        ctx_notes = "\n".join(n.get("text", "") for n in notes)
    try:
        pending = agent.hard.propose(
            code_request,
            project_root=None if self_edit else project,
            context=ctx_notes,
            self_edit=self_edit,
        )
    except Exception as exc:
        reply = f"Не смогла подготовить патч: {exc}"
        agent._remember_turn(text, reply)
        return reply
    reply = agent.hard.format_pending(pending)
    agent._remember_turn(text, reply)
    agent._after_code_role()
    return reply
