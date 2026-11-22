"""SOT→QA sync, adopt, refresh, and drift detection over files + git SOTs."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.apply import apply_unit
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport, GitLocalTransport
from cwva_dashboard.promotion.unit import GateResult, PromotionUnit
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.sot_sync.sync import adopt_external, refresh, sync

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _setup(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    qa = QAGit.init(root)
    ops = FileOps(Sandbox.open(root))
    return qa, ops


def _unit(base):
    u = PromotionUnit(workflow="derive", base_commit=base, provenance={"actor": "agent"})
    u.add_gate(GateResult("parse", ok=True))
    u.settle_gate_status()
    return u


def _promote(qa, ops, sot, write):
    base = qa.head()
    write()
    unit = _unit(base)
    return apply_unit(unit, qa, sot, expected_stamp=sot.current_stamp())


def test_sync_clean_when_sot_unchanged(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))

    res = sync(qa, sot)
    assert res.clean
    assert res.drift.is_empty()


def test_sync_detects_out_of_band_edit(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))

    # Someone edits SOT directly, behind QA's back.
    (sot.target / "a.ttl").write_text("EDITED OUTSIDE")

    res = sync(qa, sot)
    assert not res.clean
    assert res.drift.modifies == ["a.ttl"]
    # The edit was pulled into QA content but not yet committed.
    assert (qa.root / "a.ttl").read_text() == "EDITED OUTSIDE"


def test_sync_detects_external_addition_and_deletion(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))

    (sot.target / "b.ttl").write_text("NEW")   # external add
    (sot.target / "a.ttl").unlink()            # external delete

    res = sync(qa, sot)
    assert res.drift.adds == ["b.ttl"]
    assert res.drift.deletes == ["a.ttl"]


def test_adopt_external_makes_a_new_baseline(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))
    (sot.target / "a.ttl").write_text("EDITED OUTSIDE")

    sync(qa, sot)
    head_before = qa.head()
    commit = adopt_external(qa)
    assert commit == qa.head() != head_before
    # After adopting, a fresh sync is clean (QA HEAD == SOT).
    assert sync(qa, sot).clean


def test_refresh_discards_wip_then_syncs(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))

    # Uncommitted work in progress in QA.
    ops.write_text("wip.ttl", "scratch")
    ops.write_text("a.ttl", "locally changed")

    res = refresh(qa, sot)
    assert res.clean  # SOT unchanged, WIP gone
    assert not (qa.root / "wip.ttl").exists()
    assert (qa.root / "a.ttl").read_text() == "A1"  # restored to baseline


def test_sync_over_git_local_sot(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = GitLocalTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))
    assert sync(qa, sot).clean

    # Commit an out-of-band change directly in the SOT repo.
    (sot.target / "a.ttl").write_text("EDITED IN SOT")
    import subprocess

    subprocess.run(["git", "-C", str(sot.target), "commit", "-aqm", "ext"], check=True)
    assert sync(qa, sot).drift.modifies == ["a.ttl"]


def test_sync_binary_change_detected_via_pointer(tmp_path):
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_bytes("a.png", b"IMG-V1"))
    assert sync(qa, sot).clean

    # External replacement of the binary in SOT.
    (sot.target / "a.png").write_bytes(b"IMG-V2-DIFFERENT")
    res = sync(qa, sot)
    # Drift surfaces at the tracked .ptr level (the binary itself is gitignored).
    assert res.drift.modifies == ["a.png.ptr"]
    assert (qa.root / "a.png").read_bytes() == b"IMG-V2-DIFFERENT"


def test_refresh_ADOPTS_what_it_pulled(tmp_path):
    """A refresh leaves QA clean and equal to SOT — the pulled state is a
    BASELINE, not the user's work in progress.

    `sync()` deliberately does not commit; its caller "adopts or investigates",
    and the first-sync report is the investigating caller. `refresh` is the
    other kind: it has just discarded work in progress and pulled SOT wholesale.

    Without adopting, everything a refresh pulls stays uncommitted and the next
    promotion sweeps it up (law 4). Found 2026-09-11 after seeding 1093 images
    into the shadow: the next annotation's unit carried 1093 `.ptr` adds, and
    since convergence translates `<x>.ptr` -> `<x>`, approving would have pushed
    3.7 GB of images back to the bucket they came from — and put 1093 unrelated
    files in the annotation's commit, so reverting the annotation would have
    deleted every image from QA.
    """
    qa, ops = _setup(tmp_path)
    sot_dir = tmp_path / "sot"
    sot = FilesTransport(sot_dir)
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))
    # Something arrives in SOT out of band, as a seed or another machine does.
    (sot_dir / "arrived.ttl").write_text("ARRIVED")

    refresh(qa, sot)

    assert (qa.root / "arrived.ttl").is_file(), "it really pulled"
    assert qa.manifest_since(qa.head()).is_empty(), (
        "a refresh must leave nothing for the next promotion to sweep up"
    )


def test_refresh_with_nothing_to_pull_makes_no_commit(tmp_path):
    """An empty commit per refresh would fill the QA history with noise, and
    `commit` refuses an empty unit anyway."""
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))
    refresh(qa, sot)
    before = qa.head()

    refresh(qa, sot)

    assert qa.head() == before


def test_sync_does_not_refetch_unchanged_content(tmp_path):
    """Both sides of the comparison must speak the same hash.

    The local snapshot was sha256-hex and a GCS bucket reports base64 MD5, so
    `have.get(path) != fp` was ALWAYS true and every sync re-downloaded the
    whole store. Correct, but O(everything): invisible while the shadow held
    ~50 MB of TTL, and 3.7 GB per sync after 1093 production images were seeded
    — with an Approve doing two of them, the pre-push check and the
    post-promotion refresh. That was the "seems hung" of 2026-09-11.
    """
    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))

    fetched: list[str] = []
    real = sot.fetch
    sot.fetch = lambda p: (fetched.append(p), real(p))[1]

    sync(qa, sot)

    assert fetched == [], f"nothing changed, so nothing should be fetched: {fetched}"


def test_a_transport_reporting_another_hash_still_compares_correctly(tmp_path):
    """A store that reports base64 MD5 (as GCS does) must still be comparable:
    the transport supplies the local fingerprint so the two sides match."""
    import base64
    import hashlib

    qa, ops = _setup(tmp_path)
    sot = FilesTransport(tmp_path / "sot")
    _promote(qa, ops, sot, lambda: ops.write_text("a.ttl", "A1"))

    # Pretend this transport speaks MD5, on both sides.
    def md5_of_bytes(data):
        return base64.b64encode(hashlib.md5(data).digest()).decode()

    snap = sot.snapshot
    sot.snapshot = lambda: {k: md5_of_bytes((tmp_path / "sot" / k).read_bytes()) for k in snap()}
    sot.local_fingerprint = lambda p: md5_of_bytes(p.read_bytes())

    fetched: list[str] = []
    real = sot.fetch
    sot.fetch = lambda p: (fetched.append(p), real(p))[1]

    sync(qa, sot)

    assert fetched == [], f"unchanged content must not be re-fetched: {fetched}"
