"""Load a Set from YAML.

    id: india-lending-series-a
    name: Indian lending fintechs, Series A in the last 18 months
    entity: company
    query: Indian fintech startups offering loans or credit products
    backends: [corpus]            # corpus | exa | brave | searxng
    lead_sources: [fintechpulse.example]   # publishers: mined for outbound company links
    criteria:
      - id: india
        label: Headquartered in India
        question: Is the company headquartered in India?
        signals: ['headquartered in (Bengaluru|Mumbai|India)']
        against: ['headquartered in (Singapore|London)']
      - id: series_a
        label: Series A ≤ 18 months
        question: Did the company raise a Series A in the last 18 months?
        signals: ['\\bSeries A\\b']
        within_months: 18
    enrich:
      - {id: hq, label: HQ, question: Which city is the company headquartered in?, pattern: 'headquartered in ([A-Z][a-z]+)'}
    monitor: {every: 1d}
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .domain import Criterion, Enrichment, SetSpec


class SpecError(ValueError):
    pass


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def load_spec(path: str | Path) -> tuple[SetSpec, tuple[str, ...]]:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return parse_spec(data), tuple(data.get("lead_sources") or ())


def parse_spec(data: dict) -> SetSpec:
    for key in ("name", "query", "criteria"):
        if not data.get(key):
            raise SpecError(f"set spec needs '{key}'")
    criteria = []
    for c in data["criteria"]:
        for pat in [*(c.get("signals") or []), *(c.get("against") or [])]:
            try:
                re.compile(pat)
            except re.error as e:
                raise SpecError(f"criterion {c.get('id')}: bad regex {pat!r}: {e}") from e
        criteria.append(Criterion(
            id=c["id"], label=c.get("label", c["id"]), question=c.get("question", c.get("label", c["id"])),
            required=bool(c.get("required", True)), signals=tuple(c.get("signals") or ()),
            against=tuple(c.get("against") or ()), within_months=c.get("within_months"),
        ))
    ids = [c.id for c in criteria]
    if len(ids) != len(set(ids)):
        raise SpecError("criterion ids must be unique")
    enrich = tuple(Enrichment(id=e["id"], label=e.get("label", e["id"]), question=e.get("question", e["id"]),
                              pattern=e.get("pattern")) for e in (data.get("enrich") or []))
    return SetSpec(
        id=data.get("id") or _slug(data["name"]), name=data["name"], entity=data.get("entity", "company"),
        query=data["query"], criteria=tuple(criteria), enrich=enrich,
        backends=tuple(data.get("backends") or ("corpus",)), limit=int(data.get("limit", 25)),
        pages_per_candidate=int(data.get("pages_per_candidate", 4)), description=data.get("description", ""),
        monitor_every=(data.get("monitor") or {}).get("every"),
    )
