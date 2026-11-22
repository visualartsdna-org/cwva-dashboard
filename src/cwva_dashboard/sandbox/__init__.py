"""Sandbox subsystem — the single confined working set.

Layer 1 (path confinement, cross-platform) lives in ``paths.py``; Layer 2
(OS-enforced broker) lands later in ``broker.py``. All agent file operations
funnel through ``fileops.py``, which is the only module permitted to touch the
filesystem and which routes every path through the Layer-1 chokepoint.
"""

from .broker import (
    LandlockError,
    LandlockUnavailable,
    RestrictResult,
    landlock_abi,
    restrict_process,
)
from .paths import PathRejected, RejectReason, Sandbox

__all__ = [
    "Sandbox",
    "PathRejected",
    "RejectReason",
    "restrict_process",
    "landlock_abi",
    "RestrictResult",
    "LandlockError",
    "LandlockUnavailable",
]
