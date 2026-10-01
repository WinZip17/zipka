"""Локальный RAG для книг: chunk → embed → sqlite/numpy store → retrieve.

Эмбеддинги: sentence-transformers (extra ``.[rag]``).
Без пакета — ``rag_available()`` = False, BookReader откатывается к sample-выжимке.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
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
            # жёсткий разрез длинного абзаца
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

    # перенумеровать id
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


def _embed_passages(texts: list[str], *, model_name: str) -> np.ndarray:
    model = _get_embedder(model_name)
    # e5: prefix passage:
    prefixed = [f"passage: {t}" for t in texts]
    vecs = model.encode(
        prefixed,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
        convert_to_numpy=True,
    )
    return np.asarray(vecs, dtype=np.float32)


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
    """Индекс одной книги: meta.json + chunks.sqlite + embeddings.npy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.root = self.settings.data_dir / "books" / "rag"
        self.root.mkdir(parents=True, exist_ok=True)
        self.model_name = DEFAULT_EMBED_MODEL

    def book_dir(self, book_id: str) -> Path:
        safe = re.sub(r"[^\w\-]+", "_", book_id)[:80]
        return self.root / safe

    def index_exists(self, book_id: str) -> bool:
        d = self.book_dir(book_id)
        return (
            (d / "meta.json").is_file()
            and (d / "embeddings.npy").is_file()
            and (d / "chunks.sqlite").is_file()
        )

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
            return {**meta, "reused": True}

        if on_progress:
            on_progress("Дроблю книгу на фрагменты…")
        chunks = chunk_text(text)
        if not chunks:
            raise RuntimeError("Пустой текст — нечего индексировать.")

        if on_progress:
            on_progress(f"Строю эмбеддинги ({len(chunks)} фрагментов)…")
        embeddings = _embed_passages(
            [c["text"] for c in chunks], model_name=self.model_name
        )

        d = self.book_dir(book_id)
        if d.exists():
            import shutil

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
            conn.executemany(
                "INSERT INTO chunks (id, start, end, text) VALUES (?, ?, ?, ?)",
                [(c["id"], c["start"], c["end"], c["text"]) for c in chunks],
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
            "embed_dim": int(embeddings.shape[1]),
            "chars": len(text),
        }
        (d / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )
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
        matrix = np.load(d / "embeddings.npy")
        q = _embed_query(query.strip() or "основные идеи книги", model_name=model_name)
        # cosine = dot for normalized vectors
        scores = matrix @ q
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
            return out
        finally:
            conn.close()


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
    # порядок по позиции в книге для связности
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
    instruction = (
        f"Сделай краткую выжимку книги «{source_label}» "
        f"(~{meta.get('chars', len(text))} символов; ниже — релевантные фрагменты "
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
