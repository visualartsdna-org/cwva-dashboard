"""Dashboard web app: registry-driven UX shell + tool dispatch through the
worker. Verifies law 10 — every capability goes through the registry — and
that confinement/audit hold across the HTTP boundary."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from cwva_dashboard.main import create_app
from cwva_dashboard.sandbox.broker import landlock_abi
from cwva_dashboard.tools.base import Tool
from cwva_dashboard.tools.registry import ToolRegistry

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="worker requires os.fork (POSIX)")


@pytest.fixture
def client(tmp_path):
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=str(tmp_path / "stage"),
        enforce_landlock=False,
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    with TestClient(app) as c:
        yield c, tmp_path


def test_index_serves_the_real_dashboard_hub(client):
    """Phase 4.7 D1: `html/function.html` is served directly — the proven
    dashboard IS the UI. The schema-driven shell it replaced rendered itself
    from /api/tools; the hub does not, which is the trade D1 accepted (new tools
    no longer appear by themselves). The offered-set == enforced-set contract
    that mattered moved to tests/ux/test_rdf_entry_form.py."""
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200
    assert "Visual Arts" in r.text
    assert 'href="rdf/entry"' in r.text  # the wired function's card


def test_health_reports_tools_and_landlock(client):
    c, _ = client
    h = c.get("/api/health").json()
    assert "fs.write" in h["tools"]
    assert h["landlock_enforced"] is False  # disabled in this fixture


def test_tools_endpoint_is_mcp_shaped(client):
    c, _ = client
    schemas = c.get("/api/tools").json()
    names = {s["name"] for s in schemas}
    assert {"fs.list", "fs.read", "fs.write", "fs.trash"} <= names
    for s in schemas:
        assert set(s) == {"name", "description", "inputSchema"}


def test_workflow_state_panel_endpoint(client):
    c, _ = client
    st = c.get("/api/workflow-state").json()
    # Thin binding over workflow.state — the three panel groups + narration.
    assert set(st) == {"pipeline_queues", "open_obligations", "in_flight", "summary"}
    assert any(q["id"] == "concept_queue" for q in st["pipeline_queues"])


def test_tool_write_then_read_roundtrip(client):
    c, _ = client
    w = c.post("/api/tool/fs.write", json={"path": "dir/a.md", "text": "hello", "make_parents": True})
    assert w.json()["ok"] and w.json()["result"]["created"] is True
    r = c.post("/api/tool/fs.read", json={"path": "dir/a.md"})
    assert r.json()["result"]["text"] == "hello"


def test_tool_confinement_enforced_over_http(client):
    c, _ = client
    r = c.post("/api/tool/fs.read", json={"path": "../../etc/passwd"})
    body = r.json()
    assert not body["ok"]
    assert body["error"]["code"] == "path_rejected"


def test_unknown_tool_is_structured_error(client):
    c, _ = client
    r = c.post("/api/tool/fs.nope", json={})
    assert not r.json()["ok"]
    assert r.json()["error"]["code"] == "unknown_tool"


def test_bad_json_body_rejected(client):
    c, _ = client
    r = c.post("/api/tool/fs.list", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "bad_json"


def test_dispatch_is_audited_outside_sandbox(client):
    c, tmp_path = client
    c.post("/api/tool/fs.write", json={"path": "a.md", "text": "x"})
    audit = tmp_path / "audit.jsonl"  # parent of the sandbox — worker can't reach it
    assert audit.exists()
    recs = [json.loads(l) for l in audit.read_text().splitlines()]
    assert any(r["op"] == "fs.write" and r["outcome"] == "ok" for r in recs)


@pytest.mark.skipif(landlock_abi() < 1, reason="Landlock unavailable on this kernel")
def test_landlock_enforced_end_to_end(tmp_path):
    """Belt-and-suspenders: the full HTTP → registry → worker path in the
    production configuration (Landlock ON). Closes the Phase-1 'composed worker'
    deferred item — broker + fileops + audit exercised together over HTTP."""
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=str(tmp_path / "stage"),
        enforce_landlock=True,
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    with TestClient(app) as c:
        assert c.get("/api/health").json()["landlock_enforced"] is True
        assert c.post("/api/tool/fs.write", json={"path": "ok.md", "text": "hi"}).json()["ok"]
        rej = c.post("/api/tool/fs.read", json={"path": "../../etc/passwd"}).json()
        assert rej["error"]["code"] == "path_rejected"


def test_synthetic_tool_appears_and_dispatches(tmp_path):
    """The schema-driven-card contract: a newly registered tool surfaces in
    /api/tools with a well-formed inputSchema and is dispatchable — with zero UX
    code change. This is the property the whole 4.5 porting rhythm depends on."""
    reg = ToolRegistry()
    reg.register(
        Tool(
            name="synthetic.echo",
            description="Echo the message back.",
            input_schema={
                "type": "object",
                "properties": {"message": {"type": "string", "description": "text to echo"}},
                "required": ["message"],
                "additionalProperties": False,
            },
            handler=lambda fileops, **a: {"echo": a},
        )
    )
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=str(tmp_path / "stage"),
        enforce_landlock=False,
        audit_path=str(tmp_path / "audit.jsonl"),
        registry=reg,
    )
    with TestClient(app) as c:
        schemas = c.get("/api/tools").json()
        synth = next(s for s in schemas if s["name"] == "synthetic.echo")
        assert synth["inputSchema"]["type"] == "object"
        assert "message" in synth["inputSchema"]["properties"]
        r = c.post("/api/tool/synthetic.echo", json={"message": "hi"})
        assert r.json()["result"] == {"echo": {"message": "hi"}}

