from datetime import datetime, timedelta, timezone

import httpx
from conftest import run

from assay.adapters.fetch import HttpFetcher, PageCache

HTML = "<html><head><title>Kosha</title></head><body><p>Kosha Credit is headquartered in Bengaluru.</p></body></html>"


class Clock:
    def __init__(self):
        self.t = datetime(2026, 10, 19, 9, tzinfo=timezone.utc)

    def __call__(self):
        return self.t


def fetcher(handler, tmp_path, clock=None, **kw):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HttpFetcher(client, PageCache(tmp_path / "pages"), min_interval=0, clock=clock or Clock(), **kw)


def html(status=200, headers=None, body=HTML):
    return httpx.Response(status, headers={"content-type": "text/html; charset=utf-8", **(headers or {})}, text=body)


def test_robots_txt_is_honoured(tmp_path):
    seen = []

    def handler(req):
        seen.append(req.url.path)
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /private\n")
        return html()

    f = fetcher(handler, tmp_path)
    assert run(f.fetch("https://kosha.example/private/deck")) is None
    page = run(f.fetch("https://kosha.example/about"))
    assert page and "Bengaluru" in page.text and page.title == "Kosha"
    assert seen.count("/robots.txt") == 1 and "/private/deck" not in seen


def test_cache_serves_fresh_then_revalidates_with_304(tmp_path):
    hits, clock = [], Clock()

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        hits.append(dict(req.headers))
        if req.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return html(headers={"etag": '"v1"'})

    f = fetcher(handler, tmp_path, clock)
    first = run(f.fetch("https://kosha.example/"))
    assert not first.from_cache and len(hits) == 1
    again = run(f.fetch("https://kosha.example/"))
    assert again.from_cache and len(hits) == 1  # fresh: no request at all
    clock.t += timedelta(days=4)
    third = run(f.fetch("https://kosha.example/"))
    assert len(hits) == 2 and hits[1]["if-none-match"] == '"v1"'
    assert third.from_cache and third.content_hash == first.content_hash


def test_retries_on_429_then_succeeds(tmp_path, monkeypatch):
    calls = []

    async def no_sleep(_):
        return None

    monkeypatch.setattr("assay.adapters.fetch.asyncio.sleep", no_sleep)

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(1)
        return httpx.Response(429) if len(calls) < 3 else html()

    page = run(fetcher(handler, tmp_path, retries=2).fetch("https://kosha.example/"))
    assert page is not None and len(calls) == 3


def test_rejects_non_html(tmp_path):
    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF")

    assert run(fetcher(handler, tmp_path).fetch("https://kosha.example/deck.pdf")) is None


def test_network_error_falls_back_to_stale_cache(tmp_path, monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr("assay.adapters.fetch.asyncio.sleep", no_sleep)
    clock, up = Clock(), {"ok": True}

    def handler(req):
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if not up["ok"]:
            raise httpx.ConnectError("down")
        return html()

    f = fetcher(handler, tmp_path, clock)
    assert run(f.fetch("https://kosha.example/"))
    up["ok"], clock.t = False, clock.t + timedelta(days=5)
    page = run(f.fetch("https://kosha.example/"))
    assert page and page.from_cache
