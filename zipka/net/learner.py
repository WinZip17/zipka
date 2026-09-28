from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from zipka.config import Settings, get_settings
from zipka.memory.store import MemoryStore


class NetLearner:
    """Read-only самообучение по allowlist."""

    def __init__(
        self,
        llm: Any,
        memory: MemoryStore,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm
        self.memory = memory

    def learn(self, query: str) -> dict:
        if query.startswith("http://") or query.startswith("https://"):
            url = query
        else:
            # Wikipedia search fallback via topic page guess
            topic = query.strip().replace(" ", "_")
            url = f"https://ru.wikipedia.org/wiki/{topic}"
        host = urlparse(url).hostname or ""
        if not self._allowed(host):
            raise RuntimeError(
                f"Домен `{host}` не в allowlist. Разрешены: "
                + ", ".join(self.settings.net_allowlist)
            )
        text = self._fetch_text(url)
        summary = self.llm.summarize(
            text,
            instruction=(
                "Сделай краткую учебную выжимку для Зипки: факты, термины, "
                "что полезно запомнить. Без воды."
            ),
        )
        self.memory.add_note("net_learn", summary, meta={"url": url, "query": query})
        return {"url": url, "summary": summary, "chars": len(text)}

    def _allowed(self, host: str) -> bool:
        host = host.lower()
        for allowed in self.settings.net_allowlist:
            allowed = allowed.lower()
            if host == allowed or host.endswith("." + allowed):
                return True
        return False

    def _fetch_text(self, url: str) -> str:
        headers = {"User-Agent": "ZipkaLearner/0.1 (+local; read-only)"}
        with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers) as client:
            r = client.get(url)
            r.raise_for_status()
            content = r.content[: self.settings.zipka_net_max_bytes]
            ctype = r.headers.get("content-type", "")
            if "html" in ctype or url.endswith(".html"):
                soup = BeautifulSoup(content, "lxml")
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                return soup.get_text("\n", strip=True)[: self.settings.zipka_net_max_bytes]
            return content.decode("utf-8", errors="ignore")
