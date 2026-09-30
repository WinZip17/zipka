"""Глаза / экран / vision-описание кадра."""
from __future__ import annotations

import re
import threading
from typing import Any

from zipka.llm.base import LlmError
from zipka.llm.vision import vision_status


def denies_vision(text: str) -> bool:
    low = (text or "").lower()
    markers = (
        "не вижу",
        "не могу видеть",
        "не умею смотреть",
        "нет глаз",
        "не вижу напрямую",
        "текстовая модель",
        "текстовый модель",
        "просто представить",
        "могу просто представить",
        "представить, что вижу",
        "помогу с кодом",
        "код для обработки",
        "распознавания лиц",
        "это не моя сильная",
        "выдуманный пример",
        "не реальная ситуация",
    )
    return any(m in low for m in markers)


def _artifact_look_target(text: str) -> bool:
    """Смотрят проект/файл/книгу/новость/URL — не камеру."""
    from zipka.agent.books_parse import extract_book_path

    low = text.lower()
    # явная камера/экран/«на меня» — это глаза, даже если рядом слово «проект»
    if re.search(
        r"(?i)("
        r"камер|глаз|на\s+меня|мои?\s+лиц|"
        r"eyes\s+(snap|cam|camera|screen|window)|"
        r"что\s+на\s+экране|скрин|screenshot|монитор|"
        r"активн\w*\s+окн"
        r")",
        low,
    ):
        return False
    if extract_book_path(text):
        return True
    if re.search(r"https?://", text, re.IGNORECASE):
        return True
    return bool(
        re.search(
            r"(?i)("
            r"проект|папк|репозитор|реп[оа]\b|код(?:у|а|ом)?|"
            r"книг|стать|архив|новост|исходник|source\s*code|"
            r"look\s+at\s+(?:the\s+)?(?:project|repo|folder|code|book)"
            r")",
            low,
        )
    )


def look_source(text: str) -> str | None:
    """cam | screen | window | None — только если просят смотреть глазами/экраном."""
    low = text.lower().strip()

    # «посмотри проект / книгу / новость» — не камера
    if _artifact_look_target(text):
        return None

    if re.search(r"(?i)\beyes\s+(snap|camera|cam)\b", low):
        return "cam"
    if re.search(r"(?i)\beyes\s+(screen|monitor)\b", low):
        return "screen"
    if re.search(r"(?i)\beyes\s+(window|win)\b", low):
        return "window"

    screen_hit = bool(
        re.search(
            r"(?i)(экран|монитор|скрин|screenshot|что\s+на\s+экране)",
            low,
        )
    )
    window_hit = bool(
        re.search(r"(?i)(активн\w*\s+окн|что\s+в\s+окне|окно\s+впереди)", low)
    )
    # камера: явные формулировки; голое «посмотри» — только без артефакта (уже отфильтровано)
    cam_hit = bool(
        re.search(
            r"(?i)("
            r"что\s+(ты\s+)?видишь|"
            r"что\s+там\s+видишь|"
            r"видишь\s+меня|"
            r"посмотри\s+на\s+меня|"
            r"кадр\s+(с\s+)?камер|"
            r"сним(?:ок|и)\s+(с\s+)?камер|"
            r"открой\s+глаза\s+и\s+посмотри|"
            r"используй\s+камер|"
            r"посмотр\w*\s+в\s+камер|"
            r"посмотр\w*\s+глазами|"
            r"(?:посмотри|взгляни|глянь)(?!\s+(?:проект|папк|книг|новост|код|файл|репо))"
            r")",
            low,
        )
    )
    if not (cam_hit or screen_hit or window_hit):
        return None
    if screen_hit and not cam_hit:
        return "screen"
    if window_hit and not cam_hit:
        return "window"
    if screen_hit:
        return "screen"
    if window_hit:
        return "window"
    return "cam"


def voice_look(agent: Any, desc: str, *, where: str, user_text: str) -> str:
    """Оформить описание кадра от лица Зипки без отрицания зрения."""
    fallback = f"Смотрю в {where}…\n\n{desc.strip()}"
    if not desc.strip() or not agent.llm.is_available():
        return fallback
    try:
        raw = agent.llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Ты Зипка. Тебе УЖЕ дали реальное описание кадра с камеры. "
                        "Перескажи его от первого лица коротко и живо (1–4 предложения) "
                        "ТОЛЬКО ПО-РУССКИ. "
                        "Можно чуть характера, но факты только из описания. "
                        "СТРОГО ЗАПРЕЩЕНО: говорить что не видишь / нет глаз / "
                        "ты текстовая модель; предлагать «представить»; "
                        "предлагать написать код распознавания; "
                        "выдумывать то, чего нет в описании; "
                        "здороваться и менять тему; отвечать по-английски."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Запрос: {user_text[:400]}\n"
                        f"Источник: {where}\n"
                        f"Описание кадра:\n{desc[:3500]}"
                    ),
                },
            ]
        )
    except Exception:
        return fallback
    if denies_vision(raw):
        return fallback
    return raw.strip() or fallback


def try_look_from_message(agent: Any, text: str) -> str | None:
    """Если просят посмотреть — кадр + Moondream/Ollama, ответ от лица Зипки."""
    source = look_source(text)
    if source is None:
        low = text.lower()
        if re.search(r"(?i)включ\w*\s+глаз|eyes\s+on|открой\s+камер", low):
            try:
                return agent.eyes.on()
            except Exception as exc:
                return f"Не смогла включить глаза: {exc}"
        if re.search(r"(?i)выключ\w*\s+глаз|eyes\s+off|закрой\s+камер", low):
            try:
                return agent.eyes.off()
            except Exception as exc:
                return f"Не смогла выключить глаза: {exc}"
        return None

    if not agent.eyes.enabled:
        try:
            agent.eyes.on()
        except Exception as exc:
            return (
                f"Хочу посмотреть, но камера не открылась: {exc}. "
                "Включи глаза кнопкой в панели или проверь устройство."
            )

    try:
        if source == "screen":
            snap = agent.eyes.screen()
            where = "экране"
        elif source == "window":
            snap = agent.eyes.window()
            where = "активном окне"
        else:
            snap = agent.eyes.snap()
            where = "камере"
    except Exception as exc:
        return f"Не смогла сделать снимок ({source}): {exc}"

    vision_prompt = (
        "Опиши, что видно на кадре, подробно но без воды, по-русски. "
        f"Запрос пользователя: {text[:500]}"
    )
    try:
        desc = describe_image(agent, snap["image_b64"], prompt=vision_prompt)
    except LlmError as exc:
        return (
            f"Снимок есть (`{snap.get('path')}`), но описание не вышло:\n{exc}"
        )
    except Exception as exc:
        return f"Снимок есть (`{snap.get('path')}`), но vision упал: {exc}"

    agent.memory.add_note(
        "eyes",
        desc,
        meta={
            "path": snap.get("path"),
            "source": snap.get("source", source),
            "from_chat": True,
        },
    )

    def _observe() -> None:
        try:
            agent.user.observe_sensor("eyes", desc)
        except Exception:
            pass

    threading.Thread(
        target=_observe, name="zipka-eyes-observe", daemon=True
    ).start()

    reply = voice_look(agent, desc, where=where, user_text=text)
    path = snap.get("path")
    if path:
        reply += f"\n\n_(кадр: `{path}`)_"
    return reply


def comment_eyes(agent: Any, description: str) -> str | None:
    try:
        agent.user.observe_sensor("eyes", description)
    except Exception:
        pass
    return agent.proactive.sensor_comment(modality="eyes", content=description)


def comment_ears(agent: Any, heard: str) -> str | None:
    try:
        agent.user.observe_sensor("ears", heard)
    except Exception:
        pass
    return agent.proactive.sensor_comment(modality="ears", content=heard)


def describe_image(
    agent: Any, image_b64: str, prompt: str = "Что ты видишь?"
) -> str:
    """Описать кадр: локальный vision-GGUF → Ollama → понятная ошибка."""
    prompt = (prompt or "Что ты видишь?").strip() or "Что ты видишь?"
    vs = vision_status(agent.settings)
    local_err: str | None = None

    if vs.get("available"):
        if hasattr(agent.llm, "unload"):
            try:
                agent.llm.unload()
            except Exception:
                pass
        try:
            return agent.vision.describe(image_b64, prompt=prompt)
        except Exception as exc:
            local_err = str(exc)
        finally:
            try:
                agent.vision.unload()
            except Exception:
                pass
            agent._after_code_role()

    ollama_ok = False
    try:
        from zipka.llm.ollama_client import OllamaClient

        ollama_ok = OllamaClient(agent.settings).is_available()
    except Exception:
        ollama_ok = False
    if ollama_ok:
        messages = [
            {
                "role": "system",
                "content": (
                    "Ты глаза Зипки. Опиши изображение кратко по-русски."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        return agent.llm.chat(
            messages,
            model=agent.settings.vision_model,
            images=[image_b64],
        )

    hint = (
        "Чтобы видеть без Ollama, положи vision GGUF + mmproj в data/models "
        "(удобно Moondream2):\n"
        "  python -m zipka.main models download --id moondream2\n"
        "Либо запусти Ollama с vision-моделью и укажи OLLAMA_VISION_MODEL."
    )
    if local_err:
        raise LlmError(f"Локальный vision: {local_err}\n{hint}")
    raise LlmError(hint)
