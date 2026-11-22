"""Layer-2 (Landlock) containment tests — the exit-gate independence check.

Landlock restriction is irreversible for a process, so every case runs in a
forked child: the child confines itself, attempts an operation, and reports the
outcome through its exit code. The parent asserts on that code.

The key case is ``test_layer1_broken_layer2_contains``: it bypasses Layer 1
entirely (a raw absolute path outside the sandbox — i.e. Layer 1 deliberately
broken) and proves the kernel still refuses the write. That is the CE_DESIGN
§2.4 release criterion in miniature.
"""

from __future__ import annotations

import os

import pytest

from cwva_dashboard.sandbox.broker import landlock_abi, restrict_process

pytestmark = [
    pytest.mark.adversarial,
    pytest.mark.skipif(landlock_abi() < 1, reason="Landlock unavailable on this kernel"),
]

# child exit codes
OK = 0
WRITE_INSIDE_FAILED = 10
WRITE_OUTSIDE_NOT_BLOCKED = 11
READ_OUTSIDE_NOT_BLOCKED = 12
RESTRICT_RAISED = 13
UNEXPECTED = 20


def _run_in_child(fn) -> int:
    """Fork, run ``fn`` (which returns an exit code) in the child under a fresh
    process image, and return the child's exit status to the parent."""
    pid = os.fork()
    if pid == 0:  # child
        code = UNEXPECTED
        try:
            code = fn()
        except BaseException:
            code = UNEXPECTED
        finally:
            os._exit(code)
    _, status = os.waitpid(pid, 0)
    return os.waitstatus_to_exitcode(status)


def test_write_inside_allowed_writes_outside_and_reads_outside_blocked(tmp_path):
    sandbox = tmp_path / "stage"
    sandbox.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    def child() -> int:
        try:
            restrict_process(sandbox)
        except Exception:
            return RESTRICT_RAISED

        # Write inside the sandbox: must succeed.
        try:
            with open(sandbox / "ok.txt", "w") as fh:
                fh.write("inside")
        except OSError:
            return WRITE_INSIDE_FAILED

        # Write outside the sandbox: kernel must refuse.
        try:
            with open(outside / "escape.txt", "w") as fh:
                fh.write("nope")
            return WRITE_OUTSIDE_NOT_BLOCKED
        except PermissionError:
            pass

        # Read a system secret outside the granted read paths: must refuse.
        try:
            with open("/etc/passwd", "rb") as fh:
                fh.read()
            return READ_OUTSIDE_NOT_BLOCKED
        except PermissionError:
            pass

        return OK

    assert _run_in_child(child) == OK


def test_layer1_broken_layer2_contains(tmp_path):
    """Layer 1 deliberately bypassed: a raw absolute path aimed outside the
    sandbox. Layer 2 must still contain it."""
    sandbox = tmp_path / "stage"
    sandbox.mkdir()
    target = tmp_path / "outside" / "loot.txt"
    target.parent.mkdir()

    def child() -> int:
        try:
            restrict_process(sandbox)
        except Exception:
            return RESTRICT_RAISED
        try:
            # No Sandbox.resolve() here — this is the escape a broken Layer 1
            # would let through. The kernel is the only thing standing in the way.
            with open(target, "w") as fh:
                fh.write("exfiltrated")
            return WRITE_OUTSIDE_NOT_BLOCKED
        except PermissionError:
            return OK

    assert _run_in_child(child) == OK


def test_restrict_reports_abi_and_paths(tmp_path):
    sandbox = tmp_path / "stage"
    sandbox.mkdir()

    def child() -> int:
        res = restrict_process(sandbox)
        # abi>=1 and the sandbox is the first RW path.
        if res.abi >= 1 and res.rw_paths and res.rw_paths[0] == str(sandbox.resolve()):
            return OK
        return UNEXPECTED

    assert _run_in_child(child) == OK
