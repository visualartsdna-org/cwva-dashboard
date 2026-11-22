"""Trusted-side control state is unreachable from the confined surface.

The sandbox root IS the QA git repo root (CE_DESIGN §2.1), so `.git` sits inside
the confined tree. The exploit this corpus pins down needed no chmod and no
Layer-1 bypass — only sanctioned registry ops:

    copy(".git/hooks/pre-commit.sample", ".git/hooks/pre-commit")  # git ships these 0755
    write_text(".git/hooks/pre-commit", payload)                   # in-place: mode survives
    <ask for a promotion>                                          # orchestrator commits -> hook runs

Three individually-innocent operations compose into arbitrary code execution as
the orchestrator, outside Landlock. Note that Layer 2 is NOT a backstop for this
class: the hook runs in the trusted process, not the confined worker. Layer 1 is
the whole defense, which is why these tests assert the end-to-end property and
not merely the reject predicate.

`.qa/trash` is deliberately reachable (fileops.trash resolves it here, and
nothing executes or trusts its contents) and so is the hygiene ledger, which
`workflow.dismiss` legitimately writes. Those allowances are asserted too — a
deny rule that broke them would be silently over-broad.
"""

from __future__ import annotations

import hashlib
import json
import shutil

import pytest

from cwva_dashboard.concepts.ledger import LEDGER_PATH
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import PathRejected, RejectReason, Sandbox

pytestmark = pytest.mark.adversarial


def _ops(root):
    return FileOps(Sandbox.open(root))


# -- the exploit, end to end ------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_hook_exploit_cannot_land_via_the_tool_surface(tmp_path):
    """The full published exploit sequence, run against the real tool surface
    and a real promotion commit. Proven by outcome: the commit succeeds and
    nothing was written outside the sandbox."""
    root = tmp_path / "qa"
    root.mkdir()
    outside = tmp_path / "ESCAPED"  # the payload's target, outside the sandbox
    qa = QAGit.init(root)
    ops = _ops(root)

    payload = f"#!/bin/sh\necho pwned > {outside}\n"

    # Step 1 + 2: acquire the exec bit from a shipped sample, then overwrite the
    # content in place. Both must be refused at Layer 1.
    with pytest.raises(PathRejected) as e1:
        ops.copy(".git/hooks/pre-commit.sample", ".git/hooks/pre-commit", overwrite=True)
    assert e1.value.reason is RejectReason.CONTROL_PATH
    with pytest.raises(PathRejected) as e2:
        ops.write_text(".git/hooks/pre-commit", payload)
    assert e2.value.reason is RejectReason.CONTROL_PATH

    # Step 3: the orchestrator commits, as a promotion does. No hook exists to
    # fire, and even if one did, core.hooksPath neutralizes it.
    ops.write_text("content/note.md", "innocent", make_parents=True)
    qa.commit("promotion unit")

    assert not outside.exists(), "payload executed: escape reached outside the sandbox"
    assert not (root / ".git/hooks/pre-commit").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_planted_hook_does_not_run_even_if_layer1_is_bypassed(tmp_path):
    """Defense in depth, mirroring test_layer1_broken_layer2_contains: plant the
    hook by real path (the write a broken Layer 1 would allow) and show the
    orchestrator's commit still does not execute it."""
    root = tmp_path / "qa"
    root.mkdir()
    outside = tmp_path / "ESCAPED"
    qa = QAGit.init(root)

    hook = root / ".git" / "hooks" / "pre-commit"
    hook.write_text(f"#!/bin/sh\necho pwned > {outside}\n")
    hook.chmod(0o755)  # no Layer 1, no tool surface — straight to disk

    (root / "note.md").write_text("innocent")
    qa.commit("promotion unit")

    assert not outside.exists(), "hooksPath hardening failed: planted hook executed"


# -- the reject predicate, across the class ---------------------------------


@pytest.mark.parametrize(
    "path",
    [
        # git control state, top level and nested (a submodule carries its own)
        ".git",
        ".git/config",
        ".git/hooks/pre-commit",
        ".git/hooks/pre-commit.sample",
        ".git/refs/heads/main",
        "content/foo/.git/hooks/pre-commit",
        "content/.git/config",
        # case folding: these reach the same directory on Windows/macOS
        ".GIT/config",
        ".Git/hooks/pre-commit",
        "content/.GiT/config",
        # git configuration files at ordinary paths
        ".gitattributes",
        ".gitignore",
        ".gitmodules",
        "content/.gitattributes",
        "content/ttl/data/.gitignore",
        ".GITATTRIBUTES",
        # the rollback reserve
        ".qa/attic",
        ".qa/attic/deadbeef",
        ".QA/Attic/deadbeef",
    ],
)
def test_control_paths_are_rejected(tmp_path, path):
    with pytest.raises(PathRejected) as exc:
        Sandbox.open(tmp_path).resolve(path)
    assert exc.value.reason is RejectReason.CONTROL_PATH


@pytest.mark.parametrize(
    "path",
    [
        # ADS and trailing-dot aliases of the same names must still be refused,
        # by the *existing* normalization — this rule composes after it.
        (".git::$INDEX_ALLOCATION", RejectReason.INVALID_CHAR),
        (".git./config", RejectReason.TRAILING_DOT_SPACE),
        (".git /config", RejectReason.TRAILING_DOT_SPACE),
        ("../.git/config", RejectReason.TRAVERSAL),
    ],
)
def test_control_path_aliases_are_rejected_upstream(tmp_path, path):
    userpath, reason = path
    with pytest.raises(PathRejected) as exc:
        Sandbox.open(tmp_path).resolve(userpath)
    assert exc.value.reason is reason


@pytest.mark.parametrize(
    "path",
    [
        LEDGER_PATH,  # workflow.dismiss writes this through the confined surface
        ".qa/trash",  # fileops.trash() resolves it here
        ".qa/trash/20260719T000000-abcd1234-note.md",
        ".qa",
        "content/ttl/data/w1.ttl",
        "content/documents/gitignore.md",  # a normal file that merely looks like one
        "content/my.gitignore.txt",
    ],
)
def test_legitimate_paths_still_resolve(tmp_path, path):
    resolved = Sandbox.open(tmp_path).resolve(path)
    assert resolved.is_relative_to(tmp_path.resolve())


# -- derived state: pointer sidecars ----------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "content/images/a.png.ptr",
        "a.png.ptr",
        "content/images/a.PNG.PTR",  # same file on a case-insensitive FS
        "content/documents/note.md.ptr",
        "content/images/.ptr",
    ],
)
def test_sidecars_are_not_agent_authorable(tmp_path, path):
    with pytest.raises(PathRejected) as exc:
        Sandbox.open(tmp_path).resolve(path)
    assert exc.value.reason is RejectReason.DERIVED_STATE


def test_forged_sidecar_is_impossible_through_the_tool_surface(tmp_path):
    """The forgery confirmed before the fix: write a binary legitimately, then
    rewind its sidecar to a stale sha so the change goes invisible to the
    manifest. The second write must now be refused."""
    ops = _ops(tmp_path)
    ops.write_bytes("content/images/a.png", b"REAL-IMAGE-BYTES", make_parents=True)

    with pytest.raises(PathRejected) as exc:
        ops.write_text(
            "content/images/a.png.ptr", '{"sha256": "deadbeef", "size": 3, "created": ""}'
        )
    assert exc.value.reason is RejectReason.DERIVED_STATE

    # The machinery's own sidecar, written through PointerManager, is intact and
    # still describes the real bytes — the denial did not break the lockstep.
    ptr = json.loads((tmp_path / "content/images/a.png.ptr").read_text())
    assert ptr["sha256"] == hashlib.sha256(b"REAL-IMAGE-BYTES").hexdigest()
    assert ptr["size"] == len(b"REAL-IMAGE-BYTES")


def test_sidecar_maintenance_still_runs_for_every_managed_op(tmp_path):
    """The lockstep mechanism must survive the denial: fileops reaches sidecars
    through PointerManager on resolved paths, never through resolve()."""
    ops = _ops(tmp_path)

    ops.write_bytes("content/images/a.png", b"AAAA", make_parents=True)
    assert (tmp_path / "content/images/a.png.ptr").exists()

    ops.write_bytes("content/images/a.png", b"BBBBBB")  # replace -> sidecar updates
    ptr = json.loads((tmp_path / "content/images/a.png.ptr").read_text())
    assert ptr["sha256"] == hashlib.sha256(b"BBBBBB").hexdigest()

    ops.move("content/images/a.png", "content/images/b.png")  # sidecar follows
    assert not (tmp_path / "content/images/a.png.ptr").exists()
    assert (tmp_path / "content/images/b.png.ptr").exists()

    ops.copy("content/images/b.png", "content/images/c.png")  # copy gets its own
    assert (tmp_path / "content/images/c.png.ptr").exists()

    ops.trash("content/images/c.png")  # sidecar leaves with the binary
    assert not (tmp_path / "content/images/c.png.ptr").exists()


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_trash_and_dismiss_still_work(tmp_path):
    """The allowances are not theoretical: the two ops that need .qa must run."""
    root = tmp_path / "qa"
    root.mkdir()
    QAGit.init(root)
    ops = _ops(root)

    ops.write_text("content/note.md", "content", make_parents=True)
    dest = ops.trash("content/note.md")
    assert dest.startswith(".qa/trash/")

    ops.write_text(LEDGER_PATH, "# ledger\n", make_parents=True)
    assert ops.read_text(LEDGER_PATH) == "# ledger\n"
