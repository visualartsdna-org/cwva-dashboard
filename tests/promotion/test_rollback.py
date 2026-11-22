"""Rollback: the revert->converge round-trip. A rolled-back unit returns SOT to
its pre-work state (restoring deletes, removing adds, reverting edits), records
a QA rollback commit, and drift-checks before writing."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.apply import DriftError, apply_unit
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.rollback import RollbackError, rollback_unit
from cwva_dashboard.promotion.transports import FilesTransport, GitLocalTransport
from cwva_dashboard.promotion.unit import GateResult, PromotionStatus, PromotionUnit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _qa(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    return QAGit.init(root)


def _unit(base, workflow="derive"):
    u = PromotionUnit(workflow=workflow, base_commit=base, provenance={"actor": "agent"})
    u.add_gate(GateResult("parse", ok=True))
    u.add_gate(GateResult("shacl", ok=True))
    u.settle_gate_status()
    return u


def test_rollback_of_added_files_removes_them_from_sot(tmp_path):
    qa = _qa(tmp_path)
    base = qa.head()
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")

    unit = _unit(base)
    applied = apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())
    assert (sot.target / "a.ttl").exists()

    rb = rollback_unit(unit, qa, sot, expected_stamp=applied.sot_stamp)
    assert not (sot.target / "a.ttl").exists()  # added file gone
    assert unit.status is PromotionStatus.ROLLED_BACK
    assert rb.sot_stamp == sot.current_stamp()
    # SOT is back to the pre-apply (empty) state.
    assert sot.current_stamp() == FilesTransport(tmp_path / "empty").current_stamp()


def test_rollback_restores_modify_and_delete_and_removes_add(tmp_path):
    qa = _qa(tmp_path)

    # unit0 establishes a baseline SOT: {a=A0, b=B0}
    base0 = qa.head()
    (qa.root / "a.ttl").write_text("A0")
    (qa.root / "b.ttl").write_text("B0")
    sot = FilesTransport(tmp_path / "sot")
    r0 = apply_unit(_unit(base0), qa, sot, expected_stamp=sot.current_stamp())

    # unit1: modify a, delete b, add c  -> SOT {a=A1, c=C0}
    base1 = qa.head()
    (qa.root / "a.ttl").write_text("A1")
    (qa.root / "b.ttl").unlink()
    (qa.root / "c.ttl").write_text("C0")
    unit1 = _unit(base1)
    r1 = apply_unit(unit1, qa, sot, expected_stamp=r0.sot_stamp)
    assert (sot.target / "a.ttl").read_text() == "A1"
    assert not (sot.target / "b.ttl").exists()
    assert (sot.target / "c.ttl").read_text() == "C0"

    # roll back unit1 -> SOT returns to {a=A0, b=B0}
    rollback_unit(unit1, qa, sot, expected_stamp=r1.sot_stamp)
    assert (sot.target / "a.ttl").read_text() == "A0"  # edit reverted
    assert (sot.target / "b.ttl").read_text() == "B0"  # delete restored
    assert not (sot.target / "c.ttl").exists()  # add removed
    assert sot.current_stamp() == r0.sot_stamp  # exactly the post-unit0 state


def test_rollback_aborts_on_drift_without_writing(tmp_path):
    qa = _qa(tmp_path)
    base = qa.head()
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")
    unit = _unit(base)
    apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())
    head_after_apply = qa.head()

    with pytest.raises(DriftError):
        rollback_unit(unit, qa, sot, expected_stamp="stale-stamp")

    # SOT untouched, no rollback commit recorded, unit still converged.
    assert (sot.target / "a.ttl").exists()
    assert qa.head() == head_after_apply
    assert unit.status is PromotionStatus.CONVERGED


def test_rollback_refuses_unconverted_unit(tmp_path):
    qa = _qa(tmp_path)
    base = qa.head()
    sot = FilesTransport(tmp_path / "sot")
    unit = _unit(base)  # never applied
    with pytest.raises(RollbackError):
        rollback_unit(unit, qa, sot)


def test_rollback_records_qa_commit(tmp_path):
    qa = _qa(tmp_path)
    base = qa.head()
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")
    unit = _unit(base)
    applied = apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())

    rb = rollback_unit(unit, qa, sot, expected_stamp=applied.sot_stamp)
    assert rb.qa_commit == qa.head()
    assert rb.qa_commit != applied.qa_commit  # history advanced, not rewound


def test_rollback_round_trip_git_local_sot(tmp_path):
    qa = _qa(tmp_path)
    base = qa.head()
    (qa.root / "a.ttl").write_text("A1")
    sot = GitLocalTransport(tmp_path / "sot")
    unit = _unit(base)
    applied = apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())
    assert (sot.target / "a.ttl").exists()

    rollback_unit(unit, qa, sot, expected_stamp=applied.sot_stamp)
    # File removed and the SOT repo has a new (revert) commit on top.
    assert not (sot.target / "a.ttl").exists()
    assert unit.status is PromotionStatus.ROLLED_BACK


def test_rollback_emits_audit_event(tmp_path):
    qa = _qa(tmp_path)
    base = qa.head()
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")
    unit = _unit(base)
    applied = apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())

    events = []
    rollback_unit(
        unit, qa, sot, expected_stamp=applied.sot_stamp,
        audit=lambda op, a, outcome: events.append((op, outcome)),
    )
    assert ("promotion.rollback", "ok") in events
