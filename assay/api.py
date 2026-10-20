"""HTTP API + the app.

  GET  /api/bootstrap                    sets with their latest summary
  GET  /api/sets/{id}                    spec, latest run, run history
  POST /api/sets/{id}/runs               start a run (background) -> {run_id}
  GET  /api/runs/{id}                    a finished run
  GET  /api/runs/{id}/events             Server-Sent Events: history, then live
  GET  /api/sets/{id}/export.{csv|json|xlsx}
  GET  /                                 the app (static, no build step)

Set ASSAY_TOKEN to require `Authorization: Bearer <token>` (or ?token=) on the API.
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import uuid
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .domain import to_jsonable
from .service import EventBus, execute
from .store import Store

STATIC = Path(__file__).resolve().parent / "web" / "static"


def summary(store: Store, spec) -> dict:
    run = store.latest_run(spec.id)
    return {
        "id": spec.id, "name": spec.name, "entity": spec.entity, "description": spec.description,
        "monitor_every": spec.monitor_every,
        "latest": None if not run else {"id": run.id, "finished_at": run.finished_at, "matches": run.stats.matches,
                                        "candidates": run.stats.candidates, "changes": len(run.changes)},
    }


def set_detail(store: Store, set_id: str) -> dict | None:
    found = store.get_set(set_id)
    if not found:
        return None
    spec, leads, raw = found
    runs = store.runs_for(set_id)
    return {
        "spec": to_jsonable(spec), "lead_sources": list(leads), "raw": raw,
        "run": to_jsonable(runs[0]) if runs else None,
        "history": [{"id": r.id, "started_at": r.started_at, "finished_at": r.finished_at, "stats": to_jsonable(r.stats),
                     "changes": to_jsonable(r.changes)} for r in runs],
    }


def create_app(store: Store, *, corpus: str | None = None, engine_factory=None) -> Starlette:
    bus = EventBus()
    running: dict[str, asyncio.Task] = {}
    token = os.getenv("ASSAY_TOKEN")

    def authorized(req: Request) -> bool:
        if not token:
            return True
        given = req.headers.get("authorization", "").removeprefix("Bearer ").strip() or req.query_params.get("token", "")
        return secrets.compare_digest(given, token)

    def guard(fn):
        async def wrapped(req: Request):
            if not authorized(req):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await fn(req)
        return wrapped

    def make_engine(spec, leads):
        if engine_factory:
            return engine_factory(spec, leads)
        from .cli import engine_for

        return engine_for(spec, leads, corpus)

    @guard
    async def bootstrap(req: Request):
        return JSONResponse({"mode": "live", "sets": [summary(store, s) for s in store.list_sets()]})

    @guard
    async def get_set(req: Request):
        d = set_detail(store, req.path_params["set_id"])
        return JSONResponse(d) if d else JSONResponse({"error": "not found"}, status_code=404)

    @guard
    async def start_run(req: Request):
        set_id = req.path_params["set_id"]
        found = store.get_set(set_id)
        if not found:
            return JSONResponse({"error": "not found"}, status_code=404)
        if any(not t.done() for k, t in running.items() if k.startswith(set_id + ":")):
            return JSONResponse({"error": "a run is already in progress"}, status_code=409)
        spec, leads, _ = found
        run_id = uuid.uuid4().hex[:12]
        engine = make_engine(spec, leads)
        running[f"{set_id}:{run_id}"] = asyncio.create_task(execute(store, set_id, engine, bus=bus, run_id=run_id))
        return JSONResponse({"run_id": run_id}, status_code=202)

    @guard
    async def get_run(req: Request):
        run = store.get_run(req.path_params["run_id"])
        return JSONResponse(to_jsonable(run)) if run else JSONResponse({"error": "not found"}, status_code=404)

    @guard
    async def events(req: Request):
        run_id = req.path_params["run_id"]
        q = bus.subscribe(run_id)

        async def stream():
            try:
                last = -1
                for e in store.events(run_id):  # history first: late subscribers miss nothing
                    last = e["seq"]
                    yield f"id: {e['seq']}\nevent: {e['kind']}\ndata: {json.dumps(e)}\n\n"
                    if e["kind"] == "run.saved":
                        return
                while True:
                    try:
                        e = await asyncio.wait_for(q.get(), timeout=15)
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
                        continue
                    if e["seq"] <= last:
                        continue
                    yield f"id: {e['seq']}\nevent: {e['kind']}\ndata: {json.dumps(e)}\n\n"
                    if e["kind"] == "run.saved":
                        return
            finally:
                bus.unsubscribe(run_id, q)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @guard
    async def export(req: Request):
        from .exports import to_csv, to_json, to_xlsx

        set_id, fmt = req.path_params["set_id"], req.path_params["fmt"]
        found = store.get_set(set_id)
        run = store.latest_run(set_id)
        if not found or not run or fmt not in ("csv", "json", "xlsx"):
            return JSONResponse({"error": "not found"}, status_code=404)
        fn = {"csv": to_csv, "json": to_json, "xlsx": to_xlsx}[fmt]
        with tempfile.TemporaryDirectory() as tmp:
            data = fn(found[0], run, Path(tmp) / f"x.{fmt}").read_bytes()
        mime = {"csv": "text/csv", "json": "application/json",
                "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}[fmt]
        return Response(data, media_type=mime, headers={"content-disposition": f'attachment; filename="{set_id}.{fmt}"'})

    async def index(req: Request):
        return FileResponse(STATIC / "index.html")

    async def health(req: Request):
        return JSONResponse({"ok": True})

    return Starlette(routes=[
        Route("/api/bootstrap", bootstrap),
        Route("/api/sets/{set_id}", get_set),
        Route("/api/sets/{set_id}/runs", start_run, methods=["POST"]),
        Route("/api/sets/{set_id}/export.{fmt}", export),
        Route("/api/runs/{run_id}", get_run),
        Route("/api/runs/{run_id}/events", events),
        Route("/healthz", health),
        Route("/", index),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ])
