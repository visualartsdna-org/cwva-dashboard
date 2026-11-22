"""Backing up what SOT cannot give back.

The QA content tree is reconstructible from SOT — that is what SOT is for. Two
things in it are **not**, and they are the two the rollback law rests on:

- **the commit history.** Law 6 says rollback happens in the QA git and never in
  place against SOT, so the ability to undo a promotion depends on that history
  being present. It lives on one disk.
- **`.qa/attic`**, the superseded binaries kept as the rollback reserve for a
  replaced image. SOT holds the *replacement*, by definition, so these bytes
  exist nowhere else once written.
- **the hygiene ledger** (`.qa/hygiene_ledger.ttl`): dismissals, TCAP ties,
  and the workflow board's ticks and "not needed" entries, each with its date.
  Nothing in the records says when the external website was updated; the
  ledger is the only place that fact was ever written down. Gitignored like the
  attic, so it travels as its own file (2026-11-19). To restore one, copy
  `operational/qa-ledger.ttl` back to `.qa/hygiene_ledger.ttl`.

Losing the disk loses no records at all. It loses every `revert` target, and
rollback degrades from "walk it back" to "reconstruct it by hand".

**This writes outside the sandbox, and it is not a promotion.** That needs
saying plainly, because law 1 reserves outward writes for the promotion tool.
The carve-out is narrow and structural: a repository cannot back itself up
*into itself* — bundling into the tree would change the tree being bundled — so
the destination has to be outside, and it is not content, so it must not travel
the content channel. It is the same shape as the two existing exceptions: ingest
reads in from outside (law 12), promotion writes content out (law 1), and this
writes OPERATIONAL state out. Trusted-orchestrator only; never a registry tool,
and the confined worker cannot reach any of it.

The destination prefix is deliberately **outside the content tree** and excluded
from sync (`sot_sync.sync.OPERATIONAL_PREFIX`). Without that exclusion the next
refresh would pull the backup down into the tree it is a backup of, mint it a
sidecar, and make it content — a repository containing its own history as data.
"""

from __future__ import annotations

import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .concepts.ledger import LEDGER_PATH

__all__ = ["BackupResult", "attic_status", "run_backup", "OPERATIONAL_PREFIX"]

# Where operational state lives in SOT. Not content, never synced back.
OPERATIONAL_PREFIX = "operational"

BUNDLE_NAME = "qa.bundle"
ATTIC_NAME = "qa-attic.tar.gz"
LEDGER_NAME = "qa-ledger.ttl"


@dataclass
class BackupResult:
    ok: bool = False
    bundle_bytes: int = 0
    attic_files: int = 0
    attic_bytes: int = 0
    commits: int = 0
    ledger_bytes: int = 0
    stamp: str = ""
    written: list = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "bundle_bytes": self.bundle_bytes,
            "attic_files": self.attic_files, "attic_bytes": self.attic_bytes,
            "commits": self.commits, "ledger_bytes": self.ledger_bytes,
            "stamp": self.stamp,
            "written": list(self.written), "error": self.error,
        }


def attic_status(qa_root, attic_dir: str = ".qa/attic") -> dict:
    """How much irreplaceable binary sits in the attic right now.

    Surfaced on the dashboard because the number is the whole signal: while it
    is zero the only unbacked thing is history, and the moment it is not, there
    are bytes here that exist in no bucket and no production store.
    """
    base = Path(qa_root) / attic_dir
    files = [p for p in base.rglob("*") if p.is_file()] if base.is_dir() else []
    return {
        "files": len(files),
        "bytes": sum(p.stat().st_size for p in files),
        "path": attic_dir,
    }


def _git(root: Path, *args: str) -> str:
    cp = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, check=False,
    )
    if cp.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {cp.stderr.strip()}")
    return cp.stdout.strip()


def run_backup(qa_root, transport, *, attic_dir: str = ".qa/attic",
               ledger_path: str = LEDGER_PATH) -> BackupResult:
    """Bundle the QA history (and the attic, if any) and put them in SOT.

    Written to a temporary directory first and uploaded from there, so a failure
    part-way leaves the sandbox untouched — the tree being backed up is never a
    workspace for its own backup.
    """
    root = Path(qa_root)
    res = BackupResult(stamp=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    try:
        res.commits = int(_git(root, "rev-list", "--count", "HEAD") or 0)
    except RuntimeError as exc:
        res.error = str(exc)
        return res

    attic = attic_status(root, attic_dir)
    res.attic_files, res.attic_bytes = attic["files"], attic["bytes"]

    with tempfile.TemporaryDirectory(prefix="qa-backup-") as tmp:
        staging = Path(tmp)
        bundle = staging / BUNDLE_NAME
        try:
            _git(root, "bundle", "create", str(bundle), "--all")
        except RuntimeError as exc:
            res.error = str(exc)
            return res
        res.bundle_bytes = bundle.stat().st_size

        # The attic is gitignored, so the bundle cannot carry it. It travels as
        # its own archive or it does not travel at all.
        if res.attic_files:
            with tarfile.open(staging / ATTIC_NAME, "w:gz") as tar:
                tar.add(root / attic_dir, arcname="attic")

        # The ledger likewise: gitignored, small, and the only record of the
        # board's manual ticks. Absent until the first dismissal or tick.
        ledger = root / ledger_path
        if ledger.is_file():
            data = ledger.read_bytes()
            (staging / LEDGER_NAME).write_bytes(data)
            res.ledger_bytes = len(data)

        names = [BUNDLE_NAME]
        names += [ATTIC_NAME] if res.attic_files else []
        names += [LEDGER_NAME] if res.ledger_bytes else []
        for name in names:
            rel = f"{OPERATIONAL_PREFIX}/{name}"
            transport.put_operational(rel, (staging / name).read_bytes())
            res.written.append(rel)

    res.ok = True
    return res
