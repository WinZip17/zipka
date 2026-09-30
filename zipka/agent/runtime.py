"""Статус, модели, compute, reload / unload."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from zipka.books.reader import BookReader
from zipka.character.persona import Persona
from zipka.config import ensure_data_dirs
from zipka.evolve.finetune import APPROVE_PHRASE as FINETUNE_APPROVE_PHRASE
from zipka.evolve.finetune import RESET_CONFIRM_PHRASE as FINETUNE_RESET_PHRASE
from zipka.evolve.finetune import FinetuneEvolve
from zipka.evolve.hard import APPROVE_PHRASE, HardEvolve
from zipka.evolve.soft import APPROVE_PHRASE as SOFT_APPROVE_PHRASE
from zipka.evolve.soft import SoftEvolve
from zipka.llm.base import LlmError
from zipka.llm.chat_models import models_status, resolve_role_gguf
from zipka.llm.factory import LlmRouter, create_llm_client, describe_backend
from zipka.llm.ollama_client import OllamaError
from zipka.llm.vision import VisionGgufClient, vision_status
from zipka.memory.store import MemoryStore
from zipka.memory.user_profile import UserProfiler
from zipka.mind.goals import PseudoMind
from zipka.mind.proactive import ProactiveEngine
from zipka.net.learner import NetLearner
from zipka.news import NewsDesk
from zipka.reset import reset_learning_data
from zipka.runtime_settings import compute_status, save_runtime
from zipka.safety.policy import SafetyPolicy
from zipka.sensors.ears import Ears
from zipka.sensors.eyes import Eyes
from zipka.sensors.feature import force_sensors_off, sensors_feature_enabled


def is_finetune_busy(agent: Any) -> bool:
    """Идёт LoRA-дообучение: не трогаем модель и фоновые задачи."""
    try:
        return agent.finetune.is_running()
    except Exception:
        return False


def unload_inference_models(agent: Any) -> None:
    """Освободить RAM/VRAM перед тяжёлым LoRA (чат-GGUF / vision)."""
    import gc

    for holder in (agent.llm, getattr(agent, "vision", None)):
        if holder is None:
            continue
        unload = getattr(holder, "unload", None)
        if callable(unload):
            try:
                unload()
            except Exception:
                pass
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def start_finetune_approved(agent: Any) -> dict[str, Any]:
    """Старт дообучения: сначала выгрузить чат-модель, потом воркер."""
    unload_inference_models(agent)
    return agent.finetune.start_approved()


def code_llm(agent: Any) -> Any:
    if isinstance(agent.llm, LlmRouter):
        return agent.llm.code_llm
    return agent.llm


def reload_runtime(agent: Any) -> None:
    """Пересоздать модули после очистки data/."""
    ensure_data_dirs(agent.settings)
    try:
        agent.eyes.off()
    except Exception:
        pass
    agent.llm = create_llm_client(agent.settings)
    agent.memory = MemoryStore(agent.settings)
    agent.persona = Persona(agent.settings)
    agent.soft = SoftEvolve(
        agent.persona, agent.memory, agent.llm, settings=agent.settings
    )
    agent.hard = HardEvolve(code_llm(agent), agent.memory, agent.settings)
    agent.finetune = FinetuneEvolve(agent.memory, agent.settings)
    agent.books = BookReader(agent.llm, agent.memory, agent.settings)
    agent.eyes = Eyes(agent.settings)
    agent.ears = Ears(agent.settings)
    agent.user = UserProfiler(agent.memory, agent.llm, agent.settings)
    agent.mind = PseudoMind(
        agent.persona, agent.memory, agent.llm, agent.soft, agent.settings
    )
    agent.proactive = ProactiveEngine(
        agent.llm, agent.memory, agent.mind, agent.settings
    )
    agent.net = NetLearner(agent.llm, agent.memory, agent.settings)
    agent.news = NewsDesk(agent.llm, agent.memory, agent.settings)
    agent.safety = SafetyPolicy()
    agent.vision = VisionGgufClient(agent.settings)
    agent.uploads_dir = agent.settings.data_dir / "books" / "uploads"
    agent.uploads_dir.mkdir(parents=True, exist_ok=True)
    agent._reset_pending = False
    agent._chat_busy = False


def reset_learning(agent: Any, *, confirm: bool = False) -> dict[str, Any]:
    result = reset_learning_data(agent.settings, confirm=confirm)
    reload_runtime(agent)
    return result


def reset_finetune(agent: Any, *, confirm_phrase: str) -> dict[str, Any]:
    """Сброс только дообучения; перезагрузить chat GGUF на базовую."""
    result = agent.finetune.reset_finetune(confirm_phrase=confirm_phrase)
    reloaded = reload_llm(agent)
    result["llm"] = reloaded.get("llm")
    result["chat_models"] = reloaded.get("chat_models")
    return result


def status(agent: Any) -> dict[str, Any]:
    from zipka.system_limits import available_ram_bytes, format_bytes, max_book_bytes

    backend_info = describe_backend(agent.llm)
    llm_ok = agent.llm.is_available()
    models = []
    if llm_ok:
        try:
            models = agent.llm.list_models()
        except (OllamaError, LlmError):
            models = []
    book_limit = max_book_bytes()
    avail = available_ram_bytes()
    model_name = backend_info.get("model") or agent.settings.ollama_model
    roles = models_status(agent.settings)
    file_names = [f["filename"] for f in roles.get("files") or []] or models
    return {
        "name": "Зипка",
        "ollama": llm_ok if backend_info.get("backend") == "ollama" else False,
        "llm": backend_info,
        "models": file_names,
        "model": model_name,
        "vision_model": (
            (vision_status(agent.settings).get("filename"))
            or agent.settings.vision_model
        ),
        "vision": vision_status(agent.settings),
        "eyes": agent.eyes.enabled,
        "ears": agent.ears.enabled,
        "sensors_enabled": sensors_feature_enabled(agent.settings),
        "pending_patch": agent.hard.has_pending(),
        "approve_phrase": APPROVE_PHRASE,
        "pending_soft": agent.soft.has_pending(),
        "soft_approve_phrase": SOFT_APPROVE_PHRASE,
        "soft_evolve_from_dialogue": agent.soft.dialogue_enabled(),
        "pending_finetune": agent.finetune.has_pending(),
        "finetune_approve_phrase": FINETUNE_APPROVE_PHRASE,
        "finetune_reset_phrase": FINETUNE_RESET_PHRASE,
        "finetune": agent.finetune.refresh_job_status(),
        "finetune_lineage": {
            "generation": agent.finetune.load_lineage().get("generation"),
            "active_gguf": agent.finetune.load_lineage().get("active_gguf"),
            "active_checkpoint": agent.finetune.load_lineage().get(
                "active_checkpoint"
            ),
        },
        "news": {
            "sources": agent.news.load_sources(),
            "items": len(agent.news.load_items()),
        },
        "mind": agent.mind.load(),
        "proactive": agent.proactive.rare_ping_status(),
        "limits": {
            "max_book_bytes": book_limit,
            "max_book_human": format_bytes(book_limit),
            "ram_available_bytes": avail,
            "ram_available_human": format_bytes(avail) if avail else None,
        },
        "user": agent.user.summary_for_ui(),
        "compute": compute_status(
            agent.settings,
            load_info=getattr(agent.llm, "load_info", lambda: None)(),
        ),
        "chat_models": roles,
        "model_roles": roles,
    }


def reload_llm(agent: Any) -> dict[str, Any]:
    if hasattr(agent.llm, "unload"):
        try:
            agent.llm.unload()
        except Exception:
            pass
    agent.llm = create_llm_client(agent.settings)
    code = code_llm(agent)
    for holder in (
        agent.soft,
        agent.books,
        agent.mind,
        agent.proactive,
        agent.net,
        agent.news,
        agent.user,
    ):
        if hasattr(holder, "llm"):
            holder.llm = agent.llm
    agent.hard.llm = code
    return {
        "llm": describe_backend(agent.llm),
        "chat_models": models_status(agent.settings),
        "models": models_status(agent.settings),
    }


def set_compute(
    agent: Any,
    mode: str,
    *,
    gpu_layers: int | None = None,
) -> dict[str, Any]:
    """Переключить CPU / GPU / hybrid и перезагрузить LLM."""
    patch: dict[str, Any] = {"compute_mode": mode}
    if gpu_layers is not None:
        patch["gpu_layers"] = gpu_layers
    save_runtime(patch, agent.settings)
    reloaded = reload_llm(agent)
    load_info = None
    if hasattr(agent.llm, "load_info"):
        load_info = agent.llm.load_info()
    return {
        "ok": True,
        "compute": compute_status(agent.settings, load_info=load_info),
        **reloaded,
    }


def set_models(
    agent: Any,
    *,
    chat_gguf: str | None = None,
    code_gguf: str | None = None,
) -> dict[str, Any]:
    """Выбрать GGUF для чата и/или кодинга (можно одну и ту же)."""
    patch: dict[str, Any] = {}
    if chat_gguf:
        name = Path(str(chat_gguf).strip()).name
        if resolve_role_gguf("chat", agent.settings, filename=name) is None:
            raise ValueError(
                f"Файл «{name}» не найден в {agent.settings.data_dir / 'models'}"
            )
        patch["chat_gguf"] = name
    if code_gguf:
        name = Path(str(code_gguf).strip()).name
        if resolve_role_gguf("code", agent.settings, filename=name) is None:
            raise ValueError(
                f"Файл «{name}» не найден в {agent.settings.data_dir / 'models'}"
            )
        patch["code_gguf"] = name
    if not patch:
        raise ValueError("Укажи chat_gguf и/или code_gguf")
    save_runtime(patch, agent.settings)
    reloaded = reload_llm(agent)
    return {"ok": True, **reloaded}


def set_soft_evolve_from_dialogue(agent: Any, enabled: bool) -> dict[str, Any]:
    """Вкл/выкл фоновый soft-evolve из диалога (pending + approve)."""
    save_runtime({"soft_evolve_from_dialogue": bool(enabled)}, agent.settings)
    return {
        "ok": True,
        "soft_evolve_from_dialogue": agent.soft.dialogue_enabled(),
    }


def set_sensors_enabled(agent: Any, enabled: bool) -> dict[str, Any]:
    """Master-switch сенсоров. При выкл — принудительно гасим глаза/уши."""
    on = bool(enabled)
    save_runtime({"sensors_enabled": on}, agent.settings)
    if not on:
        force_sensors_off(agent)
    return {
        "ok": True,
        "sensors_enabled": sensors_feature_enabled(agent.settings),
        "eyes": bool(getattr(agent.eyes, "enabled", False)),
        "ears": bool(getattr(agent.ears, "enabled", False)),
    }
