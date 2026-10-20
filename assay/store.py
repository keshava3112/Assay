"""SQLite store: sets, runs (documents), and the event log of every run.

Runs are stored as JSON documents (they're read whole and never partially updated);
events are append-only rows so a run can be replayed in order. WAL mode lets the API
read while a run writes.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from .domain import (Change, ChangeKind, Evidence, Field, Row, Run, RunStats, SetSpec, Status, Verdict,
                     to_jsonable)
from .config import parse_spec

SCHEMA = """
CREATE TABLE IF NOT EXISTS sets (id TEXT PRIMARY KEY, spec TEXT NOT NULL, lead_sources TEXT NOT NULL DEFAULT '[]',
                                 updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, set_id TEXT NOT NULL REFERENCES sets(id), started_at TEXT NOT NULL,
                                 finished_at TEXT, doc TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS runs_by_set ON runs(set_id, started_at);
CREATE TABLE IF NOT EXISTS events (run_id TEXT NOT NULL, seq INTEGER NOT NULL, at REAL NOT NULL, kind TEXT NOT NULL,
                                   data TEXT NOT NULL, PRIMARY KEY (run_id, seq));
"""


def _evidence(d: dict) -> Evidence:
    return Evidence(**d)


def run_from_doc(doc: dict) -> Run:
    rows = []
    for r in doc["rows"]:
        verdicts = {k: Verdict(v["criterion_id"], Status(v["status"]), v.get("rationale", ""),
                               [_evidence(e) for e in v.get("evidence", [])], v.get("confidence", 0.0), v.get("gated", ""))
                    for k, v in r["verdicts"].items()}
        fields = {k: Field(f["enrichment_id"], f.get("value"), [_evidence(e) for e in f.get("evidence", [])])
                  for k, f in r["fields"].items()}
        rows.append(Row(r["key"], r["name"], r["homepage"], verdicts, fields))
    changes = [Change(ChangeKind(c["kind"]), c["key"], c["name"], c["detail"], c.get("criterion_id"), c.get("before"),
                      c.get("after"), tuple(_evidence(e) for e in c.get("evidence", []))) for c in doc.get("changes", [])]
    return Run(doc["id"], doc["set_id"], doc["started_at"], doc.get("finished_at"), doc["spec_fingerprint"], rows,
               RunStats(**doc.get("stats", {})), changes)


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, timeout=10)
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    # --------------------------------------------------------------- sets
    def put_set(self, spec_dict: dict, lead_sources: tuple[str, ...] = ()) -> SetSpec:
        spec = parse_spec(spec_dict)
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO sets(id, spec, lead_sources, updated_at) VALUES (?,?,?,?) "
                      "ON CONFLICT(id) DO UPDATE SET spec=excluded.spec, lead_sources=excluded.lead_sources, updated_at=excluded.updated_at",
                      (spec.id, json.dumps(spec_dict), json.dumps(list(lead_sources)), datetime.now(timezone.utc).isoformat()))
        return spec

    def get_set(self, set_id: str) -> tuple[SetSpec, tuple[str, ...], dict] | None:
        with self._conn() as c:
            row = c.execute("SELECT spec, lead_sources FROM sets WHERE id=?", (set_id,)).fetchone()
        if not row:
            return None
        raw = json.loads(row[0])
        return parse_spec(raw), tuple(json.loads(row[1])), raw

    def list_sets(self) -> list[SetSpec]:
        with self._conn() as c:
            return [parse_spec(json.loads(r[0])) for r in c.execute("SELECT spec FROM sets ORDER BY updated_at DESC")]

    # --------------------------------------------------------------- runs
    def save_run(self, run: Run) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT OR REPLACE INTO runs(id, set_id, started_at, finished_at, doc) VALUES (?,?,?,?,?)",
                      (run.id, run.set_id, run.started_at, run.finished_at, json.dumps(to_jsonable(run))))

    def get_run(self, run_id: str) -> Run | None:
        with self._conn() as c:
            row = c.execute("SELECT doc FROM runs WHERE id=?", (run_id,)).fetchone()
        return run_from_doc(json.loads(row[0])) if row else None

    def runs_for(self, set_id: str, limit: int = 50) -> list[Run]:
        with self._conn() as c:
            rows = c.execute("SELECT doc FROM runs WHERE set_id=? AND finished_at IS NOT NULL ORDER BY started_at DESC LIMIT ?",
                             (set_id, limit)).fetchall()
        return [run_from_doc(json.loads(r[0])) for r in rows]

    def latest_run(self, set_id: str) -> Run | None:
        runs = self.runs_for(set_id, 1)
        return runs[0] if runs else None

    # ------------------------------------------------------------- events
    def append_event(self, run_id: str, seq: int, at: float, kind: str, data: dict) -> None:
        with self._lock, self._conn() as c:
            c.execute("INSERT INTO events(run_id, seq, at, kind, data) VALUES (?,?,?,?,?)", (run_id, seq, at, kind, json.dumps(data)))

    def events(self, run_id: str, after: int = -1) -> list[dict]:
        with self._conn() as c:
            rows = c.execute("SELECT seq, at, kind, data FROM events WHERE run_id=? AND seq>? ORDER BY seq", (run_id, after)).fetchall()
        return [{"seq": s, "at": a, "kind": k, "data": json.loads(d)} for s, a, k, d in rows]
