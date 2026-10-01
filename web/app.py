from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from zipka.agent import Zipka
from zipka.evolve.hard import APPROVE_PHRASE
from zipka.evolve.finetune import APPROVE_PHRASE as FINETUNE_APPROVE_PHRASE
from zipka.evolve.finetune import RESET_CONFIRM_PHRASE as FINETUNE_RESET_PHRASE
from zipka.evolve.soft import APPROVE_PHRASE as SOFT_APPROVE_PHRASE
from zipka.reset import CONFIRM_PHRASE
from zipka.runtime_settings import compute_status, load_runtime
from zipka.llm.chat_models import models_status
from zipka.system_limits import format_bytes, max_book_bytes

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "frontend" / "dist"
_log = logging.getLogger("zipka.web")

agent = Zipka()
_news_stop = threading.Event()

_FINETUNE_BUSY_HTTP = (
    "Идёт дообучение модели. Подожди окончания или нажми "
    "«Сбросить / прервать» в Настройки → Дообучение."
)


def _ensure_not_finetuning() -> None:
    if agent.is_finetune_busy():
        raise HTTPException(409, _FINETUNE_BUSY_HTTP)


def _news_scheduler_loop() -> None:
    while True:
        try:
            if agent.is_finetune_busy():
                pass
            else:
                busy = agent.is_chat_busy()
                agent.news.maybe_auto_ingest(
                    chat_busy=busy,
                    finetune_busy=False,
                )
        except Exception as exc:
            _log.warning("news auto-ingest: %s", exc)
        if _news_stop.wait(20):
            break


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _news_stop.clear()
    threading.Thread(
        target=_news_scheduler_loop,
        name="zipka-news-auto",
        daemon=True,
    ).start()
    yield
    _news_stop.set()


app = FastAPI(title="Zipka", version="0.2.0", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str = Field(min_length=1)
    reply_to: dict | None = Field(
        default=None,
        description="Сообщение, на которое отвечают: {role, content, ts?}",
    )
    reply_chain: list[dict] | None = Field(
        default=None,
        description="Цепочка контекста от раннего к целевому сообщению",
    )


class ActionIn(BaseModel):
    action: str
    seconds: float = 5.0
    monitor: int = 1


class LearnIn(BaseModel):
    query: str


class ReadIn(BaseModel):
    path: str
    member: str | None = None
    comment: str | None = None


class ResetIn(BaseModel):
    confirm_phrase: str = Field(min_length=1)


class ComputeIn(BaseModel):
    mode: str = Field(description="cpu | gpu | hybrid")
    gpu_layers: int | None = Field(default=None, ge=1, le=128)


class ChatModelIn(BaseModel):
    model_id: str | None = Field(
        default=None, description="legacy: filename или pathfinder|qwen25"
    )
    chat_gguf: str | None = None
    code_gguf: str | None = None


class ModelsIn(BaseModel):
    chat_gguf: str | None = None
    code_gguf: str | None = None


class SoftEvolveDialogueIn(BaseModel):
    enabled: bool


class SensorsEnabledIn(BaseModel):
    enabled: bool


def _spa_index() -> Path:
    index = DIST / "index.html"
    if not index.exists():
        raise HTTPException(
            404,
            "UI не собран. В web/frontend выполни: npm install && npm run build",
        )
    return index


@app.get("/api/status")
def api_status() -> dict:
    return agent.status()


@app.get("/api/settings/compute")
def api_get_compute() -> dict:
    return compute_status()


@app.post("/api/settings/compute")
def api_set_compute(body: ComputeIn) -> dict:
    _ensure_not_finetuning()
    try:
        return agent.set_compute(body.mode, gpu_layers=body.gpu_layers)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Не удалось применить compute: {exc}") from exc


@app.get("/api/settings/chat-model")
def api_get_chat_model() -> dict:
    return models_status()


@app.post("/api/settings/chat-model")
def api_set_chat_model(body: ChatModelIn) -> dict:
    _ensure_not_finetuning()
    try:
        if body.chat_gguf or body.code_gguf:
            return agent.set_models(chat_gguf=body.chat_gguf, code_gguf=body.code_gguf)
        if body.model_id:
            return agent.set_models(chat_gguf=body.model_id)
        raise ValueError("Укажи chat_gguf / code_gguf или model_id")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Не удалось сменить модель: {exc}") from exc


@app.get("/api/settings/models")
def api_get_models() -> dict:
    return models_status()


@app.post("/api/settings/models")
def api_set_models(body: ModelsIn) -> dict:
    _ensure_not_finetuning()
    try:
        return agent.set_models(chat_gguf=body.chat_gguf, code_gguf=body.code_gguf)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Не удалось сменить модели: {exc}") from exc


@app.get("/api/settings/soft-evolve-dialogue")
def api_get_soft_evolve_dialogue() -> dict:
    return {
        "enabled": bool(load_runtime().get("soft_evolve_from_dialogue")),
        "pending": agent.soft.has_pending(),
        "approve_phrase": SOFT_APPROVE_PHRASE,
    }


@app.post("/api/settings/soft-evolve-dialogue")
def api_set_soft_evolve_dialogue(body: SoftEvolveDialogueIn) -> dict:
    try:
        return agent.set_soft_evolve_from_dialogue(body.enabled)
    except Exception as exc:
        raise HTTPException(
            400, f"Не удалось сохранить soft-evolve: {exc}"
        ) from exc


@app.get("/api/settings/sensors")
def api_get_sensors_feature() -> dict:
    from zipka.sensors.feature import sensors_feature_enabled

    return {
        "enabled": sensors_feature_enabled(),
        "eyes": agent.eyes.enabled,
        "ears": agent.ears.enabled,
    }


@app.post("/api/settings/sensors")
def api_set_sensors_feature(body: SensorsEnabledIn) -> dict:
    try:
        return agent.set_sensors_enabled(body.enabled)
    except Exception as exc:
        raise HTTPException(
            400, f"Не удалось сохранить сенсоры: {exc}"
        ) from exc


def _ensure_sensors_feature(*, kind: str = "sensors") -> None:
    from zipka.sensors.feature import refuse_sensors, sensors_feature_enabled

    if not sensors_feature_enabled():
        raise HTTPException(403, refuse_sensors(kind))  # type: ignore[arg-type]


@app.post("/api/chat")
def api_chat(body: ChatIn) -> dict:
    reply = agent.chat(
        body.message,
        reply_to=body.reply_to,
        reply_chain=body.reply_chain,
    )
    return {"reply": reply, "approve_phrase": APPROVE_PHRASE}


@app.get("/api/chat/history")
def api_chat_history(limit: int = 30, before: int | None = None) -> dict:
    limit = max(1, min(limit, 100))
    return agent.memory.chat_history(limit=limit, before=before)


@app.post("/api/eyes")
def api_eyes(body: ActionIn) -> dict:
    action = body.action.lower()
    if action == "off":
        return {"ok": True, "message": agent.eyes.off()}
    _ensure_sensors_feature(kind="eyes" if action == "on" else "look")
    try:
        if action == "on":
            return {"ok": True, "message": agent.eyes.on()}
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc

    _ensure_not_finetuning()
    try:
        if action in {"snap", "camera", "cam"}:
            snap = agent.eyes.snap()
        elif action in {"screen", "monitor"}:
            snap = agent.eyes.screen(monitor=body.monitor)
        elif action in {"window", "win"}:
            snap = agent.eyes.window()
        else:
            raise HTTPException(400, "action must be on|off|snap|screen|window")
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc

    try:
        desc = agent.describe_image(snap["image_b64"])
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    agent.memory.add_note(
        "eyes",
        desc,
        meta={"path": snap["path"], "source": snap.get("source", action)},
    )
    comment = agent.comment_eyes(desc)
    return {
        "ok": True,
        "path": snap["path"],
        "source": snap.get("source", action),
        "description": desc,
        "comment": comment,
    }


@app.post("/api/ears")
def api_ears(body: ActionIn) -> dict:
    action = body.action.lower()
    if action == "off":
        return {"ok": True, "message": agent.ears.off()}
    if action == "on":
        _ensure_sensors_feature(kind="ears")
        return {"ok": True, "message": agent.ears.on()}
    if action in {"listen_start", "start"}:
        _ensure_sensors_feature(kind="listen")
        _ensure_not_finetuning()
        try:
            msg = agent.ears.listen_start()
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "message": msg, "recording": True}
    if action in {"listen_stop", "stop"}:
        _ensure_sensors_feature(kind="listen")
        _ensure_not_finetuning()
        try:
            text = agent.ears.listen_stop()
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        if text in {"(тишина)", "(слишком коротко)"}:
            return {
                "ok": True,
                "heard": text,
                "comment": None,
                "reply": None,
                "skipped_chat": True,
            }
        comment = agent.comment_ears(text)
        reply = agent.chat(text)
        return {
            "ok": True,
            "heard": text,
            "comment": comment,
            "reply": reply,
        }
    if action == "listen":
        # CLI / старый клиент: фиксированные N секунд
        _ensure_sensors_feature(kind="listen")
        _ensure_not_finetuning()
        try:
            text = agent.ears.listen(seconds=body.seconds)
        except RuntimeError as exc:
            raise HTTPException(400, str(exc)) from exc
        if text in {"(тишина)", "(слишком коротко)"}:
            return {
                "ok": True,
                "heard": text,
                "comment": None,
                "reply": None,
                "skipped_chat": True,
            }
        comment = agent.comment_ears(text)
        reply = agent.chat(text)
        return {
            "ok": True,
            "heard": text,
            "comment": comment,
            "reply": reply,
        }
    raise HTTPException(400, "action must be on|off|listen|listen_start|listen_stop")


@app.post("/api/learn")
def api_learn(body: LearnIn) -> dict:
    _ensure_not_finetuning()
    q = (body.query or "").strip()
    note = f"[learn] {q}" if q else "[learn]"
    with agent.run_with_pending(
        user_text=note,
        phase="learning",
        kind="learn",
        label="Учусь…",
        save_user=True,
    ):
        try:
            result = agent.net.learn(body.query)
            summary = result.get("summary") or str(result)
            agent._remember_turn(note, summary)
            agent._ensure_assistant_saved(summary)
            return result
        except Exception as exc:
            agent._ensure_assistant_saved(f"Не смогла изучить: {exc}")
            raise


@app.post("/api/read")
def api_read(body: ReadIn) -> dict:
    _ensure_not_finetuning()
    return agent.books.read(
        body.path, member=body.member, comment=body.comment
    )


@app.post("/api/upload-book")
async def api_upload_book(
    file: UploadFile = File(...),
    member: str | None = Form(default=None),
    comment: str | None = Form(default=None),
) -> dict:
    _ensure_not_finetuning()
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Пустой файл")
    limit = max_book_bytes()
    if len(raw) > limit:
        raise HTTPException(
            400,
            f"Файл больше {format_bytes(limit)} "
            f"(лимит подогнан под доступную RAM)",
        )
    try:
        return agent.ingest_uploaded_book(
            file.filename or "book.txt",
            raw,
            member=member or None,
            comment=(comment or "").strip() or None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(500, f"Не удалось прочитать: {e}") from e


@app.post("/api/reset-learning")
def api_reset_learning(body: ResetIn) -> dict:
    if body.confirm_phrase.strip().lower() != CONFIRM_PHRASE:
        raise HTTPException(
            400,
            f"Нужна точная фраза: «{CONFIRM_PHRASE}»",
        )
    result = agent.reset_learning(confirm=True)
    return {
        "ok": result.get("ok", True),
        "result": result,
        "message": "Обучение сброшено. Можно начинать с чистого листа.",
        "confirm_phrase": CONFIRM_PHRASE,
    }


@app.get("/api/reset-learning/info")
def api_reset_info() -> dict:
    return {
        "confirm_phrase": CONFIRM_PHRASE,
        "pending": agent._reset_pending,
        "wipes": [
            "data/memory",
            "data/mind",
            "data/books/notes|uploads|extracted",
            "data/snapshots",
            "data/patches",
            "data/persona/persona.yaml",
        ],
    }


@app.post("/api/approve")
def api_approve() -> dict:
    _ensure_not_finetuning()
    if not agent.hard.has_pending():
        raise HTTPException(400, "Нет ожидающего патча")
    meta = agent.hard.apply_pending()
    agent._after_code_role()
    return meta


@app.get("/api/pending")
def api_pending() -> dict:
    pending = agent.hard.load_pending()
    return {"pending": pending, "approve_phrase": APPROVE_PHRASE}


@app.get("/api/finetune/status")
def api_finetune_status() -> dict:
    return {
        "status": agent.finetune.refresh_job_status(),
        "pending": agent.finetune.load_pending(),
        "lineage": agent.finetune.load_lineage(),
        "approve_phrase": FINETUNE_APPROVE_PHRASE,
        "reset_phrase": FINETUNE_RESET_PHRASE,
        "base_gguf": agent.finetune.resolve_base_chat_gguf(),
    }


@app.post("/api/finetune/propose")
def api_finetune_propose() -> dict:
    try:
        pending = agent.finetune.propose()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "pending": pending,
        "message": agent.finetune.format_pending(pending),
        "approve_phrase": FINETUNE_APPROVE_PHRASE,
    }


@app.post("/api/finetune/start")
def api_finetune_start() -> dict:
    try:
        return agent.start_finetune_approved()
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/finetune/abort")
def api_finetune_abort() -> dict:
    try:
        return agent.finetune.abort_running(kill=True)
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/finetune/reset-info")
def api_finetune_reset_info() -> dict:
    return {
        "confirm_phrase": FINETUNE_RESET_PHRASE,
        "base_gguf": agent.finetune.resolve_base_chat_gguf(),
    }


@app.post("/api/finetune/reset")
def api_finetune_reset(body: ResetIn) -> dict:
    if agent.is_finetune_busy():
        raise HTTPException(
            409,
            "Дообучение running — сначала прерви его («Сбросить / прервать»).",
        )
    try:
        return agent.reset_finetune(confirm_phrase=body.confirm_phrase)
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, f"Не удалось сбросить дообучение: {exc}") from exc


class NewsSourcesIn(BaseModel):
    global_interval_min: int | str | None = None
    rss: list[Any] | None = None
    telegram: list[Any] | None = None


class NewsAddIn(BaseModel):
    rss: str | None = None
    telegram: str | None = None
    interval: str | int | None = "global"


class NewsIntervalIn(BaseModel):
    global_interval_min: int | str | None = None
    rss: str | None = None
    telegram: str | None = None
    interval: str | int | None = None


@app.get("/api/news/sources")
def api_news_sources() -> dict:
    return {
        "sources": agent.news.load_sources(),
        "items": len(agent.news.load_items()),
        "auto": agent.news.auto_status(),
    }


@app.put("/api/news/sources")
def api_news_sources_put(body: NewsSourcesIn) -> dict:
    current = agent.news.load_sources()
    if "global_interval_min" in body.model_fields_set:
        current["global_interval_min"] = body.global_interval_min
    if body.rss is not None:
        current["rss"] = body.rss
    if body.telegram is not None:
        current["telegram"] = body.telegram
    return {
        "sources": agent.news.save_sources(current),
        "auto": agent.news.auto_status(),
    }


@app.post("/api/news/sources/add")
def api_news_sources_add(body: NewsAddIn) -> dict:
    try:
        if body.rss:
            sources = agent.news.add_rss(body.rss, interval=body.interval or "global")
        elif body.telegram:
            sources = agent.news.add_telegram(
                body.telegram, interval=body.interval or "global"
            )
        else:
            raise HTTPException(400, "Укажи rss или telegram")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"sources": sources, "auto": agent.news.auto_status()}


@app.post("/api/news/schedule")
def api_news_schedule(body: NewsIntervalIn) -> dict:
    try:
        dump = body.model_dump(exclude_unset=True)
        if body.rss or body.telegram:
            sources = agent.news.set_source_interval(
                rss=body.rss,
                telegram=body.telegram,
                interval=body.interval if body.interval is not None else "global",
            )
        elif "global_interval_min" in dump:
            sources = agent.news.set_global_interval(dump.get("global_interval_min"))
        else:
            raise HTTPException(
                400, "Укажи global_interval_min или rss/telegram + interval"
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"sources": sources, "auto": agent.news.auto_status()}


@app.get("/api/news/auto")
def api_news_auto() -> dict:
    return agent.news.auto_status()


@app.post("/api/news/ingest")
def api_news_ingest() -> dict:
    try:
        _ensure_not_finetuning()
        if agent.is_chat_busy():
            raise HTTPException(409, "Сейчас идёт ответ в чате — подожди и обнови ленту снова")
        return agent.news.ingest()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/news/search")
def api_news_search(q: str = "", days: int = 7) -> dict:
    hits = agent.news.search(q, days=max(1, min(days, 90)), limit=30)
    return {"query": q, "days": days, "hits": hits, "count": len(hits)}


@app.post("/api/reflect")
def api_reflect() -> dict:
    _ensure_not_finetuning()
    return agent.mind.reflect()


@app.get("/api/proactive/hello")
def api_hello() -> dict:
    text = agent.greet()
    return {"message": text, "pings": agent.proactive.rare_ping_status()}


@app.get("/api/proactive/ping")
def api_ping(force: bool = False) -> dict:
    _ensure_not_finetuning()
    text = agent.rare_ping(force=force)
    return {
        "ok": True,
        "message": text,
        "skipped": None if text else "no_materials",
        "pings": agent.proactive.rare_ping_status(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_spa_index())


# Serve Vite build assets (must be after API routes)
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")

_sounds_dir = DIST / "sounds"
if not _sounds_dir.is_dir():
    _sounds_dir = ROOT / "frontend" / "public" / "sounds"
if _sounds_dir.is_dir():
    app.mount("/sounds", StaticFiles(directory=str(_sounds_dir)), name="sounds")
