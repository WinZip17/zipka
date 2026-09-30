"""Новости: RSS + публичные Telegram-каналы (t.me/s), выдержки и поиск."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from zipka.config import Settings, ensure_data_dirs, get_settings
from zipka.memory.store import MemoryStore

_UA = (
    "Mozilla/5.0 (compatible; ZipkaNews/0.1; +https://github.com/local/zipka)"
)
_TG_RE = re.compile(
    r"(?:https?://)?t\.me/(?:s/)?([A-Za-z0-9_]{3,64})/?|"
    r"@([A-Za-z0-9_]{3,64})",
    re.IGNORECASE,
)
_NEWS_UPDATE_RE = re.compile(
    r"(?i)(?:новост|rss|телеграм[^\n]{0,20}канал|лент[аы] новост|"
    r"обнови\s+новост|прочитай\s+новост|изучи\s+новост|"
    r"упоминал|упоминани|за\s+последн|"
    r"что\s+нового\s+в\s+новост|были\s+ли\s+.*\s+в\s+новост|"
    r"что\s+(?:было\s+)?интересн\w*.*новост|"
    r"интересн\w*\s+в\s+(?:последн\w*\s+)?новост|"
    r"обсуд\w*.*новост|что\s+думаешь.*новост|как\s+тебе\s+новост|"
    r"мнени\w*.*новост|обзор\s+новост)"
)
_DAYS_RE = re.compile(
    r"(?i)за\s+последн(?:ие|юю|ий)\s+(\d+)\s*"
    r"(?:дн|день|дня|недел)|"
    r"за\s+неделю|за\s+последнюю\s+неделю|"
    r"за\s+(\d+)\s*(?:дн|день|дня)"
)

# частые кириллица↔латиница для ритейла/брендов
_ALIASES: dict[str, tuple[str, ...]] = {
    "озон": ("ozon", "озон"),
    "ozon": ("ozon", "озон"),
    "вайлдберриз": ("wildberries", "wb", "вайлдберриз", "wildberries"),
    "wildberries": ("wildberries", "wb", "вайлдберриз"),
    "wb": ("wildberries", "wb", "вайлдберриз"),
    "яндекс": ("yandex", "яндекс"),
    "yandex": ("yandex", "яндекс"),
    "сбер": ("sber", "сбер", "sberbank"),
    "тинькофф": ("tinkoff", "tbank", "тинькофф"),
}


def _query_variants(query: str) -> list[str]:
    q = query.strip().lower()
    variants = {q}
    for part in re.split(r"\s+", q):
        variants.add(part)
        for alt in _ALIASES.get(part, ()):
            variants.add(alt)
    return [v for v in variants if len(v) >= 2]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    d = dt or _utc_now()
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def normalize_telegram(raw: str) -> str | None:
    text = (raw or "").strip()
    m = _TG_RE.search(text)
    if not m:
        return None
    return (m.group(1) or m.group(2) or "").lstrip("@")


def item_id(source: str, link: str, title: str) -> str:
    key = f"{source}|{link}|{title}".encode("utf-8", errors="ignore")
    return hashlib.sha1(key).hexdigest()[:16]


def normalize_http_url(url: str | None) -> str:
    """Канонический http(s) URL или пустая строка."""
    raw = (url or "").strip()
    if not raw:
        return ""
    if raw.startswith("//"):
        raw = "https:" + raw
    if not raw.startswith(("http://", "https://")):
        return ""
    return raw.rstrip(").,;\"'")


def telegram_message_url(channel: str, post_id: str | int | None) -> str:
    ch = (channel or "").lstrip("@")
    if not ch:
        return ""
    if post_id is None or str(post_id).strip() == "":
        return f"https://t.me/{ch}"
    return f"https://t.me/{ch}/{post_id}"


INTERVAL_MINUTES: tuple[int, ...] = (60, 120, 180, 240, 360, 720, 1440)
INTERVAL_OPTIONS: list[dict[str, Any]] = [
    {"value": "off", "label": "выкл", "minutes": None},
    {"value": 60, "label": "1ч", "minutes": 60},
    {"value": 120, "label": "2ч", "minutes": 120},
    {"value": 180, "label": "3ч", "minutes": 180},
    {"value": 240, "label": "4ч", "minutes": 240},
    {"value": 360, "label": "6ч", "minutes": 360},
    {"value": 720, "label": "12ч", "minutes": 720},
    {"value": 1440, "label": "1д", "minutes": 1440},
]
SOURCE_INTERVAL_OPTIONS: list[dict[str, Any]] = [
    {"value": "global", "label": "как глобально", "minutes": None},
    *INTERVAL_OPTIONS,
]


def _rss_key(url: str) -> str:
    return f"rss:{url}"


def _tg_key(channel: str) -> str:
    return f"tg:{channel}"


_PROMPT_LEAK_RE = re.compile(
    r"(?is)("
    r"хочу,\s*чтобы\s+ты|"
    r"хочу\s+получить\s+кратк|"
    r"переделай\s+выдержк|"
    r"краткую\s+новостную\s+выдержк|"
    r"ты\s*[—\-]\s*зипка|"
    r"я\s+зипка\b|"
    r"ты\s+зипка\b|"
    r"стала\s+частью\s+процесса|"
    r"собираешь\s+информацию|"
    r"не\s+просто\s+пересказыва|"
    r"разумел\w*,\s*зипка|"
    r"не\s+понял,?\s+что\s+именно\s+ты\s+хочешь|"
    r"уточни,?\s+что\s+именно|"
    r"напиши\s+ответ\s+пользователю|"
    r"единственный\s+источник\s+фактов|"
    r"не\s+цитируй\s+и\s+не\s+пересказывай\s+эти\s+инструкц|"
    r"разработка:\s*зипка|"
    r"фрагмент:\s*\d+/\d+|"
    r"тон:\s*\w+|"
    r"стиль:\s*информативн|"
    r"1\s*[–\-]\s*3\s+предложения:\s*суть"
    r")"
)


def looks_like_prompt_leak(text: str) -> bool:
    """True, если текст похож на промпт/мета-реплику, а не на выдержку."""
    raw = (text or "").strip()
    if len(raw) < 8:
        return True
    return bool(_PROMPT_LEAK_RE.search(raw))


def sanitize_news_summary(text: str, *, fallback: str = "") -> str:
    """Убрать промпты и болтовню модели из сохранённой/показанной выдержки."""
    raw = (text or "").strip()
    if not raw:
        return (fallback or "").strip()
    # обращения / самопрезентация в начале
    raw = re.sub(
        r"(?is)^(разумеет\w*|конечно|хорошо|ладно|принято)[,!.]?\s*",
        "",
        raw,
    ).strip()
    raw = re.sub(r"(?is)^зипка[,!.]?\s*", "", raw).strip()
    raw = re.sub(r"(?is)^я\s+зипка\s*[—\-:.]+\s*", "", raw).strip()
    raw = re.sub(r"(?is)^вот\s+кратко\s*[:\-—]?\s*", "", raw).strip()
    raw = re.sub(r"(?is)^[.…]+\s*", "", raw).strip()
    # выкинуть служебные блоки «Разработка: Зипка | …»
    raw = re.sub(
        r"(?im)^.*(?:разработка:\s*зипка|фрагмент:\s*\d+/\d+|тон:\s*\w+).*\n?",
        "",
        raw,
    ).strip()
    if looks_like_prompt_leak(raw):
        fb = (fallback or "").strip()
        return fb[:500] if fb else ""
    return raw


class NewsDesk:
    """Источники новостей, ingest выдержек, поиск по периоду."""

    def __init__(
        self,
        llm: Any,
        memory: MemoryStore,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        ensure_data_dirs(self.settings)
        self.llm = llm
        self.memory = memory
        self.root = self.settings.data_dir / "news"
        self.root.mkdir(parents=True, exist_ok=True)
        self.sources_path = self.root / "sources.json"
        self.items_path = self.root / "items.jsonl"
        self._ingest_lock = threading.Lock()
        self._auto_running = False
        self._auto_phase = ""
        self._pending_after_chat = False
        self._last_auto_result: dict[str, Any] | None = None
        if not self.sources_path.exists():
            self.save_sources(
                {
                    "global_interval_min": None,
                    "rss": [],
                    "telegram": [],
                    "last_fetch": {},
                }
            )

    def load_sources(self) -> dict[str, Any]:
        try:
            data = json.loads(self.sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        return self._normalize_sources(data)

    def _normalize_sources(self, data: dict[str, Any]) -> dict[str, Any]:
        global_iv = self._parse_global_interval(data.get("global_interval_min"))
        last_fetch = data.get("last_fetch") if isinstance(data.get("last_fetch"), dict) else {}
        last_fetch = {str(k): str(v) for k, v in last_fetch.items() if v}

        rss_out: list[dict[str, Any]] = []
        seen_rss: set[str] = set()
        for item in data.get("rss") or []:
            if isinstance(item, str):
                url = item.strip()
                interval: Any = "global"
            elif isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                interval = self._parse_source_interval(item.get("interval"))
            else:
                continue
            if not url or url in seen_rss:
                continue
            seen_rss.add(url)
            rss_out.append({"url": url, "interval": interval})

        tg_out: list[dict[str, Any]] = []
        seen_tg: set[str] = set()
        for item in data.get("telegram") or []:
            if isinstance(item, str):
                ch = normalize_telegram(item) or item.strip().lstrip("@")
                interval = "global"
            elif isinstance(item, dict):
                raw = str(item.get("id") or item.get("channel") or "").strip()
                ch = normalize_telegram(raw) or raw.lstrip("@")
                interval = self._parse_source_interval(item.get("interval"))
            else:
                continue
            if not ch or ch in seen_tg:
                continue
            seen_tg.add(ch)
            tg_out.append({"id": ch, "interval": interval})

        return {
            "global_interval_min": global_iv,
            "rss": rss_out,
            "telegram": tg_out,
            "last_fetch": last_fetch,
            "updated_at": data.get("updated_at") or _utc_iso(),
        }

    @staticmethod
    def _parse_global_interval(raw: Any) -> int | None:
        if raw is None or raw == "" or raw == "off":
            return None
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return None
        return n if n in INTERVAL_MINUTES else None

    @staticmethod
    def _parse_source_interval(raw: Any) -> Any:
        if raw is None or raw == "" or raw == "global":
            return "global"
        if raw == "off":
            return "off"
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return "global"
        return n if n in INTERVAL_MINUTES else "global"

    def save_sources(self, data: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_sources(data)
        normalized["updated_at"] = _utc_iso()
        self.sources_path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return normalized

    def add_rss(self, url: str, *, interval: Any = "global") -> dict[str, Any]:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("RSS URL должен начинаться с http(s)://")
        src = self.load_sources()
        if not any(x["url"] == url for x in src["rss"]):
            src["rss"].append(
                {"url": url, "interval": self._parse_source_interval(interval)}
            )
        return self.save_sources(src)

    def add_telegram(self, raw: str, *, interval: Any = "global") -> dict[str, Any]:
        channel = normalize_telegram(raw)
        if not channel:
            raise ValueError("Нужен @channel или https://t.me/channel")
        src = self.load_sources()
        if not any(x["id"] == channel for x in src["telegram"]):
            src["telegram"].append(
                {
                    "id": channel,
                    "interval": self._parse_source_interval(interval),
                }
            )
        return self.save_sources(src)

    def remove_source(
        self, *, rss: str | None = None, telegram: str | None = None
    ) -> dict[str, Any]:
        src = self.load_sources()
        if rss:
            url = rss.strip()
            src["rss"] = [x for x in src["rss"] if x["url"] != url]
            src["last_fetch"].pop(_rss_key(url), None)
        if telegram:
            ch = normalize_telegram(telegram) or telegram.strip().lstrip("@")
            src["telegram"] = [x for x in src["telegram"] if x["id"] != ch]
            src["last_fetch"].pop(_tg_key(ch), None)
        return self.save_sources(src)

    def set_global_interval(self, value: Any) -> dict[str, Any]:
        src = self.load_sources()
        src["global_interval_min"] = self._parse_global_interval(value)
        return self.save_sources(src)

    def set_source_interval(
        self,
        *,
        rss: str | None = None,
        telegram: str | None = None,
        interval: Any = "global",
    ) -> dict[str, Any]:
        src = self.load_sources()
        iv = self._parse_source_interval(interval)
        if rss:
            url = rss.strip()
            for item in src["rss"]:
                if item["url"] == url:
                    item["interval"] = iv
                    break
        if telegram:
            ch = normalize_telegram(telegram) or telegram.strip().lstrip("@")
            for item in src["telegram"]:
                if item["id"] == ch:
                    item["interval"] = iv
                    break
        return self.save_sources(src)

    def effective_interval_min(self, entry: dict[str, Any], global_min: int | None) -> int | None:
        iv = entry.get("interval", "global")
        if iv == "off":
            return None
        if iv == "global":
            return global_min
        try:
            n = int(iv)
        except (TypeError, ValueError):
            return global_min
        return n if n in INTERVAL_MINUTES else global_min

    def list_due_sources(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        now = now or _utc_now()
        src = self.load_sources()
        global_min = src.get("global_interval_min")
        last = src.get("last_fetch") or {}
        due: list[dict[str, Any]] = []

        for item in src["rss"]:
            minutes = self.effective_interval_min(item, global_min)
            if minutes is None:
                continue
            key = _rss_key(item["url"])
            prev = _parse_dt(last.get(key))
            if prev is None or (now - prev) >= timedelta(minutes=minutes):
                due.append({"kind": "rss", "id": item["url"], "key": key, "minutes": minutes})

        for item in src["telegram"]:
            minutes = self.effective_interval_min(item, global_min)
            if minutes is None:
                continue
            key = _tg_key(item["id"])
            prev = _parse_dt(last.get(key))
            if prev is None or (now - prev) >= timedelta(minutes=minutes):
                due.append(
                    {
                        "kind": "telegram",
                        "id": item["id"],
                        "key": key,
                        "minutes": minutes,
                    }
                )
        return due

    def mark_fetched(self, keys: list[str]) -> None:
        if not keys:
            return
        src = self.load_sources()
        stamp = _utc_iso()
        for key in keys:
            src["last_fetch"][key] = stamp
        self.save_sources(src)

    def auto_status(self) -> dict[str, Any]:
        due = self.list_due_sources()
        return {
            "running": self._auto_running,
            "phase": self._auto_phase or None,
            "message": "Обновляю новости…" if self._auto_running else None,
            "pending_after_chat": self._pending_after_chat,
            "due_count": len(due),
            "due": due[:12],
            "last_result": self._last_auto_result,
            "interval_options": INTERVAL_OPTIONS,
            "source_interval_options": SOURCE_INTERVAL_OPTIONS,
        }

    def on_chat_idle(self) -> None:
        """Вызвать после ответа в чате: если ждали — запустить due."""
        if self._auto_running:
            return
        due = self.list_due_sources()
        if self._pending_after_chat or due:
            self._pending_after_chat = False
            self.maybe_auto_ingest(chat_busy=False, finetune_busy=False)

    def maybe_auto_ingest(
        self,
        *,
        chat_busy: bool,
        finetune_busy: bool = False,
    ) -> dict[str, Any] | None:
        due = self.list_due_sources()
        if not due:
            self._pending_after_chat = False
            return None
        if finetune_busy:
            # не копим pending: после дообучения due снова подхватит scheduler
            return None
        if chat_busy:
            self._pending_after_chat = True
            return None
        if self._auto_running:
            return None
        try:
            rss_urls = [d["id"] for d in due if d["kind"] == "rss"]
            tg_ids = [d["id"] for d in due if d["kind"] == "telegram"]
            result = self.ingest(rss_urls=rss_urls, telegram_ids=tg_ids)
            result["auto"] = True
            result["due"] = due
            self._last_auto_result = {
                "at": _utc_iso(),
                "added": result.get("added"),
                "errors": result.get("errors"),
            }
            self._pending_after_chat = False
            return result
        except RuntimeError as exc:
            if "уже идёт" in str(exc).lower():
                return None
            self._last_auto_result = {"at": _utc_iso(), "error": str(exc)}
            raise
        except Exception as exc:
            self._last_auto_result = {"at": _utc_iso(), "error": str(exc)}
            raise

    def known_ids(self) -> set[str]:
        ids: set[str] = set()
        if not self.items_path.exists():
            return ids
        with self.items_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("id"):
                    ids.add(str(row["id"]))
        return ids

    def append_item(self, item: dict[str, Any]) -> None:
        self.items_path.parent.mkdir(parents=True, exist_ok=True)
        with self.items_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    def load_items(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.items_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self.items_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        if limit is not None and limit > 0:
            return rows[-limit:]
        return rows

    def _http_get(self, url: str, *, timeout: float = 45.0) -> str:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _UA, "Accept": "*/*"},
        ) as client:
            res = client.get(url)
            res.raise_for_status()
            return res.text

    def _local_tag(self, tag: str) -> str:
        if "}" in tag:
            return tag.rsplit("}", 1)[-1].lower()
        return tag.lower()

    def _parse_rss(self, xml_text: str) -> list[dict[str, str]]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise RuntimeError(f"Невалидный RSS/Atom: {exc}") from exc

        items: list[dict[str, str]] = []
        # RSS 2.0
        for node in root.iter():
            if self._local_tag(node.tag) != "item":
                continue
            fields: dict[str, str] = {}
            for child in list(node):
                name = self._local_tag(child.tag)
                text = (child.text or "").strip()
                if name in {"title", "link", "description", "pubdate", "published"}:
                    fields[name] = text
                elif name == "guid":
                    # guid часто = permalink
                    is_perm = (child.attrib.get("isPermaLink") or "true").lower()
                    if is_perm != "false" and text.startswith("http"):
                        fields.setdefault("link", text)
                    elif text.startswith("http"):
                        fields.setdefault("link", text)
            if fields.get("title") or fields.get("description"):
                items.append(
                    {
                        "title": fields.get("title") or "",
                        "link": normalize_http_url(fields.get("link")),
                        "description": fields.get("description") or "",
                        "published": fields.get("pubdate")
                        or fields.get("published")
                        or "",
                    }
                )
        if items:
            return items

        # Atom
        for node in root.iter():
            if self._local_tag(node.tag) != "entry":
                continue
            title = ""
            link = ""
            summary = ""
            published = ""
            for child in list(node):
                name = self._local_tag(child.tag)
                if name == "title":
                    title = (child.text or "").strip()
                elif name == "summary" or name == "content":
                    summary = (child.text or "").strip() or summary
                elif name == "updated" or name == "published":
                    published = (child.text or "").strip() or published
                elif name == "link":
                    href = child.attrib.get("href") or (child.text or "").strip()
                    if href and (not link or child.attrib.get("rel") == "alternate"):
                        link = href
            if title or summary:
                items.append(
                    {
                        "title": title,
                        "link": normalize_http_url(link),
                        "description": summary,
                        "published": published,
                    }
                )
        return items

    def _strip_html(self, html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()

    def _summarize_piece(
        self, *, title: str, body: str, source: str
    ) -> str:
        text = f"Заголовок: {title}\nИсточник: {source}\n\n{body}".strip()
        text = text[:6000]
        fallback = f"{title}. {body[:400]}".strip()
        try:
            raw = self.llm.summarize(
                text,
                instruction=(
                    "Сделай краткую новостную выдержку на русском (1–3 предложения): "
                    "суть, кто/что, зачем важно. Без воды и кликбейта. "
                    "Выведи ТОЛЬКО текст выдержки, без обращений и без копирования инструкции."
                ),
            ).strip()
        except Exception as exc:
            return f"{fallback} [{exc.__class__.__name__}]".strip()
        cleaned = sanitize_news_summary(raw, fallback=fallback)
        if not cleaned:
            return fallback[:500]
        return cleaned

    def fetch_rss_entries(
        self, feed_url: str, *, limit: int = 12
    ) -> list[dict[str, Any]]:
        xml_text = self._http_get(feed_url)
        raw_items = self._parse_rss(xml_text)[:limit]
        out: list[dict[str, Any]] = []
        for it in raw_items:
            title = self._strip_html(it.get("title") or "") or "Без заголовка"
            link = normalize_http_url(it.get("link"))
            if not link:
                continue  # без первоисточника не берём
            desc = self._strip_html(it.get("description") or "")
            published = _parse_dt(it.get("published"))
            out.append(
                {
                    "kind": "rss",
                    "source": feed_url,
                    "title": title,
                    "link": link,
                    "source_url": link,
                    "body": desc,
                    "published_at": _utc_iso(published) if published else None,
                }
            )
        return out

    def fetch_telegram_entries(
        self, channel: str, *, limit: int = 12
    ) -> list[dict[str, Any]]:
        channel = normalize_telegram(channel) or channel.strip().lstrip("@")
        preview_url = f"https://t.me/s/{channel}"
        html = self._http_get(preview_url)
        soup = BeautifulSoup(html, "html.parser")
        widgets = soup.select("div.tgme_widget_message")
        out: list[dict[str, Any]] = []
        for w in widgets[-limit:]:
            text_el = w.select_one("div.tgme_widget_message_text")
            body = text_el.get_text("\n", strip=True) if text_el else ""
            if not body:
                continue

            link = ""
            published = None
            data_post = (w.get("data-post") or "").strip()  # channel/123
            if data_post and "/" in data_post:
                ch_name, post_id = data_post.split("/", 1)
                link = telegram_message_url(ch_name or channel, post_id)

            link_el = w.select_one("a.tgme_widget_message_date")
            if link_el is not None:
                href = normalize_http_url(link_el.get("href"))
                if href:
                    link = href
                time_el = link_el.select_one("time")
                if time_el and time_el.get("datetime"):
                    published = _parse_dt(time_el.get("datetime"))

            if not link:
                # последний шанс: любая ссылка t.me/channel/N в виджете
                for a in w.select("a[href]"):
                    href = normalize_http_url(a.get("href"))
                    if href and re.search(rf"t\.me/{re.escape(channel)}/\d+", href):
                        link = href
                        break

            if not link:
                continue  # без ссылки на сообщение не сохраняем

            title = body.split("\n", 1)[0][:120]
            out.append(
                {
                    "kind": "telegram",
                    "source": f"@{channel}",
                    "title": title,
                    "link": link,
                    "source_url": link,
                    "body": body,
                    "published_at": _utc_iso(published) if published else None,
                }
            )
        out.reverse()
        return out

    def ingest(
        self,
        *,
        per_source: int = 10,
        max_new: int = 40,
        rss_urls: list[str] | None = None,
        telegram_ids: list[str] | None = None,
        mark_fetch: bool = True,
    ) -> dict[str, Any]:
        src = self.load_sources()
        rss_list = [x["url"] for x in src["rss"]]
        tg_list = [x["id"] for x in src["telegram"]]
        if rss_urls is not None:
            want = set(rss_urls)
            rss_list = [u for u in rss_list if u in want]
        if telegram_ids is not None:
            want_tg = set(telegram_ids)
            tg_list = [c for c in tg_list if c in want_tg]

        if not rss_list and not tg_list:
            raise RuntimeError(
                "Нет источников. Добавь RSS или Telegram в настройках / "
                "«добавь rss …» / «добавь телеграм @channel»."
            )

        if not self._ingest_lock.acquire(blocking=False):
            raise RuntimeError("Уже идёт обновление новостей.")
        self._auto_running = True
        self._auto_phase = "ingest"

        try:
            known = self.known_ids()
            added: list[dict[str, Any]] = []
            errors: list[str] = []
            fetched_keys: list[str] = []

            candidates: list[dict[str, Any]] = []
            for feed in rss_list:
                try:
                    candidates.extend(self.fetch_rss_entries(feed, limit=per_source))
                    fetched_keys.append(_rss_key(feed))
                except Exception as exc:
                    errors.append(f"RSS {feed}: {exc}")
            for channel in tg_list:
                try:
                    candidates.extend(
                        self.fetch_telegram_entries(channel, limit=per_source)
                    )
                    fetched_keys.append(_tg_key(channel))
                except Exception as exc:
                    errors.append(f"TG @{channel}: {exc}")

            for cand in candidates:
                if len(added) >= max_new:
                    break
                iid = item_id(
                    str(cand.get("source") or ""),
                    str(cand.get("link") or ""),
                    str(cand.get("title") or ""),
                )
                if iid in known:
                    continue
                body = str(cand.get("body") or "").strip()
                title = str(cand.get("title") or "").strip()
                source_url = normalize_http_url(
                    cand.get("source_url") or cand.get("link") or cand.get("url")
                )
                if not source_url:
                    continue
                if len(body) < 20 and len(title) < 8:
                    continue
                summary = self._summarize_piece(
                    title=title,
                    body=body or title,
                    source=str(cand.get("source") or ""),
                )
                item = {
                    "id": iid,
                    "kind": cand.get("kind"),
                    "source": cand.get("source"),
                    "title": title,
                    "url": source_url,
                    "source_url": source_url,
                    "published_at": cand.get("published_at"),
                    "fetched_at": _utc_iso(),
                    "summary": summary,
                    "text": (body or title)[:2500],
                }
                self.append_item(item)
                known.add(iid)
                added.append(item)
                self.memory.add_note(
                    "news",
                    f"{summary}\nПервоисточник: {source_url}",
                    meta={
                        "id": iid,
                        "source": item["source"],
                        "url": source_url,
                        "source_url": source_url,
                        "title": title,
                        "published_at": item.get("published_at"),
                    },
                )

            if mark_fetch and fetched_keys:
                self.mark_fetched(fetched_keys)

            return {
                "ok": True,
                "added": len(added),
                "sources": {
                    "rss": len(rss_list),
                    "telegram": len(tg_list),
                },
                "errors": errors,
                "items": [
                    {
                        "title": x["title"],
                        "source": x["source"],
                        "summary": x["summary"],
                        "url": x.get("url"),
                    }
                    for x in added[:12]
                ],
            }
        finally:
            self._auto_running = False
            self._auto_phase = ""
            self._ingest_lock.release()

    def search(
        self,
        query: str,
        *,
        days: int = 7,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        q = (query or "").strip().lower()
        if not q:
            return []
        variants = _query_variants(q)
        since = _utc_now() - timedelta(days=max(1, days))
        hits: list[dict[str, Any]] = []
        for row in self.load_items():
            when = _parse_dt(row.get("published_at")) or _parse_dt(row.get("fetched_at"))
            if when and when < since:
                continue
            blob = " ".join(
                [
                    str(row.get("title") or ""),
                    str(row.get("summary") or ""),
                    str(row.get("text") or ""),
                    str(row.get("source") or ""),
                ]
            ).lower()
            score = sum(1 for tok in variants if tok in blob)
            if score <= 0:
                continue
            hits.append({**row, "_score": score})
        hits.sort(
            key=lambda r: (
                int(r.get("_score") or 0),
                str(r.get("published_at") or r.get("fetched_at") or ""),
            ),
            reverse=True,
        )
        return hits[:limit]

    @staticmethod
    def extract_days(text: str, default: int = 7) -> int:
        low = text.lower()
        if "за неделю" in low or "последнюю неделю" in low or "последней недели" in low:
            return 7
        m = _DAYS_RE.search(text)
        if not m:
            return default
        for g in m.groups():
            if g and g.isdigit():
                return max(1, min(int(g), 90))
        return default

    @staticmethod
    def extract_topic(text: str) -> str | None:
        from zipka.news.dialogue import extract_topic as _extract_topic

        return _extract_topic(text)

    @staticmethod
    def item_source_url(item: dict[str, Any]) -> str:
        return normalize_http_url(
            item.get("source_url") or item.get("url") or item.get("link")
        )

    def format_hit_block(self, h: dict[str, Any]) -> str:
        when = (h.get("published_at") or h.get("fetched_at") or "")[:10]
        src = h.get("source") or ""
        title = h.get("title") or "Без заголовка"
        body = str(h.get("text") or h.get("body") or "")
        summary = sanitize_news_summary(
            str(h.get("summary") or ""),
            fallback=(body[:280] if body else title),
        )
        url = self.item_source_url(h)
        lines = [f"• [{when}] {src}: {title}"]
        if summary and summary.strip() != str(title).strip():
            lines.append(f"  {summary[:280]}")
        if url:
            lines.append(f"  Первоисточник: {url}")
        else:
            lines.append("  Первоисточник: (ссылка не сохранена)")
        return "\n".join(lines)

    def format_search_answer(
        self, *, topic: str, days: int, hits: list[dict[str, Any]]
    ) -> str:
        if not hits:
            return (
                f"За последние {days} дн. в сохранённых новостях "
                f"упоминаний «{topic}» не нашла. "
                "Можешь сказать «обнови новости» — подтяну свежие выдержки."
            )
        lines = [
            f"За последние {days} дн. по «{topic}» нашла {len(hits)} "
            f"упоминан{'ие' if len(hits) == 1 else 'ия' if len(hits) < 5 else 'ий'}:",
            "",
        ]
        for h in hits[:10]:
            lines.append(self.format_hit_block(h))
            lines.append("")
        return "\n".join(lines).rstrip()

    def answer_news_question(self, text: str) -> str | None:
        from zipka.news.dialogue import answer_news_dialogue

        return answer_news_dialogue(self, text)

    def handle_chat_command(self, text: str) -> str | None:
        low = text.lower().strip()

        if "покажи источники" in low or "источники новостей" in low:
            src = self.load_sources()
            g = src.get("global_interval_min")
            g_label = "выкл" if not g else f"{g} мин"
            lines = [f"Глобальный интервал: {g_label}", "", "RSS:"]
            if not src["rss"]:
                lines.append("- (нет)")
            for item in src["rss"]:
                lines.append(f"- {item['url']} [{item.get('interval', 'global')}]")
            lines.append("")
            lines.append("Telegram:")
            if not src["telegram"]:
                lines.append("- (нет)")
            for item in src["telegram"]:
                lines.append(f"- @{item['id']} [{item.get('interval', 'global')}]")
            return "\n".join(lines)

        m_rss = re.search(
            r"(?i)добавь\s+rss\s+(\S+)|rss\s*[:=]\s*(\S+)",
            text,
        )
        if m_rss or (low.startswith("добавь rss") and "http" in low):
            urls = re.findall(r"https?://\S+", text)
            if not urls and m_rss:
                cand = (m_rss.group(1) or m_rss.group(2) or "").strip()
                if cand:
                    urls = [cand]
            if not urls:
                return "Укажи URL: «добавь rss https://…/feed»"
            added = []
            for u in urls:
                u = u.rstrip(".,;:)")
                try:
                    self.add_rss(u)
                    added.append(u)
                except Exception as exc:
                    return f"Не добавила RSS `{u}`: {exc}"
            return "Добавила RSS:\n" + "\n".join(f"- {u}" for u in added)

        if "добавь телеграм" in low or "добавь telegram" in low or "добавь тг" in low:
            channels = []
            for m in _TG_RE.finditer(text):
                ch = m.group(1) or m.group(2)
                if ch:
                    channels.append(ch)
            if not channels:
                return "Укажи канал: «добавь телеграм @channel» или https://t.me/channel"
            for ch in channels:
                self.add_telegram(ch)
            return "Добавила Telegram:\n" + "\n".join(f"- @{c}" for c in channels)

        if any(
            k in low
            for k in (
                "обнови новости",
                "прочитай новости",
                "изучи новости",
                "подтянуть новости",
                "собери новости",
            )
        ):
            try:
                result = self.ingest()
            except Exception as exc:
                return f"Не смогла обновить новости: {exc}"
            lines = [
                f"Обновила ленту: +{result['added']} новых выдержек "
                f"(RSS {result['sources']['rss']}, TG {result['sources']['telegram']})."
            ]
            if result.get("errors"):
                lines.append("Ошибки:")
                lines.extend(f"- {e}" for e in result["errors"][:5])
            for it in result.get("items") or []:
                lines.append(f"• {it.get('source')}: {it.get('title')}")
                if it.get("summary"):
                    lines.append(f"  {it['summary'][:220]}")
                if it.get("url"):
                    lines.append(f"  Первоисточник: {it['url']}")
            return "\n".join(lines)

        return self.answer_news_question(text)
