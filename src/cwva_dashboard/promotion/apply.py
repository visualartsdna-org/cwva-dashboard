"""Apply — the gated write toward SOT (CE_DESIGN §3.3–3.4, §4).

This is the one code path that converges QA content to the user's source of
truth. It runs in the trusted orchestrator (never the confined worker) and is
the single exit channel (CLAUDE.md law 1). Sequence:

1. **Gates must have passed** — apply certifies nothing itself; it refuses to
   converge a unit whose conformance gates did not pass.
2. **Authoritative manifest** — recompute the change set from the QA git diff
   against the unit's pre-work stamp, so what converges is exactly what QA
   holds, not a stale caller-supplied list.
3. **Drift check** — immediately before writing SOT, compare the transport's
   current stamp to the expected baseline; abort on unexpected drift rather
   than clobber an out-of-band change (§4).
4. **QA commit** — record the unit as one commit in the private QA git.
5. **Converge** — make SOT match via the transport (idempotent, full-state).

Returns the new SOT stamp, which the caller records as the baseline for the
next apply.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS
from .binaries import content_manifest
from .qa_git import QAGit
from .transports import Transport
from .unit import PromotionStatus, PromotionUnit

__all__ = ["apply_unit", "ApplyResult", "DriftError", "GatesNotPassedError", "EmptyUnitError"]

AuditFn = Callable[[str, dict, str], None]


class DriftError(RuntimeError):
    """SOT changed out of band since the recorded baseline; apply aborted
    before writing anything (CE_DESIGN §4)."""


class GatesNotPassedError(RuntimeError):
    """Refused to converge a unit whose conformance gates did not pass."""


class EmptyUnitError(RuntimeError):
    """The unit's change set is empty — nothing to converge."""


@dataclass
class ApplyResult:
    unit: PromotionUnit
    qa_commit: str
    sot_stamp: str


def apply_unit(
    unit: PromotionUnit,
    qa: QAGit,
    transport: Transport,
    *,
    content_root=None,
    expected_stamp: str | None = None,
    require_gates: bool = True,
    git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    audit: AuditFn | None = None,
) -> ApplyResult:
    """Converge ``unit`` to SOT via ``transport``. See module docstring for the
    sequence. ``expected_stamp`` is the SOT baseline captured at workflow start
    (or returned by a prior apply); if given and SOT no longer matches it, the
    call aborts with :class:`DriftError` before any write."""
    args = {"unit": unit.id, "workflow": unit.workflow, "transport": transport.name}

    def _emit(outcome: str) -> None:
        if audit:
            audit("promotion.apply", args, outcome)

    if require_gates and not unit.gates_passed():
        _emit("error:gates_not_passed")
        raise GatesNotPassedError(
            f"unit {unit.id} has failing/absent gates: {[g.name for g in unit.failing_gates()]}"
        )

    if unit.base_commit is None:
        _emit("error:no_base_commit")
        raise ValueError("apply requires unit.base_commit (the pre-work QA stamp)")

    # Authoritative change set: what QA actually holds since the pre-work stamp.
    manifest = qa.manifest_since(unit.base_commit)
    unit.manifest = manifest
    if manifest.is_empty():
        _emit("error:empty_unit")
        raise EmptyUnitError(f"unit {unit.id} produced no changes")

    # Drift check immediately before writing SOT — nothing has been committed
    # or pushed yet, so aborting here leaves both QA and SOT untouched.
    if expected_stamp is not None:
        current = transport.current_stamp()
        if current != expected_stamp:
            _emit("error:drift")
            raise DriftError(
                f"SOT drift on {transport.name}: expected {expected_stamp!r}, found {current!r}"
            )

    # Record the unit in the QA git, then converge SOT to it.
    commit = qa.commit(unit.commit_message())
    unit.qa_commit = commit
    unit.status = PromotionStatus.COMMITTED

    # Converge the *content* manifest: pointer sidecars become their real
    # binaries, and no .ptr is pushed to SOT (CE_DESIGN §3.4).
    to_sot = content_manifest(manifest, git_content_extensions)
    result = transport.converge(content_root or qa.root, to_sot, message=unit.commit_message())
    unit.status = PromotionStatus.CONVERGED

    _emit("ok")
    return ApplyResult(unit=unit, qa_commit=commit, sot_stamp=result.stamp)
