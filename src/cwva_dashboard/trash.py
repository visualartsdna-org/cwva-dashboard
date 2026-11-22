"""Pruning the QA trash, once the work it belonged to is safe in the SOT.

Nothing an agent or a form does hard-deletes content the user typed: a replaced
image, a superseded record, a draft abandoned at the review stop all move to
`.qa/trash` instead (CE_DESIGN §2.3). That rule is worth keeping — it is one
rule applied everywhere rather than a judgement at each call site, and the cost
of judging wrong is asymmetric.

What it lacked was an end. Rick's sandbox held 82 entries and 42 MB going back
two weeks, with nothing to prune them and no way to see them; the trash was
insurance with no expiry (2026-09-17). His answer, and it is the right one:
prune **after a successful convergence**, because that is the moment the work
the draft belonged to is definitively somewhere else.

Two things this deliberately does not touch:

- **`.qa/attic`** — the rollback reserve. A replaced binary lives there so law 6
  can put it back; deleting it would make a rollback that succeeds in git fail
  on disk.
- **anything younger than the retention window**, so a draft trashed minutes ago
  by an Edit-form round trip survives a promotion happening in between.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

__all__ = ["prune", "PruneResult"]


@dataclass
class PruneResult:
    ok: bool = True
    removed: int = 0
    bytes_freed: int = 0
    kept: int = 0
    error: str = ""

    def to_dict(self) -> dict:
        out = {"ok": self.ok, "removed": self.removed,
               "bytes_freed": self.bytes_freed, "kept": self.kept}
        if self.error:
            out["error"] = self.error
        return out


def prune(root, trash_dir: str = ".qa/trash", keep_days: int = 30,
          now: float | None = None) -> PruneResult:
    """Delete trash entries older than `keep_days`. Never raises.

    Age comes from the file's mtime rather than the timestamp in its name. The
    names carry one — `20260903T182730-<hash>-<original>` — but a name is a
    label and mtime is the filesystem's own answer; a hand-copied file with a
    plausible name would otherwise claim an age it never had.

    `keep_days <= 0` disables pruning, which is how a deployment says it wants
    to keep everything.
    """
    result = PruneResult()
    base = Path(root) / trash_dir
    if keep_days <= 0 or not base.is_dir():
        return result

    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    for entry in sorted(base.iterdir()):
        try:
            if entry.stat().st_mtime >= cutoff:
                result.kept += 1
                continue
            size = entry.stat().st_size if entry.is_file() else 0
            if entry.is_dir():
                from shutil import rmtree

                size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                rmtree(entry)
            else:
                entry.unlink()
            result.removed += 1
            result.bytes_freed += size
        except OSError as exc:
            # One unreadable entry must not stop the rest, and must not fail a
            # promotion that has already converged.
            result.ok = False
            result.error = f"{type(exc).__name__}: {exc}"
    return result
