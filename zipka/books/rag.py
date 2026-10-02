"""Локальный RAG для книг: chunk → embed → sqlite/numpy store → retrieve.

Эмбеддинги: sentence-transformers (extra ``.[rag]``).
Без пакета — ``rag_available()`` = False, BookReader откатывается к sample-выжимке.

Масштаб (годы/ГБ): батч-эмбеддинги, mmap при retrieve, catalog.sqlite, GC.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from zipka.config import Settings, ensure_data_dirs, get_settings

DEFAULT_EMBED_MODEL = "intfloat/multilingual-e5-small"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 100
DEFAULT_TOP_K = 10
# Не больше стольких чанков в один summarize-промпт
MAX_CONTEXT_CHARS = 14_000

_embedder: Any = None
_embedder_name: str | None = None


def rag_available() -> bool:
    try:
        import sentence_transformers  # noqa: F401

        return True
    except ImportError:
        return False


def embed_batch_size() -> int:
    raw = os.environ.get("ZIPKA_RAG_BATCH", "").strip()
    try:
        return max(8, int(raw)) if raw else 32
    except ValueError:
        return 32


def rag_max_books() -> int:
    raw = os.environ.get("ZIPKA_RAG_MAX_BOOKS", "").strip()
    try:
        return max(10, int(raw)) if raw else 200
    except ValueError:
        return 200


def book_id_for(origin: str, archive_member: str | None = None) -> str:
    raw = f"{origin}|{archive_member or ''}"
    digest = hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()[:16]
    stem = Path(origin).stem
    safe = re.sub(r"[^\w\-]+", "_", stem)[:40].strip("_") or "book"
    return f"{safe}_{digest}"


def chunk_text(
    text: str,
    *,
    size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[dict[str, Any]]:
    """Разбить текст на чанки с overlap; по возможности по границам абзацев."""
    text = re.sub(r"\n{3,}", "\n\n", (text or "")).strip()
    if not text:
        return []
    size = max(200, int(size))
    overlap = max(0, min(int(overlap), size // 2))

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        paragraphs = [text]

    chunks: list[dict[str, Any]] = []
    buf = ""
    buf_start = 0
    pos = 0

    def flush(end_pos: int) -> None:
        nonlocal buf, buf_start
        body = buf.strip()
        if not body:
            buf = ""
            return
        chunks.append(
            {
                "id": len(chunks),
                "text": body,
                "start": buf_start,
                "end": end_pos,
            }
        )
        if overlap > 0 and len(body) > overlap:
            keep = body[-overlap:]
            buf = keep
            buf_start = max(0, end_pos - len(keep))
        else:
            buf = ""
            buf_start = end_pos

    for para in paragraphs:
        para_start = text.find(para, pos)
        if para_start < 0:
            para_start = pos
        para_end = para_start + len(para)
        pos = para_end

        if not buf:
            buf_start = para_start
            buf = para
        elif len(buf) + 2 + len(para) <= size:
            buf = f"{buf}\n\n{para}"
        else:
            flush(para_start)
            if not buf:
                buf_start = para_start
                buf = para
            else:
                buf = f"{buf}\n\n{para}" if buf else para

        while len(buf) > size:
            cut = size
            piece = buf[:cut]
            chunks.append(
                {
                    "id": len(chunks),
                    "text": piece.strip(),
                    "start": buf_start,
                    "end": buf_start + cut,
                }
            )
            advance = max(1, cut - overlap)
            buf = buf[advance:]
            buf_start += advance

    if buf.strip():
        flush(len(text))

    for i, ch in enumerate(chunks):
        ch["id"] = i
    return chunks


def _get_embedder(model_name: str = DEFAULT_EMBED_MODEL) -> Any:
    global _embedder, _embedder_name
    if _embedder is not None and _embedder_name == model_name:
        return _embedder
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            'RAG недоступен. Установи: pip install -e ".[rag]"'
        ) from exc
    _embedder = SentenceTransformer(model_name)
    _embedder_name = model_name
    return _embedder


def _embed_passages(
    texts: list[str],
    *,
    model_name: str,
    on_progress: Callable[[str], None] | None = None,
) -> np.ndarray:
    model = _get_embedder(model_name)
    batch = embed_batch_size()
    parts: list[np.ndarray] = []
    total = len(texts)
    for start in range(0, total, batch):
        chunk = texts[start : start + batch]
        prefixed = [f"passage: {t}" for t in chunk]
        vecs = model.encode(
            prefixed,
            batch_size=batch,
            show_progress_bar=False,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        parts.append(np.asarray(vecs, dtype=np.float32))
        if on_progress and total > batch:
            done = min(start + batch, total)
            on_progress(f"Эмбеддинги {done}/{total}…")
    if not parts:
        return np.zeros((0, 384), dtype=np.float32)
    return np.vstack(parts)


def _embed_query(query: str, *, model_name: str) -> np.ndarray:
    model = _get_embedder(model_name)
    vec = model.encode(
        [f"query: {query}"],
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return np.asarray(vec[0], dtype=np.float32)


class BookRagStore:
    """Индекс книг: per-book dir + общий catalog.sqlite."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.root = self.settings.data_dir / "books" / "rag"
        self.root.mkdir(parents=True, exist_ok=True)
        self.catalog_path = self.root / "catalog.sqlite"
        self.model_name = DEFAULT_EMBED_MODEL
        self._ensure_catalog()

    def book_dir(self, book_id: str) -> Path:
        safe = re.sub(r"[^\w\-]+", "_", book_id)[:80]
        return self.root / safe

    def _catalog_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.catalog_path), timeout=60.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=60000")
        return conn

    def _ensure_catalog(self) -> None:
        conn = self._catalog_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS books (
                    book_id TEXT PRIMARY KEY,
                    source TEXT,
                    archive_member TEXT,
                    chunk_count INTEGER,
                    embed_model TEXT,
                    embed_dim INTEGER,
                    chars INTEGER,
                    dir_name TEXT,
                    created_at TEXT,
                    last_used_at TEXT,
                    bytes_on_disk INTEGER
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def index_exists(self, book_id: str) -> bool:
        d = self.book_dir(book_id)
        return (
            (d / "meta.json").is_file()
            and (d / "embeddings.npy").is_file()
            and (d / "chunks.sqlite").is_file()
        )

    def _dir_bytes(self, d: Path) -> int:
        total = 0
        if not d.is_dir():
            return 0
        for p in d.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
        return total

    def _catalog_upsert(self, meta: dict[str, Any], *, touch_used: bool = False) -> None:
        now = datetime.now(timezone.utc).isoformat()
        book_id = str(meta["book_id"])
        d = self.book_dir(book_id)
        conn = self._catalog_conn()
        try:
            existing = conn.execute(
                "SELECT created_at, last_used_at FROM books WHERE book_id=?",
                (book_id,),
            ).fetchone()
            created = existing["created_at"] if existing else now
            last_used = now if (touch_used or not existing) else existing["last_used_at"]
            conn.execute(
                """
                INSERT INTO books (
                    book_id, source, archive_member, chunk_count, embed_model,
                    embed_dim, chars, dir_name, created_at, last_used_at, bytes_on_disk
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(book_id) DO UPDATE SET
                    source=excluded.source,
                    archive_member=excluded.archive_member,
                    chunk_count=excluded.chunk_count,
                    embed_model=excluded.embed_model,
                    embed_dim=excluded.embed_dim,
                    chars=excluded.chars,
                    dir_name=excluded.dir_name,
                    last_used_at=excluded.last_used_at,
                    bytes_on_disk=excluded.bytes_on_disk
                """,
                (
                    book_id,
                    meta.get("source"),
                    meta.get("archive_member"),
                    int(meta.get("chunk_count") or 0),
                    meta.get("embed_model"),
                    int(meta.get("embed_dim") or 0),
                    int(meta.get("chars") or 0),
                    d.name,
                    created,
                    last_used,
                    self._dir_bytes(d),
                ),
            )
            conn.commit()
        finally:
            conn.close()

    def touch(self, book_id: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        conn = self._catalog_conn()
        try:
            conn.execute(
                "UPDATE books SET last_used_at=? WHERE book_id=?",
                (now, book_id),
            )
            conn.commit()
        finally:
            conn.close()

    def index_book(
        self,
        book_id: str,
        text: str,
        *,
        source: str,
        archive_member: str | None = None,
        force: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        if not force and self.index_exists(book_id):
            meta = self.load_meta(book_id)
            self._catalog_upsert(meta, touch_used=True)
            return {**meta, "reused": True}

        if on_progress:
            on_progress("Дроблю книгу на фрагменты…")
        chunks = chunk_text(text)
        if not chunks:
            raise RuntimeError("Пустой текст — нечего индексировать.")

        if on_progress:
            on_progress(f"Строю эмбеддинги ({len(chunks)} фрагментов)…")
        embeddings = _embed_passages(
            [c["text"] for c in chunks],
            model_name=self.model_name,
            on_progress=on_progress,
        )

        d = self.book_dir(book_id)
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True, exist_ok=True)

        np.save(d / "embeddings.npy", embeddings)

        db_path = d / "chunks.sqlite"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "CREATE TABLE chunks ("
                "id INTEGER PRIMARY KEY, start INTEGER, end INTEGER, text TEXT)"
            )
            rows = [(c["id"], c["start"], c["end"], c["text"]) for c in chunks]
            batch = 500
            for i in range(0, len(rows), batch):
                conn.executemany(
                    "INSERT INTO chunks (id, start, end, text) VALUES (?, ?, ?, ?)",
                    rows[i : i + batch],
                )
            conn.commit()
        finally:
            conn.close()

        meta = {
            "book_id": book_id,
            "source": source,
            "archive_member": archive_member,
            "chunk_count": len(chunks),
            "embed_model": self.model_name,
            "embed_dim": int(embeddings.shape[1]) if embeddings.size else 0,
            "chars": len(text),
            "indexed_at": datetime.now(timezone.utc).isoformat(),
        }
        (d / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._catalog_upsert(meta, touch_used=True)
        try:
            self.gc(max_books=rag_max_books())
        except Exception:
            pass
        return {**meta, "reused": False}

    def load_meta(self, book_id: str) -> dict[str, Any]:
        path = self.book_dir(book_id) / "meta.json"
        if not path.is_file():
            raise FileNotFoundError(f"RAG meta не найден: {book_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def retrieve(
        self,
        book_id: str,
        query: str,
        *,
        k: int = DEFAULT_TOP_K,
    ) -> list[dict[str, Any]]:
        if not self.index_exists(book_id):
            raise FileNotFoundError(f"Нет RAG-индекса: {book_id}")
        meta = self.load_meta(book_id)
        model_name = str(meta.get("embed_model") or self.model_name)
        d = self.book_dir(book_id)
        matrix = np.load(d / "embeddings.npy", mmap_mode="r")
        q = _embed_query(query.strip() or "основные идеи книги", model_name=model_name)
        scores = np.asarray(matrix @ q, dtype=np.float32)
        k = max(1, min(int(k), len(scores)))
        top_idx = np.argpartition(-scores, kth=k - 1)[:k]
        top_idx = top_idx[np.argsort(-scores[top_idx])]

        conn = sqlite3.connect(str(d / "chunks.sqlite"))
        try:
            out: list[dict[str, Any]] = []
            for i in top_idx:
                row = conn.execute(
                    "SELECT id, start, end, text FROM chunks WHERE id = ?",
                    (int(i),),
                ).fetchone()
                if not row:
                    continue
                out.append(
                    {
                        "id": int(row[0]),
                        "start": int(row[1]),
                        "end": int(row[2]),
                        "text": row[3],
                        "score": float(scores[int(i)]),
                    }
                )
            self.touch(book_id)
            return out
        finally:
            conn.close()

    def list_catalog(self) -> list[dict[str, Any]]:
        conn = self._catalog_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM books ORDER BY last_used_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def stats(self) -> dict[str, Any]:
        rows = self.list_catalog()
        total_bytes = sum(int(r.get("bytes_on_disk") or 0) for r in rows)
        orphans = 0
        for child in self.root.iterdir():
            if child.is_dir() and (child / "meta.json").is_file():
                try:
                    bid = json.loads(
                        (child / "meta.json").read_text(encoding="utf-8")
                    ).get("book_id")
                except (OSError, json.JSONDecodeError):
                    orphans += 1
                    continue
                if bid and not any(r["book_id"] == bid for r in rows):
                    orphans += 1
        return {
            "books": len(rows),
            "bytes_on_disk": total_bytes,
            "orphan_dirs": orphans,
            "max_books": rag_max_books(),
            "embed_batch": embed_batch_size(),
        }

    def gc(
        self, *, max_books: int | None = None, remove_orphans: bool = True
    ) -> dict[str, Any]:
        """Удалить лишние индексы (LRU) и сиротские каталоги."""
        max_books = max_books if max_books is not None else rag_max_books()
        removed: list[str] = []

        for child in list(self.root.iterdir()):
            if not child.is_dir() or not (child / "meta.json").is_file():
                continue
            try:
                meta = json.loads(
                    (child / "meta.json").read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                if remove_orphans:
                    shutil.rmtree(child, ignore_errors=True)
                    removed.append(child.name)
                continue
            bid = str(meta.get("book_id") or child.name)
            self._catalog_upsert({**meta, "book_id": bid})

        conn = self._catalog_conn()
        try:
            rows = conn.execute(
                "SELECT book_id, dir_name, last_used_at FROM books "
                "ORDER BY last_used_at ASC"
            ).fetchall()
            if len(rows) > max_books:
                overflow = rows[: len(rows) - max_books]
                for r in overflow:
                    d = self.root / str(r["dir_name"] or r["book_id"])
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
                        removed.append(str(r["book_id"]))
                    conn.execute(
                        "DELETE FROM books WHERE book_id=?", (r["book_id"],)
                    )
                conn.commit()

            for r in conn.execute("SELECT book_id, dir_name FROM books").fetchall():
                d = self.root / str(r["dir_name"] or r["book_id"])
                if not d.is_dir():
                    conn.execute(
                        "DELETE FROM books WHERE book_id=?", (r["book_id"],)
                    )
                    removed.append(f"catalog:{r['book_id']}")
            conn.commit()
        finally:
            conn.close()
        return {"removed": removed, "remaining": len(self.list_catalog())}


def build_study_queries(comment: str | None) -> list[str]:
    """Несколько ракурсов для retrieve → более полное изучение."""
    focus = (comment or "").strip()
    if focus:
        return [
            focus,
            f"детали и факты по теме: {focus}",
            f"контекст и связанные идеи: {focus}",
        ]
    return [
        "основные идеи, сюжет, герои, тон повествования",
        "ключевые темы, выводы, важные события",
        "характер персонажей и конфликты",
    ]


def merge_retrieved(
    hits_lists: list[list[dict[str, Any]]],
    *,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> list[dict[str, Any]]:
    seen: set[int] = set()
    merged: list[dict[str, Any]] = []
    for hits in hits_lists:
        for h in sorted(hits, key=lambda x: -float(x.get("score") or 0)):
            cid = int(h["id"])
            if cid in seen:
                continue
            seen.add(cid)
            merged.append(h)
    merged.sort(key=lambda x: int(x.get("start") or 0))
    out: list[dict[str, Any]] = []
    total = 0
    for h in merged:
        t = str(h.get("text") or "")
        if total + len(t) > max_chars and out:
            break
        out.append(h)
        total += len(t)
    return out


def study_from_rag(
    llm: Any,
    store: BookRagStore,
    *,
    book_id: str,
    text: str,
    source: str,
    source_label: str,
    archive_member: str | None = None,
    comment: str | None = None,
    force_reindex: bool = False,
    on_progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Индекс (если нужно) → retrieve по ракурсам → LLM-выжимка."""
    if not rag_available():
        raise RuntimeError('RAG недоступен. pip install -e ".[rag]"')

    if not force_reindex and store.index_exists(book_id):
        meta = store.index_book(
            book_id,
            "",
            source=source,
            archive_member=archive_member,
            force=False,
            on_progress=on_progress,
        )
    else:
        meta = store.index_book(
            book_id,
            text,
            source=source,
            archive_member=archive_member,
            force=force_reindex,
            on_progress=on_progress,
        )

    if on_progress:
        on_progress("Ищу фрагменты по книге…")
    queries = build_study_queries(comment)
    hits_lists = [
        store.retrieve(book_id, q, k=DEFAULT_TOP_K) for q in queries
    ]
    chunks = merge_retrieved(hits_lists)
    if not chunks:
        raise RuntimeError("RAG не вернул фрагментов.")

    corpus = "\n\n".join(
        f"### Фрагмент {i} (поз. {c['start']}–{c['end']})\n{c['text']}"
        for i, c in enumerate(chunks, 1)
    )
    focus = ""
    if comment and comment.strip():
        focus = (
            f"\nКомментарий/фокус пользователя (обязательно учти): {comment.strip()}\n"
            "Отвечай в первую очередь на этот фокус, остальное — кратко.\n"
        )
    chars_hint = meta.get("chars") or len(text)
    instruction = (
        f"Сделай краткую выжимку книги «{source_label}» "
        f"(~{chars_hint} символов; ниже — релевантные фрагменты "
        f"из RAG-индекса, {len(chunks)} шт.). "
        "Сюжет, герои, тон, ключевые идеи. Не цитируй длинные куски дословно. "
        "Опирайся только на данные фрагменты; если чего-то нет во фрагментах — "
        "не выдумывай."
        f"{focus}"
    )

    if on_progress:
        on_progress("Пишу выжимку по фрагментам…")
    digest = llm.summarize(corpus, instruction=instruction)
    return {
        "digest": digest,
        "book_id": book_id,
        "rag_id": book_id,
        "chunk_count": int(meta.get("chunk_count") or 0),
        "retrieved": len(chunks),
        "embed_model": meta.get("embed_model"),
        "reused_index": bool(meta.get("reused")),
        "queries": queries,
    }
