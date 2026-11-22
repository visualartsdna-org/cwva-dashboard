"""A0 — the human-driven promotion driver: gates → preview → STOP → approve.

The property under test is not "promotion works" (that is `test_apply.py`) but
"nothing converges without a human decision, and what converges is what was
reviewed."
"""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.driver import PromotionDriver, PromotionDriverError
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

TTL = "@prefix ex: <http://example.org/> .\nex:a ex:b ex:c .\n"


def _setup(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    sot = FilesTransport(tmp_path / "sot")
    return qa, sot, PromotionDriver(qa, sot)


def _write(qa, rel: str, body: str = TTL):
    p = qa.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_preview_converges_nothing(tmp_path):
    """The stop is real: after previewing, SOT is still empty and QA uncommitted."""
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")

    out = driver.preview(workflow="entry", description="one work")

    assert out["status"] == "previewed"
    assert out["token"]
    assert out["manifest"]["adds"] == 1
    assert list(sot.target.rglob("*.ttl")) == [], "preview must not converge"
    assert qa.status_porcelain().strip(), "work must remain uncommitted"


def test_approve_converges_and_refreshes(tmp_path):
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")

    token = driver.preview(workflow="entry")["token"]
    out = driver.approve(token)

    assert out["status"] == "converged"
    assert (sot.target / "content/ttl/data/w1.ttl").exists()
    assert out["refreshed"] is True
    assert not qa.status_porcelain().strip(), "converged work is committed"


def test_reject_leaves_qa_and_sot_untouched(tmp_path):
    """Reject before convergence abandons the unit: SOT never saw it, and the
    QA work is still there to fix rather than lost."""
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")
    head_before = qa.head()

    token = driver.preview(workflow="entry")["token"]
    out = driver.reject(token)

    assert out["status"] == "rejected"
    assert list(sot.target.rglob("*.ttl")) == []
    assert qa.head() == head_before
    assert (qa.root / "content/ttl/data/w1.ttl").exists()


def test_a_decided_token_cannot_be_reused(tmp_path):
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")
    token = driver.preview(workflow="entry")["token"]
    driver.reject(token)

    with pytest.raises(PromotionDriverError, match="unknown or already-decided"):
        driver.approve(token)


def test_approving_a_changed_tree_is_STALE_not_converged(tmp_path):
    """The load-bearing case. If the QA tree changes between preview and
    approval, the human's approval no longer describes the change — so it must
    abort rather than converge something nobody reviewed."""
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")
    token = driver.preview(workflow="entry")["token"]

    # a second work appears after the human looked at the preview
    _write(qa, "content/ttl/data/w2.ttl")

    out = driver.approve(token)

    assert out["status"] == "stale"
    assert out["was"] != out["now"]
    assert list(sot.target.rglob("*.ttl")) == [], "nothing may converge on stale"
    assert driver.pending() == [], "the stale token is spent"


def test_gate_failure_yields_no_approvable_token(tmp_path):
    """Unparseable RDF fails the parse gate, so there is nothing to approve —
    the stop cannot be walked past by holding a token."""
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/bad.ttl", "this is not turtle {{{")

    out = driver.preview(workflow="entry")

    assert out["status"] == "gates_failed"
    assert "token" not in out
    assert any(not g["ok"] for g in out["gates"])
    assert list(sot.target.rglob("*.ttl")) == []


def test_empty_manifest_is_reported_not_promoted(tmp_path):
    qa, sot, driver = _setup(tmp_path)
    out = driver.preview(workflow="entry")
    assert out["status"] == "empty"
    assert "token" not in out


def test_pending_lists_what_awaits_a_decision(tmp_path):
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")
    driver.preview(workflow="entry", description="one work")

    pend = driver.pending()
    assert len(pend) == 1
    assert pend[0]["workflow"] == "entry"
    assert pend[0]["description"] == "one work"


def test_hand_placed_binaries_become_visible_to_promotion(tmp_path):
    """A binary dropped into the sandbox outside fileops has no .ptr sidecar, and
    the sidecar is the only thing the git-derived manifest can see — so without
    reconciliation it is silently never converged, while the record referencing
    it lands on SOT anyway. Found on the first real approve."""
    qa, sot, driver = _setup(tmp_path)
    images = qa.root / "content" / "images"
    images.mkdir(parents=True)
    (images / "by-hand.jpg").write_bytes(b"\xff\xd8jpeg")  # a plain copy, no fileops
    _write(qa, "content/ttl/data/w1.ttl")

    out = driver.preview(workflow="entry")

    assert (images / "by-hand.jpg.ptr").is_file(), "sidecar must be minted"
    token = out["token"]
    assert driver.approve(token)["status"] == "converged"
    # the real bytes reach SOT, not the sidecar
    assert (sot.target / "content/images/by-hand.jpg").is_file()
    assert not (sot.target / "content/images/by-hand.jpg.ptr").exists()


# -- discard work in progress ------------------------------------------------


def test_wip_reports_the_pile_a_promotion_would_sweep_up(tmp_path):
    """Abandoned submissions accumulate: a promotion unit is everything
    uncommitted since the base commit (law 4)."""
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")
    _write(qa, "content/ttl/data/w2.ttl")

    wip = driver.work_in_progress()

    assert wip["clean"] is False
    assert wip["counts"]["adds"] == 2
    assert "content/ttl/data/w1.ttl" in wip["adds"]


def test_discard_restores_qa_to_head(tmp_path):
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")
    head_before = qa.head()

    out = driver.discard_work_in_progress()

    assert out["discarded"] is True
    assert not (qa.root / "content/ttl/data/w1.ttl").exists()
    assert qa.head() == head_before, "history must not move"
    assert driver.work_in_progress()["clean"] is True


def test_discard_removes_orphaned_MANAGED_BINARIES_too(tmp_path):
    """The binary policy makes this two steps: restoring tracked files removes
    the .ptr sidecar, and only reconciliation removes the gitignored binary it
    described. Otherwise the image survives as an orphan — on disk, invisible to
    git, and swept into some later manifest."""
    qa, sot, driver = _setup(tmp_path)
    images = qa.root / "content" / "images"
    images.mkdir(parents=True)
    (images / "stray.jpg").write_bytes(b"\xff\xd8jpeg")
    _write(qa, "content/ttl/data/w1.ttl")
    driver.work_in_progress()  # mints the sidecar
    assert (images / "stray.jpg.ptr").is_file()

    driver.discard_work_in_progress()

    assert not (images / "stray.jpg.ptr").exists(), "sidecar gone"
    assert not (images / "stray.jpg").exists(), "orphaned binary must go too"


def test_discard_never_touches_sot_or_committed_work(tmp_path):
    """Narrow by design: converged work is rollback's problem, not this one."""
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/kept.ttl")
    driver.approve(driver.preview(workflow="entry")["token"])
    assert (sot.target / "content/ttl/data/kept.ttl").exists()
    head_after_promote = qa.head()

    _write(qa, "content/ttl/data/scratch.ttl")
    driver.discard_work_in_progress()

    assert (sot.target / "content/ttl/data/kept.ttl").exists(), "SOT untouched"
    assert (qa.root / "content/ttl/data/kept.ttl").exists(), "committed work kept"
    assert not (qa.root / "content/ttl/data/scratch.ttl").exists()
    assert qa.head() == head_after_promote


def test_discard_on_a_clean_tree_is_a_no_op(tmp_path):
    qa, sot, driver = _setup(tmp_path)
    out = driver.discard_work_in_progress()
    assert out["discarded"] is False and out["clean"] is True


def test_discard_drops_pending_tokens(tmp_path):
    """The tree a token described is gone, so the token is meaningless. Approve
    would catch it as stale anyway; dropping it makes the outcome plain."""
    qa, sot, driver = _setup(tmp_path)
    _write(qa, "content/ttl/data/w1.ttl")
    token = driver.preview(workflow="entry")["token"]

    out = driver.discard_work_in_progress()

    assert out["tokens_dropped"] == 1
    assert driver.pending() == []
    with pytest.raises(PromotionDriverError):
        driver.approve(token)
    assert list(sot.target.rglob("*.ttl")) == []
