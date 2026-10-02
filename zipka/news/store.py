"""Масштабируемое хранилище новостей: SQLite + FTS5.

Миграция с legacy ``items.jsonl`` при первом открытии.
Hot-срез + prune/archive для работы «годами».
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso() -> str:
    return _utc_now().isoformat()


def _parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def news_hot_days() -> int:
    raw = os.environ.get("ZIPKA_NEWS_HOT_DAYS", "").strip()
    try:
        return max(7, int(raw)) if raw else 365
    except ValueError:
        return 365


def news_max_items() -> int:
    raw = os.environ.get("ZIPKA_NEWS_MAX_ITEMS", "").strip()
    try:
        return max(1000, int(raw)) if raw else 100_000
    except ValueError:
        return 100_000


class NewsStore:
    """Потокобезопасный store для выдержек новостей."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "news.sqlite"
        self.legacy_jsonl = self.root / "items.jsonl"
        self.archive_dir = self.root / "archive"
        self._lock = threading.RLock()
        self._local = threading.local()
        self._ensure_schema()
        self._maybe_migrate_jsonl()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=60.0,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=60000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            c = self._conn()
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    kind TEXT,
                    source TEXT,
                    title TEXT,
                    url TEXT,
                    source_url TEXT,
                    published_at TEXT,
                    fetched_at TEXT,
                    summary TEXT,
                    text TEXT,
                    lemmas_json TEXT,
                    published_ts REAL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_items_url
                    ON items(url) WHERE url IS NOT NULL AND url != '';
                CREATE INDEX IF NOT EXISTS idx_items_published_ts
                    ON items(published_ts DESC);
                CREATE INDEX IF NOT EXISTS idx_items_source_ts
                    ON items(source, published_ts DESC);
                CREATE INDEX IF NOT EXISTS idx_items_fetched
                    ON items(fetched_at DESC);

                CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                    title, summary, text, source,
                    content='items',
                    content_rowid='rowid'
                );

                CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
                    INSERT INTO items_fts(rowid, title, summary, text, source)
                    VALUES (new.rowid, new.title, new.summary, new.text, new.source);
                END;
                CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
                    INSERT INTO items_fts(items_fts, rowid, title, summary, text, source)
                    VALUES ('delete', old.rowid, old.title, old.summary, old.text, old.source);
                END;
                CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
                    INSERT INTO items_fts(items_fts, rowid, title, summary, text, source)
                    VALUES ('delete', old.rowid, old.title, old.summary, old.text, old.source);
                    INSERT INTO items_fts(rowid, title, summary, text, source)
                    VALUES (new.rowid, new.title, new.summary, new.text, new.source);
                END;

                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );
                """
            )
            c.commit()

    def _row_to_item(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        d = dict(row)
        lemmas_raw = d.pop("lemmas_json", None)
        d.pop("published_ts", None)
        out = {k: v for k, v in d.items() if v is not None}
        if lemmas_raw:
            try:
                out["lemmas"] = json.loads(lemmas_raw)
            except json.JSONDecodeError:
                pass
        return out

    def _published_ts(self, item: dict[str, Any]) -> float:
        for key in ("published_at", "fetched_at"):
            dt = _parse_dt(str(item.get(key) or "") or None)
            if dt:
                return dt.timestamp()
        return _utc_now().timestamp()

    def upsert(self, item: dict[str, Any]) -> bool:
        """Вставить выдержку. True если новая (или обновлена)."""
        from zipka.news.ru_index import ensure_item_lemmas

        ensure_item_lemmas(item)
        iid = str(item.get("id") or "").strip()
        if not iid:
            return False
        url = str(item.get("url") or item.get("source_url") or "").strip()
        lemmas = item.get("lemmas")
        lemmas_json = json.dumps(lemmas, ensure_ascii=False) if lemmas else None
        with self._lock:
            c = self._conn()
            try:
                c.execute(
                    """
                    INSERT INTO items (
                        id, kind, source, title, url, source_url,
                        published_at, fetched_at, summary, text, lemmas_json, published_ts
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        kind=excluded.kind,
                        source=excluded.source,
                        title=excluded.title,
                        url=excluded.url,
                        source_url=excluded.source_url,
                        published_at=excluded.published_at,
                        fetched_at=excluded.fetched_at,
                        summary=excluded.summary,
                        text=excluded.text,
                        lemmas_json=excluded.lemmas_json,
                        published_ts=excluded.published_ts
                    """,
                    (
                        iid,
                        item.get("kind"),
                        item.get("source"),
                        item.get("title"),
                        url or None,
                        str(item.get("source_url") or url or "") or None,
                        item.get("published_at"),
                        item.get("fetched_at") or _utc_iso(),
                        item.get("summary"),
                        item.get("text"),
                        lemmas_json,
                        self._published_ts(item),
                    ),
                )
            except sqlite3.IntegrityError:
                # дубликат url с другим id — обновить существующую строку по url
                if url:
                    c.execute(
                        """
                        UPDATE items SET
                            kind=?, source=?, title=?, source_url=?,
                            published_at=?, fetched_at=?, summary=?, text=?,
                            lemmas_json=?, published_ts=?
                        WHERE url=?
                        """,
                        (
                            item.get("kind"),
                            item.get("source"),
                            item.get("title"),
                            str(item.get("source_url") or url or "") or None,
                            item.get("published_at"),
                            item.get("fetched_at") or _utc_iso(),
                            item.get("summary"),
                            item.get("text"),
                            lemmas_json,
                            self._published_ts(item),
                            url,
                        ),
                    )
                else:
                    raise
            c.commit()
            return True

    def known_ids(self) -> set[str]:
        with self._lock:
            rows = self._conn().execute("SELECT id FROM items").fetchall()
        return {str(r["id"]) for r in rows}

    def count(self) -> int:
        with self._lock:
            row = self._conn().execute("SELECT COUNT(*) AS n FROM items").fetchone()
        return int(row["n"] if row else 0)

    def load_items(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        """Последние N по published_ts (или все, если limit=None — осторожно)."""
        with self._lock:
            c = self._conn()
            if limit is not None and limit > 0:
                rows = c.execute(
                    "SELECT * FROM items ORDER BY published_ts DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                # chronological for callers that expect jsonl tail order
                items = [self._row_to_item(r) for r in reversed(rows)]
            else:
                rows = c.execute(
                    "SELECT * FROM items ORDER BY published_ts ASC"
                ).fetchall()
                items = [self._row_to_item(r) for r in rows]
        return items

    def iter_since(self, since_ts: float) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn().execute(
                "SELECT * FROM items WHERE published_ts >= ? ORDER BY published_ts DESC",
                (since_ts,),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def search_pool(self, *, days: int, limit_scan: int = 50_000) -> list[dict[str, Any]]:
        since = (_utc_now() - timedelta(days=max(1, days))).timestamp()
        with self._lock:
            rows = self._conn().execute(
                """
                SELECT * FROM items
                WHERE published_ts >= ?
                ORDER BY published_ts DESC
                LIMIT ?
                """,
                (since, max(100, int(limit_scan))),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def fts_search(
        self,
        query: str,
        *,
        days: int = 7,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip()
        if not q:
            return []
        # FTS5 query: quote tokens loosely
        tokens = [t for t in q.replace('"', " ").split() if len(t) > 1]
        if not tokens:
            return []
        fts_q = " OR ".join(f'"{t}"' for t in tokens[:12])
        since = (_utc_now() - timedelta(days=max(1, days))).timestamp()
        with self._lock:
            try:
                rows = self._conn().execute(
                    """
                    SELECT items.*
                    FROM items_fts
                    JOIN items ON items.rowid = items_fts.rowid
                    WHERE items_fts MATCH ?
                      AND items.published_ts >= ?
                    ORDER BY bm25(items_fts), items.published_ts DESC
                    LIMIT ?
                    """,
                    (fts_q, since, max(1, int(limit))),
                ).fetchall()
            except sqlite3.OperationalError:
                # fallback: LIKE
                like = f"%{q[:80]}%"
                rows = self._conn().execute(
                    """
                    SELECT * FROM items
                    WHERE published_ts >= ?
                      AND (title LIKE ? OR summary LIKE ? OR text LIKE ?)
                    ORDER BY published_ts DESC
                    LIMIT ?
                    """,
                    (since, like, like, like, max(1, int(limit))),
                ).fetchall()
        return [self._row_to_item(r) for r in rows]

    def update_lemmas_batch(self, items: Iterable[dict[str, Any]]) -> int:
        from zipka.news.ru_index import ensure_item_lemmas

        changed = 0
        with self._lock:
            c = self._conn()
            for item in items:
                before = item.get("lemmas")
                ensure_item_lemmas(item)
                if before == item.get("lemmas"):
                    continue
                c.execute(
                    "UPDATE items SET lemmas_json=? WHERE id=?",
                    (
                        json.dumps(item.get("lemmas"), ensure_ascii=False),
                        str(item.get("id")),
                    ),
                )
                changed += 1
            if changed:
                c.commit()
        return changed

    def ensure_lemmas(self, *, force: bool = False) -> int:
        with self._lock:
            c = self._conn()
            if not force:
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM items "
                    "WHERE lemmas_json IS NULL OR lemmas_json = '' OR lemmas_json = '[]'"
                ).fetchone()
                missing = int(row["n"] if row else 0)
                if missing == 0:
                    return 0
                rows = c.execute(
                    "SELECT * FROM items WHERE lemmas_json IS NULL "
                    "OR lemmas_json = '' OR lemmas_json = '[]'"
                ).fetchall()
            else:
                rows = c.execute("SELECT * FROM items").fetchall()
        items = [self._row_to_item(r) for r in rows]
        return self.update_lemmas_batch(items)

    def prune(
        self,
        *,
        max_items: int | None = None,
        hot_days: int | None = None,
        archive: bool = True,
    ) -> dict[str, Any]:
        """Удалить старые сверх hot_days / max_items; опционально в archive/."""
        max_items = max_items if max_items is not None else news_max_items()
        hot_days = hot_days if hot_days is not None else news_hot_days()
        cutoff = (_utc_now() - timedelta(days=hot_days)).timestamp()
        archived = 0
        deleted = 0
        with self._lock:
            c = self._conn()
            old = c.execute(
                "SELECT * FROM items WHERE published_ts < ? ORDER BY published_ts ASC",
                (cutoff,),
            ).fetchall()
            if old and archive:
                archived += self._archive_rows(old)
            if old:
                c.execute("DELETE FROM items WHERE published_ts < ?", (cutoff,))
                deleted += len(old)
                c.commit()

            total = int(c.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"])
            if total > max_items:
                overflow = total - max_items
                rows = c.execute(
                    "SELECT * FROM items ORDER BY published_ts ASC LIMIT ?",
                    (overflow,),
                ).fetchall()
                if rows and archive:
                    archived += self._archive_rows(rows)
                ids = [str(r["id"]) for r in rows]
                c.executemany("DELETE FROM items WHERE id=?", [(i,) for i in ids])
                deleted += len(ids)
                c.commit()
            # keep FTS in sync after bulk delete — triggers handle row deletes
            try:
                c.execute("INSERT INTO items_fts(items_fts) VALUES('optimize')")
                c.commit()
            except sqlite3.OperationalError:
                pass
        return {
            "deleted": deleted,
            "archived_batches": archived,
            "remaining": self.count(),
            "hot_days": hot_days,
            "max_items": max_items,
        }

    def _archive_rows(self, rows: list[sqlite3.Row]) -> int:
        if not rows:
            return 0
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        # bucket by YYYY-MM of published_ts
        buckets: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            item = self._row_to_item(r)
            ts = float(r["published_ts"] or 0)
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            key = dt.strftime("%Y-%m")
            buckets.setdefault(key, []).append(item)
        for key, items in buckets.items():
            path = self.archive_dir / f"{key}.sqlite"
            ac = sqlite3.connect(str(path))
            try:
                ac.execute(
                    """
                    CREATE TABLE IF NOT EXISTS items (
                        id TEXT PRIMARY KEY,
                        kind TEXT, source TEXT, title TEXT, url TEXT,
                        source_url TEXT, published_at TEXT, fetched_at TEXT,
                        summary TEXT, text TEXT, lemmas_json TEXT, published_ts REAL
                    )
                    """
                )
                for it in items:
                    ac.execute(
                        """
                        INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            it.get("id"),
                            it.get("kind"),
                            it.get("source"),
                            it.get("title"),
                            it.get("url"),
                            it.get("source_url"),
                            it.get("published_at"),
                            it.get("fetched_at"),
                            it.get("summary"),
                            it.get("text"),
                            json.dumps(it.get("lemmas"), ensure_ascii=False)
                            if it.get("lemmas")
                            else None,
                            self._published_ts(it),
                        ),
                    )
                ac.commit()
            finally:
                ac.close()
        return len(buckets)

    def stats(self) -> dict[str, Any]:
        with self._lock:
            c = self._conn()
            n = int(c.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"])
            oldest = c.execute(
                "SELECT COALESCE(published_at, fetched_at) AS t FROM items "
                "ORDER BY published_ts ASC LIMIT 1"
            ).fetchone()
            newest = c.execute(
                "SELECT COALESCE(published_at, fetched_at) AS t FROM items "
                "ORDER BY published_ts DESC LIMIT 1"
            ).fetchone()
        size = self.db_path.stat().st_size if self.db_path.exists() else 0
        archives = 0
        if self.archive_dir.is_dir():
            archives = len(list(self.archive_dir.glob("*.sqlite")))
        return {
            "backend": "sqlite",
            "count": n,
            "db_bytes": size,
            "oldest": oldest["t"] if oldest else None,
            "newest": newest["t"] if newest else None,
            "archive_files": archives,
            "hot_days": news_hot_days(),
            "max_items": news_max_items(),
        }

    def _maybe_migrate_jsonl(self) -> None:
        with self._lock:
            c = self._conn()
            done = c.execute(
                "SELECT value FROM meta WHERE key='jsonl_migrated'"
            ).fetchone()
            if done:
                return
            if not self.legacy_jsonl.exists():
                c.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES('jsonl_migrated',?)",
                    (_utc_iso(),),
                )
                c.commit()
                return
            n = 0
            with self.legacy_jsonl.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if not item.get("id"):
                        continue
                    # direct insert without nested lock
                    from zipka.news.ru_index import ensure_item_lemmas

                    ensure_item_lemmas(item)
                    url = str(item.get("url") or item.get("source_url") or "").strip()
                    c.execute(
                        """
                        INSERT OR REPLACE INTO items (
                            id, kind, source, title, url, source_url,
                            published_at, fetched_at, summary, text, lemmas_json, published_ts
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(item["id"]),
                            item.get("kind"),
                            item.get("source"),
                            item.get("title"),
                            url or None,
                            str(item.get("source_url") or url or "") or None,
                            item.get("published_at"),
                            item.get("fetched_at"),
                            item.get("summary"),
                            item.get("text"),
                            json.dumps(item.get("lemmas"), ensure_ascii=False)
                            if item.get("lemmas")
                            else None,
                            self._published_ts(item),
                        ),
                    )
                    n += 1
                    if n % 500 == 0:
                        c.commit()
            c.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('jsonl_migrated',?)",
                (_utc_iso(),),
            )
            c.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('jsonl_migrated_count',?)",
                (str(n),),
            )
            c.commit()
            # rename legacy so we don't double-migrate; keep backup
            bak = self.legacy_jsonl.with_suffix(".jsonl.migrated")
            try:
                if not bak.exists():
                    self.legacy_jsonl.rename(bak)
            except OSError:
                pass
