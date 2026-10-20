"""Judges decide one criterion for one candidate from fetched passages.

RuleJudge  offline and deterministic: per sentence, `against` beats `signals`;
           recency criteria need a date in the same sentence. Evidence both ways = unclear.
ClaudeJudge a forced tool call that must return a verbatim quote and its URL.
Neither is trusted: the engine's receipt gate checks every quote against the page.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

from ..domain import Candidate, Criterion, Enrichment, Evidence, Field, Page, SetSpec, Status, Verdict
from ..text import context_around, dates_in, months_between, sentences


def _ev(page: Page, quote: str) -> Evidence:
    return Evidence(url=page.url, quote=quote, content_hash=page.content_hash, fetched_at=page.fetched_at,
                    context=context_around(page.text, quote))


class RuleJudge:
    name = "rules"

    async def judge(self, spec: SetSpec, candidate: Candidate, criterion: Criterion,
                    passages: list[tuple[Page, str]], now: datetime) -> Verdict:
        sig = [re.compile(p, re.I) for p in criterion.signals]
        neg = [re.compile(p, re.I) for p in criterion.against]
        pro: list[Evidence] = []
        con: list[Evidence] = []
        stale: list[tuple[Evidence, int]] = []
        undated: list[Evidence] = []
        name = re.compile(re.escape(candidate.name), re.I) if candidate.name else None
        for page in candidate.pages:  # rules are cheap: read every sentence, not just top passages
            for s in sentences(page.text):
                if len(s.split()) < 5:  # headings and labels are not evidence
                    continue
                probe = name.sub(" ", s) if name else s  # "Saral Loans" the name is not "offers loans"
                if any(p.search(probe) for p in neg):
                    con.append(_ev(page, s))
                elif any(p.search(probe) for p in sig):
                    if criterion.within_months is None:
                        pro.append(_ev(page, s))
                        continue
                    ds = dates_in(probe)
                    if not ds:
                        undated.append(_ev(page, s))
                        continue
                    age = months_between(max(ds), now)
                    if age <= criterion.within_months:
                        pro.append(_ev(page, s))
                    else:
                        stale.append((_ev(page, s), age))
        if pro and con:
            return Verdict(criterion.id, Status.UNCLEAR, "Pages contain evidence both ways.", pro[:1] + con[:1], 0.3)
        if pro:
            return Verdict(criterion.id, Status.PASS, ("One sentence on the fetched pages states this." if len(pro) == 1 else f"{len(pro)} sentences on the fetched pages state this."), pro[:2], 0.75)
        if con:
            return Verdict(criterion.id, Status.FAIL, "A page states the opposite.", con[:2], 0.75)
        if stale:
            ev, age = stale[0]
            return Verdict(criterion.id, Status.FAIL, f"The dated event is {age} months old; the window is {criterion.within_months}.",
                           [ev], 0.7)
        if undated:
            return Verdict(criterion.id, Status.UNCLEAR, "Mentioned, but no date to check against the window.", undated[:1], 0.4)
        return Verdict(criterion.id, Status.UNCLEAR, "No evidence on the fetched pages.", [], 0.0)

    async def enrich(self, spec: SetSpec, candidate: Candidate, enrichment: Enrichment,
                     passages: list[tuple[Page, str]]) -> Field:
        if not enrichment.pattern:
            return Field(enrichment.id, None)
        pat = re.compile(enrichment.pattern)
        for page in candidate.pages:
            for s in sentences(page.text):
                m = pat.search(s)
                if m:
                    return Field(enrichment.id, (m.group(1) if m.groups() else m.group(0)).strip(), [_ev(page, s)])
        return Field(enrichment.id, None)


VERDICT_TOOL = {
    "name": "record_verdict",
    "description": "Decide the criterion from the passages only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["pass", "fail", "unclear"]},
            "rationale": {"type": "string", "description": "One sentence"},
            "quote": {"type": ["string", "null"], "description": "Exact sentence copied from ONE passage; required for pass/fail"},
            "passage_id": {"type": ["string", "null"], "description": "The id of the passage the quote comes from, e.g. P3"},
            "confidence": {"type": "number"},
        },
        "required": ["status", "rationale", "confidence"],
    },
}
FIELD_TOOL = {
    "name": "record_field",
    "description": "Extract the field from the passages only.",
    "input_schema": {
        "type": "object",
        "properties": {
            "value": {"type": ["string", "null"], "description": "Short value exactly as written, or null if not stated"},
            "quote": {"type": ["string", "null"]},
            "passage_id": {"type": ["string", "null"]},
        },
        "required": ["value"],
    },
}
SYSTEM = """You verify facts about a {entity} for a research list. Today is {today}.
Answer ONLY from the numbered passages, which were fetched from the {entity}'s own site or reputable sources.
- pass/fail require a quote copied character-for-character from one passage, with its passage_id.
- If the passages don't settle it, answer "unclear". Never infer from the company's name or your memory.
- For time windows, use dates stated in the passages relative to today."""


class ClaudeJudge:
    name = "claude"

    def __init__(self, client=None, model: str | None = None):
        if client is None:
            import anthropic

            client = anthropic.AsyncAnthropic()
        self.client = client
        self.model = model or os.getenv("ASSAY_MODEL", "claude-sonnet-5-5")

    async def _call(self, spec: SetSpec, tool: dict, prompt: str, now: datetime) -> dict:
        resp = await self.client.messages.create(
            model=self.model, max_tokens=600,
            system=[{"type": "text", "text": SYSTEM.format(entity=spec.entity, today=now.strftime("%d %B %Y")),
                     "cache_control": {"type": "ephemeral"}}],
            tools=[tool], tool_choice={"type": "tool", "name": tool["name"]},
            messages=[{"role": "user", "content": prompt}],
        )
        block = next(b for b in resp.content if getattr(b, "type", "") == "tool_use")
        return block.input if isinstance(block.input, dict) else json.loads(block.input)

    @staticmethod
    def _render(candidate: Candidate, passages: list[tuple[Page, str]]) -> str:
        lines = [f"[P{i}] ({p.url}) {text}" for i, (p, text) in enumerate(passages, 1)]
        return f"{candidate.name} ({candidate.homepage})\n<passages>\n" + "\n".join(lines) + "\n</passages>"

    @staticmethod
    def _evidence(passages: list[tuple[Page, str]], pid: str | None, quote: str | None) -> list[Evidence]:
        if not quote or not pid:
            return []
        try:
            page, _ = passages[int(pid.strip().lstrip("Pp")) - 1]
        except (ValueError, IndexError):
            return []
        return [_ev(page, quote)]

    async def judge(self, spec, candidate, criterion, passages, now) -> Verdict:
        if not passages:
            return Verdict(criterion.id, Status.UNCLEAR, "No relevant passages fetched.")
        window = f" (window: last {criterion.within_months} months)" if criterion.within_months else ""
        d = await self._call(spec, VERDICT_TOOL, f"Criterion: {criterion.question}{window}\n\n{self._render(candidate, passages)}", now)
        return Verdict(criterion.id, Status(d.get("status", "unclear")), d.get("rationale", ""),
                       self._evidence(passages, d.get("passage_id"), d.get("quote")), float(d.get("confidence", 0)))

    async def enrich(self, spec, candidate, enrichment, passages) -> Field:
        if not passages:
            return Field(enrichment.id, None)
        d = await self._call(spec, FIELD_TOOL, f"Field: {enrichment.question}\n\n{self._render(candidate, passages)}", datetime.now())
        return Field(enrichment.id, d.get("value"), self._evidence(passages, d.get("passage_id"), d.get("quote")))
