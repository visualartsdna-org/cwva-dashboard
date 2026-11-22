"""Backing up what SOT cannot give back.

Two things in the QA tree are irrecoverable, and they are the two law 6 rests
on: the commit history (rollback needs something to revert TO) and `.qa/attic`
(superseded binaries — SOT holds the replacement by definition). Content and
`.ptr` sidecars are not: SOT holds the content, and sidecars regenerate from the
binaries.

The backup writes OUTSIDE the sandbox and is not a promotion. That is a narrow,
structural carve-out from law 1: a repository cannot back itself up into itself.
"""

from __future__ import annotations

import shutil
import subprocess
import tarfile

import pytest

from cwva_dashboard.backup import OPERATIONAL_PREFIX, attic_status, run_backup
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.sot_sync.sync import sync

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def env(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    (qa_root / "a.ttl").write_text("@prefix x: <http://x/> .\nx:a x:b x:c .\n")
    qa.stage_all()
    qa.commit("first")
    return qa, FilesTransport(tmp_path / "sot"), tmp_path


def test_the_attic_count_is_zero_until_something_is_superseded(env):
    qa, _t, _tmp = env
    assert attic_status(qa.root) == {"files": 0, "bytes": 0, "path": ".qa/attic"}


def test_a_backup_writes_the_bundle_to_the_operational_prefix(env):
    qa, transport, tmp_path = env

    res = run_backup(qa.root, transport)

    assert res.ok and res.commits >= 1  # QAGit.init commits, then the fixture does
    bundle = tmp_path / "sot" / OPERATIONAL_PREFIX / "qa.bundle"
    assert bundle.is_file() and bundle.stat().st_size > 0
    assert res.written == [f"{OPERATIONAL_PREFIX}/qa.bundle"]


def test_the_bundle_really_restores_the_history(env):
    """The point of the exercise. A bundle that cannot be cloned is a file, not
    a backup."""
    qa, transport, tmp_path = env
    run_backup(qa.root, transport)

    restored = tmp_path / "restored"
    subprocess.run(
        ["git", "clone", "-q", str(tmp_path / "sot" / OPERATIONAL_PREFIX / "qa.bundle"),
         str(restored)],
        check=True, capture_output=True,
    )

    log = subprocess.run(["git", "-C", str(restored), "log", "--oneline"],
                         capture_output=True, text=True).stdout
    assert "first" in log
    assert (restored / "a.ttl").is_file()


def test_the_attic_travels_as_its_own_archive(env):
    """It is gitignored, so the bundle cannot carry it. It travels separately or
    it does not travel at all."""
    qa, transport, tmp_path = env
    attic = qa.root / ".qa" / "attic"
    attic.mkdir(parents=True)
    (attic / "deadbeef").write_bytes(b"\xff\xd8superseded image bytes")

    res = run_backup(qa.root, transport)

    assert res.attic_files == 1
    archive = tmp_path / "sot" / OPERATIONAL_PREFIX / "qa-attic.tar.gz"
    assert archive.is_file()
    with tarfile.open(archive) as tar:
        assert any(m.name.endswith("deadbeef") for m in tar.getmembers())


def test_no_attic_means_no_archive(env):
    """An empty archive every run would be noise in the target."""
    qa, transport, tmp_path = env
    run_backup(qa.root, transport)

    assert not (tmp_path / "sot" / OPERATIONAL_PREFIX / "qa-attic.tar.gz").exists()


def test_the_backup_NEVER_syncs_back(env):
    """Without the exclusion the next refresh pulls the backup into the tree it
    is a backup OF, mints it a sidecar and makes it content — a repository
    carrying its own history as data, growing every cycle."""
    qa, transport, tmp_path = env
    # Put the content in SOT first, so the sync has nothing else to do and any
    # change it makes is attributable to the backup.
    (tmp_path / "sot").mkdir(exist_ok=True)
    (tmp_path / "sot" / "a.ttl").write_text((qa.root / "a.ttl").read_text())
    run_backup(qa.root, transport)

    sync(qa, transport)

    assert not (qa.root / OPERATIONAL_PREFIX).exists(), "operational state is not content"
    changed = qa.manifest_since(qa.head()).all_paths()
    assert not [c for c in changed if c.startswith(OPERATIONAL_PREFIX)], changed


def test_the_sandbox_is_untouched_by_a_backup(env):
    """Built in a temp dir and uploaded from there: the tree being backed up is
    never a workspace for its own backup."""
    qa, transport, _tmp = env
    before = sorted(p.name for p in qa.root.rglob("*") if p.is_file())

    run_backup(qa.root, transport)

    assert sorted(p.name for p in qa.root.rglob("*") if p.is_file()) == before


def test_a_transport_that_cannot_store_operational_state_says_so(env):
    """Deliberately a separate method from `converge`, so a transport can simply
    not implement it and nothing in the content path is affected."""
    from cwva_dashboard.promotion.transports import Transport

    # A stand-in: git used to be the example, and since 2026-11-21 it keeps
    # backups beside the checkout, so the base behaviour is tested directly.
    class NoBackups(Transport):
        current_stamp = converge = snapshot = fetch = lambda *a, **k: None

    with pytest.raises(NotImplementedError):
        NoBackups().put_operational("operational/x", b"")


# -- automatic after a successful promotion ----------------------------------


def test_a_successful_promotion_backs_up_the_history(tmp_path):
    """A promotion is exactly the moment new history exists worth keeping, and
    the QA git is the only copy of it."""
    from cwva_dashboard.promotion.unit import GateResult
    from cwva_dashboard.workflows.promote import run_promotion

    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    transport = FilesTransport(tmp_path / "sot")
    (qa_root / "a.ttl").write_text("@prefix x: <http://x/> .\nx:a x:b x:c .\n")

    res = run_promotion(qa, transport, workflow="t", base_commit=qa.head(),
                        description="first")

    assert res.ok
    assert res.backup and res.backup["ok"], res.backup
    assert (tmp_path / "sot" / OPERATIONAL_PREFIX / "qa.bundle").is_file()


def test_a_failing_backup_does_NOT_fail_the_promotion(tmp_path):
    """The content has already reached SOT by then. Raising would report a
    successful publish as an error and invite a re-run with nothing to do."""
    from cwva_dashboard.workflows.promote import run_promotion

    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    transport = FilesTransport(tmp_path / "sot")
    (qa_root / "a.ttl").write_text("@prefix x: <http://x/> .\nx:a x:b x:c .\n")

    def boom(rel, data):
        raise RuntimeError("bucket unreachable")

    transport.put_operational = boom

    res = run_promotion(qa, transport, workflow="t", base_commit=qa.head(),
                        description="first")

    assert res.ok, "the promotion still converged"
    assert res.backup and res.backup["ok"] is False
    assert "bucket unreachable" in res.backup["error"], "and it is recorded, not swallowed"


def test_a_promotion_that_does_not_converge_backs_up_nothing(tmp_path):
    """Nothing new to keep, and a bundle per rejected attempt would be noise."""
    from cwva_dashboard.workflows.promote import run_promotion

    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    transport = FilesTransport(tmp_path / "sot")

    res = run_promotion(qa, transport, workflow="t", base_commit=qa.head())

    assert res.status == "empty"
    assert res.backup is None
    assert not (tmp_path / "sot" / OPERATIONAL_PREFIX).exists()


def test_the_backup_does_not_trip_the_next_promotion_s_drift_check(tmp_path):
    """The stamp describes CONTENT. A promotion writes the backup, so if the
    stamp covered it, the very next promotion would compare against a stamp the
    previous one invalidated and abort with DriftError — found exactly that way,
    by two scenarios failing after the backup was made automatic."""
    from cwva_dashboard.workflows.promote import run_promotion

    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    transport = FilesTransport(tmp_path / "sot")

    (qa_root / "a.ttl").write_text("@prefix x: <http://x/> .\nx:a x:b x:c .\n")
    first = run_promotion(qa, transport, workflow="t", base_commit=qa.head())
    assert first.ok and first.backup["ok"]

    (qa_root / "b.ttl").write_text("@prefix x: <http://x/> .\nx:d x:e x:f .\n")
    second = run_promotion(qa, transport, workflow="t", base_commit=qa.head(),
                           expected_stamp=first.applied.sot_stamp)

    assert second.ok, "a backup is not content drift"


def test_the_stamp_ignores_operational_state(tmp_path):
    transport = FilesTransport(tmp_path / "sot")
    (tmp_path / "sot").mkdir(exist_ok=True)
    (tmp_path / "sot" / "a.ttl").write_text("x")
    before = transport.current_stamp()

    transport.put_operational("operational/qa.bundle", b"a backup")

    assert transport.current_stamp() == before


def test_the_ledger_is_backed_up_beside_the_bundle(env):
    """The workflow board's ticks are dated only here (2026-11-19)."""
    from cwva_dashboard.concepts.ledger import LEDGER_PATH, HygieneLedger

    qa, transport, tmp_path = env
    ledger = HygieneLedger.from_ttl()
    ledger.dismiss("board:A:website", "http://example.org/work/w1", "done")
    (qa.root / LEDGER_PATH).parent.mkdir(parents=True, exist_ok=True)
    (qa.root / LEDGER_PATH).write_text(ledger.to_ttl())

    res = run_backup(qa.root, transport)

    copy = tmp_path / "sot" / OPERATIONAL_PREFIX / "qa-ledger.ttl"
    assert f"{OPERATIONAL_PREFIX}/qa-ledger.ttl" in res.written
    assert res.ledger_bytes == copy.stat().st_size > 0
    restored = HygieneLedger.from_ttl(copy.read_text())
    assert restored.dismissals_at("board:A:website").keys() == {"http://example.org/work/w1"}


def test_no_ledger_no_ledger_file(env):
    qa, transport, tmp_path = env
    res = run_backup(qa.root, transport)
    assert res.ledger_bytes == 0
    assert not (tmp_path / "sot" / OPERATIONAL_PREFIX / "qa-ledger.ttl").exists()
