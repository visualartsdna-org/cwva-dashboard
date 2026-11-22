"""Audit-log sink: append-only durability, hash-chain integrity, tamper
detection, and the fileops hook adapter."""

from __future__ import annotations

import json

import pytest

from cwva_dashboard.audit import AuditLog, verify
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox


def test_records_appended_and_verify_clean(tmp_path):
    logpath = tmp_path / "audit" / "log.jsonl"
    with AuditLog(logpath, actor="system") as log:
        log.record("write_bytes", {"path": "a.txt", "bytes": 3}, "ok")
        log.record("read_bytes", {"path": "a.txt"}, "ok")
        log.record("trash", {"path": "a.txt"}, "error:FileNotFoundError")

    lines = logpath.read_text().splitlines()
    assert len(lines) == 3
    first = json.loads(lines[0])
    assert first["op"] == "write_bytes"
    assert first["actor"] == "system"
    assert first["seq"] == 0
    assert first["prev"] == ""

    res = verify(logpath)
    assert res.ok and res.count == 3


def test_chain_links_across_reopen(tmp_path):
    logpath = tmp_path / "log.jsonl"
    with AuditLog(logpath) as log:
        log.record("op1")
    # Reopen: the new record must chain onto the persisted one.
    with AuditLog(logpath) as log:
        rec = log.record("op2")
    assert rec["seq"] == 1
    assert rec["prev"] != ""
    assert verify(logpath).ok


def test_tamper_in_arguments_detected(tmp_path):
    logpath = tmp_path / "log.jsonl"
    with AuditLog(logpath) as log:
        log.record("write_bytes", {"path": "safe.txt"}, "ok")
        log.record("write_bytes", {"path": "safe2.txt"}, "ok")

    lines = logpath.read_text().splitlines()
    rec = json.loads(lines[0])
    rec["args"]["path"] = "evil.txt"  # edit content, keep the old hash
    lines[0] = json.dumps(rec, sort_keys=True, separators=(",", ":"))
    logpath.write_text("\n".join(lines) + "\n")

    res = verify(logpath)
    assert not res.ok
    assert res.first_bad_seq == 0


def test_truncation_of_earlier_record_detected(tmp_path):
    logpath = tmp_path / "log.jsonl"
    with AuditLog(logpath) as log:
        log.record("a")
        log.record("b")
        log.record("c")
    lines = logpath.read_text().splitlines()
    # Drop the middle record: the chain's prev-link and seq break.
    logpath.write_text(lines[0] + "\n" + lines[2] + "\n")
    res = verify(logpath)
    assert not res.ok


def test_hook_adapter_drives_fileops(tmp_path):
    logpath = tmp_path / "log.jsonl"
    sb = Sandbox.open(tmp_path / "stage", create=True)
    with AuditLog(logpath, actor="agent") as log:
        ops = FileOps(sb, audit=log.as_hook())
        ops.write_text("note.md", "hi")
        with pytest.raises(Exception):
            ops.read_text("missing.md")

    recs = [json.loads(l) for l in logpath.read_text().splitlines()]
    ops_seen = {(r["op"], r["outcome"]) for r in recs}
    assert ("write_bytes", "ok") in ops_seen
    assert any(op == "read_bytes" and outcome.startswith("error:") for op, outcome in ops_seen)
    assert all(r["actor"] == "agent" for r in recs)
    assert verify(logpath).ok
