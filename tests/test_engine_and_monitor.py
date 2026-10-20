from dataclasses import replace

from conftest import AUG, make_engine, run

from assay.domain import ChangeKind, Status
from assay.engine import Budget
from assay.monitor import diff, summarize


def rows(r):
    return {row.name: row for row in r.rows}


def test_august_snapshot_matches(spec, aug_run):
    matches = sorted(row.name for row in aug_run.rows if row.is_match(spec))
    assert matches == ["Kosha Credit", "Mitra Money", "Saral Loans"]
    assert aug_run.stats.gated == 0


def test_october_snapshot_and_reasons(spec, oct_run):
    r = rows(oct_run)
    assert sorted(n for n, row in r.items() if row.is_match(spec)) == ["Kosha Credit", "Mitra Money", "Saral Loans", "Udhaar Grid"]
    assert r["Paisaloom"].verdicts["series_a"].status is Status.FAIL  # stale round
    assert r["Ledgerline"].verdicts["india"].status is Status.FAIL  # Singapore HQ
    assert r["Tijori Pay"].verdicts["credit"].status is Status.FAIL  # "does not offer loans"
    assert r["Anvil Finance"].verdicts["series_a"].status is Status.UNCLEAR  # undated
    assert r["Kosha Credit"].fields["hq"].value == "Bengaluru"


def test_every_definite_verdict_carries_a_verbatim_receipt(oct_run):
    for row in oct_run.rows:
        for v in row.verdicts.values():
            if v.status is not Status.UNCLEAR:
                assert v.evidence, (row.name, v.criterion_id)
                for e in v.evidence:
                    assert len(e.quote) >= 12 and e.content_hash


def test_lead_sources_are_mined_not_listed(spec, oct_run):
    from assay.adapters.backends import CorpusBackend, Corpus
    from conftest import DEMO
    from assay.text import registrable_domain

    hits = run(CorpusBackend(Corpus(DEMO / "oct")).search(spec.query, spec.limit))
    searched = {registrable_domain(h.url) for h in hits}
    keys = {row.key for row in oct_run.rows}
    assert "fintechpulse.example" not in keys  # the publisher is a source, not a candidate
    assert "paisaloom.example" not in searched and "paisaloom.example" in keys  # reached only via its outbound link


def test_events_tell_the_whole_story(spec, leads):
    seen = []

    async def go():
        await make_engine("aug", leads, AUG).run(spec, emit=lambda kind, data: seen.append(kind))

    run(go())
    assert seen[0] == "run.started" and seen[-1] == "run.finished"
    for k in ("search.done", "candidate.found", "candidate.fetched", "verdict", "row.done"):
        assert k in seen


def test_budget_caps_pages(spec, leads):
    eng = make_engine("aug", leads, AUG)
    eng = replace(eng, budget=Budget(max_pages=5))
    r = run(eng.run(spec))
    assert r.stats.pages_fetched + r.stats.pages_cached <= 5


# ------------------------------------------------------------------ monitor
def test_diff_reports_only_what_changed(spec, aug_run, oct_run):
    changes = diff(aug_run, oct_run, spec)
    kinds = [(c.kind, c.name) for c in changes]
    assert (ChangeKind.NEW_MATCH, "Udhaar Grid") in kinds
    assert any(c.kind is ChangeKind.VERDICT and c.name == "Mitra Money" and c.criterion_id == "security" for c in changes)
    new = next(c for c in changes if c.kind is ChangeKind.NEW_MATCH)
    assert new.evidence and "Series A" in new.evidence[0].quote  # cites the flip, not the HQ
    assert diff(oct_run, oct_run, spec) == []


def test_diff_skips_runs_of_a_different_question(spec, aug_run, oct_run):
    other = replace(aug_run, spec_fingerprint="different")
    assert diff(other, oct_run, spec) == []
    assert diff(None, oct_run, spec) == []


def test_lost_match(spec, aug_run, oct_run):
    changes = diff(oct_run, aug_run, spec)  # time running backwards: Udhaar Grid loses its match
    assert any(c.kind is ChangeKind.LOST_MATCH and c.name == "Udhaar Grid" for c in changes)


def test_summarize(spec, aug_run, oct_run):
    title, body = summarize(diff(aug_run, oct_run, spec), spec)
    assert "1 new match" in title and "Udhaar Grid" in body
    assert "Mitra Money, SOC 2 / ISO 27001: unclear → pass" in body
