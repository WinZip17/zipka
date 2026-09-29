"""Новости: RSS + публичные Telegram-каналы (t.me/s), выдержки и поиск."""
from __future__ import annotations

import hashlib
import json
import re
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
    r"что\s+нового\s+в\s+новост|были\s+ли\s+.*\s+в\s+новост)"
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
        if not self.sources_path.exists():
            self.save_sources({"rss": [], "telegram": [], "updated_at": _utc_iso()})

    def load_sources(self) -> dict[str, Any]:
        try:
            data = json.loads(self.sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("rss", [])
        data.setdefault("telegram", [])
        data["rss"] = [str(x).strip() for x in data["rss"] if str(x).strip()]
        data["telegram"] = [
            normalize_telegram(str(x)) or str(x).strip().lstrip("@")
            for x in data["telegram"]
            if str(x).strip()
        ]
        # unique preserve order
        data["rss"] = list(dict.fromkeys(data["rss"]))
        data["telegram"] = list(dict.fromkeys([t for t in data["telegram"] if t]))
        return data

    def save_sources(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = {
            "rss": list(dict.fromkeys([str(x).strip() for x in (data.get("rss") or []) if str(x).strip()])),
            "telegram": list(
                dict.fromkeys(
                    [
                        normalize_telegram(str(x)) or str(x).strip().lstrip("@")
                        for x in (data.get("telegram") or [])
                        if str(x).strip()
                    ]
                )
            ),
            "updated_at": _utc_iso(),
        }
        payload["telegram"] = [t for t in payload["telegram"] if t]
        self.sources_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return payload

    def add_rss(self, url: str) -> dict[str, Any]:
        url = (url or "").strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("RSS URL должен начинаться с http(s)://")
        src = self.load_sources()
        if url not in src["rss"]:
            src["rss"].append(url)
        return self.save_sources(src)

    def add_telegram(self, raw: str) -> dict[str, Any]:
        channel = normalize_telegram(raw)
        if not channel:
            raise ValueError("Нужен @channel или https://t.me/channel")
        src = self.load_sources()
        if channel not in src["telegram"]:
            src["telegram"].append(channel)
        return self.save_sources(src)

    def remove_source(self, *, rss: str | None = None, telegram: str | None = None) -> dict[str, Any]:
        src = self.load_sources()
        if rss:
            src["rss"] = [u for u in src["rss"] if u != rss.strip()]
        if telegram:
            ch = normalize_telegram(telegram) or telegram.strip().lstrip("@")
            src["telegram"] = [t for t in src["telegram"] if t != ch]
        return self.save_sources(src)

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
        try:
            return self.llm.summarize(
                text,
                instruction=(
                    "Сделай краткую новостную выдержку на русском (1–3 предложения): "
                    "суть, кто/что, зачем важно. Без воды и кликбейта."
                ),
            ).strip()
        except Exception as exc:
            # fallback без LLM
            snippet = body[:400].strip()
            return f"{title}. {snippet}".strip() + f" [{exc.__class__.__name__}]"

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
    ) -> dict[str, Any]:
        src = self.load_sources()
        if not src["rss"] and not src["telegram"]:
            raise RuntimeError(
                "Нет источников. Добавь RSS или Telegram в настройках / "
                "«добавь rss …» / «добавь телеграм @channel»."
            )
        known = self.known_ids()
        added: list[dict[str, Any]] = []
        errors: list[str] = []

        candidates: list[dict[str, Any]] = []
        for feed in src["rss"]:
            try:
                candidates.extend(self.fetch_rss_entries(feed, limit=per_source))
            except Exception as exc:
                errors.append(f"RSS {feed}: {exc}")
        for channel in src["telegram"]:
            try:
                candidates.extend(
                    self.fetch_telegram_entries(channel, limit=per_source)
                )
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
                continue  # обязателен первоисточник
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

        return {
            "ok": True,
            "added": len(added),
            "sources": {
                "rss": len(src["rss"]),
                "telegram": len(src["telegram"]),
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
        # явные «про X» / «о X»
        m = re.search(
            r"(?i)(?:про|о|об|насчёт|насчет)\s+[«\"]?"
            r"([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-\.& ]{0,40}?)"
            r"[»\"]?(?=\s+в\s+новост|\s+за\s+|\s*\?|$)",
            text,
        )
        if m:
            topic = m.group(1).strip(" .,!?:;")
            if topic.lower() not in {"новостях", "новости", "ленте", "канале"}:
                return topic
        # «упоминания Озон» / «упоминали Wildberries»
        m2 = re.search(
            r"(?i)упоминал\w*\s+(?:про\s+|о\s+)?"
            r"[«\"]?([A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-\.& ]{1,40})[»\"]?",
            text,
        )
        if m2:
            return m2.group(1).strip(" .,!?:;")
        return None

    @staticmethod
    def item_source_url(item: dict[str, Any]) -> str:
        return normalize_http_url(
            item.get("source_url") or item.get("url") or item.get("link")
        )

    def format_hit_block(self, h: dict[str, Any]) -> str:
        when = (h.get("published_at") or h.get("fetched_at") or "")[:10]
        src = h.get("source") or ""
        title = h.get("title") or "Без заголовка"
        summary = (h.get("summary") or "")[:280]
        url = self.item_source_url(h)
        lines = [f"• [{when}] {src}: {title}"]
        if summary:
            lines.append(f"  {summary}")
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
        if not _NEWS_UPDATE_RE.search(text):
            return None
        low = text.lower()
        # ingest commands handled elsewhere
        if any(
            k in low
            for k in (
                "обнови новости",
                "прочитай новости",
                "изучи новости",
                "добавь rss",
                "добавь телеграм",
                "покажи источники",
            )
        ):
            return None
        topic = self.extract_topic(text)
        days = self.extract_days(text, default=7)
        if not topic:
            # общий обзор
            items = [
                r
                for r in self.load_items(limit=200)
                if (
                    (_parse_dt(r.get("published_at")) or _parse_dt(r.get("fetched_at")) or _utc_now())
                    >= _utc_now() - timedelta(days=days)
                )
            ]
            if not items:
                return (
                    f"За {days} дн. сохранённых новостей нет. "
                    "Скажи «обнови новости» после настройки источников."
                )
            lines = [f"Краткий обзор за {days} дн. ({len(items)} выдержек):", ""]
            for h in items[-8:]:
                lines.append(self.format_hit_block(h))
                lines.append("")
            return "\n".join(lines).rstrip()
        hits = self.search(topic, days=days, limit=15)
        return self.format_search_answer(topic=topic, days=days, hits=hits)

    def handle_chat_command(self, text: str) -> str | None:
        low = text.lower().strip()

        if "покажи источники" in low or "источники новостей" in low:
            src = self.load_sources()
            rss = "\n".join(f"- {u}" for u in src["rss"]) or "- (нет)"
            tg = "\n".join(f"- @{c}" for c in src["telegram"]) or "- (нет)"
            return f"RSS:\n{rss}\n\nTelegram:\n{tg}"

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
