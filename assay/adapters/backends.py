"""Search backends. Each turns a query into ranked Hits; none of them is trusted for facts.

    corpus   a local folder of pages (the demo, or your own saved pages)
    exa      https://exa.ai            EXA_API_KEY
    brave    https://brave.com/search  BRAVE_API_KEY
    searxng  your own SearXNG          SEARXNG_URL
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import yaml

from ..domain import Hit
from ..text import html_to_text, top_passages


class BackendError(RuntimeError):
    pass


class Corpus:
    """A snapshot of a small web: corpus.yaml maps URL -> HTML file. Also serves as a Fetcher source."""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        manifest = yaml.safe_load((self.root / "corpus.yaml").read_text()) or {}
        self.pages: dict[str, Path] = {url: self.root / f for url, f in (manifest.get("pages") or {}).items()}
        self.fetched_at = str(manifest.get("captured", "2026-01-01T00:00:00Z"))

    def html(self, url: str) -> str | None:
        p = self.pages.get(url.rstrip("/")) or self.pages.get(url)
        return p.read_text() if p and p.exists() else None


class CorpusBackend:
    name = "corpus"

    def __init__(self, corpus: Corpus):
        self.corpus = corpus
        self._docs: list[tuple[str, str]] | None = None

    def _index(self) -> list[tuple[str, str]]:
        if self._docs is None:
            self._docs = []
            for url in self.corpus.pages:
                title, text, _ = html_to_text(self.corpus.html(url) or "", url)
                self._docs.append((url, f"{title}\n{text}"))
        return self._docs

    async def search(self, query: str, limit: int) -> list[Hit]:
        ranked = top_passages(self._index(), query, k=limit * 3, window=3)
        hits, seen = [], set()
        for url, passage in ranked:
            if url in seen:
                continue
            seen.add(url)
            hits.append(Hit(url=url, title=passage.split("\n")[0][:120], snippet=passage[:240], backend=self.name, rank=len(hits)))
            if len(hits) >= limit:
                break
        return hits


class ExaBackend:
    name = "exa"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None):
        self.client, self.key = client, api_key or os.getenv("EXA_API_KEY")
        if not self.key:
            raise BackendError("exa backend needs EXA_API_KEY")

    async def search(self, query: str, limit: int) -> list[Hit]:
        r = await self.client.post("https://api.exa.ai/search", headers={"x-api-key": self.key},
                                   json={"query": query, "numResults": min(limit, 100), "type": "auto"})
        if r.status_code >= 400:
            raise BackendError(f"exa: HTTP {r.status_code}")
        return [Hit(url=x["url"], title=x.get("title") or "", snippet=(x.get("text") or "")[:240], backend=self.name, rank=i)
                for i, x in enumerate(r.json().get("results", []))]


class BraveBackend:
    name = "brave"

    def __init__(self, client: httpx.AsyncClient, api_key: str | None = None):
        self.client, self.key = client, api_key or os.getenv("BRAVE_API_KEY")
        if not self.key:
            raise BackendError("brave backend needs BRAVE_API_KEY")

    async def search(self, query: str, limit: int) -> list[Hit]:
        r = await self.client.get("https://api.search.brave.com/res/v1/web/search",
                                  params={"q": query, "count": min(limit, 20)},
                                  headers={"X-Subscription-Token": self.key, "Accept": "application/json"})
        if r.status_code >= 400:
            raise BackendError(f"brave: HTTP {r.status_code}")
        return [Hit(url=x["url"], title=x.get("title") or "", snippet=x.get("description") or "", backend=self.name, rank=i)
                for i, x in enumerate((r.json().get("web") or {}).get("results", []))]


class SearxngBackend:
    name = "searxng"

    def __init__(self, client: httpx.AsyncClient, base_url: str | None = None):
        self.client, self.base = client, (base_url or os.getenv("SEARXNG_URL") or "").rstrip("/")
        if not self.base:
            raise BackendError("searxng backend needs SEARXNG_URL")

    async def search(self, query: str, limit: int) -> list[Hit]:
        r = await self.client.get(f"{self.base}/search", params={"q": query, "format": "json"})
        if r.status_code >= 400:
            raise BackendError(f"searxng: HTTP {r.status_code}")
        return [Hit(url=x["url"], title=x.get("title") or "", snippet=x.get("content") or "", backend=self.name, rank=i)
                for i, x in enumerate(r.json().get("results", [])[:limit])]


def make_backends(names: tuple[str, ...], client: httpx.AsyncClient, corpus: Corpus | None = None) -> list:
    out = []
    for n in names:
        if n == "corpus":
            if corpus is None:
                raise BackendError("corpus backend needs --corpus DIR")
            out.append(CorpusBackend(corpus))
        elif n == "exa":
            out.append(ExaBackend(client))
        elif n == "brave":
            out.append(BraveBackend(client))
        elif n == "searxng":
            out.append(SearxngBackend(client))
        else:
            raise BackendError(f"unknown backend {n!r}")
    return out
