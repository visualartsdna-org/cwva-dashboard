"""Leaving without saving puts the sandbox back (promotion/episode.py).

Rick, 2026-09-18: "in every form I've ever used, if I exit the form without
explicitly saving, when I come back the record state is the original state, not
some state I never explicitly saved." It was not true here — a submit wrote the
record into QA and the review stop gated only the SOT — and the behaviour was
unguessable: "no user will understand it."

The commit point is Approve & distribute. These are the three things that makes
true: a modified record goes back, a created record goes away, and a replaced
binary comes back out of the attic.
"""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.episode import EpisodeStore
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.sandbox.pointers import PointerManager

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

RECORD = '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\nex:a rdfs:label "One" .\n'


@pytest.fixture
def qa(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    repo = QAGit.init(root)
    (root / "content" / "ttl" / "data").mkdir(parents=True)
    (root / "content" / "ttl" / "data" / "w1.ttl").write_text(RECORD)
    repo.stage_all()
    repo.commit("baseline")
    return repo


@pytest.fixture
def store(qa):
    return EpisodeStore(qa, pointers=PointerManager(qa.root))


def _rec(qa, name="w1.ttl"):
    return qa.root / "content" / "ttl" / "data" / name


def test_a_MODIFIED_record_goes_back(store, qa):
    store.begin("edit_record", "content/ttl/data/w1.ttl")
    _rec(qa).write_text(RECORD.replace("One", "Two"))

    out = store.abandon()

    assert out["abandoned"]
    assert _rec(qa).read_text() == RECORD


def test_a_CREATED_record_goes_away(store, qa):
    """"As it was" for a thing that did not exist is not existing."""
    store.begin("rdf_entry", "/rdf/entry")
    _rec(qa, "new.ttl").write_text(RECORD)

    out = store.abandon()

    assert not _rec(qa, "new.ttl").exists()
    assert "content/ttl/data/new.ttl" in out["removed"]


def test_work_that_was_ALREADY_THERE_is_left_alone(store, qa):
    """The restore is scoped to this session. A draft staged yesterday and not
    touched today is nobody's business — reverting to HEAD would eat it."""
    _rec(qa, "yesterday.ttl").write_text(RECORD)

    store.begin("annotate_work", "work:w1")
    _rec(qa).write_text(RECORD.replace("One", "Two"))
    store.abandon()

    assert _rec(qa, "yesterday.ttl").exists()


def test_an_UNTRACKED_file_edited_today_still_goes_back(store, qa):
    """`git stash create` captures tracked modifications only, so this is the
    case that decides the snapshot mechanism: yesterday's draft is untracked,
    uncommitted and entirely real."""
    _rec(qa, "yesterday.ttl").write_text(RECORD)

    store.begin("edit_record", "content/ttl/data/yesterday.ttl")
    _rec(qa, "yesterday.ttl").write_text(RECORD.replace("One", "Changed"))
    store.abandon()

    assert _rec(qa, "yesterday.ttl").read_text() == RECORD


def test_SUBMITTING_AGAIN_builds_on_the_same_restore_point(store, qa):
    """Submit, read the review, go back, submit again: one piece of work, and
    its restore point is where the user started — not where their second
    thoughts started."""
    store.begin("edit_record", "content/ttl/data/w1.ttl")
    _rec(qa).write_text(RECORD.replace("One", "Two"))
    again = store.begin("edit_record", "content/ttl/data/w1.ttl")
    _rec(qa).write_text(RECORD.replace("One", "Three"))

    assert again["continued"]
    store.abandon()
    assert _rec(qa).read_text() == RECORD


def test_APPROVING_drops_the_restore_point(store, qa):
    store.begin("edit_record", "content/ttl/data/w1.ttl")
    _rec(qa).write_text(RECORD.replace("One", "Two"))

    store.approved()

    assert store.open() is None
    assert store.abandon() == {"abandoned": False, "reason": "nothing open"}
    assert _rec(qa).read_text() != RECORD, "approved work is not undone"


def test_a_DIFFERENT_workflow_supersedes_rather_than_reverting(store, qa):
    """Abandoning is explicit. Reverting on the guess that starting something
    else meant abandoning would delete a record nobody asked to delete."""
    store.begin("rdf_entry", "/rdf/entry")
    _rec(qa, "new.ttl").write_text(RECORD)

    out = store.begin("annotate_work", "work:w1")

    assert out["superseded"] == {"workflow": "rdf_entry", "subject": "/rdf/entry"}
    assert _rec(qa, "new.ttl").exists()


def test_the_restore_point_SURVIVES_A_RESTART(store, qa):
    """On disk, not in memory: a restart must not cost the ability to undo."""
    store.begin("edit_record", "content/ttl/data/w1.ttl")
    _rec(qa).write_text(RECORD.replace("One", "Two"))

    fresh = EpisodeStore(qa, pointers=PointerManager(qa.root))
    fresh.abandon()

    assert _rec(qa).read_text() == RECORD


def test_a_REPLACED_BINARY_comes_back_out_of_the_attic(store, qa):
    """Git holds the sidecar, never the bytes. Without the pointer reconcile a
    restore would put back `image.jpg.ptr` and leave the wrong JPEG on disk."""
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    ops = FileOps(Sandbox.open(qa.root, create=False))
    ops.write_bytes("content/images/pic.jpg", b"\xff\xd8original", make_parents=True)
    qa.stage_all(); qa.commit("the image")

    store.begin("edit_record", "content/ttl/data/w1.ttl")
    ops.write_bytes("content/images/pic.jpg", b"\xff\xd8replacement")
    assert (qa.root / "content/images/pic.jpg").read_bytes() == b"\xff\xd8replacement"

    out = store.abandon()

    assert (qa.root / "content/images/pic.jpg").read_bytes() == b"\xff\xd8original"
    assert "content/images/pic.jpg" in out["restored"]


def test_a_NEW_BINARY_goes_with_its_sidecar(store, qa):
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    ops = FileOps(Sandbox.open(qa.root, create=False))

    store.begin("rdf_entry", "/rdf/entry")
    ops.write_bytes("content/images/fresh.jpg", b"\xff\xd8new", make_parents=True)

    store.abandon()

    assert not (qa.root / "content/images/fresh.jpg").exists()
    assert not (qa.root / "content/images/fresh.jpg.ptr").exists()


def test_DISCARDING_WORK_IN_PROGRESS_drops_the_restore_point(tmp_path, qa):
    """A snapshot that outlives its tree is worse than none: pressing Discard on
    a review page left open from before would put back the very files the user
    had just thrown away."""
    from cwva_dashboard.promotion.driver import PromotionDriver
    from cwva_dashboard.promotion.transports import FilesTransport

    drv = PromotionDriver(qa, FilesTransport(tmp_path / "sot"))
    drv.begin_episode("edit_record", "content/ttl/data/w1.ttl")
    _rec(qa).write_text(RECORD.replace("One", "Two"))

    drv.discard_work_in_progress()
    assert _rec(qa).read_text() == RECORD, "wip discard restores HEAD"

    out = drv.abandon_episode()

    assert not out["abandoned"], "there is nothing left to put back"
    assert _rec(qa).read_text() == RECORD


def test_abandoning_REPORTS_what_it_put_back(store, qa):
    """An undo that reports nothing is indistinguishable from an undo that did
    nothing — and the page showed exactly that: "Discarded", with no list
    (Rick, 2026-09-19). A restored record is neither created nor deleted, so it
    appeared in none of the categories the page knew about."""
    store.begin("annotate_work", "work:w1")
    _rec(qa).write_text(RECORD.replace("One", "Two"))

    out = store.abandon()

    assert out["reverted"] == ["content/ttl/data/w1.ttl"]
