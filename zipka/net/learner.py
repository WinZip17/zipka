from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from zipka.config import Settings, get_settings
from zipka.memory.store import MemoryStore

_URL_RE = re.compile(
    r"https?://[^\s<>\"')\]]+",
    re.IGNORECASE,
)

_PRIVATE_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "0.0.0.0",
    "::1",
}


class NetLearner:
    """Чтение страниц по URL (чат) и самообучение по allowlist."""

    def __init__(
        self,
        llm: Any,
        memory: MemoryStore,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.memory = memory

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for raw in _URL_RE.findall(text or ""):
            url = raw.rstrip(".,;:!?)]}>\"'")
            if url.lower() in seen:
                continue
            seen.add(url.lower())
            found.append(url)
        return found

    def learn(self, query: str) -> dict:
        if query.startswith("http://") or query.startswith("https://"):
            url = query.strip()
        else:
            topic = query.strip().replace(" ", "_")
            url = f"https://ru.wikipedia.org/wiki/{topic}"
        self._assert_allowed_host(url)
        return self.read_url(url, mode="learn", enforce_allowlist=True)

    def read_url(
        self,
        url: str,
        *,
        mode: str = "chat",
        enforce_allowlist: bool = False,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Скачать страницу, сделать выжимку, сохранить заметку."""
        url = (url or "").strip()
        self._assert_safe_url(url)
        if enforce_allowlist:
            self._assert_allowed_host(url)

        text = self._fetch_text(url)
        if len(text.strip()) < 40:
            raise RuntimeError(
                f"По ссылке мало текста (возможно, JS-страница или пустая): {url}"
            )

        instruction = (
            "Сделай краткую выжимку статьи/страницы для Зипки: о чём текст, "
            "ключевые факты, полезные выводы. Без воды, по-русски."
        )
        if comment:
            instruction += f"\nУчти комментарий читателя: {comment}"
        if mode == "learn":
            instruction = (
                "Сделай краткую учебную выжимку для Зипки: факты, термины, "
                "что полезно запомнить. Без воды."
            )

        summary = self.llm.summarize(text, instruction=instruction)
        title = self._guess_title(text) or url
        note_kind = "net_read" if mode == "chat" else "net_learn"
        self.memory.add_note(
            note_kind,
            summary,
            meta={"url": url, "title": title, "chars": len(text), "mode": mode},
        )
        # короткий снимок исходника в books/notes для «прочитала»
        digest_path = self._store_digest(url=url, title=title, text=text, summary=summary)
        return {
            "url": url,
            "title": title,
            "summary": summary,
            "chars": len(text),
            "digest_path": str(digest_path) if digest_path else None,
        }

    def _store_digest(
        self,
        *,
        url: str,
        title: str,
        text: str,
        summary: str,
    ) -> Any:
        try:
            ensure = getattr(self.memory, "settings", None) or self.settings
            from zipka.config import ensure_data_dirs

            base = ensure_data_dirs(ensure) / "books" / "notes"
            base.mkdir(parents=True, exist_ok=True)
            host = (urlparse(url).hostname or "page").replace(".", "_")
            safe = re.sub(r"[^\w\-]+", "_", host)[:40]
            path = base / f"url_{safe}.md"
            body = (
                f"# {title}\n\n"
                f"Источник: {url}\n\n"
                f"## Выжимка\n\n{summary}\n\n"
                f"## Текст (обрезка)\n\n{text[:12000]}\n"
            )
            path.write_text(body, encoding="utf-8")
            return path
        except Exception:
            return None

    @staticmethod
    def _guess_title(text: str) -> str:
        for line in (text or "").splitlines():
            s = line.strip()
            if 12 <= len(s) <= 160:
                return s
        return ""

    def _assert_allowed_host(self, url: str) -> None:
        host = urlparse(url).hostname or ""
        if not self._allowed(host):
            raise RuntimeError(
                f"Домен `{host}` не в allowlist. Разрешены: "
                + ", ".join(self.settings.net_allowlist)
            )

    def _allowed(self, host: str) -> bool:
        host = host.lower()
        for allowed in self.settings.net_allowlist:
            allowed = allowed.lower()
            if host == allowed or host.endswith("." + allowed):
                return True
        return False

    def _assert_safe_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise RuntimeError("Только http/https ссылки.")
        host = (parsed.hostname or "").lower()
        if not host or host in _PRIVATE_HOSTS or host.endswith(".local"):
            raise RuntimeError(f"Локальный/служебный хост запрещён: {host or '—'}")
        # блокируем явные IP в приватных диапазонах
        try:
            ip = ipaddress.ip_address(host)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                raise RuntimeError(f"Приватный/служебный адрес запрещён: {host}")
        except ValueError:
            # hostname — проверяем DNS на приватные A/AAAA
            self._assert_public_dns(host)

    def _assert_public_dns(self, host: str) -> None:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            raise RuntimeError(f"Не удалось разрешить хост `{host}`: {exc}") from exc
        for info in infos:
            addr = info[4][0]
            try:
                ip = ipaddress.ip_address(addr)
            except ValueError:
                continue
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                raise RuntimeError(
                    f"Хост `{host}` резолвится в служебный адрес {addr} — не читаю."
                )

    def _fetch_text(self, url: str) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (compatible; Zipka/0.2; +local; read-only; "
                "https://github.com/)"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.7",
            "Accept-Language": "ru,en;q=0.8",
        }
        max_bytes = int(self.settings.zipka_net_max_bytes or 500_000)
        with httpx.Client(timeout=45.0, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            r.raise_for_status()
            # после редиректа ещё раз safety на финальный URL
            final = str(r.url)
            if final != url:
                self._assert_safe_url(final)
            content = r.content[:max_bytes]
            ctype = (r.headers.get("content-type") or "").lower()
            if (
                "html" in ctype
                or final.endswith((".html", ".htm"))
                or content[:32].lstrip().lower().startswith((b"<!doctype", b"<html"))
            ):
                return self._html_to_text(content)[:max_bytes]
            return content.decode("utf-8", errors="ignore")[:max_bytes]

    def _html_to_text(self, content: bytes) -> str:
        soup = BeautifulSoup(content, "lxml")
        for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
            tag.decompose()
        for tag in soup.find_all(["nav", "footer", "aside", "header", "form"]):
            tag.decompose()

        root = None
        selectors = [
            ("article", {}),
            ("main", {}),
            (True, {"itemprop": "articleBody"}),
            (True, {"class": re.compile(r"(article|post|content|entry)[-_]?(body|content|text)?", re.I)}),
            ("div", {"class": re.compile(r"tm-article-body", re.I)}),  # Habr
        ]
        for name, attrs in selectors:
            found = soup.find(name, attrs) if attrs else soup.find(name)
            if found and len(found.get_text(" ", strip=True)) > 200:
                root = found
                break
        if root is None:
            root = soup.body or soup

        title = ""
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        h1 = root.find("h1") if root else None
        if h1:
            title = h1.get_text(" ", strip=True) or title

        text = root.get_text("\n", strip=True)
        # ужимаем пустые строки
        lines = [ln.strip() for ln in text.splitlines()]
        compact = "\n".join(ln for ln in lines if ln)
        if title and title not in compact[:200]:
            compact = f"{title}\n\n{compact}"
        return compact
