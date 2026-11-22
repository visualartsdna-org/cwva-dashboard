"""Layer 1 — path confinement (CE_DESIGN §2.2).

Every agent-supplied path is a *logical* relative path inside the sandbox.
This module is the sole authority that turns such a string into a real,
contained filesystem path — or rejects it. The rules are **reject, never
sanitize**: an input that is not obviously safe is refused, not repaired.
Silent repair is how confinement bugs hide.

Security is enforced here and in the OS (Layer 2), never in prompts. This code
must be safe against a fully adversarial caller: the strings arriving here may
originate from file contents the model read (markdown, TTL, user data), i.e.
they are a prompt-injection vector.

Cross-platform note: the reject set covers Windows-specific hazards (reserved
device names, ADS, drive-relative forms, long-path prefixes, backslashes) even
when running on Linux, so the same corpus and the same guarantees hold on both
targets. Backslashes are rejected wholesale — the logical path vocabulary uses
'/' only — which collapses UNC, mixed-separator, and drive-relative tricks
into one rule.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

__all__ = ["Sandbox", "PathRejected", "RejectReason"]


class RejectReason(str, Enum):
    """Why a path was refused. Stable identifiers so tests and the audit log
    can assert on structure rather than message strings."""

    EMPTY = "empty"
    NULL_BYTE = "null_byte"
    UNENCODABLE = "unencodable"  # not representable in the filesystem encoding
    CONTROL_CHAR = "control_char"
    BACKSLASH = "backslash"  # UNC / mixed separator / drive-relative / long-path
    ABSOLUTE = "absolute"
    DRIVE_LETTER = "drive_letter"
    HOME_EXPANSION = "home_expansion"
    TRAVERSAL = "traversal"  # a '..' component
    DOT_COMPONENT = "dot_component"  # a bare '.' component mid-path
    EMPTY_COMPONENT = "empty_component"  # '//'
    INVALID_CHAR = "invalid_char"  # < > : " | ? * in a component
    TRAILING_DOT_SPACE = "trailing_dot_space"  # Windows strips these -> aliasing
    RESERVED_NAME = "reserved_name"  # CON, NUL, COM1, ...
    SYMLINK = "symlink"  # an existing component is a symlink
    ESCAPES_ROOT = "escapes_root"  # resolved path left the sandbox
    CONTROL_PATH = "control_path"  # trusted-side control state (git dir, attic)
    DERIVED_STATE = "derived_state"  # machinery-maintained derived file (.ptr)


# Windows reserved device names. Reserved regardless of extension: "NUL.txt"
# still resolves to the NUL device. Compared against the component's stem,
# upper-cased. Enforced on every platform for cross-target parity.
_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

# Characters illegal in a Windows path component (plus they are excellent
# injection fodder). '/' is the separator and handled separately; '\\' is
# rejected wholesale before we get here.
_INVALID_COMPONENT_CHARS = frozenset('<>:"|?*')

# Trusted-side control state the confined surface must never touch.
#
# The rule is scoped to the *mechanism*, not to the paths of one known exploit:
# the sandbox root IS the QA git repo root (CE_DESIGN §2.1), and the only code
# the trusted side ever executes is git (qa_git.py, transports.py). So anything
# git reads out of a working tree as configuration or as code is reachable
# machinery, and a write here becomes execution or corruption on the trusted
# side later — the class this rule closes, not the two files that revealed it:
#
#   .git/hooks/*    executed verbatim by the orchestrator's commit
#   .git/config     core.fsmonitor / core.pager / filter.*.clean / alias.* run commands
#   .git/**         refs + objects: the history rollback and drift detection trust
#   .gitattributes  selects filter/diff/merge drivers (commands live in config)
#   .gitignore      decides what `git add -A` stages, i.e. what the manifest sees
#   .gitmodules     submodule config; the classic vector for planting a hook
#
# Compared case-folded: on a case-insensitive filesystem (Windows, default
# macOS) ".GIT" reaches the same directory, so a case-sensitive check would be
# bypassable there. Composes *after* the existing component normalization, which
# already kills the ADS (".git::$INDEX_ALLOCATION" -> INVALID_CHAR) and
# trailing-dot (".git." -> TRAILING_DOT_SPACE) aliases of these same names.
#
# Nothing legitimate reaches these through the confined surface: qa_git writes
# .gitignore via a real path at init, and git is dashboard machinery, never an
# agent tool (law 6). Reads are refused as well as writes, for that reason.
_GIT_CONTROL_NAMES = frozenset({".git", ".gitattributes", ".gitignore", ".gitmodules"})

# The content-addressed attic (.qa/attic/<sha256>) is the rollback reserve: a
# write there substitutes content under a hash the orchestrator restores by.
# PointerManager reaches it by real path, never through this chokepoint, so
# denying it costs nothing. Sibling .qa/trash is deliberately NOT denied —
# fileops.trash() resolves it here, and nothing executes or trusts its contents.
_CONTROL_PREFIXES = ((".qa", "attic"),)

# Pointer sidecars are *derived* state: fileops writes one whenever a managed
# binary is written, moved, or trashed, so its sha256 always describes the bytes
# actually on disk. Nothing legitimate authors one by name — and a hand-written
# sidecar is a forgery with real consequences, because the promotion manifest is
# a git diff over tracked files and the tracked file for a binary IS its .ptr.
# A sidecar rewound to a stale sha hides a binary change from the manifest, and
# a sidecar naming another blob's hash makes reconcile() materialize that blob
# at this path (bounded by attic contents; it cannot push wrong bytes to SOT,
# since transports upload the real file).
#
# This is a denial on the *agent-facing* surface only, and it is structural
# rather than a rule to enforce: fileops' own sidecar maintenance runs through
# PointerManager and pointer_path_of() on already-resolved paths, and never
# re-enters resolve(). So the machinery keeps writing sidecars; only paths
# arriving as agent-supplied strings are refused.
_DERIVED_SUFFIX = ".ptr"


class PathRejected(ValueError):
    """A path failed Layer-1 confinement. Carries the machine-readable reason
    and the offending input for the audit log."""

    def __init__(self, reason: RejectReason, userpath: str, detail: str = ""):
        self.reason = reason
        self.userpath = userpath
        self.detail = detail
        msg = f"path rejected ({reason.value}): {userpath!r}"
        if detail:
            msg += f" — {detail}"
        super().__init__(msg)


@dataclass(frozen=True)
class Sandbox:
    """The confinement boundary. ``root`` is the resolved, canonical sandbox
    directory; ``resolve()`` maps a logical relative path to a real contained
    path or raises :class:`PathRejected`.

    Construct via :meth:`open` so the root is canonicalized once and its own
    ancestry is fixed; thereafter every request is checked against that fixed
    root.
    """

    root: Path

    @classmethod
    def open(cls, root: str | os.PathLike[str], *, create: bool = False) -> "Sandbox":
        """Canonicalize the sandbox root once. With ``create=True`` the root is
        created if absent (parents included). The root must exist and be a
        directory afterwards."""
        p = Path(root)
        if create:
            p.mkdir(parents=True, exist_ok=True)
        if not p.exists():
            raise FileNotFoundError(f"sandbox root does not exist: {root!r}")
        resolved = p.resolve(strict=True)
        if not resolved.is_dir():
            raise NotADirectoryError(f"sandbox root is not a directory: {root!r}")
        return cls(root=resolved)

    # -- the chokepoint -----------------------------------------------------

    def resolve(self, userpath: str) -> Path:
        """Validate and canonicalize a logical relative path. Returns a real
        path guaranteed to sit inside the sandbox with no symlink in its
        existing ancestry. Raises :class:`PathRejected` otherwise.

        The empty string and ``"."`` denote the sandbox root itself (useful for
        listing the top level); any other ``.`` or ``..`` component is refused.
        """
        components = self._validate_to_components(userpath)

        # Purely lexical join — we have already refused '..', absolute forms,
        # and separators, so this cannot climb out of root.
        candidate = self.root.joinpath(*components)

        # Refuse any symlink in the existing prefix: following an in-sandbox
        # symlink (even one pointing back inside) is forbidden by policy, and a
        # symlink pointing out is exactly the escape we guard against. We check
        # before trusting resolve(), which would silently traverse links.
        self._reject_symlinks_in_prefix(candidate, userpath)

        resolved = candidate.resolve(strict=False)

        # Belt and suspenders: after canonicalization the path must still be
        # within root. With the checks above this should always hold; if it
        # does not, something climbed out and we refuse.
        if resolved != self.root and not resolved.is_relative_to(self.root):
            raise PathRejected(RejectReason.ESCAPES_ROOT, userpath, str(resolved))
        return resolved

    # -- validation stages --------------------------------------------------

    def _validate_to_components(self, userpath: str) -> list[str]:
        if userpath is None:  # type: ignore[comparison-overlap]
            raise PathRejected(RejectReason.EMPTY, "")
        if "\x00" in userpath:
            raise PathRejected(RejectReason.NULL_BYTE, userpath)
        # Reject anything the filesystem cannot represent (e.g. lone
        # surrogates) up front, so later os.* calls cannot crash on it.
        try:
            userpath.encode(sys.getfilesystemencoding(), "strict")
        except UnicodeError:
            raise PathRejected(RejectReason.UNENCODABLE, userpath) from None

        stripped = userpath.strip()
        # Whole-path aliases for "the root itself".
        if stripped in ("", "."):
            return []

        if "\\" in userpath:
            raise PathRejected(RejectReason.BACKSLASH, userpath)
        if userpath.startswith("~"):
            raise PathRejected(RejectReason.HOME_EXPANSION, userpath)
        if userpath.startswith("/"):
            raise PathRejected(RejectReason.ABSOLUTE, userpath)
        # Drive-relative / drive-absolute (e.g. "C:", "C:foo", "C:/foo").
        if len(userpath) >= 2 and userpath[1] == ":" and userpath[0].isalpha():
            raise PathRejected(RejectReason.DRIVE_LETTER, userpath)

        components: list[str] = []
        for part in userpath.split("/"):
            self._validate_component(part, userpath)
            components.append(part)
        self._reject_control_prefix(components, userpath)
        return components

    def _reject_control_prefix(self, components: list[str], userpath: str) -> None:
        """Refuse trusted-side control subtrees identified by a path prefix
        (as opposed to a reserved component name, handled per-component)."""
        folded = [c.casefold() for c in components]
        for prefix in _CONTROL_PREFIXES:
            if folded[: len(prefix)] == list(prefix):
                raise PathRejected(RejectReason.CONTROL_PATH, userpath, "/".join(prefix))

    def _validate_component(self, part: str, userpath: str) -> None:
        if part == "":
            # Leading/trailing/double slash. (Trailing slash yields one empty
            # part; we refuse it rather than guess intent.)
            raise PathRejected(RejectReason.EMPTY_COMPONENT, userpath)
        if part == ".":
            raise PathRejected(RejectReason.DOT_COMPONENT, userpath)
        if part == "..":
            raise PathRejected(RejectReason.TRAVERSAL, userpath)

        for ch in part:
            if ord(ch) < 0x20:
                raise PathRejected(RejectReason.CONTROL_CHAR, userpath, repr(ch))
            if ch in _INVALID_COMPONENT_CHARS:
                raise PathRejected(RejectReason.INVALID_CHAR, userpath, repr(ch))

        # Windows aliases a component to its rstrip('. ') form, so a trailing
        # dot or space lets "foo " masquerade as "foo". Refuse.
        if part != part.rstrip(". "):
            raise PathRejected(RejectReason.TRAILING_DOT_SPACE, userpath, repr(part))

        stem = part.split(".", 1)[0].upper()
        if stem in _RESERVED_NAMES:
            raise PathRejected(RejectReason.RESERVED_NAME, userpath, part)

        # Git control state, at ANY depth: a nested repo (content/foo/.git/...)
        # carries its own hooks and config, so this is not a root-only rule.
        if part.casefold() in _GIT_CONTROL_NAMES:
            raise PathRejected(RejectReason.CONTROL_PATH, userpath, part)

        # Machinery-maintained derived state. Case-folded for the same reason as
        # above: ".PTR" names the same file on a case-insensitive filesystem.
        if part.casefold().endswith(_DERIVED_SUFFIX):
            raise PathRejected(RejectReason.DERIVED_STATE, userpath, part)

    def _reject_symlinks_in_prefix(self, candidate: Path, userpath: str) -> None:
        rel = candidate.relative_to(self.root)
        cur = self.root
        for part in rel.parts:
            cur = cur / part
            try:
                is_link = cur.is_symlink()
            except (OSError, ValueError):
                # Broken/odd entry (e.g. name too long) — treat conservatively
                # as existing-but-bad and refuse.
                is_link = True
            if is_link:
                raise PathRejected(RejectReason.SYMLINK, userpath, str(cur))
            if not cur.exists():
                # Remaining components do not exist yet (e.g. a write target).
                # Nothing left to follow, so nothing left to forbid.
                return
