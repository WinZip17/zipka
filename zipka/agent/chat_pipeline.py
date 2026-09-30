"""Упорядоченный chat pipeline вместо длинной if-лестницы."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from zipka.llm.base import LlmError
from zipka.llm.factory import describe_backend
from zipka.reset import CONFIRM_PHRASE, is_reset_confirm, is_reset_request

from . import books_intent, evolve_handlers, prompting, vision_intent

Handler = Callable[[Any, "ChatCtx"], str | None]


@dataclass
class ChatCtx:
    text: str
    auto_soft: bool = True
    reply_context: list[dict[str, Any]] = field(default_factory=list)


def handle_safety(agent: Any, ctx: ChatCtx) -> str | None:
    if not agent.safety.is_blocked(ctx.text):
        return None
    reply = agent.safety.refusal()
    agent._remember_turn(ctx.text, reply)
    return reply


def handle_reset(agent: Any, ctx: ChatCtx) -> str | None:
    text = ctx.text
    if agent._reset_pending:
        if is_reset_confirm(text):
            result = agent.reset_learning(confirm=True)
            removed_n = len(result.get("removed") or [])
            reply = (
                f"Обучение сброшено ({removed_n} путей очищено). "
                "Я снова с чистого листа."
            )
            agent._remember_turn(text, reply)
            return reply
        if is_reset_request(text):
            return (
                f"Сброс всё ещё ждёт подтверждения. "
                f"Напиши точно: «{CONFIRM_PHRASE}» "
                "или что угодно другое, чтобы отменить."
            )
        agent._reset_pending = False
        reply = "Сброс отменён."
        agent._remember_turn(text, reply)
        return reply

    if is_reset_request(text):
        agent._reset_pending = True
        reply = (
            "Это сотрёт чат, заметки, цели, книги, снимки и патчи в `data/`. "
            f"Если уверена — напиши точно: «{CONFIRM_PHRASE}». "
            "Любой другой ответ отменит сброс."
        )
        agent._remember_turn(text, reply)
        return reply
    return None


def handle_url_read(agent: Any, ctx: ChatCtx) -> str | None:
    # URL раньше файлов: иначе https://habr.com ловится как s:\habr.c
    agent.set_chat_phase("reading")
    reply = books_intent.try_read_url_from_message(agent, ctx.text)
    if reply is not None:
        agent._remember_turn(ctx.text, reply)
        return reply
    agent.set_chat_phase("replying")
    return None


def handle_news(agent: Any, ctx: ChatCtx) -> str | None:
    agent.set_chat_phase("news")
    reply = agent.news.handle_chat_command(ctx.text)
    if reply is not None:
        agent._remember_turn(ctx.text, reply)
        return reply
    agent.set_chat_phase("replying")
    return None


def handle_book_read(agent: Any, ctx: ChatCtx) -> str | None:
    agent.set_chat_phase("studying")
    reply = books_intent.try_read_from_message(agent, ctx.text)
    if reply is not None:
        agent._remember_turn(ctx.text, reply)
        return reply
    agent.set_chat_phase("replying")
    return None


def handle_look(agent: Any, ctx: ChatCtx) -> str | None:
    agent.set_chat_phase("looking")
    reply = vision_intent.try_look_from_message(agent, ctx.text)
    if reply is not None:
        agent._remember_turn(ctx.text, reply)
        return reply
    agent.set_chat_phase("replying")
    return None


def handle_llm_reply(agent: Any, ctx: ChatCtx) -> str | None:
    """Финальный хендлер: всегда возвращает str (не None)."""
    text = ctx.text
    reply_context = ctx.reply_context
    agent.set_chat_phase("replying")

    if not agent.llm.is_available():
        info = describe_backend(agent.llm)
        if info.get("backend") == "gguf":
            return (
                f"Локальная модель {info.get('model') or 'GGUF'} найдена в data/models, "
                "но недоступна. Установи: pip install llama-cpp-python "
                "и перезапусти Зипку."
            )
        return (
            f"Ollama не отвечает на {agent.settings.ollama_host}. "
            "Запусти `ollama serve` и подтяни модель "
            f"`ollama pull {agent.settings.ollama_model}`, "
            "либо положи *.gguf в data/models (см. README)."
        )

    try:
        agent.user.check_speaker(text)
    except Exception:
        pass

    messages = prompting.build_messages(agent, text, reply_context=reply_context)
    try:
        reply = agent.llm.chat(messages)
    except LlmError as exc:
        agent.user._turn_alert = None
        return str(exc)
    agent._remember_turn(
        text,
        reply,
        reply_to=(reply_context[-1] if reply_context else None),
    )
    agent.mind.bump_turn()
    agent.proactive.bump_turn()

    try:
        nudge = agent.proactive.maybe_goal_nudge()
        reply = agent.proactive.attach(reply, nudge)
    except Exception:
        pass

    do_soft = ctx.auto_soft and evolve_handlers.wants_soft_evolve(text)
    do_reflect = agent.mind.should_reflect()
    if do_soft:
        try:
            result = agent.soft.apply_user_request(text)
            reply += f"\n\n[soft-evolve] {result.get('reason') or 'обновилась'}"
        except Exception:
            pass
    try:
        offer = agent.soft.pending_offer_once()
        reply = agent.proactive.attach(reply, offer)
    except Exception:
        pass
    agent._schedule_post_chat(
        text,
        reply,
        reflect=do_reflect,
        observe=True,
        soft_dialogue=not do_soft,
    )
    return reply


PIPELINE: list[Handler] = [
    handle_safety,
    handle_reset,
    handle_url_read,
    handle_news,
    handle_book_read,
    handle_look,
    evolve_handlers.handle_soft_approve,
    evolve_handlers.handle_soft_decline,
    evolve_handlers.handle_finetune_approve,
    evolve_handlers.handle_hard_approve,
    evolve_handlers.handle_soft_pending_hint,
    evolve_handlers.handle_finetune_pending_hint,
    evolve_handlers.handle_hard_pending_hint,
    evolve_handlers.handle_finetune_propose,
    evolve_handlers.handle_hard_propose,
    handle_llm_reply,
]


def run_chat_pipeline(agent: Any, ctx: ChatCtx) -> str:
    for handler in PIPELINE:
        result = handler(agent, ctx)
        if result is not None:
            return result
    return "Пусто. Скажи что-нибудь."
