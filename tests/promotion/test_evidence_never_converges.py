"""`evidence/` is committed to the QA git and never reaches the SOT.

The claim is old — `workflows/annotate.py` has said "QA git, never pushed to
SOT" since #15 was built — and until 2026-09-29 only `operational/` was
actually excluded, so every evidence file #15 wrote converged. Round 3 of the
DTS review then put the orphan backlog and the agent's proposal history there,
which promoted this from a defect to a blocker: it had to be true before the
first DTS run wrote anything.

The exclusion is in the MANIFEST, not the transport, and the difference is
visible in these tests: the review stop does not list the file, the gates do
not read it, a rollback does not delete it from a SOT that never had it — and
`git log` still shows it.
"""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.promotion.unit import is_local_only

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def qa(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    repo = QAGit.init(root)
    (root / "content" / "ttl" / "data").mkdir(parents=True)
    (root / "content" / "ttl" / "data" / "w1.ttl").write_text("# a record\n")
    base = repo.commit("base")
    return repo, root, base


def test_the_predicate_names_the_directory_not_a_substring():
    assert is_local_only("evidence/dts/g1/derive.ttl")
    assert is_local_only("evidence")
    assert not is_local_only("content/ttl/data/evidence-of-provenance.ttl")
    assert not is_local_only("evidence_notes/x.ttl")


def test_an_evidence_file_is_NOT_in_the_manifest(qa):
    repo, root, base = qa
    (root / "evidence").mkdir()
    (root / "evidence" / "orphans.ttl").write_text("# backlog\n")
    (root / "content" / "ttl" / "data" / "w2.ttl").write_text("# another\n")

    m = repo.manifest_since(base)

    assert "content/ttl/data/w2.ttl" in m.adds
    assert not any(p.startswith("evidence/") for p in m.all_paths())


def test_it_IS_in_the_git_history(qa):
    """History is the whole reason it lives here rather than in `.qa/`, which
    is gitignored and would not survive rebuilding the sandbox."""
    repo, root, base = qa
    (root / "evidence").mkdir()
    (root / "evidence" / "orphans.ttl").write_text("# backlog\n")

    repo.commit("dts: derivation evidence")

    assert "evidence/orphans.ttl" in repo._run("show", "--name-only", "HEAD")


def test_it_does_not_reach_the_TARGET(qa, tmp_path):
    repo, root, base = qa
    (root / "evidence").mkdir()
    (root / "evidence" / "orphans.ttl").write_text("# backlog\n")
    (root / "content" / "ttl" / "data" / "w2.ttl").write_text("# another\n")
    target = tmp_path / "sot"
    transport = FilesTransport(target)

    transport.converge(root, repo.manifest_since(base))

    assert (target / "content/ttl/data/w2.ttl").exists()
    assert not (target / "evidence").exists()


def test_an_evidence_ONLY_change_is_an_empty_promotion_unit(qa):
    """Nothing to distribute, and the review stop should say so rather than
    offer to publish the curator's working notes."""
    repo, root, base = qa
    (root / "evidence").mkdir()
    (root / "evidence" / "orphans.ttl").write_text("# backlog\n")

    assert repo.manifest_since(base).is_empty()


# -- and the REFRESH that follows a promotion must not delete it -------------
#
# The second of two independent faults making the same claim false. The
# manifest shipped evidence to the SOT (above); the refresh that runs after
# every successful convergence then DELETED it, because `sync` brings the tree
# into line with the target and the target deliberately never holds it.
#
# So every evidence file #15 and DTS ever wrote was destroyed moments after
# being committed. Found 2026-10-01 by noticing six empty directories and a
# staged deletion in Rick's sandbox, and traced through the reflog: a `reset`
# one second after the promotion commit.


def test_the_SYNC_does_not_see_local_only_paths(qa, tmp_path):
    """The whole fix: the SOT has no opinion about `evidence/`, so a comparison
    against the target must not include it in either direction."""
    from cwva_dashboard.sot_sync.sync import _content_snapshot

    _repo, root, _base = qa
    (root / "evidence").mkdir()
    (root / "evidence" / "orphans.ttl").write_text("# backlog\n")

    snapshot = _content_snapshot(root)

    assert not any(p.startswith("evidence/") for p in snapshot)
    assert "content/ttl/data/w1.ttl" in snapshot


def test_a_FULL_PROMOTION_leaves_evidence_on_disk(qa, tmp_path):
    """The end-to-end claim, through the path that broke it: preview, approve,
    converge, and the refresh that follows."""
    from cwva_dashboard.promotion.driver import PromotionDriver
    from cwva_dashboard.promotion.layout import Layout

    repo, root, _base = qa
    evidence = root / "evidence" / "dts" / "g1"
    evidence.mkdir(parents=True)
    (evidence / "derive.ttl").write_text("# the curation record\n")
    (root / "content" / "ttl" / "data" / "w2.ttl").write_text("# new\n")

    driver = PromotionDriver(repo, FilesTransport(tmp_path / "sot"),
                             layout=Layout.default())
    out = driver.preview(workflow="t", description="t",
                         context={"values": {}, "minted": []})
    result = driver.approve(out["token"])

    assert result["status"] == "converged"
    assert (evidence / "derive.ttl").exists(), "the refresh deleted it"
    assert "evidence/dts/g1/derive.ttl" in repo._run(
        "ls-tree", "-r", "--name-only", "HEAD"), "and it is in the history"
    assert not (tmp_path / "sot" / "evidence").exists(), "but not in the SOT"


def test_a_nested_directory_NAMED_evidence_is_still_content(qa):
    """The exclusion is the top-level directory, not the word. A work whose
    path happens to contain it is ordinary content."""
    from cwva_dashboard.sot_sync.sync import _content_snapshot

    _repo, root, _base = qa
    deep = root / "content" / "ttl" / "evidence"
    deep.mkdir(parents=True)
    (deep / "w9.ttl").write_text("# a record that lives under that name\n")

    assert "content/ttl/evidence/w9.ttl" in _content_snapshot(root)
