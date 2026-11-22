"""Hardened worker process: tool roundtrips over IPC, confinement pass-through,
audit persistence in the (unconfined) parent, and Landlock enforcement."""

from __future__ import annotations

import pytest

from cwva_dashboard.audit import AuditLog, verify
from cwva_dashboard.sandbox.broker import landlock_abi
from cwva_dashboard.sandbox.worker import WorkerClient
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(
    not hasattr(__import__("os"), "fork"), reason="worker requires os.fork (POSIX)"
)


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "stage"
    root.mkdir()
    audit = AuditLog(tmp_path / "audit" / "log.jsonl", actor="tester")
    wc = WorkerClient(root, build_default_registry(domain=TEST_DOMAIN), actor="tester", audit=audit)
    yield wc, audit, tmp_path
    wc.close()
    audit.close()


def test_write_read_list_roundtrip(client):
    wc, _audit, _ = client
    w = wc.call("fs.write", path="dir/a.txt", text="hello", make_parents=True)
    assert w["ok"] and w["result"]["created"] is True

    r = wc.call("fs.read", path="dir/a.txt")
    assert r["ok"] and r["result"]["text"] == "hello"

    ls = wc.call("fs.list", path="dir")
    assert ls["ok"]
    assert [e["name"] for e in ls["result"]["entries"]] == ["a.txt"]


def test_confinement_enforced_through_tools(client):
    wc, _audit, _ = client
    resp = wc.call("fs.read", path="../../etc/passwd")
    assert not resp["ok"]
    assert resp["error"]["code"] == "path_rejected"


def test_unknown_tool_is_error_not_crash(client):
    wc, _audit, _ = client
    resp = wc.call("fs.destroy_everything", path="x")
    assert not resp["ok"] and resp["error"]["code"] == "unknown_tool"


def test_audit_persisted_in_parent_and_chained(client):
    wc, audit, _ = client
    wc.call("fs.write", path="a.txt", text="secret content")
    wc.call("fs.read", path="a.txt")
    wc.call("fs.read", path="missing.txt")  # error path still audited

    recs = [__import__("json").loads(l) for l in audit.path.read_text().splitlines()]
    ops = {(r["op"], r["outcome"]) for r in recs}
    assert ("fs.write", "ok") in ops
    assert ("fs.read", "ok") in ops
    assert any(op == "fs.read" and outcome.startswith("error:") for op, outcome in ops)
    # Payload was redacted before it ever left the worker.
    write_rec = next(r for r in recs if r["op"] == "fs.write")
    assert write_rec["args"]["text"] == "<14 chars>"
    assert all(r["actor"] == "tester" for r in recs)
    assert verify(audit.path).ok


def test_trash_soft_deletes_via_tool(client):
    wc, _audit, _ = client
    wc.call("fs.write", path="doomed.txt", text="bye")
    t = wc.call("fs.trash", path="doomed.txt")
    assert t["ok"] and t["result"]["path"].startswith(".qa/trash/")
    assert wc.call("fs.read", path="doomed.txt")["error"]["code"] == "FileNotFoundError"


@pytest.mark.skipif(landlock_abi() < 1, reason="Landlock unavailable on this kernel")
def test_worker_reports_landlock_enforced(client):
    wc, _audit, _ = client
    assert wc.landlock_abi >= 1
    assert wc.landlock_enforced is True


def test_worker_runs_unconfined_when_disabled(tmp_path):
    root = tmp_path / "stage"
    root.mkdir()
    wc = WorkerClient(root, build_default_registry(domain=TEST_DOMAIN), enforce_landlock=False)
    try:
        assert wc.landlock_enforced is False
        assert wc.call("fs.write", path="x.txt", text="y")["ok"]
    finally:
        wc.close()
