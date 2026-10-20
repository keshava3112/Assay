from datetime import datetime
from types import SimpleNamespace

from conftest import run

from assay.adapters.judges import ClaudeJudge, RuleJudge
from assay.domain import Candidate, Criterion, Enrichment, Evidence, Field, Page, SetSpec, Status, Verdict
from assay.gate import check_field, check_verdict

TEXT = ("Kosha Credit is headquartered in Bengaluru. "
        "In July 2026 Kosha Credit raised a $12M Series A led by Banyan Partners. "
        "The company does not offer loans to consumers.")
PAGE = Page("https://kosha.example/", 200, "Kosha Credit", TEXT, Page.hash_text(TEXT), "2026-10-19T09:00:00")
CAND = Candidate("kosha.example", "Kosha Credit", "https://kosha.example/", pages=[PAGE])


def ev(quote, url=PAGE.url, h=PAGE.content_hash):
    return Evidence(url, quote, h, PAGE.fetched_at)


# ------------------------------------------------------------------ gate
def test_g1_definite_verdict_needs_evidence():
    v = check_verdict(Verdict("india", Status.PASS, "trust me"), CAND)
    assert v.status is Status.UNCLEAR and v.gated.startswith("G1")


def test_g2_quote_must_be_on_the_page():
    v = check_verdict(Verdict("india", Status.PASS, evidence=[ev("Kosha Credit is headquartered in Mumbai.")]), CAND)
    assert v.status is Status.UNCLEAR and v.gated.startswith("G2") and v.evidence == []


def test_g2_quote_must_cite_a_fetched_page():
    v = check_verdict(Verdict("india", Status.PASS, evidence=[ev("Kosha Credit is headquartered in Bengaluru.",
                                                                 url="https://elsewhere.example/")]), CAND)
    assert v.status is Status.UNCLEAR and "wasn't fetched" in v.gated


def test_g3_hash_must_match_the_fetched_version():
    v = check_verdict(Verdict("india", Status.PASS, evidence=[ev("Kosha Credit is headquartered in Bengaluru.", h="0" * 64)]), CAND)
    assert v.status is Status.UNCLEAR and v.gated.startswith("G3")


def test_gate_passes_a_good_receipt_and_ignores_unclear():
    good = Verdict("india", Status.PASS, evidence=[ev("kosha credit is headquartered in bengaluru")])
    assert check_verdict(good, CAND) is good
    unclear = Verdict("india", Status.UNCLEAR)
    assert check_verdict(unclear, CAND) is unclear


def test_g4_field_value_must_be_inside_its_quote():
    ok = Field("raised", "$12M", [ev("Kosha Credit raised a $12M Series A")])
    assert check_field(ok, CAND).value == "$12M"
    bad = Field("raised", "$40M", [ev("Kosha Credit raised a $12M Series A")])
    assert check_field(bad, CAND).value is None


# ------------------------------------------------------------------ rule judge
SPEC = SetSpec("s", "S", "company", "q", criteria=())


def judge(criterion, now=datetime(2026, 10, 19)):
    return run(RuleJudge().judge(SPEC, CAND, criterion, [], now))


def test_rule_judge_signal_passes_with_quote():
    v = judge(Criterion("india", "India", "?", signals=(r"headquartered in (Bengaluru|Mumbai)",)))
    assert v.status is Status.PASS
    assert check_verdict(v, CAND).status is Status.PASS


def test_rule_judge_against_beats_signal_in_same_sentence():
    v = judge(Criterion("credit", "Credit", "?", signals=(r"\bloans?\b",), against=(r"does not offer loans",)))
    assert v.status is Status.FAIL


def test_rule_judge_recency_window():
    c = Criterion("a", "Series A", "?", signals=(r"\bSeries A\b",), within_months=18)
    assert judge(c).status is Status.PASS
    stale = judge(c, now=datetime(2028, 6, 1))
    assert stale.status is Status.FAIL and "months old" in stale.rationale


def test_rule_judge_ignores_the_company_name():
    text = "Saral Loans helps teams with payroll and expense cards for employees."
    page = Page("https://saralloans.example/", 200, "Saral Loans", text, Page.hash_text(text), "2026-10-19")
    cand = Candidate("saralloans.example", "Saral Loans", page.url, pages=[page])
    v = run(RuleJudge().judge(SPEC, cand, Criterion("credit", "Credit", "?", signals=(r"\bloans?\b",)), [], datetime(2026, 10, 19)))
    assert v.status is Status.UNCLEAR


def test_rule_judge_enrich():
    f = run(RuleJudge().enrich(SPEC, CAND, Enrichment("hq", "HQ", "?", pattern=r"headquartered in ([A-Z][a-z]+)"), []))
    assert f.value == "Bengaluru" and check_field(f, CAND).value == "Bengaluru"


# ------------------------------------------------------------------ claude judge (fake client)
class FakeMessages:
    def __init__(self, payload):
        self.payload, self.calls = payload, []

    async def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=self.payload)])


def claude(payload):
    msgs = FakeMessages(payload)
    return ClaudeJudge(client=SimpleNamespace(messages=msgs), model="test-model"), msgs


def test_claude_judge_forces_tool_and_maps_passage_to_evidence():
    j, msgs = claude({"status": "pass", "rationale": "stated", "passage_id": "P1",
                      "quote": "Kosha Credit is headquartered in Bengaluru.", "confidence": 0.9})
    v = run(j.judge(SPEC, CAND, Criterion("india", "India", "Is it in India?"), [(PAGE, TEXT)], datetime(2026, 10, 19)))
    call = msgs.calls[0]
    assert call["model"] == "test-model" and call["tool_choice"]["type"] == "tool"
    assert "[P1]" in call["messages"][0]["content"]
    assert v.status is Status.PASS and v.evidence[0].url == PAGE.url
    assert check_verdict(v, CAND).status is Status.PASS


def test_claude_judge_hallucinated_quote_is_gated():
    j, _ = claude({"status": "pass", "rationale": "x", "passage_id": "P1",
                   "quote": "Kosha Credit is the largest lender in India.", "confidence": 0.9})
    v = run(j.judge(SPEC, CAND, Criterion("india", "India", "?"), [(PAGE, TEXT)], datetime(2026, 10, 19)))
    assert check_verdict(v, CAND).status is Status.UNCLEAR


def test_claude_judge_bad_passage_id_yields_no_evidence():
    j, _ = claude({"status": "pass", "passage_id": "P9", "quote": "anything at all goes here", "confidence": 1})
    v = run(j.judge(SPEC, CAND, Criterion("india", "India", "?"), [(PAGE, TEXT)], datetime(2026, 10, 19)))
    assert v.evidence == [] and check_verdict(v, CAND).gated.startswith("G1")


def test_claude_judge_no_passages_skips_the_call():
    j, msgs = claude({})
    v = run(j.judge(SPEC, CAND, Criterion("india", "India", "?"), [], datetime(2026, 10, 19)))
    assert v.status is Status.UNCLEAR and msgs.calls == []
