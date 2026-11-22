"""Bring a SOT target into the QA tree — the entry point `sync()` never had.

:func:`sync.sync` has always been able to pull a SOT into QA, but nothing
constructed the pieces: no code opened the configured target, initialized the QA
repo at ``sandbox.stage_root``, and ran it. The sync was reachable only from the
scenario harness and from ``refresh``, so the dashboard could not be pointed at
real content at all (PROJECT_PLAN Phase 4.6 §5, gate item **B2**).

Two properties this module exists to guarantee:

**The source is read-only.** :func:`sync.sync` calls only ``pull_remote`` /
``snapshot`` / ``fetch`` / ``current_stamp``, so a :class:`ReadOnlySource` — which
has no ``converge`` — satisfies it completely. Callers seeding QA from a target
they must not modify pass one, and then "this sync wrote to the SOT" is not a
mistake the code can express. :func:`sync_into_qa` additionally *refuses* a
writable source unless told otherwise, so the safe path is the default rather
than the disciplined one.

**Layout is not translated here.** Per CE_DESIGN §3.6 the QA tree adopts the
target's own layout: relpaths are copied verbatim in both directions, and
readers resolve through the target's placement map (``config.target_layout``).
A sync that rewrote paths would make QA and SOT disagree about every address,
and drift detection, the diff manifest and convergence would each need the same
mapping applied consistently — the "two mechanisms disagreeing" shape behind
every bug in this area.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..promotion.qa_git import QAGit
from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, is_managed_binary
from .sync import AuditFn, SyncResult, sync

__all__ = ["SyncRunReport", "sync_into_qa"]


@dataclass
class SyncRunReport:
    """What a sync did, in terms the first-sync checkpoint is stated in."""

    qa_root: str
    source: str
    initialized: bool  # True when this run created the QA repo
    objects: int = 0  # files in the QA tree after the sync
    bytes: int = 0
    git_content: int = 0  # tracked as ordinary git content
    pointer_managed: int = 0  # tracked as a .ptr sidecar, binary gitignored
    sidecars: int = 0  # .ptr files actually present
    drift_adds: int = 0
    drift_modifies: int = 0
    drift_deletes: int = 0
    stamp: str = ""
    top_level: dict[str, int] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        """True when the QA tree matches HEAD — nothing to adopt."""
        return not (self.drift_adds or self.drift_modifies or self.drift_deletes)

    def summary(self) -> str:
        return (
            f"{self.objects} files ({self.bytes / 1e6:.1f} MB) in {self.qa_root}: "
            f"{self.git_content} git content, {self.pointer_managed} pointer-managed "
            f"({self.sidecars} sidecars); drift +{self.drift_adds} "
            f"~{self.drift_modifies} -{self.drift_deletes}"
        )

    def to_dict(self) -> dict:
        return {
            "qa_root": self.qa_root,
            "source": self.source,
            "initialized": self.initialized,
            "objects": self.objects,
            "bytes": self.bytes,
            "git_content": self.git_content,
            "pointer_managed": self.pointer_managed,
            "sidecars": self.sidecars,
            "drift": {
                "adds": self.drift_adds,
                "modifies": self.drift_modifies,
                "deletes": self.drift_deletes,
            },
            "stamp": self.stamp,
            "top_level": self.top_level,
        }


def _walk_content(root: Path):
    """Every real file in the QA tree, skipping machinery.

    Machinery is `.git/`, `.qa/`, and the root `.gitignore` the QA repo lays down
    at init. Counting the `.gitignore` would inflate the git-content total by one
    and quietly break comparison against the first-sync expectations, which are
    stated in SOT objects — the report must describe *what came from the SOT*.
    """
    import os

    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", ".qa")]
        for name in files:
            path = Path(dirpath) / name
            if path.parent == root and name == ".gitignore":
                continue
            yield path


def sync_into_qa(
    source,
    qa_root: str | Path,
    *,
    git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    project_root: str | Path | None = None,
    allow_writable_source: bool = False,
    audit: AuditFn | None = None,
) -> tuple[SyncRunReport, SyncResult]:
    """Open/initialize the QA repo at ``qa_root`` and pull ``source`` into it.

    ``source`` should be a :class:`ReadOnlySource`; a writable Transport is
    refused unless ``allow_writable_source`` is set, so pointing this at a target
    it could damage takes a deliberate argument rather than an oversight. The
    sync itself never writes to the source either way — the guard is about what
    the *caller* handed over, since that object is usually built from config and
    may be production.

    Returns the report plus the raw :class:`SyncResult`, whose ``drift`` is the
    authority on what changed: the caller decides whether to ``adopt_external``
    (make it the new baseline) or investigate. This function deliberately does
    **not** commit — adopting an unexamined SOT state is the operator's call.
    """
    if hasattr(source, "converge") and not allow_writable_source:
        raise TypeError(
            "sync source is writable (has converge); wrap it in ReadOnlySource, "
            "or pass allow_writable_source=True if writing back is genuinely intended"
        )

    root = Path(qa_root)
    root.mkdir(parents=True, exist_ok=True)
    initialized = not (root / ".git").exists()

    qa = QAGit.init(
        root, project_root=project_root, git_content_extensions=git_content_extensions
    )
    result = sync(
        qa, source, git_content_extensions=git_content_extensions, audit=audit
    )

    report = SyncRunReport(
        qa_root=str(root),
        source=getattr(source, "name", "source"),
        initialized=initialized,
        stamp=result.stamp,
        drift_adds=len(result.drift.adds),
        drift_modifies=len(result.drift.modifies),
        drift_deletes=len(result.drift.deletes),
    )

    for path in _walk_content(root):
        rel = path.relative_to(root).as_posix()
        report.objects += 1
        report.bytes += path.stat().st_size
        head = rel.split("/", 1)[0] if "/" in rel else "(root)"
        report.top_level[head] = report.top_level.get(head, 0) + 1
        if rel.endswith(".ptr"):
            report.sidecars += 1
            continue
        if is_managed_binary(rel, git_content_extensions):
            report.pointer_managed += 1
        else:
            report.git_content += 1

    return report, result
