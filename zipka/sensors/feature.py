"""Master-switch сенсоров (глаза+уши): runtime.json → sensors_enabled."""
from __future__ import annotations

from typing import Any, Literal

from zipka.config import Settings, get_settings
from zipka.runtime_settings import load_runtime

SensorKind = Literal["eyes", "ears", "look", "listen", "sensors"]

REFUSE: dict[str, str] = {
    "eyes": (
        "Если хочешь, чтобы я смотрела — сначала включи «Сенсоры» в Настройках. "
        "Пока общий рубильник выключен, камера для меня как за шторой: "
        "кнопки глаз/камер на главной даже не появятся."
    ),
    "look": (
        "Хотела бы глянуть — но сенсоры сейчас выключены целиком. "
        "Открой Настройки и включи «Сенсоры»: тогда снова будут глаза, "
        "камера и снимки. Пока рубильник off — я слепая по правилам дома."
    ),
    "ears": (
        "Если хочешь, чтобы я слышала — включи «Сенсоры» в Настройках. "
        "Пока общий выключатель выключен, микрофон мне не подать: "
        "блок ушей на главной спрятан вместе с глазами."
    ),
    "listen": (
        "Прислушаться бы — да сенсоры выключены в Настройках. "
        "Включи «Сенсоры» (один рубильник на глаза и уши), "
        "потом уже можно «Уши» и «Слушать»."
    ),
    "sensors": (
        "Сенсоры сейчас выключены в Настройках — и глаза, и уши. "
        "Включи там переключатель «Сенсоры», если хочешь, чтобы я снова "
        "видела и слышала."
    ),
}


def sensors_feature_enabled(settings: Settings | None = None) -> bool:
    try:
        return bool(load_runtime(settings or get_settings()).get("sensors_enabled"))
    except Exception:
        return False


def refuse_sensors(kind: SensorKind = "sensors") -> str:
    return REFUSE.get(kind) or REFUSE["sensors"]


def detect_sensor_chat_intent(text: str) -> SensorKind | None:
    """Какой сенсорный запрос в фразе (для отказа при выключенном master-switch)."""
    import re

    low = (text or "").lower().strip()
    if not low:
        return None
    if re.search(
        r"(?i)включ\w*\s+уш|ears\s+on|открой\s+микрофон|включи\s+микрофон",
        low,
    ):
        return "ears"
    if re.search(
        r"(?i)(послуш\w*|послуш\w*\s+меня|ears\s+listen|послуш\w*\s+\d|"
        r"слушай\s+меня|послуш\w*\s+микрофон)",
        low,
    ):
        return "listen"
    if re.search(
        r"(?i)включ\w*\s+глаз|eyes\s+on|открой\s+камер|включи\s+камер",
        low,
    ):
        return "eyes"
    if re.search(
        r"(?i)включ\w*\s+сенсор|включи\s+сенсор",
        low,
    ):
        return "sensors"
    return None


def force_sensors_off(agent: Any) -> None:
    """Принудительно погасить глаза и уши (после выключения master-switch)."""
    try:
        if getattr(agent, "eyes", None) is not None:
            agent.eyes.off()
    except Exception:
        pass
    try:
        if getattr(agent, "ears", None) is not None:
            agent.ears.off()
    except Exception:
        pass
