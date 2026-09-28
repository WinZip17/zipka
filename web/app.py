from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from zipka.agent import Zipka
from zipka.evolve.hard import APPROVE_PHRASE

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

app = FastAPI(title="Zipka", version="0.1.0")
agent = Zipka()

if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


class ChatIn(BaseModel):
    message: str = Field(min_length=1)


class ActionIn(BaseModel):
    action: str
    seconds: float = 5.0


class LearnIn(BaseModel):
    query: str


class ReadIn(BaseModel):
    path: str
    member: str | None = None


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    index_path = STATIC / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "index.html not found")
    return FileResponse(index_path)


@app.get("/api/status")
def api_status() -> dict:
    return agent.status()


@app.post("/api/chat")
def api_chat(body: ChatIn) -> dict:
    reply = agent.chat(body.message)
    return {"reply": reply, "approve_phrase": APPROVE_PHRASE}


@app.post("/api/eyes")
def api_eyes(body: ActionIn) -> dict:
    action = body.action.lower()
    if action == "on":
        return {"ok": True, "message": agent.eyes.on()}
    if action == "off":
        return {"ok": True, "message": agent.eyes.off()}
    if action == "snap":
        snap = agent.eyes.snap()
        desc = agent.describe_image(snap["image_b64"])
        agent.memory.add_note("eyes", desc, meta={"path": snap["path"]})
        return {"ok": True, "path": snap["path"], "description": desc}
    raise HTTPException(400, "action must be on|off|snap")


@app.post("/api/ears")
def api_ears(body: ActionIn) -> dict:
    action = body.action.lower()
    if action == "on":
        return {"ok": True, "message": agent.ears.on()}
    if action == "off":
        return {"ok": True, "message": agent.ears.off()}
    if action == "listen":
        text = agent.ears.listen(seconds=body.seconds)
        reply = agent.chat(text)
        return {"ok": True, "heard": text, "reply": reply}
    raise HTTPException(400, "action must be on|off|listen")


@app.post("/api/learn")
def api_learn(body: LearnIn) -> dict:
    return agent.net.learn(body.query)


@app.post("/api/read")
def api_read(body: ReadIn) -> dict:
    return agent.books.read(body.path, member=body.member)


@app.post("/api/upload-book")
async def api_upload_book(
    file: UploadFile = File(...),
    member: str | None = Form(default=None),
) -> dict:
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Пустой файл")
    if len(raw) > 80 * 1024 * 1024:
        raise HTTPException(400, "Файл больше 80 МБ")
    try:
        return agent.ingest_uploaded_book(
            file.filename or "book.txt", raw, member=member or None
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"Не удалось прочитать: {exc}") from exc


@app.post("/api/reflect")
def api_reflect() -> dict:
    return agent.mind.reflect()


@app.post("/api/approve")
def api_approve() -> dict:
    if not agent.hard.has_pending():
        raise HTTPException(400, "Нет ожидающего патча")
    return agent.hard.apply_pending()


@app.get("/api/pending")
def api_pending() -> dict:
    pending = agent.hard.load_pending()
    return {"pending": pending, "approve_phrase": APPROVE_PHRASE}
