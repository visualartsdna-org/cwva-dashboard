"""End-to-end gated convergence: QA git -> gates -> apply -> SOT, plus the
drift-abort and gates-not-passed guards. Uses the files and git_local
transports as fixture SOT targets."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.apply import (
    DriftError,
    EmptyUnitError,
    GatesNotPassedError,
    apply_unit,
)
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport, GitLocalTransport
from cwva_dashboard.promotion.unit import ChangeManifest, GateResult, PromotionStatus, PromotionUnit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _qa_with_base(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    qa = QAGit.init(root)
    return qa, qa.head()


def _passed_unit(base, **kw):
    u = PromotionUnit(workflow="derive", base_commit=base, provenance={"actor": "agent"}, **kw)
    u.add_gate(GateResult("parse", ok=True))
    u.add_gate(GateResult("shacl", ok=True))
    u.settle_gate_status()
    return u


def test_apply_converges_to_files_sot(tmp_path):
    qa, base = _qa_with_base(tmp_path)
    (qa.root / "a.ttl").write_text("A1")
    (qa.root / "sub").mkdir()
    (qa.root / "sub" / "b.ttl").write_text("B1")

    sot = FilesTransport(tmp_path / "sot")
    baseline = sot.current_stamp()
    unit = _passed_unit(base, description="add two works")

    res = apply_unit(unit, qa, sot, expected_stamp=baseline)

    # SOT now mirrors QA content.
    assert (sot.target / "a.ttl").read_text() == "A1"
    assert (sot.target / "sub" / "b.ttl").read_text() == "B1"
    # Unit lifecycle + stamps.
    assert unit.status is PromotionStatus.CONVERGED
    assert unit.qa_commit == res.qa_commit
    assert res.sot_stamp == sot.current_stamp()
    # The QA git recorded exactly one promotion commit past base.
    assert qa.head() != base
    assert unit.manifest.adds == ["a.ttl", "sub/b.ttl"]


def test_apply_records_stamp_usable_as_next_baseline(tmp_path):
    qa, base = _qa_with_base(tmp_path)
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")
    r1 = apply_unit(_passed_unit(base), qa, sot, expected_stamp=sot.current_stamp())

    # second workflow from the new base, using r1.sot_stamp as the baseline
    base2 = qa.head()
    (qa.root / "a.ttl").write_text("A2")
    r2 = apply_unit(_passed_unit(base2), qa, sot, expected_stamp=r1.sot_stamp)
    assert (sot.target / "a.ttl").read_text() == "A2"
    assert r2.sot_stamp == sot.current_stamp()


def test_apply_aborts_on_drift_without_writing(tmp_path):
    qa, base = _qa_with_base(tmp_path)
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")
    unit = _passed_unit(base)

    with pytest.raises(DriftError):
        apply_unit(unit, qa, sot, expected_stamp="some-other-stamp")

    # Nothing converged, nothing committed to QA; the unit never advanced past
    # gates (no COMMITTED/CONVERGED transition).
    assert not (sot.target / "a.ttl").exists()
    assert qa.head() == base
    assert unit.status is PromotionStatus.GATES_PASSED


def test_apply_refuses_failing_gates(tmp_path):
    qa, base = _qa_with_base(tmp_path)
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")
    unit = PromotionUnit(workflow="derive", base_commit=base)
    unit.add_gate(GateResult("parse", ok=False, messages=["boom"]))

    with pytest.raises(GatesNotPassedError):
        apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())
    assert qa.head() == base


def test_apply_refuses_empty_unit(tmp_path):
    qa, base = _qa_with_base(tmp_path)  # no content changes
    sot = FilesTransport(tmp_path / "sot")
    with pytest.raises(EmptyUnitError):
        apply_unit(_passed_unit(base), qa, sot, expected_stamp=sot.current_stamp())


def test_apply_converges_to_git_local_sot(tmp_path):
    qa, base = _qa_with_base(tmp_path)
    (qa.root / "a.ttl").write_text("A1")
    sot = GitLocalTransport(tmp_path / "sot")
    unit = _passed_unit(base, description="into git sot")

    res = apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())
    assert (sot.target / "a.ttl").read_text() == "A1"
    assert res.sot_stamp == sot.current_stamp()  # HEAD advanced to the promotion


def test_apply_emits_audit_event(tmp_path):
    qa, base = _qa_with_base(tmp_path)
    (qa.root / "a.ttl").write_text("A1")
    sot = FilesTransport(tmp_path / "sot")
    events = []
    apply_unit(
        _passed_unit(base),
        qa,
        sot,
        expected_stamp=sot.current_stamp(),
        audit=lambda op, args, outcome: events.append((op, outcome)),
    )
    assert ("promotion.apply", "ok") in events
