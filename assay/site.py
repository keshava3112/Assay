"""Static demo: the same app, with its data baked in.

The app's data layer reads `window.ASSAY_DATA` when present, so a static build is the
real UI over real engine output. "Run" replays the recorded event stream of the last
run with its original timing, so visitors watch the engine work without a server.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .api import STATIC, set_detail, summary
from .store import Store


def build_site(store: Store, out: Path) -> Path:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(STATIC, out / "static", ignore=shutil.ignore_patterns("index.html"))
    sets = store.list_sets()
    details, events = {}, {}
    for s in sets:
        d = set_detail(store, s.id)
        details[s.id] = d
        if d and d["run"]:
            events[d["run"]["id"]] = store.events(d["run"]["id"])
    data = {"mode": "static", "sets": [summary(store, s) for s in sets], "details": details, "events": events}
    (out / "static" / "data.js").write_text("window.ASSAY_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n")
    html = (STATIC / "index.html").read_text().replace("<!-- data -->", '<script src="static/data.js"></script>')
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    (out / "index.html").write_text(html)
    (out / ".nojekyll").write_text("")
    return out
