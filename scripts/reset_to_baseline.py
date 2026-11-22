"""Reset QA **and** the shadow bucket back to a baseline commit — the dev loop.

For driving the same entry more than once: enter a work, approve, look at the
bucket, then put both sides back exactly as they were and do it again.

    python scripts/reset_to_baseline.py --dry-run   # what would change
    python scripts/reset_to_baseline.py             # reset to the adopted baseline
    python scripts/reset_to_baseline.py --to <sha>  # reset to a specific commit

**This is rollback, not deletion** (law 6). QA is restored to the baseline tree
and the restoration is recorded as a *new* commit — history is never rewritten,
because rollback depends on it being immutable. The bucket is then converged to
that restored state, which is what removes the promoted TTL and images from the
SOT. Nothing is deleted out of band, and nothing touches production: the target
is whatever `shadow_sot` names.

Difference from `promotion/rollback.py`'s `rollback_unit`: that reverts one
identified promotion unit and needs the unit object. This resets to a *commit*,
which is what a repeatable manual test loop actually wants — it works no matter
how many entries were made since, and it needs nothing kept in memory between
runs.

**One consequence worth knowing:** an image you dropped into the sandbox becomes
part of the promoted change, so the reset removes it from QA too. Keep the
original outside the sandbox and re-copy it before the next run, or pass
``--keep`` to have this script preserve and restore matching files.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from cwva_dashboard import config as cfgmod
from cwva_dashboard.promotion.apply import content_manifest
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import GcpBucketTransport
from cwva_dashboard.sandbox.pointers import PointerManager

BASELINE_MESSAGE = "qa: adopt shadow baseline"


def _find_baseline(qa: QAGit) -> str:
    """The adopted-baseline commit, by its message — the state the shadow sync
    established and every acceptance run starts from."""
    out = qa._run("log", "--format=%H %s")
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if subject.strip() == BASELINE_MESSAGE:
            return sha
    raise SystemExit(
        f"no commit titled {BASELINE_MESSAGE!r} — pass --to <sha> explicitly"
    )


#: `--config`, else `CWVA_DASHBOARD_CONFIG`, else this repo's default. The same
#: precedence `sync_shadow_to_qa.py` and `split_aggregate.py` use.
#:
#: **It was missing, and the omission was silent.** This script called
#: `load_config()` with no argument, so it honoured neither the flag nor the
#: environment variable that SELECTS the production instance — it was hardwired
#: to QA, and a `--config config/production.rson` was accepted and ignored. I
#: ran it that way myself and read QA's numbers as production's (2026-10-01).
def _config_path(argv: list[str]) -> str:
    if "--config" in argv:
        return argv[argv.index("--config") + 1]
    return os.environ.get("CWVA_DASHBOARD_CONFIG") or cfgmod.DEFAULT_CONFIG_PATH


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    keep = "--keep" in argv
    to = None
    if "--to" in argv:
        to = argv[argv.index("--to") + 1]

    config_path = _config_path(argv)
    cfg = cfgmod.load_config(config_path)
    print(f"config : {config_path}")
    qa_root = cfgmod.sandbox_root(cfg, create=False)
    exts = cfgmod.git_content_extensions(cfg)
    target = cfgmod.shadow_sot(cfg)

    qa = QAGit(root=qa_root)
    head = qa.head()
    base = to or _find_baseline(qa)

    manifest = qa.manifest_between(head, base)
    print(f"qa      : {qa_root}")
    print(f"head    : {head[:12]}")
    print(f"baseline: {base[:12]}")
    print(f"reverting: {manifest.summary()}")
    for p in (*manifest.adds, *manifest.modifies, *manifest.deletes):
        print(f"   {p}")

    if manifest.is_empty():
        print("\nalready at the baseline — nothing to reset.")
        return 0

    dirty = qa.status_porcelain().strip()
    if dirty:
        print("\nNOTE: the QA tree has uncommitted work; it will be discarded:")
        for line in dirty.splitlines()[:10]:
            print(f"   {line}")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    bucket_name = os.environ.get(target["bucket_env"], "")
    if not bucket_name:
        print(f"error: {target['bucket_env']} is not set")
        return 2

    from google.cloud import storage

    transport = GcpBucketTransport(
        storage.Client().bucket(bucket_name), prefix=target["prefix"]
    )
    print(f"target  : {bucket_name}/{target['prefix']}")

    stash = None
    if keep:
        # Preserve files the reset would remove, so a re-run does not need them
        # staged again by hand.
        stash = Path(tempfile.mkdtemp(prefix="qa-keep-"))
        for rel in manifest.adds:
            src = qa_root / rel
            if src.is_file():
                dst = stash / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        print(f"kept    : {len(list(stash.rglob('*')))} file(s) under {stash}")

    # QA back to the baseline tree, recorded as a NEW commit (never a rewrite).
    qa.restore_to(base)
    PointerManager(qa.root, git_content=exts).reconcile(qa.root)
    commit = qa.commit(f"reset: restore to {base[:10]}", allow_empty=True)
    print(f"qa reset: {commit[:12]}")

    # Converge the bucket to the restored state — this is what deletes the
    # promoted TTL and images from the SOT.
    to_sot = content_manifest(manifest, exts)
    result = transport.converge(qa.root, to_sot, message="reset to baseline")
    print(f"sot     : converged, stamp {result.stamp[:12]}")

    if stash:
        print(f"\nkept files remain at {stash} — copy them back to re-run:")
        for p in sorted(stash.rglob("*")):
            if p.is_file():
                print(f"   cp {p} {qa_root / p.relative_to(stash)}")

    print("\nBoth sides are back at the baseline. Verify with:")
    print("   python scripts/verify_shadow.py --compare")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
