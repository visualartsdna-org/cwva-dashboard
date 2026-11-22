"""Rollback — restore known-good state and converge (CE_DESIGN §3.4, law 6).

Rollback is **not** an in-place undo against SOT. Because there is no uniform
transactional undo across the transports, rollback restores a known-good state
in the QA git and converges *that* outward — the same one-way convergence apply
uses. It reverts a promotion unit by returning QA to the unit's pre-work commit,
recording that restoration as a new QA commit, and pushing the reverted state to
SOT (which may delete files there).

Coarse-grained by design: the promotion unit is the undo granule; there is no
triple-level undo. Under the CE v1 single-user/single-workflow model the unit
being rolled back is normally the latest promotion, so restoring to its
pre-work commit is exactly "remove this unit's effect."

Like apply, rollback writes toward SOT, so it drift-checks first and aborts
before touching anything if SOT moved out of band.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, PointerManager
from .apply import DriftError
from .binaries import content_manifest
from .qa_git import QAGit
from .transports import Transport
from .unit import ChangeManifest, PromotionStatus, PromotionUnit

__all__ = ["rollback_unit", "RollbackResult", "RollbackError", "DriftError"]

AuditFn = Callable[[str, dict, str], None]


class RollbackError(RuntimeError):
    """The unit cannot be rolled back (never converged, or nothing to undo)."""


@dataclass
class RollbackResult:
    unit: PromotionUnit
    qa_commit: str  # the new QA commit recording the restoration
    sot_stamp: str
    reverted: ChangeManifest


def rollback_unit(
    unit: PromotionUnit,
    qa: QAGit,
    transport: Transport,
    *,
    content_root=None,
    expected_stamp: str | None = None,
    git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    attic_dir: str = ".qa/attic",
    audit: AuditFn | None = None,
) -> RollbackResult:
    """Revert ``unit`` by converging SOT back to the unit's pre-work state.
    ``expected_stamp`` is the SOT stamp recorded when the unit was applied; if
    given and SOT no longer matches, the call aborts with :class:`DriftError`
    before any write."""
    args = {"unit": unit.id, "workflow": unit.workflow, "transport": transport.name}

    def _emit(outcome: str) -> None:
        if audit:
            audit("promotion.rollback", args, outcome)

    if unit.base_commit is None:
        _emit("error:no_base_commit")
        raise ValueError("rollback requires unit.base_commit (the pre-work QA stamp)")
    if unit.qa_commit is None or unit.status not in (
        PromotionStatus.COMMITTED,
        PromotionStatus.CONVERGED,
    ):
        _emit("error:not_converged")
        raise RollbackError(f"unit {unit.id} was never committed/converged; nothing to roll back")

    # The reverting change set: what it takes to move SOT (currently at HEAD's
    # state) back to the pre-work state. `git diff HEAD base` inverts the unit:
    # files it added -> deletes, files it removed -> adds, edits -> restored.
    current = qa.head()
    manifest = qa.manifest_between(current, unit.base_commit)
    if manifest.is_empty():
        _emit("error:nothing_to_revert")
        raise RollbackError(f"unit {unit.id} has no effect to revert at HEAD")

    # Drift check before any SOT write.
    if expected_stamp is not None:
        cur = transport.current_stamp()
        if cur != expected_stamp:
            _emit("error:drift")
            raise DriftError(
                f"SOT drift on {transport.name}: expected {expected_stamp!r}, found {cur!r}"
            )

    # Restore QA to the pre-work tree and record it as a new commit (history
    # gains a rollback entry; we never rewrite the reverted unit's commit).
    qa.restore_to(unit.base_commit)

    # restore_to only touches tracked files, so it restores the .ptr sidecars
    # but not the gitignored binaries. Reconcile the binary set to the restored
    # pointers, re-materializing superseded content from the attic (§3.4).
    manager = PointerManager(qa.root, git_content=git_content_extensions, attic_dir=attic_dir)
    manager.reconcile(qa.root)

    message = (
        f"rollback({unit.workflow}): revert unit {unit.id[:12]} "
        f"to {unit.base_commit[:10]}\n\ncwva-rollback: {unit.id}\n"
    )
    commit = qa.commit(message, allow_empty=False)

    # Converge SOT to the restored (pre-work) content — real binaries, not .ptr.
    to_sot = content_manifest(manifest, git_content_extensions)
    result = transport.converge(content_root or qa.root, to_sot, message=message)
    unit.status = PromotionStatus.ROLLED_BACK

    _emit("ok")
    return RollbackResult(unit=unit, qa_commit=commit, sot_stamp=result.stamp, reverted=manifest)
