"""SOT→QA sync, adopt, and refresh (CE_DESIGN §4).

``sync`` pulls current SOT content into the QA working tree via a transport,
rebuilds the pointer sidecars so binary changes surface, and reports **drift**:
the difference between what SOT now holds and QA's last-known baseline (HEAD).
Drift means SOT changed out of band — a direct user edit or another publisher.

The user then either **adopts** the drift (``adopt_external`` commits it as the
new baseline, so QA HEAD ≡ SOT again) or investigates first. ``refresh`` is the
coarse reset: discard work in progress, reconcile binaries to HEAD, then sync —
it doubles as crash recovery.

Sync never writes toward SOT; it only reads. It is safe to run before every
workflow start.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, PointerManager, POINTER_SUFFIX
from ..promotion.qa_git import QAGit
from ..promotion.transports import Transport
from ..promotion.unit import LOCAL_ONLY_DIRS, ChangeManifest

__all__ = ["sync", "adopt_external", "refresh", "SyncResult"]

AuditFn = Callable[[str, dict, str], None]


@dataclass
class SyncResult:
    drift: ChangeManifest
    stamp: str
    clean: bool = field(default=False)

    def __post_init__(self) -> None:
        self.clean = self.drift.is_empty()


# QA-internal files that mirror nothing in SOT and must never be synced/deleted.
_QA_INTERNAL = {".gitignore"}


def _content_snapshot(root: Path, fingerprint=None) -> dict[str, str]:
    """{relpath: fingerprint} of QA's real content — RDF, md, binaries —
    excluding git/QA-internal files and the derived .ptr sidecars (which SOT
    never has).

    ``fingerprint`` comes from the TRANSPORT so both sides of the sync
    comparison speak the same hash. Defaults to sha256 for callers that just
    want a content digest.
    """
    import hashlib

    if fingerprint is None:
        def fingerprint(fp):
            return hashlib.sha256(fp.read_bytes()).hexdigest()

    out: dict[str, str] = {}
    for dirpath, dirs, files in _walk(root):
        for f in files:
            fp = Path(dirpath) / f
            if fp.name.endswith(POINTER_SUFFIX) or fp.name in _QA_INTERNAL:
                continue
            rel = fp.relative_to(root).as_posix()
            out[rel] = fingerprint(fp)
    return out


def _walk(root: Path):
    """Every file the SOT has an opinion about.

    `.git` and `.qa` are machinery. **`evidence/` is excluded for a different
    reason and it is the one that bit**: it is content the SOT deliberately
    never holds (`promotion/unit.py`), so a sync comparing the tree against
    the target found it locally, found it absent there, and deleted it — on
    every promotion, because a successful convergence is followed by a
    refresh (#25).

    So every evidence file #15 and DTS ever wrote was destroyed moments after
    being committed, which is how the directory came to hold six empty
    folders and a staged deletion. Two independent faults made the same claim
    false: the manifest shipped it (fixed 2026-09-29) and the refresh deleted
    it. One predicate now governs both, because "never converges" and "must
    not be deleted for being absent from the target" are two consequences of
    one fact.
    """
    import os

    skip = {".git", ".qa", *LOCAL_ONLY_DIRS}
    for dirpath, dirs, files in os.walk(root):
        if Path(dirpath) == root:
            dirs[:] = [d for d in dirs if d not in skip]
        else:
            dirs[:] = [d for d in dirs if d not in (".git", ".qa")]
        yield dirpath, dirs, files


def sync(
    qa: QAGit,
    transport: Transport,
    *,
    git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    audit: AuditFn | None = None,
) -> SyncResult:
    """Pull SOT into the QA content tree and report drift against HEAD. Does not
    commit — the caller adopts (see :func:`adopt_external`) or investigates."""
    root = qa.root
    transport.pull_remote()

    # OPERATIONAL state is not content and must never come back down. Without
    # this the next refresh would pull the QA backup into the tree it is a
    # backup OF, mint it a sidecar and make it content — a repository carrying
    # its own history as data, growing on every cycle.
    from ..backup import OPERATIONAL_PREFIX

    sot = {
        k: v for k, v in transport.snapshot().items()
        if not k.startswith(OPERATIONAL_PREFIX + "/")
    }
    have = _content_snapshot(root, getattr(transport, "local_fingerprint", None))

    # Bring QA content into line with SOT (write changed/new, delete removed).
    # If fingerprints are not directly comparable (e.g. bucket md5 vs sha256),
    # we re-fetch and write identical bytes — still correct, just less lazy.
    for path, fp in sot.items():
        if have.get(path) != fp:
            dest = root / path
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(transport.fetch(path))
    for path in have:
        if path not in sot:
            (root / path).unlink(missing_ok=True)

    # Binary is truth here: update .ptr sidecars to match pulled binaries.
    PointerManager(root, git_content=git_content_extensions).rebuild_sidecars(root)

    # Drift = QA working tree vs HEAD, at the tracked (.ptr/RDF/md) level.
    drift = qa.manifest_since(qa.head())
    result = SyncResult(drift=drift, stamp=transport.current_stamp())
    if audit:
        audit("sot.sync", {"transport": transport.name, "drift": drift.counts}, "ok")
    return result


def adopt_external(qa: QAGit, *, message: str | None = None) -> str:
    """Commit the currently-synced changes as an 'external change' baseline, so
    QA HEAD ≡ SOT again. Returns the new commit sha."""
    return qa.commit(message or "external: adopt out-of-band SOT changes")


def refresh(
    qa: QAGit,
    transport: Transport,
    *,
    git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    audit: AuditFn | None = None,
) -> SyncResult:
    """Coarse reset (CE_DESIGN §4): discard work in progress, reconcile binaries
    back to HEAD, then sync from SOT. Doubles as crash recovery."""
    qa.reset_hard("HEAD")
    qa.clean_untracked()
    # reset_hard restores tracked .ptr; reconcile fixes the gitignored binaries.
    PointerManager(qa.root, git_content=git_content_extensions).reconcile(qa.root)
    result = sync(qa, transport, git_content_extensions=git_content_extensions, audit=audit)

    # ADOPT what the sync brought down. `sync()` deliberately does not commit —
    # its caller "adopts or investigates" — and the first-sync report is the
    # investigating caller. `refresh` is the other kind: it has just discarded
    # work in progress and pulled SOT wholesale, so by definition QA is now a
    # copy of SOT and that is a BASELINE, not the user's work.
    #
    # Without this, everything a refresh pulls stays uncommitted and the next
    # promotion sweeps it up (law 4). Found 2026-09-11 after seeding 1093 images
    # into the shadow: the next annotation's unit carried 1093 `.ptr` adds, and
    # since convergence translates `<x>.ptr` -> `<x>`, approving it would have
    # pushed 3.7 GB of images back to the bucket they came from. Worse than the
    # waste, the annotation's commit would have contained 1093 unrelated files,
    # so reverting that annotation (law 6 rollback) would have deleted every
    # image from QA.
    if not result.drift.is_empty():
        adopt_external(qa, message="external: adopt refreshed SOT state")
        if audit:
            audit("sot.adopt", {"counts": result.drift.counts}, "ok")

    if audit:
        audit("sot.refresh", {"transport": transport.name}, "ok")
    return result
