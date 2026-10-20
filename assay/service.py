"""Application service: one function runs a Set end to end. The CLI, the API and the
scheduler all call it, so behaviour is identical everywhere.

    execute(store, set_id, engine)  ->  Run (saved, diffed, events persisted, notified)
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from .engine import Engine
from .monitor import diff, summarize
from .ports import Notifier
from .store import Store


@dataclass
class EventBus:
    """Fan-out of live run events to SSE subscribers; history comes from the store."""

    subscribers: dict[str, list[asyncio.Queue]] = field(default_factory=lambda: defaultdict(list))

    def subscribe(self, run_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        self.subscribers[run_id].append(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        if q in self.subscribers.get(run_id, []):
            self.subscribers[run_id].remove(q)

    def publish(self, run_id: str, event: dict) -> None:
        for q in list(self.subscribers.get(run_id, [])):
            q.put_nowait(event)


async def execute(store: Store, set_id: str, engine: Engine, *, bus: EventBus | None = None,
                  notifier: Notifier | None = None, run_id: str | None = None):
    found = store.get_set(set_id)
    if not found:
        raise KeyError(set_id)
    spec, _, _ = found
    run_id = run_id or uuid.uuid4().hex[:12]
    previous = store.latest_run(set_id)
    seq = 0
    t0 = time.monotonic()

    def emit(kind: str, data: dict):
        nonlocal seq
        event = {"seq": seq, "at": round(time.monotonic() - t0, 3), "kind": kind, "data": data}
        store.append_event(run_id, seq, event["at"], kind, data)
        if bus:
            bus.publish(run_id, event)
        seq += 1

    run = await engine.run(spec, emit=emit, run_id=run_id)
    run.changes = diff(previous, run, spec)
    store.save_run(run)
    emit("run.saved", {"run_id": run.id, "changes": len(run.changes)})
    if notifier and run.changes:
        notifier.send(*summarize(run.changes, spec))
    return run
