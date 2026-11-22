"""End-to-end binary assets: promote real binaries (not .ptr) to SOT, and roll
back to a superseded binary re-materialized from the attic."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.apply import apply_unit
from cwva_dashboard.promotion.binaries import content_manifest
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.workflows.promote import run_promotion
from cwva_dashboard.promotion.rollback import rollback_unit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.promotion.unit import ChangeManifest, GateResult, PromotionUnit
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _setup(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    qa = QAGit.init(root)
    ops = FileOps(Sandbox.open(root))  # sandbox root == QA content root
    return qa, ops


def _unit(base):
    u = PromotionUnit(workflow="form_drafting", base_commit=base, provenance={"actor": "agent"})
    u.add_gate(GateResult("parse", ok=True))
    u.settle_gate_status()
    return u


def test_content_manifest_maps_pointer_to_binary():
    m = ChangeManifest(adds=["img/a.png.ptr", "works/w.ttl"], deletes=["old.pdf.ptr"])
    c = content_manifest(m)
    assert c.adds == ["img/a.png", "works/w.ttl"]  # .ptr -> real binary, ttl passes through
    assert c.deletes == ["old.pdf"]


def test_binary_promotes_real_file_and_not_sidecar(tmp_path):
    qa, ops = _setup(tmp_path)
    base = qa.head()
    ops.write_bytes("img/a.png", b"IMG-V1", make_parents=True)

    sot = FilesTransport(tmp_path / "sot")
    unit = _unit(base)
    apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())

    # The QA git tracked the sidecar, but SOT received the real binary only.
    assert unit.manifest.adds == ["img/a.png.ptr"]
    assert (sot.target / "img" / "a.png").read_bytes() == b"IMG-V1"
    assert not (sot.target / "img" / "a.png.ptr").exists()


def test_binary_rollback_rematerializes_previous_version(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")

    # promote V1
    base0 = qa.head()
    ops.write_bytes("a.png", b"IMG-V1")
    r0 = apply_unit(_unit(base0), qa, sot, expected_stamp=sot.current_stamp())
    assert (sot.target / "a.png").read_bytes() == b"IMG-V1"

    # promote V2 (V1 goes to the attic)
    base1 = qa.head()
    ops.write_bytes("a.png", b"IMG-V2-bigger")
    unit1 = _unit(base1)
    r1 = apply_unit(unit1, qa, sot, expected_stamp=r0.sot_stamp)
    assert (sot.target / "a.png").read_bytes() == b"IMG-V2-bigger"

    # roll back V2 -> SOT holds V1 again, re-materialized from the attic
    rollback_unit(unit1, qa, sot, expected_stamp=r1.sot_stamp)
    assert (sot.target / "a.png").read_bytes() == b"IMG-V1"


def test_binary_add_rollback_removes_it_from_sot(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    base = qa.head()
    ops.write_bytes("new.png", b"ADDED")
    unit = _unit(base)
    r = apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())
    assert (sot.target / "new.png").exists()

    rollback_unit(unit, qa, sot, expected_stamp=r.sot_stamp)
    assert not (sot.target / "new.png").exists()  # added binary removed on rollback


def test_forged_sidecar_stops_the_promotion_at_the_gate(tmp_path):
    """End-to-end wiring of the pointer gate: a binary whose sidecar no longer
    describes it must not reach SOT. Constructed by real path, since the tool
    surface can no longer author a sidecar at all."""
    qa, ops = _setup(tmp_path)
    base = qa.head()
    ops.write_bytes("img/a.png", b"IMG-V1", make_parents=True)

    # Divergence: the bytes change, the sidecar keeps describing the old ones.
    (qa.root / "img" / "a.png").write_bytes(b"SUBSTITUTED-BYTES")

    sot = FilesTransport(tmp_path / "sot")
    res = run_promotion(
        qa,
        sot,
        workflow="form_drafting",
        base_commit=base,
        description="binary with a stale sidecar",
        expected_stamp=sot.current_stamp(),
    )

    assert not res.ok and res.status == "gates_failed"
    pointer = [g for g in res.unit.gates if g.name == "pointer"]
    assert pointer and not pointer[0].ok
    assert "img/a.png" in pointer[0].messages[0]
    # Nothing converged: SOT never saw the substituted bytes.
    assert not (sot.target / "img" / "a.png").exists()


def test_pointer_gate_runs_on_binary_units_and_passes_when_consistent(tmp_path):
    qa, ops = _setup(tmp_path)
    base = qa.head()
    ops.write_bytes("img/a.png", b"IMG-V1", make_parents=True)

    sot = FilesTransport(tmp_path / "sot")
    res = run_promotion(
        qa,
        sot,
        workflow="form_drafting",
        base_commit=base,
        description="clean binary add",
        expected_stamp=sot.current_stamp(),
    )

    assert res.ok
    assert [g.name for g in res.unit.gates if g.name == "pointer"] == ["pointer"]
    assert (sot.target / "img" / "a.png").read_bytes() == b"IMG-V1"
