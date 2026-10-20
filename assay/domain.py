"""The domain. Plain, immutable-by-convention data; no I/O, no frameworks.

A *Set* is a standing question about the world ("Indian lending fintechs that raised
a Series A in the last 18 months"). A *Run* answers it at a point in time: it finds
*Candidates*, fetches their *Pages*, and asks a *Judge* for a *Verdict* on every
criterion. A verdict only counts if it carries *Evidence*: a quote that appears
verbatim in a page whose content hash we recorded. Monitors diff consecutive runs
into *Changes*.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    UNCLEAR = "unclear"


@dataclass(frozen=True)
class Criterion:
    id: str
    label: str
    question: str
    required: bool = True
    signals: tuple[str, ...] = ()  # regexes for the offline judge: evidence that it holds
    against: tuple[str, ...] = ()  # regexes: evidence that it does not
    within_months: int | None = None  # recency: the dated event must fall inside this window


@dataclass(frozen=True)
class Enrichment:
    id: str
    label: str
    question: str
    pattern: str | None = None  # regex with one group, for the offline judge


@dataclass(frozen=True)
class SetSpec:
    id: str
    name: str
    entity: str
    query: str
    criteria: tuple[Criterion, ...]
    enrich: tuple[Enrichment, ...] = ()
    backends: tuple[str, ...] = ("corpus",)
    limit: int = 25
    pages_per_candidate: int = 4
    description: str = ""
    monitor_every: str | None = None  # "1d", "6h"…

    @property
    def fingerprint(self) -> str:
        """Changes to the question invalidate cached verdicts; cosmetic edits don't."""
        payload = repr((self.query, self.criteria, self.enrich, self.entity))
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass(frozen=True)
class Hit:
    url: str
    title: str
    snippet: str = ""
    backend: str = ""
    rank: int = 0


@dataclass(frozen=True)
class Page:
    url: str
    status: int
    title: str
    text: str
    content_hash: str
    fetched_at: str
    links: tuple[str, ...] = ()
    from_cache: bool = False

    @staticmethod
    def hash_text(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class Candidate:
    key: str  # canonical identity: registrable domain
    name: str
    homepage: str
    hits: list[Hit] = field(default_factory=list)
    pages: list[Page] = field(default_factory=list)


@dataclass(frozen=True)
class Evidence:
    url: str
    quote: str
    content_hash: str
    fetched_at: str
    context: str = ""  # surrounding text, for display


@dataclass
class Verdict:
    criterion_id: str
    status: Status
    rationale: str = ""
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    gated: str = ""  # why the receipt gate changed this verdict, if it did


@dataclass
class Field:
    enrichment_id: str
    value: str | None
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Row:
    key: str
    name: str
    homepage: str
    verdicts: dict[str, Verdict]
    fields: dict[str, Field]

    def score(self, spec: SetSpec) -> float:
        req = [c for c in spec.criteria if c.required] or list(spec.criteria)
        return sum(self.verdicts[c.id].status is Status.PASS for c in req if c.id in self.verdicts) / max(1, len(req))

    def is_match(self, spec: SetSpec) -> bool:
        return all(self.verdicts.get(c.id) and self.verdicts[c.id].status is Status.PASS for c in spec.criteria if c.required)


class ChangeKind(str, Enum):
    NEW_MATCH = "new_match"
    LOST_MATCH = "lost_match"
    VERDICT = "verdict"
    FIELD = "field"


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    key: str
    name: str
    detail: str
    criterion_id: str | None = None
    before: str | None = None
    after: str | None = None
    evidence: tuple[Evidence, ...] = ()


@dataclass
class RunStats:
    searched: int = 0
    candidates: int = 0
    pages_fetched: int = 0
    pages_cached: int = 0
    judge_calls: int = 0
    gated: int = 0
    matches: int = 0
    seconds: float = 0.0


@dataclass
class Run:
    id: str
    set_id: str
    started_at: str
    finished_at: str | None
    spec_fingerprint: str
    rows: list[Row] = field(default_factory=list)
    stats: RunStats = field(default_factory=RunStats)
    changes: list[Change] = field(default_factory=list)


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return obj.value
    if hasattr(obj, "__dataclass_fields__"):
        return {k: to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj
