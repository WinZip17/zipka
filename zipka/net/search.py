"""Веб-поиск: DuckDuckGo HTML + SearXNG → 2–3 страницы → выжимка со ссылками."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from zipka.config import Settings, get_settings
from zipka.memory.store import MemoryStore
from zipka.net.learner import NetLearner

# Явный запрос «поищи в сети», не путать с «найди файл» / новостями без веба
_SEARCH_INTENT = re.compile(
    r"(?i)(?:"
    r"\b(?:погугли|пошукай|прогугли)\b|"
    r"\b(?:найди|найти|поищи|поиск)\b.{0,40}\b(?:инф|свед|данн|факт|характеристик|спецификац|параметр)\w*|"
    r"\b(?:найди|найти|поищи)\b.{0,20}\b(?:в\s+(?:интернете|сети|вебе)|про\b|о\b)|"
    r"что\s+пишут\s+(?:про|о)\b|"
    r"\bтехническ\w*\s+характеристик\w*|"
    r"\bweb\s*search\b|\bgoogle\b"
    r")"
)

_NEWS_ONLY = re.compile(r"(?i)\bновост")
_STRIP_PREFIX = re.compile(
    r"(?i)^\s*(?:"
    r"пожалуйста[, ]*|плиз[, ]*|hey[, ]*|"
    r"(?:можешь|можешь\s+ли)\s+|"
    r"(?:погугли|пошукай|прогугли|найди|найти|поищи)\s+"
    r"(?:мне\s+|пожалуйста\s+)*"
    r"(?:информацию\s+|инфу\s+|сведения\s+|данные\s+)?"
    r"(?:о\s+|об\s+|про\s+)?"
    r")+"
)

_UA = (
    "Mozilla/5.0 (compatible; Zipka/0.2; +local; read-only; "
    "https://github.com/)"
)


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""


class WebSearch:
    """Поиск в сети и краткий ответ по 2–3 первоисточникам."""

    def __init__(
        self,
        llm: Any,
        memory: MemoryStore,
        net: NetLearner,
        settings: Settings | None = None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.net = net
        self.settings = settings or get_settings()

    @staticmethod
    def wants_search(text: str) -> bool:
        t = (text or "").strip()
        if len(t) < 8:
            return False
        if not _SEARCH_INTENT.search(t):
            return False
        # «найди новости…» — ветка news
        if _NEWS_ONLY.search(t) and not re.search(
            r"(?i)характеристик|спецификац|параметр|сайт|в\s+интернете|в\s+сети",
            t,
        ):
            return False
        # явный URL без «погугли» — URL-reader
        if NetLearner.extract_urls(t) and not re.search(
            r"(?i)погугли|пошукай|в\s+интернете|в\s+сети",
            t,
        ):
            return False
        return True

    def research(
        self,
        user_text: str,
        *,
        on_phase: Callable[[str], None] | None = None,
    ) -> str:
        def phase(name: str) -> None:
            if on_phase:
                on_phase(name)

        phase("searching")
        query = self.compose_query(user_text)
        backend, hits = self.search(query)
        if not hits:
            return (
                f"По запросу «{query}» ничего не нашла "
                f"(бэкенд: {backend}). Уточни формулировку или подними SearXNG "
                f"(`ZIPKA_SEARXNG_URL`)."
            )

        max_pages = max(1, min(int(self.settings.zipka_search_max_pages or 3), 5))
        allowlist_only = (
            (self.settings.zipka_search_fetch_mode or "open").strip().lower()
            == "allowlist"
        )

        phase("reading")
        pages: list[dict[str, Any]] = []
        errors: list[str] = []
        for hit in hits:
            if len(pages) >= max_pages:
                break
            try:
                if allowlist_only:
                    self.net._assert_allowed_host(hit.url)
                self.net._assert_safe_url(hit.url)
                text = self.net._fetch_text(hit.url)
                if len(text.strip()) < 80:
                    errors.append(f"{hit.url}: мало текста")
                    continue
                title = self.net._guess_title(text) or hit.title or hit.url
                pages.append(
                    {
                        "title": title,
                        "url": hit.url,
                        "snippet": hit.snippet,
                        "text": text[:12_000],
                    }
                )
            except Exception as exc:
                errors.append(f"{hit.url}: {exc}")

        if not pages:
            links = "\n".join(f"- {h.title}: {h.url}" for h in hits[:5])
            err = "; ".join(errors[:3]) if errors else "страницы не открылись"
            return (
                f"Нашла ссылки по «{query}», но не смогла прочитать содержимое ({err}).\n\n"
                f"Ссылки:\n{links}"
            )

        phase("replying")
        answer = self._synthesize(user_text=user_text, query=query, pages=pages)
        sources = "\n".join(
            f"{i}. {p['title']}\n   {p['url']}" for i, p in enumerate(pages, 1)
        )
        reply = (
            f"{answer.strip()}\n\n"
            f"---\n"
            f"Источники (запрос «{query}», {backend}):\n{sources}"
        )

        try:
            self.memory.add_note(
                "net_search",
                reply[:4000],
                meta={
                    "query": query,
                    "backend": backend,
                    "urls": [p["url"] for p in pages],
                },
            )
        except Exception:
            pass
        return reply

    def compose_query(self, user_text: str) -> str:
        fallback = _STRIP_PREFIX.sub("", (user_text or "").strip())
        fallback = re.sub(r"[?!.]+$", "", fallback).strip() or user_text.strip()
        fallback = fallback[:200]

        if not self.llm.is_available():
            return fallback
        try:
            raw = self.llm.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Составь один короткий поисковый запрос (ru/en) для веб-поиска. "
                            "Только текст запроса, без кавычек и пояснений. "
                            "Сохрани ключевые имена, модели, числа."
                        ),
                    },
                    {"role": "user", "content": user_text[:800]},
                ]
            )
            q = (raw or "").strip().splitlines()[0].strip(" «»\"'")
            q = re.sub(r"^(запрос|query)\s*:\s*", "", q, flags=re.I).strip()
            if 3 <= len(q) <= 200:
                return q
        except Exception:
            pass
        return fallback

    def search(self, query: str) -> tuple[str, list[SearchHit]]:
        backend = (self.settings.zipka_search_backend or "auto").strip().lower()
        limit = max(3, min(int(self.settings.zipka_search_result_limit or 8), 15))

        if backend in {"searxng", "searx"}:
            return "searxng", self._search_searxng(query, limit=limit)
        if backend in {"ddg", "duckduckgo"}:
            return "ddg", self._search_ddg(query, limit=limit)

        # auto: SearXNG если задан URL, иначе DDG; при пустой выдаче — fallback
        searx = (self.settings.zipka_searxng_url or "").strip()
        if searx:
            try:
                hits = self._search_searxng(query, limit=limit)
                if hits:
                    return "searxng", hits
            except Exception:
                pass
        hits = self._search_ddg(query, limit=limit)
        return "ddg", hits

    def _search_searxng(self, query: str, *, limit: int) -> list[SearchHit]:
        base = (self.settings.zipka_searxng_url or "").strip().rstrip("/")
        if not base:
            raise RuntimeError("ZIPKA_SEARXNG_URL не задан")
        url = f"{base}/search"
        with httpx.Client(timeout=25.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            r = client.get(
                url,
                params={
                    "q": query,
                    "format": "json",
                    "language": "ru-RU",
                },
            )
            r.raise_for_status()
            data = r.json()
        results = data.get("results") or []
        hits: list[SearchHit] = []
        for row in results:
            href = str(row.get("url") or "").strip()
            title = str(row.get("title") or href).strip()
            snippet = str(row.get("content") or row.get("snippet") or "").strip()
            if not href or not self._usable_result_url(href):
                continue
            hits.append(SearchHit(title=title or href, url=href, snippet=snippet[:400]))
            if len(hits) >= limit:
                break
        return hits

    def _search_ddg(self, query: str, *, limit: int) -> list[SearchHit]:
        """Парсинг html.duckduckgo.com / lite — без API-ключа."""
        headers = {
            "User-Agent": _UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }
        hits: list[SearchHit] = []
        with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers) as client:
            # 1) HTML version
            try:
                r = client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query, "b": "", "kl": "ru-ru"},
                )
                r.raise_for_status()
                hits = self._parse_ddg_html(r.text, limit=limit)
            except Exception:
                hits = []
            if len(hits) >= min(3, limit):
                return hits
            # 2) Lite fallback
            try:
                r2 = client.get(
                    "https://lite.duckduckgo.com/lite/",
                    params={"q": query, "kl": "ru-ru"},
                )
                r2.raise_for_status()
                lite = self._parse_ddg_lite(r2.text, limit=limit)
                hits = self._merge_hits(hits, lite, limit=limit)
            except Exception:
                pass
        return hits

    def _parse_ddg_html(self, html: str, *, limit: int) -> list[SearchHit]:
        soup = BeautifulSoup(html, "lxml")
        hits: list[SearchHit] = []
        for res in soup.select("div.result"):
            a = res.select_one("a.result__a")
            if not a or not a.get("href"):
                continue
            href = self._unwrap_ddg_href(str(a.get("href")))
            if not self._usable_result_url(href):
                continue
            title = a.get_text(" ", strip=True) or href
            sn_el = res.select_one("a.result__snippet, div.result__snippet")
            snippet = sn_el.get_text(" ", strip=True) if sn_el else ""
            hits.append(SearchHit(title=title, url=href, snippet=snippet[:400]))
            if len(hits) >= limit:
                break
        if hits:
            return hits
        # запасной селектор
        for a in soup.select("a.result__a"):
            href = self._unwrap_ddg_href(str(a.get("href") or ""))
            if not self._usable_result_url(href):
                continue
            hits.append(
                SearchHit(title=a.get_text(" ", strip=True) or href, url=href)
            )
            if len(hits) >= limit:
                break
        return hits

    def _parse_ddg_lite(self, html: str, *, limit: int) -> list[SearchHit]:
        soup = BeautifulSoup(html, "lxml")
        hits: list[SearchHit] = []
        for a in soup.select("a[href]"):
            href = self._unwrap_ddg_href(str(a.get("href") or ""))
            if not self._usable_result_url(href):
                continue
            title = a.get_text(" ", strip=True)
            if not title or len(title) < 3:
                continue
            # lite часто даёт относительные /l/?uddg=
            hits.append(SearchHit(title=title, url=href))
            if len(hits) >= limit:
                break
        return hits

    @staticmethod
    def _merge_hits(
        a: list[SearchHit], b: list[SearchHit], *, limit: int
    ) -> list[SearchHit]:
        seen: set[str] = set()
        out: list[SearchHit] = []
        for hit in [*a, *b]:
            key = hit.url.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(hit)
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _unwrap_ddg_href(href: str) -> str:
        href = (href or "").strip()
        if not href:
            return ""
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/"):
            href = urljoin("https://duckduckgo.com", href)
        parsed = urlparse(href)
        if "duckduckgo.com" in (parsed.netloc or "") and (
            "/l/" in parsed.path or "uddg=" in (parsed.query or "")
        ):
            qs = parse_qs(parsed.query)
            if "uddg" in qs and qs["uddg"]:
                return unquote(qs["uddg"][0])
        return href

    def _usable_result_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in {"http", "https"}:
            return False
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        blocked = (
            "duckduckgo.com",
            "duck.com",
            "google.com",
            "google.ru",
            "bing.com",
            "yandex.ru",
            "yandex.com",
            "youtube.com",
            "youtu.be",
        )
        if any(host == b or host.endswith("." + b) for b in blocked):
            return False
        return True

    def _synthesize(
        self,
        *,
        user_text: str,
        query: str,
        pages: list[dict[str, Any]],
    ) -> str:
        blocks = []
        for i, p in enumerate(pages, 1):
            blocks.append(
                f"### Источник {i}: {p['title']}\n"
                f"URL: {p['url']}\n"
                f"{p['text'][:8000]}"
            )
        corpus = "\n\n".join(blocks)
        instruction = (
            "По запросу пользователя и текстам источников дай краткий ответ по-русски.\n"
            "Правила:\n"
            "- опирайся ТОЛЬКО на факты из источников;\n"
            "- если данных нет — так и скажи, не выдумывай цифры;\n"
            "- структурируй (список характеристик / факты);\n"
            "- не копируй длинные абзацы;\n"
            "- не добавляй блок «Источники» — его добавят отдельно;\n"
            f"Запрос пользователя: {user_text[:500]}\n"
            f"Поисковый запрос: {query}"
        )
        try:
            return self.llm.summarize(corpus, instruction=instruction)
        except Exception as exc:
            # fallback без LLM: сниппеты
            parts = [f"(Выжимка LLM не удалась: {exc})", "Кратко по страницам:"]
            for p in pages:
                snip = (p.get("snippet") or p["text"][:400]).strip()
                parts.append(f"- {p['title']}: {snip}")
            return "\n".join(parts)
