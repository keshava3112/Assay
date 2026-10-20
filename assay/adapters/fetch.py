"""Fetching the web politely, once.

HttpFetcher
  * robots.txt is honoured per host (cached for the run); disallowed URLs are skipped
  * one request at a time per host, with a minimum interval between them
  * HTML only, capped size, timeouts, bounded retries with backoff on 429/5xx
  * a content-addressed disk cache: fresh entries are served without a request;
    stale ones are revalidated with If-None-Match / If-Modified-Since (304 = keep)
CorpusFetcher serves the same Page shape from a local corpus snapshot.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

from ..domain import Page
from ..text import html_to_text
from .backends import Corpus

log = logging.getLogger(__name__)
USER_AGENT = "AssayBot/0.1 (+https://github.com/keshava3112/Assay)"
MAX_BYTES = 2_000_000


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class PageCache:
    def __init__(self, root: str | Path, ttl: timedelta = timedelta(days=3)):
        self.root, self.ttl = Path(root), ttl
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()
        return self.root / h[:2] / f"{h}.json"

    def get(self, url: str) -> dict | None:
        p = self._path(url)
        return json.loads(p.read_text()) if p.exists() else None

    def put(self, url: str, entry: dict) -> None:
        p = self._path(url)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(entry))
        tmp.replace(p)  # atomic: concurrent runs never read a half-written entry

    def fresh(self, entry: dict, now: datetime) -> bool:
        return now - datetime.fromisoformat(entry["fetched_at"]) < self.ttl


def _page_from(entry: dict, from_cache: bool) -> Page:
    return Page(url=entry["url"], status=entry["status"], title=entry["title"], text=entry["text"],
                content_hash=entry["content_hash"], fetched_at=entry["fetched_at"], links=tuple(entry.get("links", [])),
                from_cache=from_cache)


class HttpFetcher:
    def __init__(self, client: httpx.AsyncClient, cache: PageCache | None = None, min_interval: float = 1.0,
                 retries: int = 2, clock=_now):
        self.client, self.cache, self.min_interval, self.retries, self.clock = client, cache, min_interval, retries, clock
        self._robots: dict[str, RobotFileParser | None] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def _allowed(self, url: str) -> bool:
        u = urlparse(url)
        host = f"{u.scheme}://{u.netloc}"
        if host not in self._robots:
            rp = RobotFileParser()
            try:
                r = await self.client.get(f"{host}/robots.txt", headers={"User-Agent": USER_AGENT}, timeout=10)
                if r.status_code == 200:
                    rp.parse(r.text.splitlines())
                    self._robots[host] = rp
                else:
                    self._robots[host] = None  # no robots.txt: allowed
            except httpx.HTTPError:
                self._robots[host] = None
        rp = self._robots[host]
        return rp is None or rp.can_fetch(USER_AGENT, url)

    async def _polite_get(self, url: str, headers: dict) -> httpx.Response | None:
        host = urlparse(url).netloc
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:  # serialise per host
            wait = self.min_interval - (time.monotonic() - self._last.get(host, 0))
            if wait > 0:
                await asyncio.sleep(wait)
            for attempt in range(self.retries + 1):
                try:
                    r = await self.client.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html", **headers},
                                              timeout=20, follow_redirects=True)
                except httpx.HTTPError as e:
                    log.info("fetch %s failed: %s", url, e)
                    r = None
                self._last[host] = time.monotonic()
                if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                    return r
                if attempt < self.retries:
                    await asyncio.sleep(min(8.0, 0.5 * 2 ** attempt))
            return r

    async def fetch(self, url: str) -> Page | None:
        now = self.clock()
        cached = self.cache.get(url) if self.cache else None
        if cached and self.cache.fresh(cached, now):
            return _page_from(cached, True)
        if not await self._allowed(url):
            log.info("robots.txt disallows %s", url)
            return None
        headers = {}
        if cached:
            if cached.get("etag"):
                headers["If-None-Match"] = cached["etag"]
            if cached.get("last_modified"):
                headers["If-Modified-Since"] = cached["last_modified"]
        r = await self._polite_get(url, headers)
        if r is None:
            return _page_from(cached, True) if cached else None
        if r.status_code == 304 and cached:
            cached["fetched_at"] = now.isoformat()
            self.cache.put(url, cached)
            return _page_from(cached, True)
        ctype = r.headers.get("content-type", "")
        if r.status_code != 200 or "html" not in ctype or len(r.content) > MAX_BYTES:
            return None
        title, text, links = html_to_text(r.text, str(r.url))
        entry = {"url": url, "status": 200, "title": title, "text": text, "links": links[:200],
                 "content_hash": Page.hash_text(text), "fetched_at": now.isoformat(),
                 "etag": r.headers.get("etag"), "last_modified": r.headers.get("last-modified")}
        if self.cache:
            self.cache.put(url, entry)
        return _page_from(entry, False)


class CorpusFetcher:
    def __init__(self, corpus: Corpus):
        self.corpus = corpus

    async def fetch(self, url: str) -> Page | None:
        html = self.corpus.html(url)
        if html is None:
            return None
        title, text, links = html_to_text(html, url)
        return Page(url=url, status=200, title=title, text=text, content_hash=Page.hash_text(text),
                    fetched_at=self.corpus.fetched_at, links=tuple(links))
