"""Assay over MCP, so agents can query verified lists (and their receipts).

    claude mcp add assay -- assay mcp
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer

from .api import set_detail, summary
from .store import Store


def build_server(store: Store) -> MCPServer:
    server = MCPServer("assay", instructions="Verified lists. Every 'pass' carries a verbatim quote and its source URL.")

    @server.tool()
    def list_sets() -> list[dict]:
        """All sets with their latest match counts."""
        return [summary(store, s) for s in store.list_sets()]

    @server.tool()
    def matches(set_id: str) -> list[dict]:
        """The rows that meet every required criterion, with the evidence for each criterion."""
        d = set_detail(store, set_id)
        if not d or not d["run"]:
            return []
        req = {c["id"] for c in d["spec"]["criteria"] if c["required"]}
        out = []
        for r in d["run"]["rows"]:
            if all(r["verdicts"][c]["status"] == "pass" for c in req):
                out.append({"name": r["name"], "website": r["homepage"],
                            "evidence": {k: (v["evidence"][0] if v["evidence"] else None) for k, v in r["verdicts"].items()},
                            "fields": {k: f["value"] for k, f in r["fields"].items()}})
        return out

    @server.tool()
    def changes(set_id: str) -> list[dict]:
        """What changed in the most recent monitor run."""
        d = set_detail(store, set_id)
        return d["run"]["changes"] if d and d["run"] else []

    return server
