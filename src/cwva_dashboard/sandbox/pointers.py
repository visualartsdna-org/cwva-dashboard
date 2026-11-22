"""Binary-asset pointers — hand-rolled LFS (CE_DESIGN §3.4).

Binaries (images, pdf) are large and never revised, only replaced. They live at
their real paths in the QA content tree — the true SOT mirror the browser, QA
store, and convergence all read — but git **ignores** them and tracks a small
sidecar **pointer** instead (``<name>.ptr``: sha256, size, timestamp). This is
the git-LFS pattern without the filter machinery.

Two invariants make it work, both enforced through ``fileops.py`` (the single
write chokepoint):

1. A managed binary and its ``.ptr`` sidecar are always consistent — every
   write/move/delete updates both atomically.
2. When a binary is replaced, the superseded content is preserved in a
   content-addressed **attic** (``.qa/attic/<sha256>``) outside the mirrored
   tree. The content tree therefore always equals the desired SOT state (no
   accumulation), while rollback can re-materialize an old binary from the
   attic to match a pointer restored by git.

The sha256 in the pointer doubles as the convergence/drift comparison key on
every transport. This module is pure sandbox machinery; it imports nothing from
the promotion layer.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "Pointer",
    "PointerManager",
    "sha256_file",
    "is_managed_binary",
    "pointer_path_of",
    "binary_path_of",
    "DEFAULT_GIT_CONTENT_EXTENSIONS",
    "POINTER_SUFFIX",
]

POINTER_SUFFIX = ".ptr"

# THE POLICY IS INVERTED (2026-07-21): this enumerates what stays ORDINARY GIT
# CONTENT; everything else is pointer-managed. Previously it listed the binaries
# and everything unlisted defaulted to git, which meant every unanticipated
# type (.svg, .heic, .glb, .zip) silently became a tracked blob in a history
# that can never be rewritten (law 6).
#
# The criterion is editorial intent, NOT detectable structure: "does a user edit
# this and want to see a diff of it?" That cannot be sniffed. An .svg is valid
# UTF-8 and structurally diffable, yet nobody hand-edits one or reads its diff —
# extension is the honest proxy for intent, and the judgment belongs in a list.
#
# Omission now fails SAFE but not free: a forgotten text type becomes
# pointer-managed and quietly stops being diffable. That is recoverable (add it,
# re-sync) whereas the old direction was not, so the list is enumerated from
# "what does a user author" rather than derived from what happens to exist.
#
# Deliberately absent, with reasons:
#   .svg   authored by tools, never hand-edited; a diff is meaningless
#   .json  in this domain it is generated web analytics (production carries 18,
#          one of them 17 MB) — meaningless to diff, ruinous in history
#   images/.pdf/.glb/.zip/.heic/.ico — binary
DEFAULT_GIT_CONTENT_EXTENSIONS = frozenset(
    {
        # RDF / semantic sources — hand-edited, diffed constantly
        ".ttl",
        ".turtle",
        ".nt",
        ".n3",
        ".trig",
        ".jsonld",
        ".rdf",
        ".owl",
        ".xml",
        # CWVA's own authored formats
        ".tsh",  # topic/scheme DSL (ttl/topics/topics.tsh in production)
        ".sparql",
        ".rq",
        ".rson",
        # prose and tabular sources
        ".md",
        ".txt",
        ".rst",
        ".csv",
        ".tsv",
        # authored markup/config. .html is ambiguous in practice — production has
        # hand-written prose (ttl/topics/topic.html) AND generated pages
        # (stats/chart.html) — and extension cannot separate them. Diffability of
        # authored prose wins; a generated page tracked as text is cheap.
        ".html",
        ".htm",
        ".css",
        ".js",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
    }
)

# Machinery that must stay git content no matter what the user-facing rule says.
# These share the path space with user content, so the inversion would otherwise
# swallow them:
#   *.ptr        the sidecars themselves — a sidecar for a sidecar is absurd
#   dotfiles     .gitignore is tracked, extensionless, and rewritten by the
#                machinery; PointerManager walks real paths, so Layer 1's
#                control-path denial does not protect it here
# The hygiene ledger needs no carve-out: /.qa/ is gitignored wholesale, so it
# is genuinely a separate path space.
_MACHINERY_SUFFIXES = (POINTER_SUFFIX,)

_CHUNK = 1 << 16


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> tuple[str, int]:
    """Return (hex sha256, size) of a file, streamed."""
    h = hashlib.sha256()
    size = 0
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def is_managed_binary(name: str, git_content: frozenset[str]) -> bool:
    """True if ``name`` is pointer-managed — i.e. **not** one of the types kept
    as ordinary git content.

    The complement is the default (see :data:`DEFAULT_GIT_CONTENT_EXTENSIONS`),
    so an unrecognized type gets a sidecar rather than becoming a permanent blob
    in git history. Three things are never managed:

    - ``.ptr`` sidecars (machinery, and a sidecar for a sidecar is absurd)
    - dotfiles such as ``.gitignore`` — extensionless machinery in the content
      path space, which ``PointerManager`` reaches by real path
    - extensionless files generally: binaries essentially always carry an
      extension, while ``README``/``LICENSE``-style files are text
    """
    base = Path(name).name
    low = base.lower()
    if low.endswith(_MACHINERY_SUFFIXES):
        return False
    if base.startswith("."):  # dotfile: machinery/config, keep it diffable
        return False
    suffix = Path(low).suffix
    if not suffix:  # extensionless -> treat as text
        return False
    return suffix not in {e.lower() for e in git_content}


def pointer_path_of(binary: str | Path) -> Path:
    return Path(str(binary) + POINTER_SUFFIX)


def binary_path_of(pointer: str | Path) -> Path:
    s = str(pointer)
    if not s.endswith(POINTER_SUFFIX):
        raise ValueError(f"not a pointer path: {pointer!r}")
    return Path(s[: -len(POINTER_SUFFIX)])


@dataclass(frozen=True)
class Pointer:
    sha256: str
    size: int
    created: str

    def to_json(self) -> str:
        return json.dumps(
            {"sha256": self.sha256, "size": self.size, "created": self.created},
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, text: str) -> "Pointer":
        d = json.loads(text)
        return cls(sha256=d["sha256"], size=int(d["size"]), created=d.get("created", ""))


class PointerManager:
    """Sidecar + attic operations over a content tree. Given real (resolved)
    paths inside the sandbox; does no path validation itself (fileops does)."""

    def __init__(
        self,
        root: Path,
        *,
        git_content: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
        attic_dir: str = ".qa/attic",
    ):
        self.root = Path(root)
        self.git_content = frozenset(e.lower() for e in git_content)
        self.attic = self.root / attic_dir

    def is_managed(self, name: str | Path) -> bool:
        return is_managed_binary(Path(name).name, self.git_content)

    # -- sidecars -----------------------------------------------------------

    def write_sidecar(self, binary: Path) -> Pointer:
        sha, size = sha256_file(binary)
        ptr = Pointer(sha256=sha, size=size, created=_now())
        pointer_path_of(binary).write_text(ptr.to_json())
        return ptr

    def read_sidecar(self, binary: Path) -> Pointer | None:
        p = pointer_path_of(binary)
        if p.exists():
            return Pointer.from_json(p.read_text())
        return None

    # -- attic --------------------------------------------------------------

    def attic_store(self, binary: Path) -> str | None:
        """Preserve a binary's current content in the content-addressed attic.
        Returns its sha, or None if the file is absent. Deduplicated by hash."""
        if not binary.exists():
            return None
        sha, _ = sha256_file(binary)
        dest = self.attic / sha
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(binary, dest)
        return sha

    def attic_retrieve(self, sha: str, dest: Path) -> bool:
        """Re-materialize attic content ``sha`` to ``dest``. False if absent."""
        src = self.attic / sha
        if not src.exists():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return True

    # -- rebuild (sync support) ---------------------------------------------

    def rebuild_sidecars(self, content_root: Path | None = None) -> dict:
        """Make the pointer set match the binary set (binary is truth), the
        direction SOT→QA sync needs: write/update a ``.ptr`` for every managed
        binary, and drop any sidecar whose binary is gone. Inverse of
        :meth:`reconcile` (which treats the pointer as truth, for rollback)."""
        content_root = Path(content_root) if content_root is not None else self.root
        updated: list[str] = []
        removed: list[str] = []

        for f in content_root.rglob("*"):
            if not f.is_file() or _skip(f):
                continue
            if self.is_managed(f.name):
                existing = self.read_sidecar(f)
                sha, _ = sha256_file(f)
                if existing is None or existing.sha256 != sha:
                    self.write_sidecar(f)
                    updated.append(f.relative_to(content_root).as_posix())

        for ptr in content_root.rglob("*" + POINTER_SUFFIX):
            if _skip(ptr):
                continue
            if not binary_path_of(ptr).exists():
                ptr.unlink()
                removed.append(binary_path_of(ptr).relative_to(content_root).as_posix())

        return {"updated": sorted(updated), "removed": sorted(removed)}

    # -- reconciliation (rollback support) ----------------------------------

    def reconcile(self, content_root: Path | None = None) -> dict:
        """Make the binary set match the pointer set after a git tree restore
        (rollback): re-materialize any binary whose sidecar was restored to an
        older sha, and delete any managed binary whose sidecar is gone."""
        content_root = Path(content_root) if content_root is not None else self.root
        restored: list[str] = []
        removed: list[str] = []

        for ptr in content_root.rglob("*" + POINTER_SUFFIX):
            if _skip(ptr):
                continue
            binary = binary_path_of(ptr)
            want = Pointer.from_json(ptr.read_text())
            if not binary.exists() or sha256_file(binary)[0] != want.sha256:
                if self.attic_retrieve(want.sha256, binary):
                    restored.append(binary.relative_to(content_root).as_posix())

        for f in content_root.rglob("*"):
            if not f.is_file() or _skip(f):
                continue
            if self.is_managed(f.name) and not pointer_path_of(f).exists():
                f.unlink()
                removed.append(f.relative_to(content_root).as_posix())

        return {"restored": sorted(restored), "removed": sorted(removed)}


def _skip(p: Path) -> bool:
    parts = set(p.parts)
    return ".git" in parts or ".qa" in parts
