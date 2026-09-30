"""Сборка сообщений для LLM-чата."""
from __future__ import annotations

from typing import Any

from zipka.sensors.feature import sensors_feature_enabled


def normalize_reply_context(
    reply_chain: list[dict[str, Any]] | None,
    reply_to: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Цепочка сообщений для приоритетного контекста (от раннего к цели)."""
    raw = list(reply_chain or [])
    if not raw and reply_to:
        raw = [reply_to]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        role = str(item.get("role") or "user").strip().lower()
        if role in {"bot", "assistant", "zipka"}:
            role = "assistant"
        else:
            role = "user"
        key = f"{role}:{content[:200]}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"role": role, "content": content[:4000]})
        if len(out) >= 12:
            break
    return out


def build_messages(
    agent: Any,
    user_text: str,
    *,
    reply_context: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    note_limit = 4 if getattr(agent.llm, "backend", "") == "gguf" else 8
    hist_limit = 6 if getattr(agent.llm, "backend", "") == "gguf" else 16
    # короткие заметки: длинные выжимки книг иначе раздувают ctx и тормозят чат
    note_cap = 350 if getattr(agent.llm, "backend", "") == "gguf" else 500
    notes = [
        (n.get("text") or "")[:note_cap]
        for n in agent.memory.recent_notes(limit=note_limit)
    ]
    system = agent.persona.system_prompt(
        skills=agent.memory.get_skills(),
        preferences=agent.memory.get_preferences(),
        notes=notes,
        mind_state=agent.mind.load(),
        user_profile_block=agent.user.prompt_block(),
    )
    system += (
        "\nПользователь может дать путь к книге или исходному коду "
        "(.py/.js/.ts/…), папке с кодом, zip/rar — или загрузить файл в web. "
        "Также можно дать URL статьи (https://…) со словами «прочитай/прочти» — "
        "Зипка скачает страницу и сделает выжимку."
    )
    if sensors_feature_enabled(agent.settings):
        if agent.eyes.enabled:
            system += (
                "\nГлаза СЕЙЧАС ВКЛЮЧЕНЫ (веб-камера активна). "
                "Если просят посмотреть / что видишь — ты реально смотришь "
                "(система даст описание кадра). "
                "Запрещено отнекиваться: «не умею смотреть», «у меня нет глаз», "
                "«я текстовая модель», «не вижу напрямую»."
            )
        else:
            system += (
                "\nСенсоры разрешены в настройках, но глаза сейчас выключены. "
                "Если просят посмотреть — скажи включить глаза в UI "
                "или напиши «включи глаза»."
            )
        if not agent.ears.enabled:
            system += (
                "\nУши сейчас выключены. Слушать — кнопка «Уши»/«Слушать» "
                "или «включи уши»."
            )
    else:
        system += (
            "\nСенсоры (глаза и уши) ВЫКЛЮЧЕНЫ master-switch'ем в Настройках. "
            "Не предлагай кнопки на главной и не делай вид, что видишь/слышишь. "
            "Если просят камеру/микрофон — направь включить «Сенсоры» в Настройках."
        )
    system += (
        "\nЕсли просят изменить файлы zipka/ или web/ — не присылай пример кода "
        "«как будто уже сделала». Hard-evolve сам подготовит патч на approve "
        "(«разрешаю правку кода»). В обычном чате не выдавай большие блоки кода "
        "вместо реальной правки."
    )
    if reply_context:
        system += (
            "\n\nПРИОРИТЕТНЫЙ КОНТЕКСТ: пользователь нажал «ответить» на старое "
            "сообщение и продолжает ИМЕННО ту ветку разговора. "
            "Опирайся на цепочку ниже сильнее, чем на недавний общий чат. "
            "Не меняй тему на последние сообщения, если они не про это.\n"
            "Цепочка (от более раннего к сообщению, на которое ответили):\n"
        )
        for i, item in enumerate(reply_context, 1):
            role = item.get("role") or "user"
            who = "USER" if role == "user" else "ZIPKA"
            content = str(item.get("content") or "").strip()[:2500]
            if not content:
                continue
            system += f"{i}. [{who}]: {content}\n"

    history = agent.memory.recent_chat(limit=hist_limit)
    messages: list[dict[str, str]] = [{"role": "system", "content": system}]
    messages.extend(history)
    if reply_context:
        target = reply_context[-1]
        preview = str(target.get("content") or "")[:400]
        messages.append(
            {
                "role": "user",
                "content": (
                    f"(Ответ на сообщение: «{preview}»)\n\n{user_text}"
                ),
            }
        )
    else:
        messages.append({"role": "user", "content": user_text})
    return messages
