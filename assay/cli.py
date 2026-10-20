"""assay — command line.

  assay demo                      August + October runs of the demo Set, then the app
  assay add SET.yaml              register a Set
  assay run SET_ID [--corpus DIR] [--notify]
  assay watch SET_ID              re-run on the Set's monitor schedule
  assay show SET_ID               the latest results, in the terminal
  assay export SET_ID --csv out.csv | --json out.json | --xlsx out.xlsx
  assay serve [--port 8800]       the app and API
  assay site --out dist/          the static demo (one folder, host it anywhere)
  assay mcp                       the API as an MCP server, for agents
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
DEMO = HERE / "examples" / "demo"
DEFAULT_DB = os.getenv("ASSAY_DB", ".assay/assay.db")


def _store(db: str):
    from .store import Store

    return Store(db)


def engine_for(spec, leads, corpus_dir: str | None, clock=None):
    import httpx

    from .adapters.backends import Corpus, make_backends
    from .adapters.fetch import CorpusFetcher, HttpFetcher, PageCache
    from .adapters.judges import ClaudeJudge, RuleJudge
    from .engine import Engine

    corpus = Corpus(corpus_dir) if corpus_dir else None
    client = httpx.AsyncClient()
    backends = make_backends(spec.backends, client, corpus)
    fetcher = CorpusFetcher(corpus) if corpus else HttpFetcher(client, PageCache(Path(DEFAULT_DB).parent / "pages"))
    judge = ClaudeJudge() if os.getenv("ANTHROPIC_API_KEY") and not os.getenv("ASSAY_OFFLINE") else RuleJudge()
    kw = {"clock": clock} if clock else {}
    return Engine(backends, fetcher, judge, lead_sources=leads, **kw)


def _notifier():
    from .notify import default_notifier

    return default_notifier()


def print_run(spec, run) -> None:
    from .domain import Status

    sym = {Status.PASS: "✓", Status.FAIL: "✗", Status.UNCLEAR: "?"}
    width = max([len(r.name) for r in run.rows] + [12])
    head = "  ".join(f"{c.label[:16]:^16}" for c in spec.criteria)
    print(f"\n  {spec.name}\n  {run.stats.matches} match{'es' if run.stats.matches != 1 else ''} of {run.stats.candidates} candidates, "
          f"{run.stats.pages_fetched + run.stats.pages_cached} pages, {run.stats.judge_calls} checks, {run.stats.seconds}s\n")
    print(f"     {'':{width}}  {head}")
    for r in run.rows:
        cells = "  ".join(f"{sym[r.verdicts[c.id].status]:^16}" for c in spec.criteria)
        print(f"  {'◆' if r.is_match(spec) else ' '}  {r.name:{width}}  {cells}")
    if run.changes:
        from .monitor import summarize

        print("\n  " + summarize(run.changes, spec)[1].replace("\n", "\n  "))


async def _run(store, set_id, corpus, notify, clock=None):
    from .service import execute

    spec, leads, _ = store.get_set(set_id)
    engine = engine_for(spec, leads, corpus, clock)
    run = await execute(store, set_id, engine, notifier=_notifier() if notify else None)
    print_run(spec, run)
    return run


def demo(db: str, serve: bool, port: int) -> int:
    Path(db).unlink(missing_ok=True)
    store = _store(db)
    raw = yaml.safe_load((DEMO / "set.yaml").read_text())
    store.put_set(raw, tuple(raw.get("lead_sources") or ()))
    print("\n  ◆ Assay demo: two snapshots of a fictional web, two months apart")
    print("  ──────────────────────────────────────────────────────────────")
    print("  August 18, 2026")
    asyncio.run(_run(store, raw["id"], str(DEMO / "aug"), False, lambda: datetime(2026, 8, 18, 9)))
    print("\n  October 19, 2026: the monitor re-runs and reports only what changed")
    asyncio.run(_run(store, raw["id"], str(DEMO / "oct"), False, lambda: datetime(2026, 10, 19, 9)))
    if serve:
        return _serve(db, port, corpus=str(DEMO / "oct"))
    return 0


def _serve(db: str, port: int, host: str = "127.0.0.1", corpus: str | None = None) -> int:
    import uvicorn

    from .api import create_app

    print(f"\n  Assay is open at http://{host}:{port}\n")
    uvicorn.run(create_app(_store(db), corpus=corpus), host=host, port=port, log_level="warning")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="assay", description="Lists you can prove.")
    ap.add_argument("--db", default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("demo")
    d.add_argument("--no-serve", action="store_true")
    d.add_argument("--port", type=int, default=8800)
    a = sub.add_parser("add")
    a.add_argument("spec")
    for name in ("run", "watch"):
        r = sub.add_parser(name)
        r.add_argument("set_id")
        r.add_argument("--corpus", help="search a local corpus folder instead of the web")
        r.add_argument("--notify", action="store_true")
    s = sub.add_parser("show")
    s.add_argument("set_id")
    e = sub.add_parser("export")
    e.add_argument("set_id")
    e.add_argument("--csv")
    e.add_argument("--json")
    e.add_argument("--xlsx")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=8800)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--corpus")
    st = sub.add_parser("site")
    st.add_argument("--out", default="dist")
    sub.add_parser("mcp")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    if args.cmd == "demo":
        return demo(args.db, not args.no_serve, args.port)
    store = _store(args.db)
    if args.cmd == "add":
        raw = yaml.safe_load(Path(args.spec).read_text())
        spec = store.put_set(raw, tuple(raw.get("lead_sources") or ()))
        print(f"Added set '{spec.id}'. Run it with: assay run {spec.id}")
        return 0
    if args.cmd in ("run", "watch", "show", "export") and not store.get_set(args.set_id):
        print(f"No set '{args.set_id}'. Add one with: assay add SET.yaml")
        return 1
    if args.cmd == "run":
        asyncio.run(_run(store, args.set_id, args.corpus, args.notify))
    elif args.cmd == "watch":
        spec, _, _ = store.get_set(args.set_id)
        every = _seconds(spec.monitor_every or "1d")
        print(f"Watching '{spec.name}' every {spec.monitor_every or '1d'}. Ctrl-C to stop.")
        while True:
            asyncio.run(_run(store, args.set_id, args.corpus, args.notify))
            asyncio.run(asyncio.sleep(every))
    elif args.cmd == "show":
        spec, _, _ = store.get_set(args.set_id)
        run = store.latest_run(args.set_id)
        print_run(spec, run) if run else print("No runs yet.")
    elif args.cmd == "export":
        from .exports import to_csv, to_json, to_xlsx

        spec, _, _ = store.get_set(args.set_id)
        run = store.latest_run(args.set_id)
        if not run:
            print("No runs yet.")
            return 1
        for path, fn in ((args.csv, to_csv), (args.json, to_json), (args.xlsx, to_xlsx)):
            if path:
                fn(spec, run, path)
                print(f"wrote {path}")
    elif args.cmd == "serve":
        return _serve(args.db, args.port, args.host, args.corpus)
    elif args.cmd == "site":
        from .site import build_site

        out = build_site(store, Path(args.out))
        print(f"Static demo written to {out}/. Host the folder anywhere: GitHub Pages, Netlify, S3.")
    elif args.cmd == "mcp":
        from .mcp_server import build_server

        build_server(store).run("stdio")
    return 0


def _seconds(every: str) -> int:
    m = re.fullmatch(r"(\d+)\s*([mhd])", every.strip())
    if not m:
        raise SystemExit(f"bad monitor interval {every!r} (use 30m, 6h, 1d)")
    return int(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]


if __name__ == "__main__":
    sys.exit(main())
