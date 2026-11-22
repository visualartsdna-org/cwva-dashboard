"""Promotion unit model: manifest math, gate aggregation → status, commit
message, and round-trip serialization."""

from __future__ import annotations

import json

from cwva_dashboard.promotion.unit import (
    ChangeManifest,
    GateResult,
    PromotionStatus,
    PromotionUnit,
)


def test_manifest_summary_and_counts():
    m = ChangeManifest(adds=["a.ttl"], modifies=["b.ttl", "c.ttl"], deletes=["d.ttl"])
    assert m.counts == {"adds": 1, "modifies": 2, "deletes": 1}
    assert m.summary() == "+1 ~2 -1"
    assert m.all_paths() == ["a.ttl", "b.ttl", "c.ttl", "d.ttl"]
    assert not m.is_empty()
    assert ChangeManifest().is_empty()


def test_gate_aggregation_sets_status():
    u = PromotionUnit(workflow="derive", manifest=ChangeManifest(adds=["x.ttl"]))
    assert u.status is PromotionStatus.DRAFT
    u.add_gate(GateResult("parse", ok=True))
    u.add_gate(GateResult("shacl", ok=True))
    assert u.settle_gate_status() is PromotionStatus.GATES_PASSED
    u.add_gate(GateResult("sparql", ok=False, messages=["assert X failed"]))
    assert u.settle_gate_status() is PromotionStatus.GATES_FAILED
    assert [g.name for g in u.failing_gates()] == ["sparql"]


def test_no_gates_is_not_passed():
    u = PromotionUnit(workflow="derive")
    assert not u.gates_passed()
    assert u.settle_gate_status() is PromotionStatus.GATES_FAILED


def test_commit_message_has_readable_header_and_machine_block():
    u = PromotionUnit(
        workflow="merge_demote",
        description="retire 'tonal massing' into 'tonal mass'",
        manifest=ChangeManifest(adds=["concepts/x.ttl"], modifies=["works/w1.ttl"]),
        base_commit="abc123",
        provenance={"actor": "agent", "model": "claude-x"},
    )
    u.add_gate(GateResult("parse", ok=True))
    msg = u.commit_message()
    assert msg.startswith("promote(merge_demote): retire 'tonal massing'")
    # The machine block is embedded and parseable.
    block = msg.split("cwva-promotion: |\n", 1)[1]
    body = json.loads(block)
    assert body["manifest"]["adds"] == ["concepts/x.ttl"]
    assert body["base_commit"] == "abc123"
    assert body["gates"] == [{"name": "parse", "ok": True}]


def test_roundtrip_serialization():
    u = PromotionUnit(
        workflow="tag",
        description="tag batch",
        manifest=ChangeManifest(adds=["a.ttl"], deletes=["b.ttl"]),
        base_commit="deadbeef",
        provenance={"actor": "agent"},
    )
    u.add_gate(GateResult("parse", ok=True, summary="parsed 1 file"))
    u.status = PromotionStatus.COMMITTED
    u.qa_commit = "cafe"

    u2 = PromotionUnit.from_dict(u.to_dict())
    assert u2.id == u.id
    assert u2.manifest.to_dict() == u.manifest.to_dict()
    assert u2.status is PromotionStatus.COMMITTED
    assert u2.qa_commit == "cafe"
    assert u2.gates[0].summary == "parsed 1 file"


def test_committed_status_not_overwritten_by_gate_settle():
    u = PromotionUnit(workflow="derive")
    u.add_gate(GateResult("parse", ok=True))
    u.status = PromotionStatus.CONVERGED
    assert u.settle_gate_status() is PromotionStatus.CONVERGED
