"""The receipt gate. The engine's only source of truth about whether a verdict counts.

  G1  pass/fail needs at least one piece of evidence.
  G2  Every quote must appear verbatim (whitespace, quote-style and case aside) in the
      text of the page it cites.
  G3  The evidence's content hash must match the page we actually fetched, so a quote
      can never outlive the page version it came from.
  G4  An enriched value must appear inside its own quote.
A verdict that fails the gate is not deleted. It is downgraded to `unclear`, with the
reason recorded, because "we couldn't prove it" is itself useful information.
"""
from __future__ import annotations

from dataclasses import replace

from .domain import Candidate, Field, Status, Verdict
from .text import contains_verbatim, norm


def check_verdict(v: Verdict, candidate: Candidate) -> Verdict:
    if v.status is Status.UNCLEAR:
        return v
    pages = {p.url: p for p in candidate.pages}
    if not v.evidence:
        return replace(v, status=Status.UNCLEAR, gated="G1: no evidence for a definite verdict", confidence=0.0)
    for e in v.evidence:
        page = pages.get(e.url)
        if page is None:
            return replace(v, status=Status.UNCLEAR, gated=f"G2: cites a page that wasn't fetched ({e.url})", evidence=[])
        if not contains_verbatim(page.text, e.quote):
            return replace(v, status=Status.UNCLEAR, gated="G2: quote is not verbatim on the cited page", evidence=[])
        if e.content_hash != page.content_hash:
            return replace(v, status=Status.UNCLEAR, gated="G3: evidence is from a different version of the page", evidence=[])
    return v


def check_field(f: Field, candidate: Candidate) -> Field:
    if f.value is None:
        return f
    pages = {p.url: p for p in candidate.pages}
    for e in f.evidence:
        page = pages.get(e.url)
        if page and contains_verbatim(page.text, e.quote) and norm(f.value) in norm(e.quote) and e.content_hash == page.content_hash:
            return f
    return Field(f.enrichment_id, None, [])  # G4
