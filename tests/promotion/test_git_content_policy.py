"""The inverted binary policy (2026-07-21) and its migration.

`git_content_extensions` enumerates what stays ORDINARY GIT CONTENT; everything
else is pointer-managed. The old direction listed binaries and let anything
unlisted default into git, so each unanticipated type (.svg, .heic, .glb, .zip)
became a permanent blob in a history that cannot be rewritten (law 6).

The criterion is editorial intent — "does a user edit this and want a diff?" —
which is not detectable: .svg is valid UTF-8 and structurally diffable, and its
diff is still meaningless. So the judgment lives in a list, and these tests pin
the list's edges, the machinery carve-outs, and the migration.
"""

from __future__ import annotations

import json
import shutil

import pytest

from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.sandbox.pointers import (
    DEFAULT_GIT_CONTENT_EXTENSIONS,
    is_managed_binary,
    pointer_path_of,
)

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

_G = DEFAULT_GIT_CONTENT_EXTENSIONS


def _repo(tmp_path, git_content=_G):
    root = tmp_path / "qa"
    root.mkdir(exist_ok=True)
    qa = QAGit.init(root, git_content_extensions=git_content)
    return qa, FileOps(Sandbox.open(root), git_content_extensions=git_content)


# -- the policy edges -------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [".ttl", ".md", ".txt", ".sparql", ".rson", ".html", ".csv", ".jsonld", ".tsh"],
)
def test_authored_types_stay_git_content(name):
    assert not is_managed_binary(f"file{name}", _G)


@pytest.mark.parametrize(
    "name",
    [
        ".png",
        ".jpg",
        ".pdf",
        ".heic",
        ".glb",
        ".zip",
        ".ico",
        ".svg",  # diffable in principle, meaningless in practice — the case that drove this
        ".json",  # generated analytics here; production has one at 17 MB
        ".mp4",  # never anticipated: the new direction handles it without a config change
        ".woff2",
    ],
)
def test_everything_else_is_pointer_managed(name):
    assert is_managed_binary(f"file{name}", _G)


@pytest.mark.parametrize(
    "name", ["a.png.ptr", "a.ttl.ptr", ".gitignore", "README", "LICENSE", "Makefile"]
)
def test_machinery_and_extensionless_are_never_managed(name):
    """The carve-out: sidecars and dotfiles share the content path space, and
    PointerManager reaches them by real path, so Layer 1 does not protect them."""
    assert not is_managed_binary(name, _G)


def test_classification_is_case_insensitive():
    assert is_managed_binary("PHOTO.PNG", _G)
    assert not is_managed_binary("DATA.TTL", _G)


# -- .gitignore agrees with the Python rule ---------------------------------


@pytest.mark.parametrize(
    "rel,expect_ignored",
    [
        ("content/a.png", True),
        ("content/a.svg", True),
        ("content/a.json", True),
        ("content/a.ttl", False),
        ("content/a.md", False),
        ("content/a.tsh", False),
        ("content/a.png.ptr", False),
        (".gitignore", False),
        ("content/README", False),
        ("content/v1.2/a.ttl", False),  # a dotted DIRECTORY must stay traversable
    ],
)
def test_gitignore_matches_the_python_rule(tmp_path, rel, expect_ignored):
    """Both mechanisms must agree. If they disagree a file is either tracked
    nowhere and unsidecarred, or double-tracked — the two failure modes this
    whole area keeps producing."""
    qa, _ = _repo(tmp_path)
    target = qa.root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"x")

    ignored = _check_ignored(qa, rel)
    assert ignored is expect_ignored, f"{rel}: git ignored={ignored}, expected {expect_ignored}"
    # and the Python side agrees, for files (directories are not classified)
    assert is_managed_binary(rel, _G) is expect_ignored


def _check_ignored(qa, rel) -> bool:
    import subprocess

    # --no-index: ask what the ignore RULES say, independent of whether the path
    # happens to be in the index already (check-ignore reports tracked files as
    # not-ignored, which is a different question).
    cp = subprocess.run(
        qa._argv("check-ignore", "-q", "--no-index", "--", rel), capture_output=True
    )
    return cp.returncode == 0


@pytest.mark.parametrize(
    "name", [".env", ".npmrc", ".dockerignore", ".editorconfig", ".gitignore", ".prettierrc"]
)
def test_single_dot_dotfiles_do_not_fall_between_the_mechanisms(tmp_path, name):
    """`*.*` DOES match a single-dot dotfile — `*` matches the empty string, so
    the leading dot satisfies the pattern's dot. Without the `!.*` carve-out git
    ignores these while is_managed_binary() calls them text, which is
    tracked-nowhere: no git content AND no sidecar. `.gitignore` was safe only
    because it happened to be re-admitted by name.

    This is the recurring bug shape in this area — the two mechanisms
    disagreeing — so it is asserted per-name rather than in aggregate.
    """
    qa, _ = _repo(tmp_path)
    if name != ".gitignore":
        (qa.root / name).write_text("x")

    assert _check_ignored(qa, name) is False, f"{name}: git ignores it"
    assert is_managed_binary(name, _G) is False, f"{name}: python would sidecar it"


def test_qa_internal_still_wins_over_the_dotfile_negation(tmp_path):
    """`!.*` must not re-admit QA-internal state; `/.qa/` is last for that."""
    qa, _ = _repo(tmp_path)
    (qa.root / ".qa" / "attic").mkdir(parents=True, exist_ok=True)
    (qa.root / ".qa" / "attic" / "deadbeef").write_text("x")

    assert _check_ignored(qa, ".qa/attic/deadbeef") is True


def test_new_unanticipated_binary_needs_no_config_change(tmp_path):
    """The point of the inversion: an .mp4 nobody listed gets a sidecar and stays
    out of git, instead of silently becoming a permanent blob."""
    qa, ops = _repo(tmp_path)
    ops.write_bytes("content/clip.mp4", b"MP4DATA", make_parents=True)
    qa.commit("add a type nobody enumerated")

    tracked = qa._run("ls-files").split()
    assert "content/clip.mp4.ptr" in tracked
    assert "content/clip.mp4" not in tracked


# -- migration --------------------------------------------------------------


def test_migration_mints_sidecar_and_seeds_attic_before_untracking(tmp_path):
    """The gap this closes: managed-by-extension with no .ptr is owned by
    NEITHER rollback mechanism — git no longer has the content, the attic has
    nothing to restore."""
    wide = _G | {".svg"}  # .svg started as git content...
    qa, ops = _repo(tmp_path, git_content=wide)
    ops.write_text("content/logo.svg", "<svg>original</svg>", make_parents=True)
    first = qa.commit("svg tracked as content under the old list")
    assert "content/logo.svg" in qa._run("ls-files")

    # ...and the operator now narrows the list, moving .svg to the sidecar bucket.
    qa2 = QAGit.init(qa.root, git_content_extensions=_G)
    report = qa2.migrate_to_pointer_management(_G)
    qa2.commit("migrate svg to pointer management")

    assert report["untracked"] == 1
    assert report["sidecars_minted"] == ["content/logo.svg"]
    assert report["attic_seeded"] == ["content/logo.svg"]

    # Every owner is in place: sidecar exists, attic holds the bytes, git let go.
    assert pointer_path_of(qa2.root / "content/logo.svg").exists()
    sha = json.loads(pointer_path_of(qa2.root / "content/logo.svg").read_text())["sha256"]
    assert (qa2.root / ".qa/attic" / sha).read_text() == "<svg>original</svg>"
    tracked = qa2._run("ls-files").split()
    assert "content/logo.svg" not in tracked
    assert "content/logo.svg.ptr" in tracked
    # The file itself survives, and its old content stays reachable in history.
    assert (qa2.root / "content/logo.svg").exists()
    assert qa2.file_at(first, "content/logo.svg") == "<svg>original</svg>"


def test_migration_is_idempotent(tmp_path):
    wide = _G | {".svg"}
    qa, ops = _repo(tmp_path, git_content=wide)
    ops.write_text("content/logo.svg", "<svg/>", make_parents=True)
    qa.commit("tracked")

    qa2 = QAGit.init(qa.root, git_content_extensions=_G)
    qa2.migrate_to_pointer_management(_G)
    qa2.commit("migrated")

    again = qa2.migrate_to_pointer_management(_G)
    assert again["untracked"] == 0 and again["sidecars_minted"] == []


def test_migration_reports_files_missing_from_the_worktree(tmp_path):
    """Tracked but absent: nothing to mint from, so it must be reported rather
    than untracked into the ownerless gap."""
    wide = _G | {".svg"}
    qa, ops = _repo(tmp_path, git_content=wide)
    ops.write_text("content/logo.svg", "<svg/>", make_parents=True)
    qa.commit("tracked")
    (qa.root / "content/logo.svg").unlink()

    qa2 = QAGit.init(qa.root, git_content_extensions=_G)
    report = qa2.migrate_to_pointer_management(_G)
    assert report["missing_from_worktree"] == ["content/logo.svg"]
    assert report["untracked"] == 0


def test_nothing_to_migrate_when_the_list_was_right_from_the_start(tmp_path):
    qa, ops = _repo(tmp_path)
    ops.write_bytes("content/a.png", b"PNG", make_parents=True)
    ops.write_text("content/a.ttl", "<a> <b> <c> .", make_parents=True)
    qa.commit("clean")

    report = qa.migrate_to_pointer_management(_G)
    assert report["untracked"] == 0 and report["sidecars_minted"] == []
