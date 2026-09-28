from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from zipka.agent import Zipka
from zipka.evolve.hard import APPROVE_PHRASE
from zipka.reset import CONFIRM_PHRASE
from zipka.system_limits import format_bytes, max_book_bytes

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="Zipka", version="0.2.0")
agent = Zipka()


class ChatIn(BaseModel):
    message: str = Field(min_length=1)


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


@app.post("/api/chat")
def api_chat(body: ChatIn) -> dict:
    reply = agent.chat(body.message)
    return {"reply": reply, "approve_phrase": APPROVE_PHRASE}


@app.get("/api/chat/history")
def api_chat_history(limit: int = 30, before: int | None = None) -> dict:
    limit = max(1, min(limit, 100))
    return agent.memory.chat_history(limit=limit, before=before)


@app.post("/api/eyes")
def api_eyes(body: ActionIn) -> dict:
    action = body.action.lower()
    if action == "on":
        return {"ok": True, "message": agent.eyes.on()}
    if action == "off":
        return {"ok": True, "message": agent.eyes.off()}

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

    desc = agent.describe_image(snap["image_b64"])
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
    if action == "on":
        return {"ok": True, "message": agent.ears.on()}
    if action == "off":
        return {"ok": True, "message": agent.ears.off()}
    if action == "listen":
        text = agent.ears.listen(seconds=body.seconds)
        comment = agent.comment_ears(text)
        reply = agent.chat(text)
        return {
            "ok": True,
            "heard": text,
            "comment": comment,
            "reply": reply,
        }
    raise HTTPException(400, "action must be on|off|listen")


@app.post("/api/learn")
def api_learn(body: LearnIn) -> dict:
    return agent.net.learn(body.query)


@app.post("/api/read")
def api_read(body: ReadIn) -> dict:
    return agent.books.read(
        body.path, member=body.member, comment=body.comment
    )


@app.post("/api/upload-book")
async def api_upload_book(
    file: UploadFile = File(...),
    member: str | None = Form(default=None),
    comment: str | None = Form(default=None),
) -> dict:
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
    if not agent.hard.has_pending():
        raise HTTPException(400, "Нет ожидающего патча")
    return agent.hard.apply_pending()


@app.get("/api/pending")
def api_pending() -> dict:
    pending = agent.hard.load_pending()
    return {"pending": pending, "approve_phrase": APPROVE_PHRASE}


@app.post("/api/reflect")
def api_reflect() -> dict:
    return agent.mind.reflect()


@app.get("/api/proactive/hello")
def api_hello() -> dict:
    text = agent.greet()
    return {"message": text, "pings": agent.proactive.rare_ping_status()}


@app.get("/api/proactive/ping")
def api_ping(force: bool = False) -> dict:
    text = agent.rare_ping(force=force)
    return {
        "message": text,
        "pings": agent.proactive.rare_ping_status(),
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_spa_index())


# Serve Vite build assets (must be after API routes)
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(DIST / "assets")), name="assets")
