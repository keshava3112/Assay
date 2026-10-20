# Contributing to Assay

Thanks for helping. Assay has one rule that every change must keep: **a verdict only counts if its quote is on the page.** If a change could let an unproven claim reach a user, it needs a test that shows the gate still holds.

## Setup

```bash
git clone https://github.com/keshava3112/Assay && cd Assay
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
ASSAY_OFFLINE=1 assay demo     # opens the app at http://127.0.0.1:8800
```

## Where things go

| You want to… | Touch |
|---|---|
| Add a search API | `assay/adapters/backends.py`, implement `SearchBackend.search` |
| Add a model provider | `assay/adapters/judges.py`, implement `Judge.judge` and `Judge.enrich` |
| Add an alert channel | `assay/notify.py`, implement `Notifier.send` |
| Change what counts as proof | `assay/gate.py`, and expect careful review |
| Change the UI | `assay/web/static/`, then check `assay site` still works |

The domain (`domain.py`, `gate.py`, `monitor.py`) imports nothing from adapters. Keep it that way.

## Pull requests

- One idea per PR, with tests. `pytest -q` must pass on 3.11 to 3.13.
- New adapters need a test with a fake transport (see `tests/test_fetch.py` for the `httpx.MockTransport` pattern).
- UI changes: include a screenshot at desktop and phone width.
- The demo web is fictional and lives in `scripts/build_demo_corpus.py`. Never put real companies in it.
