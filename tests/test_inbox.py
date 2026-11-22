"""The user's drop folder — listing, and the untrusted-name boundary.

The inbox sits **outside** every containment boundary the project owns, and a
submitted filename is untrusted input about to be joined to a path. The listing
tests are ordinary; the `resolve` tests are the security ones, and they exist
because "the form only sends names we listed" is a property of the renderer, and
the renderer is not a guard (the same render-≠-enforce rule as the affordances).
"""

from __future__ import annotations

import pytest

from cwva_dashboard.inbox import Inbox, InboxError
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox

JPEG = b"\xff\xd8\xff\xe0 pretend jpeg"


@pytest.fixture
def inbox(tmp_path):
    root = tmp_path / "drop"
    root.mkdir()
    (root / "photo.jpg").write_bytes(JPEG)
    (root / "scan.PNG").write_bytes(b"png")
    (root / "notes.md").write_text("# notes")
    (root / "ignored.exe").write_bytes(b"MZ")
    (root / ".hidden.jpg").write_bytes(JPEG)
    (root / "subdir").mkdir()
    return Inbox(root)


# -- listing ----------------------------------------------------------------


def test_lists_only_the_kind_asked_for(inbox):
    names = [f.name for f in inbox.list("image")]
    assert names == ["photo.jpg", "scan.PNG"]  # case-insensitive extension match
    # "markdown" and "pdf" are separate kinds, not one "document" kind: the
    # entity form has a picker for each, and one kind holding both extensions
    # let the .md field offer a .pdf.
    assert [f.name for f in inbox.list("markdown")] == ["notes.md"]
    assert inbox.list("document") == [], "the conflated kind is gone"


def test_ignores_unlisted_types_hidden_files_and_dirs(inbox):
    names = {f.name for f in inbox.list("image")} | {f.name for f in inbox.list("markdown")}
    assert "ignored.exe" not in names
    assert ".hidden.jpg" not in names
    assert "subdir" not in names


def test_missing_folder_lists_empty_rather_than_raising(tmp_path):
    """A fresh install has not made the folder yet; the form must still render."""
    absent = Inbox(tmp_path / "not-created")
    assert absent.exists() is False
    assert absent.list("image") == []


def test_symlinks_are_never_offered(tmp_path):
    """A link in the drop folder would otherwise read a file the user never put
    there — the sandbox prohibits symlinks and so does this boundary."""
    root = tmp_path / "drop"
    root.mkdir()
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"not yours")
    (root / "innocent.jpg").symlink_to(secret)

    assert Inbox(root).list("image") == []


# -- resolve: the untrusted-name boundary -----------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "../../../etc/passwd",
        "../outside.jpg",
        "sub/photo.jpg",
        "..\\..\\windows\\system32\\config.jpg",
        "/etc/passwd",
        "/absolute/photo.jpg",
        "C:\\Windows\\photo.jpg",
        "photo.jpg\x00.txt",
        "..",
        ".",
        "",
    ],
)
def test_traversal_and_absolute_names_are_refused(inbox, name):
    with pytest.raises(InboxError):
        inbox.resolve(name)


def test_a_name_outside_the_allowlist_is_refused(inbox):
    with pytest.raises(InboxError, match="accepted image type"):
        inbox.resolve("ignored.exe")
    # right file, wrong kind: .md is a document, not an image
    with pytest.raises(InboxError, match="accepted image type"):
        inbox.resolve("notes.md", "image")


def test_a_name_that_is_not_there_is_refused(inbox):
    with pytest.raises(InboxError, match="not a file in the drop folder"):
        inbox.resolve("absent.jpg")


def test_a_symlinked_name_is_refused_even_when_it_resolves(tmp_path):
    """Belt and braces: listing hides symlinks, and resolve refuses them too, so
    a hand-typed name cannot follow one out of the folder."""
    root = tmp_path / "drop"
    root.mkdir()
    secret = tmp_path / "secret.jpg"
    secret.write_bytes(b"not yours")
    (root / "innocent.jpg").symlink_to(secret)

    with pytest.raises(InboxError):
        Inbox(root).resolve("innocent.jpg")


def test_a_legitimate_name_resolves(inbox):
    p = inbox.resolve("photo.jpg")
    assert p.name == "photo.jpg" and p.read_bytes() == JPEG


# -- copy_into --------------------------------------------------------------


def test_copy_mints_the_pointer_sidecar(tmp_path, inbox):
    """The whole reason the folder exists: a hand-copied binary has no sidecar
    and is invisible to promotion. Going through FileOps mints it on arrival."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ops = FileOps(Sandbox.open(sandbox))

    out = inbox.copy_into("photo.jpg", ops, "images")

    assert out["copied"] is True
    assert (sandbox / "images" / "photo.jpg").read_bytes() == JPEG
    assert (sandbox / "images" / "photo.jpg.ptr").is_file(), "sidecar must exist"


def test_copying_the_same_file_twice_is_a_no_op(tmp_path, inbox):
    """Re-running an entry must not needlessly attic the previous copy."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ops = FileOps(Sandbox.open(sandbox))

    first = inbox.copy_into("photo.jpg", ops, "images")
    second = inbox.copy_into("photo.jpg", ops, "images")

    assert first["copied"] is True
    assert second["copied"] is False


def test_copy_refuses_a_traversal_name(tmp_path, inbox):
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    ops = FileOps(Sandbox.open(sandbox))

    with pytest.raises(InboxError):
        inbox.copy_into("../../../etc/passwd", ops, "images")


def test_the_inbox_is_never_modified(tmp_path, inbox):
    """The user's folder is theirs: ingest copies, never moves or deletes."""
    before = {p.name for p in inbox.root.iterdir()}
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    inbox.copy_into("photo.jpg", FileOps(Sandbox.open(sandbox)), "images")

    assert {p.name for p in inbox.root.iterdir()} == before
    assert (inbox.root / "photo.jpg").read_bytes() == JPEG
