"""Monitors: a Set re-run on a schedule, reported only as *changes* with evidence.

  M1  A row that becomes a match is a NEW_MATCH; one that stops is a LOST_MATCH.
  M2  Any criterion whose status changes is a VERDICT change, with the new evidence.
  M3  An enriched value that changes is a FIELD change.
  M4  Rows that appear or disappear without affecting matches are not noise-worthy:
      only matches are announced for new rows.
  M5  Runs with different spec fingerprints are not compared (the question changed).
"""
from __future__ import annotations

from .domain import Change, ChangeKind, Run, SetSpec


def diff(prev: Run | None, cur: Run, spec: SetSpec) -> list[Change]:
    if prev is None or prev.spec_fingerprint != cur.spec_fingerprint:  # M5
        return []
    before = {r.key: r for r in prev.rows}
    out: list[Change] = []
    for row in cur.rows:
        old = before.get(row.key)
        now_match = row.is_match(spec)
        was_match = bool(old and old.is_match(spec))
        if now_match and not was_match:  # M1: cite what changed, not just any evidence
            flipped = [v for cid, v in row.verdicts.items() if old and cid in old.verdicts and old.verdicts[cid].status != v.status]
            ev = tuple(e for v in (flipped or list(row.verdicts.values())) for e in v.evidence[:1])
            out.append(Change(ChangeKind.NEW_MATCH, row.key, row.name, f"{row.name} now meets every required criterion.", evidence=ev))
        elif was_match and not now_match:
            failed = [cid for cid, v in row.verdicts.items() if v.status.value != "pass" and any(c.id == cid and c.required for c in spec.criteria)]
            out.append(Change(ChangeKind.LOST_MATCH, row.key, row.name, f"{row.name} no longer matches ({', '.join(failed)})."))
        if old is None:  # M4
            continue
        for cid, v in row.verdicts.items():  # M2
            ov = old.verdicts.get(cid)
            if ov and ov.status != v.status:
                label = next((c.label for c in spec.criteria if c.id == cid), cid)
                out.append(Change(ChangeKind.VERDICT, row.key, row.name, f"{label}: {ov.status.value} → {v.status.value}",
                                  criterion_id=cid, before=ov.status.value, after=v.status.value, evidence=tuple(v.evidence[:1])))
        for fid, f in row.fields.items():  # M3
            of = old.fields.get(fid)
            if of and of.value != f.value and (of.value or f.value):
                label = next((e.label for e in spec.enrich if e.id == fid), fid)
                out.append(Change(ChangeKind.FIELD, row.key, row.name, f"{label}: {of.value or '—'} → {f.value or '—'}",
                                  criterion_id=fid, before=of.value, after=f.value, evidence=tuple(f.evidence[:1])))
    order = {ChangeKind.NEW_MATCH: 0, ChangeKind.LOST_MATCH: 1, ChangeKind.VERDICT: 2, ChangeKind.FIELD: 3}
    return sorted(out, key=lambda c: (order[c.kind], c.name))


def summarize(changes: list[Change], spec: SetSpec) -> tuple[str, str]:
    news = [c for c in changes if c.kind is ChangeKind.NEW_MATCH]
    title = f"Assay, {spec.name}: " + (f"{len(news)} new match{'es' if len(news) != 1 else ''}" if news else (f"{len(changes)} change" + ("s" if len(changes) != 1 else "")))
    lines = []
    for c in changes:
        mark = {"new_match": "◆", "lost_match": "◇", "verdict": "•", "field": "·"}[c.kind.value]
        who = f"{c.name}, " if c.kind in (ChangeKind.VERDICT, ChangeKind.FIELD) else ""
        lines.append(f"{mark} {who}{c.detail}")
        if c.evidence:
            lines.append(f"    “{c.evidence[0].quote}” — {c.evidence[0].url}")
    return title, "\n".join(lines)
