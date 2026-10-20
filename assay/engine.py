"""The run pipeline.

    search ─► resolve ─► fetch ─► passages ─► judge ─► gate ─► rows
       (all backends      (one-hop discovery,     (bounded      (receipt
        in parallel)       polite, cached)         concurrency)   gate)

Design notes
  * Every stage emits an Event. The UI streams them (SSE); the store keeps them,
    so a finished run can be replayed exactly, which is how the static demo animates.
  * Concurrency is bounded per stage (fetch, judge), never globally unbounded.
  * A Budget caps pages and judge calls. Hitting it ends the run cleanly with
    whatever is proven so far; nothing is silently guessed.
  * Candidates are keyed by registrable domain, so a company found via its homepage,
    a press page and a news article is one row, not three.
  * Lead sources (publishers) are never candidates: their outbound links are mined
    to discover the companies they write about.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .domain import Candidate, Evidence, Field, Hit, Row, Run, RunStats, SetSpec, Status, Verdict
from .gate import check_field, check_verdict
from .ports import Fetcher, Judge, SearchBackend
from .text import registrable_domain, same_site, top_passages

Emit = Callable[[str, dict], Awaitable[None] | None]
DISCOVER = re.compile(r"/(about|company|press|news|blog|security|trust|compliance|pricing|products?|careers|investors?)\b", re.I)


@dataclass
class Budget:
    max_pages: int = 200
    max_judge_calls: int = 400
    pages: int = 0
    judge_calls: int = 0

    def take_page(self) -> bool:
        if self.pages >= self.max_pages:
            return False
        self.pages += 1
        return True

    def take_judge(self) -> bool:
        if self.judge_calls >= self.max_judge_calls:
            return False
        self.judge_calls += 1
        return True


@dataclass
class Engine:
    backends: list[SearchBackend]
    fetcher: Fetcher
    judge: Judge
    lead_sources: tuple[str, ...] = ()
    fetch_concurrency: int = 6
    judge_concurrency: int = 8
    budget: Budget = field(default_factory=Budget)
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)

    async def run(self, spec: SetSpec, emit: Emit | None = None, run_id: str | None = None) -> Run:
        t0 = time.monotonic()
        now = self.clock()
        run = Run(id=run_id or uuid.uuid4().hex[:12], set_id=spec.id, started_at=now.isoformat(), finished_at=None,
                  spec_fingerprint=spec.fingerprint)
        stats = run.stats

        async def say(kind: str, **data):
            if emit:
                r = emit(kind, data)
                if asyncio.iscoroutine(r):
                    await r

        await say("run.started", run_id=run.id, set=spec.name, query=spec.query, backends=[b.name for b in self.backends])

        # 1. search every backend in parallel; one failing backend never sinks the run
        results = await asyncio.gather(*(b.search(spec.query, spec.limit * 2) for b in self.backends), return_exceptions=True)
        hits: list[Hit] = []
        for b, res in zip(self.backends, results):
            if isinstance(res, Exception):
                await say("backend.error", backend=b.name, error=str(res))
                continue
            hits.extend(res)
        stats.searched = len(hits)
        await say("search.done", hits=len(hits))

        # 2. resolve hits into candidates (and mine lead sources for outbound company links)
        fetch_sem = asyncio.Semaphore(self.fetch_concurrency)
        candidates = await self._resolve(spec, hits, fetch_sem, say)
        stats.candidates = len(candidates)

        # 3. fetch each candidate's pages, with one-hop discovery on its own site
        await asyncio.gather(*(self._gather_pages(spec, c, fetch_sem, stats, say) for c in candidates))

        # 4. judge every criterion and enrichment, gate, assemble rows
        judge_sem = asyncio.Semaphore(self.judge_concurrency)
        rows = await asyncio.gather(*(self._row(spec, c, judge_sem, stats, now, say) for c in candidates))
        run.rows = sorted(rows, key=lambda r: (-r.is_match(spec), -r.score(spec), r.name.lower()))
        stats.matches = sum(r.is_match(spec) for r in run.rows)
        stats.seconds = round(time.monotonic() - t0, 2)
        run.finished_at = self.clock().isoformat()
        await say("run.finished", matches=stats.matches, candidates=stats.candidates, seconds=stats.seconds,
                  budget_exhausted=self.budget.pages >= self.budget.max_pages or self.budget.judge_calls >= self.budget.max_judge_calls)
        return run

    # ------------------------------------------------------------ resolve
    def _is_lead_source(self, url: str) -> bool:
        return registrable_domain(url) in {registrable_domain("https://" + d) for d in self.lead_sources}

    async def _resolve(self, spec: SetSpec, hits: list[Hit], sem: asyncio.Semaphore, say) -> list[Candidate]:
        by_key: dict[str, Candidate] = {}
        order: list[str] = []

        def add(url: str, hit: Hit | None):
            key = registrable_domain(url)
            if not key or self._is_lead_source(url):
                return
            if key not in by_key:
                by_key[key] = Candidate(key=key, name="", homepage=f"https://{key}")
                order.append(key)
            if hit:
                by_key[key].hits.append(hit)

        leads = []
        for h in sorted(hits, key=lambda h: h.rank):
            if self._is_lead_source(h.url):
                leads.append(h)
            else:
                add(h.url, h)
        for lead in leads:  # a publisher page: its outbound links are the companies it covers
            async with sem:
                page = await self.fetcher.fetch(lead.url)
            if page:
                for link in page.links:
                    if not same_site(link, lead.url) and not self._is_lead_source(link):
                        add(link, None)
        cands = [by_key[k] for k in order][: spec.limit]
        for c in cands:
            await say("candidate.found", key=c.key)
        return cands

    async def _gather_pages(self, spec: SetSpec, c: Candidate, sem: asyncio.Semaphore, stats: RunStats, say) -> None:
        queue = [c.homepage] + [h.url for h in c.hits]
        seen: set[str] = set()
        while queue and len(c.pages) < spec.pages_per_candidate:
            url = queue.pop(0).rstrip("/")
            if url in seen or not same_site(url, c.homepage):
                continue
            seen.add(url)
            if not self.budget.take_page():
                break
            async with sem:
                page = await self.fetcher.fetch(url)
            if page is None:
                continue
            c.pages.append(page)
            stats.pages_fetched += not page.from_cache
            stats.pages_cached += page.from_cache
            if url == c.homepage.rstrip("/") or not c.name:
                c.name = c.name or _name_from(page.title, c.key)
            # one hop: prefer the pages where facts usually live
            found = [l for l in page.links if same_site(l, c.homepage) and DISCOVER.search(l) and l.rstrip("/") not in seen]
            queue.extend(found)
        c.name = c.name or _name_from("", c.key)
        await say("candidate.fetched", key=c.key, name=c.name, pages=len(c.pages))

    # -------------------------------------------------------------- judge
    async def _row(self, spec: SetSpec, c: Candidate, sem: asyncio.Semaphore, stats: RunStats, now: datetime, say) -> Row:
        docs = [(p, p.text) for p in c.pages]

        async def one(criterion) -> Verdict:
            passages = top_passages(docs, f"{criterion.label} {criterion.question}", k=6)
            if not self.budget.take_judge():
                return Verdict(criterion.id, Status.UNCLEAR, "Budget exhausted before this check.")
            async with sem:
                stats.judge_calls += 1
                v = await self.judge.judge(spec, c, criterion, passages, now)
            checked = check_verdict(v, c)
            if checked.gated:
                stats.gated += 1
            await say("verdict", key=c.key, name=c.name, criterion=criterion.id, status=checked.status.value,
                      quote=(checked.evidence[0].quote if checked.evidence else None), gated=checked.gated or None)
            return checked

        async def field_(e) -> Field:
            passages = top_passages(docs, e.question, k=4)
            if not self.budget.take_judge():
                return Field(e.id, None)
            async with sem:
                stats.judge_calls += 1
                f = await self.judge.enrich(spec, c, e, passages)
            return check_field(f, c)

        verdicts = await asyncio.gather(*(one(cr) for cr in spec.criteria))
        fields = await asyncio.gather(*(field_(e) for e in spec.enrich))
        row = Row(key=c.key, name=c.name, homepage=c.homepage, verdicts={v.criterion_id: v for v in verdicts},
                  fields={f.enrichment_id: f for f in fields})
        await say("row.done", key=c.key, name=c.name, match=row.is_match(spec), score=round(row.score(spec), 2))
        return row


SEPARATORS = re.compile(r"\s+[|\-–—:·]\s+")


def _name_from(title: str, key: str) -> str:
    """Brand from a page title: 'Kosha Credit — Working capital…' or 'Some article — Chai & Code'."""
    parts = [p.strip() for p in SEPARATORS.split(title.strip())] if title else []
    label = key.split(".")[0].lower()
    for p in parts:  # the part that looks like the domain is the brand
        if p and p.lower().replace(" ", "").replace("&", "and").startswith(label[:5]):
            return p
    if parts and len(parts[0]) <= 32:
        return parts[0]
    if len(parts) > 1 and len(parts[-1]) <= 32:
        return parts[-1]
    return label.replace("-", " ").title()
