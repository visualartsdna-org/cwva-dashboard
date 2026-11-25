"""Layer 2 — OS-enforced confinement (CE_DESIGN §2.2).

Layer 1 (``paths.py``) is portable code that *should* keep every operation
inside the sandbox. Layer 2 is the OS making sure it does even when Layer 1 is
wrong: a validation bug is contained by the kernel, and (symmetrically) a
kernel/config gap is contained by validation. The release gate is exactly this
independence — with Layer 1 deliberately broken, Layer 2 still contains every
escape (CE_DESIGN §2.4).

Linux path (implemented here): **Landlock** self-restriction at process
startup. The broker process calls :func:`restrict_process` before it does any
agent work; from that point the kernel permits writes only under the sandbox
root and reads only under the sandbox plus the interpreter/library paths the
process needs to keep running. Landlock is unprivileged and irreversible for
the process, so it is applied once, at the start of a dedicated worker.

Windows path (scripted at install, Phase 11): a dedicated low-privilege local
user plus NTFS ACLs granting modify on the sandbox only. There is no in-process
equivalent to call here; :func:`restrict_process` refuses on non-Linux and
points the caller at the install-time mechanism.

This module speaks the Landlock syscalls directly via ctypes to avoid a
third-party dependency in the security core. Syscall numbers 444/445/446 are
architecture-independent for Landlock.
"""

from __future__ import annotations

import ctypes
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "restrict_process",
    "landlock_abi",
    "LandlockError",
    "LandlockUnavailable",
    "RestrictResult",
]

# -- syscall numbers (arch-independent for Landlock) ------------------------
_NR_landlock_create_ruleset = 444
_NR_landlock_add_rule = 445
_NR_landlock_restrict_self = 446

_LANDLOCK_CREATE_RULESET_VERSION = 1
_LANDLOCK_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

# -- filesystem access-right bits (linux/landlock.h) ------------------------
_FS_EXECUTE = 1 << 0
_FS_WRITE_FILE = 1 << 1
_FS_READ_FILE = 1 << 2
_FS_READ_DIR = 1 << 3
_FS_REMOVE_DIR = 1 << 4
_FS_REMOVE_FILE = 1 << 5
_FS_MAKE_CHAR = 1 << 6
_FS_MAKE_DIR = 1 << 7
_FS_MAKE_REG = 1 << 8
_FS_MAKE_SOCK = 1 << 9
_FS_MAKE_FIFO = 1 << 10
_FS_MAKE_BLOCK = 1 << 11
_FS_MAKE_SYM = 1 << 12
_FS_REFER = 1 << 13  # ABI >= 2 (cross-directory rename/link)
_FS_TRUNCATE = 1 << 14  # ABI >= 3

# Rights that let a process read/traverse/execute a tree.
_READ_RIGHTS = _FS_EXECUTE | _FS_READ_FILE | _FS_READ_DIR

# ABI 1 baseline: every right through MAKE_SYM.
_ABI1_RIGHTS = (
    _FS_EXECUTE
    | _FS_WRITE_FILE
    | _FS_READ_FILE
    | _FS_READ_DIR
    | _FS_REMOVE_DIR
    | _FS_REMOVE_FILE
    | _FS_MAKE_CHAR
    | _FS_MAKE_DIR
    | _FS_MAKE_REG
    | _FS_MAKE_SOCK
    | _FS_MAKE_FIFO
    | _FS_MAKE_BLOCK
    | _FS_MAKE_SYM
)


class LandlockError(RuntimeError):
    """A Landlock syscall failed unexpectedly."""


class LandlockUnavailable(LandlockError):
    """Landlock is not usable here (non-Linux, or kernel without Landlock)."""


@dataclass(frozen=True)
class RestrictResult:
    abi: int
    rw_paths: tuple[str, ...]
    ro_paths: tuple[str, ...]
    handled_access_fs: int


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _pack_ = 1  # struct landlock_path_beneath_attr is packed
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
    ]


def _libc() -> ctypes.CDLL:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def _handled_mask(abi: int) -> int:
    """The set of rights the ruleset governs, capped to what the kernel ABI
    supports. Rights outside this mask are left unrestricted (e.g. device
    ioctls on ABI 5), which is deliberate: the threat we contain is filesystem
    read/write escape, not tty ioctls."""
    mask = _ABI1_RIGHTS
    if abi >= 2:
        mask |= _FS_REFER
    if abi >= 3:
        mask |= _FS_TRUNCATE
    return mask


def landlock_abi() -> int:
    """Return the supported Landlock ABI version (>= 1), or 0 if Landlock is
    unavailable on this kernel. Never raises."""
    if platform.system() != "Linux":
        return 0
    try:
        libc = _libc()
    except OSError:
        return 0
    ctypes.set_errno(0)
    abi = libc.syscall(
        ctypes.c_long(_NR_landlock_create_ruleset),
        ctypes.c_void_p(0),
        ctypes.c_size_t(0),
        ctypes.c_uint32(_LANDLOCK_CREATE_RULESET_VERSION),
    )
    return abi if abi > 0 else 0


def _default_ro_paths() -> list[str]:
    """Interpreter and system library paths the process must keep reading after
    it is confined, so a running Python does not break. These grant *read*
    (not write); anything outside them and outside the sandbox — /etc/passwd,
    the user's home, other projects — becomes unreadable."""
    candidates = [
        sys.base_prefix,
        sys.prefix,
        str(Path(sys.executable).resolve().parent),
        "/usr",
        "/lib",
        "/lib64",
    ]
    seen: list[str] = []
    for c in candidates:
        if c and c not in seen and os.path.isdir(c):
            seen.append(c)
    return seen


def _add_path_rule(libc: ctypes.CDLL, ruleset_fd: int, path: str, access: int) -> None:
    try:
        pfd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except OSError as exc:
        raise LandlockError(f"cannot open {path!r} for a Landlock rule: {exc}") from exc
    try:
        attr = _PathBeneathAttr(allowed_access=access, parent_fd=pfd)
        ctypes.set_errno(0)
        rc = libc.syscall(
            ctypes.c_long(_NR_landlock_add_rule),
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(_LANDLOCK_RULE_PATH_BENEATH),
            ctypes.byref(attr),
            ctypes.c_uint32(0),
        )
        if rc != 0:
            err = ctypes.get_errno()
            raise LandlockError(f"landlock_add_rule({path!r}) failed: {os.strerror(err)}")
    finally:
        os.close(pfd)


def restrict_process(
    sandbox_root: str | os.PathLike[str],
    *,
    extra_ro_paths: tuple[str, ...] = (),
    extra_rw_paths: tuple[str, ...] = (),
) -> RestrictResult:
    """Irreversibly confine the current process with Landlock: read+write only
    under ``sandbox_root`` (plus ``extra_rw_paths``), read-only under the
    interpreter/library paths and ``extra_ro_paths``. Everything else on the
    filesystem becomes inaccessible.

    Call once, at broker startup, before any agent work. Raises
    :class:`LandlockUnavailable` on non-Linux or a kernel without Landlock, and
    :class:`LandlockError` if a syscall fails.
    """
    if platform.system() != "Linux":
        raise LandlockUnavailable(
            "Landlock is Linux-only; on Windows the sandbox is confined by a "
            "dedicated low-privilege user + NTFS ACLs scripted at install "
            "(CE_DESIGN §2.2, project plan Phase 11)."
        )
    abi = landlock_abi()
    if abi < 1:
        raise LandlockUnavailable(
            "kernel does not support Landlock (need 5.13+ with "
            "CONFIG_SECURITY_LANDLOCK enabled)"
        )

    root = Path(sandbox_root).resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"sandbox root is not a directory: {sandbox_root!r}")

    handled = _handled_mask(abi)
    rw_paths = [str(root), *[str(Path(p).resolve()) for p in extra_rw_paths]]
    ro_paths = [*_default_ro_paths(), *[str(Path(p).resolve()) for p in extra_ro_paths]]

    libc = _libc()

    attr = _RulesetAttr(handled_access_fs=handled)
    ctypes.set_errno(0)
    ruleset_fd = libc.syscall(
        ctypes.c_long(_NR_landlock_create_ruleset),
        ctypes.byref(attr),
        ctypes.c_size_t(ctypes.sizeof(attr)),
        ctypes.c_uint32(0),
    )
    if ruleset_fd < 0:
        err = ctypes.get_errno()
        raise LandlockError(f"landlock_create_ruleset failed: {os.strerror(err)}")

    try:
        for p in rw_paths:
            _add_path_rule(libc, ruleset_fd, p, handled)
        for p in ro_paths:
            _add_path_rule(libc, ruleset_fd, p, _READ_RIGHTS & handled)

        # Required before restrict_self: forbid gaining privileges (e.g. via
        # setuid) that could shed the restriction.
        if libc.prctl(
            ctypes.c_int(_PR_SET_NO_NEW_PRIVS),
            ctypes.c_ulong(1),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
            ctypes.c_ulong(0),
        ) != 0:
            err = ctypes.get_errno()
            raise LandlockError(f"prctl(PR_SET_NO_NEW_PRIVS) failed: {os.strerror(err)}")

        ctypes.set_errno(0)
        rc = libc.syscall(
            ctypes.c_long(_NR_landlock_restrict_self),
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint32(0),
        )
        if rc != 0:
            err = ctypes.get_errno()
            raise LandlockError(f"landlock_restrict_self failed: {os.strerror(err)}")
    finally:
        os.close(ruleset_fd)

    return RestrictResult(
        abi=abi,
        rw_paths=tuple(rw_paths),
        ro_paths=tuple(ro_paths),
        handled_access_fs=handled,
    )
