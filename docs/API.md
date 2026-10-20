# Assay HTTP API

Assay serves a JSON API wherever you run `assay serve`. Every proven or disproven value in a response carries its evidence: the exact quote, the source URL, the capture time and a SHA-256 fingerprint of the page text.

```bash
pip install git+https://github.com/keshava3112/Assay
export ASSAY_TOKEN=change-me        # optional; when set, every /api route needs it
assay add lending.yaml              # define a set (see the README for the spec format)
assay serve --host 0.0.0.0 --port 8800
```

## Authentication

If `ASSAY_TOKEN` is set, send it as a bearer token:

```
Authorization: Bearer change-me
```

For the event stream (where browsers can't set headers) `?token=change-me` is also accepted. Requests without a valid token get `401`.

## Endpoints

| Method | Path | What it does |
|---|---|---|
| `GET` | `/api/bootstrap` | Lists every set with its latest run summary |
| `GET` | `/api/sets/{set_id}` | One set: its spec, the latest run with every row and its evidence, and run history |
| `POST` | `/api/sets/{set_id}/runs` | Starts a run in the background. Returns `202 {"run_id": "…"}`, or `409` if that set is already running |
| `GET` | `/api/runs/{run_id}` | A finished run: rows, verdicts, evidence, fields, stats and changes since the previous run |
| `GET` | `/api/runs/{run_id}/events` | Server-sent events for a run: history first, then live, ending with `run.saved` |
| `GET` | `/api/sets/{set_id}/export.{csv,json,xlsx}` | The latest run as a file, one quote and source column per criterion |
| `GET` | `/healthz` | `{"ok": true}` |

## A run, step by step

```bash
curl -X POST -H "Authorization: Bearer $ASSAY_TOKEN" \
  http://localhost:8800/api/sets/india-lending-series-a/runs
# 202 {"run_id": "11e208e634ac"}

curl -N "http://localhost:8800/api/runs/11e208e634ac/events?token=$ASSAY_TOKEN"
# event: run.started … event: verdict … event: run.saved

curl -H "Authorization: Bearer $ASSAY_TOKEN" http://localhost:8800/api/runs/11e208e634ac
```

## Response shape

A row in `GET /api/runs/{run_id}` (trimmed):

```json
{
  "key": "kosha.example",
  "name": "Kosha Credit",
  "homepage": "https://kosha.example",
  "verdicts": {
    "india": {
      "criterion_id": "india",
      "status": "pass",
      "rationale": "2 sentences on the fetched pages state this.",
      "confidence": 0.75,
      "gated": "",
      "evidence": [{
        "url": "https://kosha.example",
        "quote": "Kosha Credit is headquartered in Bengaluru and has disbursed over ₹900 crore since launch.",
        "content_hash": "5c3ebab64b5e5d469fdaa9bfeb40808fd706b612178389094c2bf01ae4c776f5",
        "fetched_at": "2026-10-19T09:00:00",
        "context": "…Decisions in 48 hours, using GST and bank data rather than collateral. Kosha Credit is headquartered in Bengaluru…"
      }]
    }
  },
  "fields": {
    "raised": {
      "enrichment_id": "raised",
      "value": "$18M",
      "evidence": [{"url": "https://kosha.example/press", "quote": "March 12, 2026: Kosha Credit raises $18M Series A led by Northfield Ventures.", "…": "…"}]
    }
  }
}
```

- `status` is `pass`, `fail` or `unclear`. `unclear` means "not proven": no source states it, or the receipt gate rejected the evidence. When the gate downgrades a verdict, `gated` says why (`G1` to `G4`, see the README).
- A field's `value` is `null` when no source states it.
- `changes` on a run lists what moved since the previous run (`new_match`, `lost_match`, `verdict`, `field`), each with its evidence.

## Limits

- One run per set at a time (`409` otherwise). Different sets run in parallel.
- Inside a run, page fetches and model calls run in separate bounded pools (6 and 8 by default), with a per-run budget of 200 pages and 400 model calls.
- Fetching is polite: robots.txt is honoured and requests to the same host are spaced at least one second apart.
- The API itself applies no request-rate limit; put a proxy in front if you expose it publicly.
