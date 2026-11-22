"""Append-only, tamper-evident audit log (CE_DESIGN §2.3, §8).

Every tool call is recorded: operation, arguments, outcome, timestamp, and the
provenance actor (agent identity / model identity for AI-driven actions). The
log is the operational complement to git history and the promotion audit trail.

**Append-only + hash-chained.** Each record carries the hash of the record
before it and its own hash over that chain, so any edit, reorder, or truncation
of earlier lines is detectable by :func:`verify`. The chain is not a substitute
for keeping the file out of the agent's reach — it is defense for the case
where it is not.

**Placement.** The audit log should live where the confined agent cannot rewrite
it: the intended architecture has the least-privilege broker *emit* records over
IPC to the unconfined orchestrator, which persists them here (outside the
sandbox). Writing the log is dashboard machinery — never an agent tool, and not
the promotion channel; it is operational telemetry, not SOT content. This module
is transport-agnostic about that wiring; it just needs an append target.

The record shape is intentionally simple JSON so the log is greppable and
replayable without this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

__all__ = ["AuditLog", "VerifyResult", "verify", "default_path"]

_Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(obj: Any) -> str:
    """Deterministic JSON for hashing and storage: sorted keys, no spaces,
    non-ASCII preserved, anything exotic coerced to str."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def default_path(sandbox_root) -> Path:
    """Where an instance's audit log lives: **beside** the sandbox, and named
    after it.

    Outside the sandbox, because the confined worker must not be able to rewrite
    the record of what it did. Named after the sandbox, because the log is one
    instance's — `Dashboard` owns "the registry, the hardened worker, and the
    audit log for one app instance" — and a fixed name in the shared parent gave
    two sandboxes one file.

    The chain is the reason this matters rather than being untidy. Each record
    carries the hash of the one before it, and the tail is read ONCE at
    construction, so two live writers each link onto the tail as it was when
    they started. `verify()` then reports a broken link — correctly, because it
    cannot tell two honest writers from one dishonest one. Rick's log has been
    failing verification since 2026-08-25 for exactly this reason (42 backward
    sequence jumps), from a dev server and a test run overlapping; a second
    dashboard would have made that permanent rather than occasional.

    It lives HERE rather than in `main.py` so that everything which opens an
    `AuditLog` can reach it. `tools/repl.py` could not, and used a fixed
    `~/.local/state/cwva-dashboard/audit.jsonl` — so a REPL pointed at
    production wrote the same file as a running QA dashboard, which is the
    overlap above, deliberately reintroduced (fixed 2026-10-29).
    """
    root = Path(sandbox_root)
    return root.parent / f"audit-{root.name}.jsonl"


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    count: int
    first_bad_seq: int | None = None
    detail: str = ""


class AuditLog:
    """A durable, append-only JSONL log with a per-record hash chain.

    Construct with the append target path. The chain continues correctly across
    process restarts: on open, the last record's hash and sequence are read back
    so new records link onto the existing chain.
    """

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        actor: str | None = None,
        durable: bool = True,
        clock: _Clock = _utcnow,
    ):
        self._path = Path(path)
        self._default_actor = actor
        self._durable = durable
        self._clock = clock
        self._lock = threading.Lock()

        self._path.parent.mkdir(parents=True, exist_ok=True)
        last = _read_last_record(self._path)
        self._seq = (last["seq"] + 1) if last else 0
        self._prev_hash = last["hash"] if last else ""

        # O_APPEND makes every write atomic at the end of the file, even under
        # concurrent writers; 0o600 keeps the audit trail owner-only.
        fd = os.open(self._path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        self._fd = fd

    # -- writing ------------------------------------------------------------

    def record(
        self,
        op: str,
        args: dict | None = None,
        outcome: str = "ok",
        *,
        actor: str | None = None,
        **extra: Any,
    ) -> dict:
        """Append one record and return it. Thread-safe; durable (fsync) unless
        constructed with ``durable=False``."""
        with self._lock:
            rec: dict[str, Any] = {
                "seq": self._seq,
                "ts": self._clock().isoformat(),
                "actor": actor if actor is not None else self._default_actor,
                "op": op,
                "args": args or {},
                "outcome": outcome,
                "prev": self._prev_hash,
            }
            if extra:
                rec.update(extra)
            rec["hash"] = hashlib.sha256(_canonical(rec).encode("utf-8")).hexdigest()

            line = (_canonical(rec) + "\n").encode("utf-8")
            os.write(self._fd, line)
            if self._durable:
                os.fsync(self._fd)

            self._seq += 1
            self._prev_hash = rec["hash"]
            return rec

    def as_hook(self, actor: str | None = None) -> Callable[[str, dict, str], None]:
        """Adapter matching ``fileops.AuditHook`` — ``(op, args, outcome)``.
        Binds an optional actor for all records emitted through this hook."""

        def hook(op: str, args: dict, outcome: str) -> None:
            self.record(op, args, outcome, actor=actor)

        return hook

    # -- lifecycle ----------------------------------------------------------

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None  # type: ignore[assignment]

    def __enter__(self) -> "AuditLog":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _read_last_record(path: Path) -> dict | None:
    """Return the last JSON record in the log, or None if empty/absent. Reads
    only the tail of the file rather than the whole thing."""
    if not path.exists() or path.stat().st_size == 0:
        return None
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        chunk = min(size, 65536)
        fh.seek(size - chunk)
        data = fh.read()
    lines = [ln for ln in data.split(b"\n") if ln.strip()]
    if not lines:
        return None
    return json.loads(lines[-1].decode("utf-8"))


def verify(path: str | os.PathLike[str]) -> VerifyResult:
    """Validate the hash chain end to end. Detects tampering, reordering, and
    truncation of earlier records."""
    p = Path(path)
    if not p.exists():
        return VerifyResult(ok=True, count=0, detail="no log file")

    prev = ""
    count = 0
    with open(p, "r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh):
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                return VerifyResult(False, count, count, f"line {lineno}: not JSON")

            stored = rec.pop("hash", None)
            if stored is None:
                return VerifyResult(False, count, rec.get("seq", count), "missing hash")
            if rec.get("prev") != prev:
                return VerifyResult(
                    False, count, rec.get("seq", count), "broken prev-hash link"
                )
            recomputed = hashlib.sha256(_canonical(rec).encode("utf-8")).hexdigest()
            if recomputed != stored:
                return VerifyResult(
                    False, count, rec.get("seq", count), "record hash mismatch"
                )
            if rec.get("seq") != count:
                return VerifyResult(
                    False, count, rec.get("seq", count), "sequence gap"
                )
            prev = stored
            count += 1

    return VerifyResult(ok=True, count=count)
