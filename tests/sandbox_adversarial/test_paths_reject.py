"""Starter Layer-1 rejection corpus (CE_DESIGN §2.4).

This is the seed of the adversarial corpus, not the whole thing: the full
release gate adds Windows-run CI, Hypothesis properties, and a Layer-2
fault-injection case. What is here already asserts the reject-not-sanitize
contract by *structure* (RejectReason), never by message string.
"""

from __future__ import annotations

import os

import pytest

from cwva_dashboard.sandbox.paths import PathRejected, RejectReason, Sandbox


@pytest.fixture
def sandbox(tmp_path):
    return Sandbox.open(tmp_path / "stage", create=True)


# input -> expected reason
REJECT_CORPUS = {
    # traversal chains
    "..": RejectReason.TRAVERSAL,
    "../etc/passwd": RejectReason.TRAVERSAL,
    "a/../../b": RejectReason.TRAVERSAL,
    "a/b/../../../c": RejectReason.TRAVERSAL,
    # absolute / home
    "/etc/passwd": RejectReason.ABSOLUTE,
    "/": RejectReason.ABSOLUTE,
    "~": RejectReason.HOME_EXPANSION,
    "~/secrets": RejectReason.HOME_EXPANSION,
    # drive-relative / drive-absolute
    "C:": RejectReason.DRIVE_LETTER,
    "C:foo": RejectReason.DRIVE_LETTER,
    "C:/Windows": RejectReason.DRIVE_LETTER,
    "z:data": RejectReason.DRIVE_LETTER,
    # backslash family: UNC, mixed separators, long-path prefix
    "\\\\server\\share": RejectReason.BACKSLASH,
    "a\\b": RejectReason.BACKSLASH,
    "\\\\?\\C:\\x": RejectReason.BACKSLASH,
    "..\\..\\x": RejectReason.BACKSLASH,
    # null / control chars
    "a\x00b": RejectReason.NULL_BYTE,
    "a\x01b": RejectReason.CONTROL_CHAR,
    "tab\tfile": RejectReason.CONTROL_CHAR,
    # ADS and other Windows-invalid component chars
    "file:stream": RejectReason.INVALID_CHAR,
    "wild*card": RejectReason.INVALID_CHAR,
    'quo"te': RejectReason.INVALID_CHAR,
    "pi|pe": RejectReason.INVALID_CHAR,
    # reserved device names (with and without extension)
    "CON": RejectReason.RESERVED_NAME,
    "nul": RejectReason.RESERVED_NAME,
    "COM1": RejectReason.RESERVED_NAME,
    "LPT9.txt": RejectReason.RESERVED_NAME,
    "dir/NUL.dat": RejectReason.RESERVED_NAME,
    # trailing dot / space aliasing
    "name ": RejectReason.TRAILING_DOT_SPACE,
    "name.": RejectReason.TRAILING_DOT_SPACE,
    "dir/child .": RejectReason.TRAILING_DOT_SPACE,
    # empty components
    "a//b": RejectReason.EMPTY_COMPONENT,
    "a/": RejectReason.EMPTY_COMPONENT,
    "/a": RejectReason.ABSOLUTE,
    # bare dot component mid-path
    "a/./b": RejectReason.DOT_COMPONENT,
}


@pytest.mark.adversarial
@pytest.mark.parametrize("userpath,reason", sorted(REJECT_CORPUS.items()))
def test_rejected_paths(sandbox, userpath, reason):
    with pytest.raises(PathRejected) as ei:
        sandbox.resolve(userpath)
    assert ei.value.reason is reason


@pytest.mark.adversarial
@pytest.mark.parametrize("userpath", ["", ".", "a", "a/b/c", "dir/file.ttl", ".qa/trash"])
def test_accepted_paths_stay_inside(sandbox, userpath):
    resolved = sandbox.resolve(userpath)
    assert resolved == sandbox.root or resolved.is_relative_to(sandbox.root)


@pytest.mark.adversarial
def test_unencodable_surrogate_rejected(sandbox):
    # A lone surrogate is not representable on disk; refuse it up front rather
    # than let a later os.* call crash.
    with pytest.raises(PathRejected) as ei:
        sandbox.resolve("bad\ud800name")
    assert ei.value.reason is RejectReason.UNENCODABLE


def _symlink_or_skip(src, dst):
    try:
        os.symlink(src, dst)
    except (OSError, NotImplementedError):  # unprivileged Windows, etc.
        pytest.skip("symlink creation not permitted on this platform")


@pytest.mark.adversarial
def test_symlink_in_prefix_rejected(sandbox):
    # A symlink planted inside the sandbox pointing OUT must not be followable.
    outside = sandbox.root.parent / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("top secret")
    _symlink_or_skip(outside, sandbox.root / "escape")

    with pytest.raises(PathRejected) as ei:
        sandbox.resolve("escape/secret.txt")
    assert ei.value.reason is RejectReason.SYMLINK


@pytest.mark.adversarial
def test_symlink_pointing_inside_still_rejected(sandbox):
    # Policy forbids ALL symlinks in the sandbox, even ones that stay inside.
    (sandbox.root / "real").mkdir()
    _symlink_or_skip(sandbox.root / "real", sandbox.root / "alias")
    with pytest.raises(PathRejected) as ei:
        sandbox.resolve("alias/file.txt")
    assert ei.value.reason is RejectReason.SYMLINK
