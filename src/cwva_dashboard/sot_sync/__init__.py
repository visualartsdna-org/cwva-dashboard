"""SOT sync, refresh, and drift (CE_DESIGN §4).

QA can always be rebuilt from SOT. This package pulls current SOT state into the
QA working tree, detects out-of-band SOT edits (drift), lets the user adopt them
as a new baseline, and refreshes QA (sync + reset of work in progress; also
crash recovery). It is the read side of the single channel — the complement to
``promotion`` (the write side).

Policy (CE_DESIGN §4): sync before every workflow start; re-sync and compare
immediately before every push (the pre-push check already lives in
``promotion.apply`` via the transport stamp). CE v1 is single-user,
single-workflow.
"""

from .orphans import OrphanReport, orphan_binaries
from .sync import SyncResult, adopt_external, refresh, sync

__all__ = ["sync", "adopt_external", "refresh", "SyncResult", "orphan_binaries", "OrphanReport"]
