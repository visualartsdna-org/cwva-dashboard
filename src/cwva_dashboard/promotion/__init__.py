"""Promotion lifecycle — the single gated exit (CE_DESIGN §3).

Everything one workflow produces promotes to the user's source of truth (SOT)
**atomically** as a promotion unit: manifest -> gates -> preview -> commit in
the private QA git -> transport-specific state convergence. Nothing else in the
dashboard writes toward SOT.

This subpackage is trusted dashboard machinery and runs in the orchestrator
process, not in the confined worker: the worker is Landlock-bound to the
sandbox and could not converge to SOT even if asked. Git here is machinery,
never an agent tool (CLAUDE.md law 6).
"""

from .apply import ApplyResult, DriftError, apply_unit
from .preview import ChangePreview, build_preview
from .rollback import RollbackError, RollbackResult, rollback_unit
from .transports import (
    FilesTransport,
    GcpBucketTransport,
    GitLocalTransport,
    GitRemoteTransport,
    Transport,
)
from .unit import ChangeManifest, GateResult, PromotionStatus, PromotionUnit

__all__ = [
    "PromotionUnit",
    "ChangeManifest",
    "GateResult",
    "PromotionStatus",
    "apply_unit",
    "ApplyResult",
    "DriftError",
    "rollback_unit",
    "RollbackResult",
    "RollbackError",
    "build_preview",
    "ChangePreview",
    "Transport",
    "FilesTransport",
    "GitLocalTransport",
    "GitRemoteTransport",
    "GcpBucketTransport",
]
