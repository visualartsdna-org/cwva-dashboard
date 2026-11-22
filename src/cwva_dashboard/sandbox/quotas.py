"""Operational hardening — quotas (CE_DESIGN §2.3).

Coarse limits that cap the blast radius of a runaway or adversarial agent:
per-write size, total regular-file count, and a rolling ops-per-minute rate.
These are policy, not security — Layers 1 and 2 are the boundary — but they
keep a well-formed-but-abusive workload from filling the disk or spinning.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

__all__ = ["Quotas", "QuotaExceeded", "RateLimiter"]


class QuotaExceeded(RuntimeError):
    """A quota would be violated. Carries which limit and the offending value."""

    def __init__(self, limit: str, value: int, ceiling: int):
        self.limit = limit
        self.value = value
        self.ceiling = ceiling
        super().__init__(f"quota exceeded ({limit}): {value} > {ceiling}")


@dataclass(frozen=True)
class Quotas:
    """Static limits, loaded from config (``quotas:`` block)."""

    max_file_bytes: int = 50 * 1024 * 1024
    max_file_count: int = 100_000
    # Kept equal to config/dashboard.rson: scripts build FileOps without config.
    max_ops_per_minute: int = 2000

    def check_write_size(self, nbytes: int) -> None:
        if nbytes > self.max_file_bytes:
            raise QuotaExceeded("max_file_bytes", nbytes, self.max_file_bytes)

    def check_file_count(self, current: int, adding: int = 1) -> None:
        projected = current + adding
        if projected > self.max_file_count:
            raise QuotaExceeded("max_file_count", projected, self.max_file_count)


class RateLimiter:
    """Rolling-window ops/minute limiter. Shared across all fileops so the cap
    is on the agent's total activity, not per-operation."""

    def __init__(self, max_ops_per_minute: int, *, window_s: float = 60.0):
        self._max = max_ops_per_minute
        self._window = window_s
        self._events: deque[float] = deque()

    def tick(self, *, now: float | None = None) -> None:
        """Record one operation; raise :class:`QuotaExceeded` if the window is
        full. ``now`` is injectable for deterministic tests."""
        t = time.monotonic() if now is None else now
        cutoff = t - self._window
        while self._events and self._events[0] <= cutoff:
            self._events.popleft()
        if len(self._events) >= self._max:
            raise QuotaExceeded("max_ops_per_minute", len(self._events) + 1, self._max)
        self._events.append(t)
