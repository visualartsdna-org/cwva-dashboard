"""The SOT→QA sync runner (gate item B2): opens/initializes the QA repo at a
configured root, pulls a target in, and reports the split the first-sync
checkpoint is stated in."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport, ReadOnlySource
from cwva_dashboard.sot_sync.runner import sync_into_qa
from cwva_dashboard.sot_sync.sync import adopt_external

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _sot(tmp_path, files: dict[str, bytes | str]):
    """A files-transport SOT laid out flat, the way the shadow bucket is."""
    root = tmp_path / "sot"
    root.mkdir()
    for rel, body in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body.encode() if isinstance(body, str) else body)
    return FilesTransport(root)


CONTENT = {
    "ttl/data/w1.ttl": "<a> <b> <c> .",
    "ttl/model/cwva.ttl": "<m> <b> <c> .",
    "ttl/vocab/watercolorPaper.ttl": "<v> <b> <c> .",
    "documents/note.md": "# note",
    "images/pic.jpg": b"\xff\xd8\xff\xe0 not really a jpeg",
    "stats/data.json": '{"a": 1}',
}


def test_first_sync_initializes_qa_and_reports_the_split(tmp_path):
    sot = ReadOnlySource(_sot(tmp_path, CONTENT), label="shadow")
    qa_root = tmp_path / "qa"

    report, result = sync_into_qa(sot, qa_root)

    assert report.initialized is True
    assert (qa_root / ".git").is_dir()
    # Paths are copied VERBATIM: the QA tree adopts the target's flat layout
    # rather than being translated into the default mirror layout (§3.6).
    assert (qa_root / "ttl" / "model" / "cwva.ttl").exists()
    assert not (qa_root / "metacontent").exists()

    # .ttl/.md/.json-by-policy split: 4 git-content files, 2 pointer-managed
    # (.jpg and .json are not in the git-content list).
    assert report.git_content == 4
    assert report.pointer_managed == 2
    assert report.sidecars == 2
    assert report.top_level["ttl"] == 3
    assert result.stamp


def test_sidecars_are_minted_and_binaries_stay_untracked(tmp_path):
    sot = ReadOnlySource(_sot(tmp_path, CONTENT), label="shadow")
    qa_root = tmp_path / "qa"

    sync_into_qa(sot, qa_root)

    assert (qa_root / "images" / "pic.jpg.ptr").exists()
    assert (qa_root / "images" / "pic.jpg").exists()  # real bytes on disk
    # The binary itself is gitignored; only the sidecar is tracked (§3.4).
    tracked = QAGit(root=qa_root)._run("ls-files").split()
    assert "images/pic.jpg.ptr" in tracked
    assert "images/pic.jpg" not in tracked


def test_second_sync_is_a_no_op(tmp_path):
    """Re-runnable, like the seed script: syncing an unchanged SOT twice leaves
    nothing new to adopt. A runner that reported drift every time would make
    real drift unreadable."""
    sot = ReadOnlySource(_sot(tmp_path, CONTENT), label="shadow")
    qa_root = tmp_path / "qa"

    first, _ = sync_into_qa(sot, qa_root)
    adopt_external(QAGit(root=qa_root))

    second, _ = sync_into_qa(sot, qa_root)

    assert second.initialized is False
    assert second.clean, second.summary()
    assert second.objects == first.objects


def test_drift_is_reported_not_committed(tmp_path):
    sot_t = _sot(tmp_path, CONTENT)
    qa_root = tmp_path / "qa"
    sync_into_qa(ReadOnlySource(sot_t, label="shadow"), qa_root)
    adopt_external(QAGit(root=qa_root))

    # An out-of-band SOT edit shows up as drift, and the runner leaves it
    # uncommitted for the operator to adopt or investigate.
    (sot_t.target / "ttl" / "data" / "w2.ttl").write_text("<d> <b> <c> .")
    report, result = sync_into_qa(ReadOnlySource(sot_t, label="shadow"), qa_root)

    assert report.drift_adds == 1
    assert not report.clean
    assert result.drift.adds == ["ttl/data/w2.ttl"]
    assert QAGit(root=qa_root).status_porcelain().strip(), "drift must stay uncommitted"


def test_writable_source_is_refused_by_default(tmp_path):
    """The safe path is the default: handing the runner something it could write
    to takes a deliberate argument, not an oversight."""
    writable = _sot(tmp_path, CONTENT)  # a FilesTransport — has converge()
    qa_root = tmp_path / "qa"

    with pytest.raises(TypeError, match="writable"):
        sync_into_qa(writable, qa_root)

    report, _ = sync_into_qa(writable, qa_root, allow_writable_source=True)
    assert report.objects == len(CONTENT) + report.sidecars


def test_git_content_extensions_are_honoured(tmp_path):
    """The split follows the configured list, so a narrower list means more
    pointer-managed files."""
    sot = ReadOnlySource(_sot(tmp_path, CONTENT), label="shadow")
    qa_root = tmp_path / "qa"

    report, _ = sync_into_qa(
        sot, qa_root, git_content_extensions=frozenset({".ttl"})
    )

    assert report.git_content == 3  # only the .ttl files
    assert report.pointer_managed == 3  # .md now pointer-managed too
