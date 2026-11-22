"""The QA trash gets an end: convergence.

Nothing hard-deletes what the user typed — a replaced image, a superseded
record, a draft abandoned at the review stop all move to `.qa/trash` (CE_DESIGN
§2.3). Rick's sandbox held 82 entries and 42 MB going back two weeks, with
nothing to prune them: insurance with no expiry is sediment.

His call, and the right one: prune after a SUCCESSFUL convergence, because that
is the moment the work a draft belonged to is definitively somewhere else. Not
on a timer, not on startup, and not when a promotion fails.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import time

import pytest

from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.trash import prune
from cwva_dashboard.workflows.promote import run_promotion

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

DAY = 86400


def _aged(path, days: float, body: str = "x"):
    """A trash entry that looks `days` old to the filesystem."""
    path = Path(path)
    if not path.exists():
        path.write_text(body)
    when = time.time() - days * DAY
    os.utime(path, (when, when))
    return path


@pytest.fixture
def trash(tmp_path):
    root = tmp_path / "qa"
    (root / ".qa" / "trash").mkdir(parents=True)
    return root


def test_it_removes_the_OLD_and_keeps_the_RECENT(trash):
    """A draft trashed minutes ago by an Edit-form round trip must survive a
    promotion that happens in between — the user is still in the middle of it."""
    old = _aged(trash / ".qa/trash/20260101T000000-aaaa-old.ttl", 45, "old draft")
    recent = _aged(trash / ".qa/trash/20260917T000000-bbbb-recent.ttl", 0.01,
                   "today's draft")

    result = prune(trash, keep_days=30)

    assert result.removed == 1 and result.kept == 1
    assert not old.exists() and recent.exists()
    assert result.bytes_freed == len("old draft")


def test_zero_days_means_KEEP_EVERYTHING(trash):
    """How a deployment opts out, rather than a magic number meaning "forever"
    and another meaning "immediately"."""
    old = _aged(trash / ".qa/trash/x.ttl", 999)

    assert prune(trash, keep_days=0).removed == 0
    assert old.exists()


def test_one_unreadable_entry_does_not_stop_the_rest(trash):
    """And does not raise: this runs after the content has already reached the
    SOT, where raising would report a successful publish as an error."""
    good = _aged(trash / ".qa/trash/a-good.ttl", 40, "gone")
    stuck = trash / ".qa/trash/b-stuck"
    stuck.mkdir()
    (stuck / "inner.txt").write_text("held")
    _aged(stuck, 40)
    stuck.chmod(0o500)  # can read, cannot remove from
    try:
        result = prune(trash, keep_days=30)
    finally:
        stuck.chmod(0o700)

    assert not good.exists(), "the readable one still went"
    assert result.removed >= 1


def test_the_ATTIC_is_never_touched(trash):
    """It is the rollback reserve (law 6). A replaced binary lives there so a
    revert can put it back; pruning it would make a rollback that succeeds in
    git fail on disk."""
    attic = trash / ".qa" / "attic"
    attic.mkdir(parents=True)
    kept = _aged(attic / "deadbeef", 400, "superseded image")

    prune(trash, keep_days=1)

    assert kept.exists()


def test_a_missing_trash_dir_is_not_an_error(tmp_path):
    assert prune(tmp_path / "nothing-here", keep_days=30).removed == 0


# ---------------------------------------------------------------------------
# Where it runs: after convergence, and only after convergence.
# ---------------------------------------------------------------------------

def _qa_with_trash(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    qa = QAGit.init(root)
    (root / ".qa" / "trash").mkdir(parents=True)
    stale = _aged(root / ".qa/trash/old-draft.ttl", 90, "an abandoned draft")
    return qa, stale


def test_a_CONVERGED_promotion_prunes(tmp_path):
    qa, stale = _qa_with_trash(tmp_path)
    base = qa.commit("seed", allow_empty=True)
    (qa.root / "w.ttl").write_text("@prefix ex: <http://e/> .\nex:a ex:b ex:c .\n")

    result = run_promotion(qa, FilesTransport(tmp_path / "sot"), workflow="t",
                           base_commit=base, description="d", refresh_after=False,
                           backup_after=False, trash_keep_days=30)

    assert result.status == "converged"
    assert result.pruned["removed"] == 1
    assert not stale.exists()


def test_a_PREVIEW_prunes_NOTHING(tmp_path):
    """The stop is a stop. Nothing has reached the SOT, so nothing is safe to
    let go of — and a user who rejects at the review must find their own trash
    where they left it."""
    qa, stale = _qa_with_trash(tmp_path)
    base = qa.commit("seed", allow_empty=True)
    (qa.root / "w.ttl").write_text("@prefix ex: <http://e/> .\nex:a ex:b ex:c .\n")

    result = run_promotion(qa, FilesTransport(tmp_path / "sot"), workflow="t",
                           base_commit=base, description="d", preview_only=True,
                           trash_keep_days=30)

    assert result.status == "previewed"
    assert result.pruned is None
    assert stale.exists()


def test_the_prune_is_AUDITED(tmp_path):
    """A deletion nobody can see is a deletion nobody can question — and Rick
    asked not to have a trash screen, so the audit log is where it is answerable."""
    qa, _stale = _qa_with_trash(tmp_path)
    base = qa.commit("seed", allow_empty=True)
    (qa.root / "w.ttl").write_text("@prefix ex: <http://e/> .\nex:a ex:b ex:c .\n")
    events = []

    run_promotion(qa, FilesTransport(tmp_path / "sot"), workflow="t",
                  base_commit=base, description="d", refresh_after=False,
                  backup_after=False, trash_keep_days=30,
                  audit=lambda op, args, outcome: events.append((op, args, outcome)))

    pruned = [e for e in events if e[0] == "qa.trash_pruned"]
    assert pruned and pruned[0][1]["removed"] == 1
    assert pruned[0][2] == "ok"
