"""Seed (or re-seed) the shadow SOT from production.

The shadow is a disposable copy of production content the dashboard can be
driven against by a human — realistic drift, orphans and legacy quirks instead
of fixtures. Re-seeding is expected to happen repeatedly, which is why this is a
committed entry point rather than a one-off snippet.

    export GCP_BUCKET=<production>        # read-only, never written
    export GCP_TEST_BUCKET=<disposable>   # holds shadow-sot/
    python scripts/seed_shadow_sot.py                 # everything
    python scripts/seed_shadow_sot.py ttl/,documents/ # selected prefixes
    python scripts/seed_shadow_sot.py ttl/model/ --force-qa-only   # incl. QA-only
    python scripts/seed_shadow_sot.py --mirror --dry-run   # what a mirror would do
    python scripts/seed_shadow_sot.py --mirror             # make shadow == production

**`--mirror` makes the shadow EQUAL to production** (within the prefix filter):
it copies only what is new or changed, and DELETES what production does not
have. NOTHING of QA's survives (Rick, 2026-11-19): `operational/` is mirrored
like everything else, so the shadow's QA backups are replaced by production's,
and `qa_only` protection does not apply. Only paths outside the prefix filter
are left alone. It refuses to run if production lists nothing or more than
a quarter of the shadow would go. Always `--dry-run` first: it lists every
deletion and writes nothing. After a mirror, refresh the QA instance (its
Refresh card) so the QA tree follows, and re-freeze `verify_shadow.py`.

Paths listed in `shadow_sot.qa_only` are held deliberately ahead of production
and are SKIPPED, because re-seeding would otherwise replace an ontology change
being tried in QA with production's older copy — silently, since the
convergence is adds-only and the previous content is simply gone.

Safety: production is opened as a ReadOnlySource, which has no ``converge``
method, so this script *cannot* write to it — the guarantee is the type, not
this docstring (CE_DESIGN §2e). Everything it writes goes under the configured
`shadow_sot.prefix` on the test bucket, never at the bucket root, and never in
the `cwva-dashboard-tests/` prefix the live suite owns.

Cost note (re-measured 2026-10-29, and the earlier note was off by ~8x): a
FULL clone is now bandwidth-bound. 1741 objects, 3.93 GB, 960 s at a steady
4.09 MB/s. The 2026-07-19 measurement — 392 objects, 1.5 MB, 119 s,
latency-bound at ~0.30 s per small RDF object, time scaling with object COUNT
rather than size — held only while the shadow was image-less. The 2026-09-11
image seed brought 1093 objects and 3.72 GB, and images are now 94% of the
bytes.

**So scope the prefixes.** A metadata-or-data-only change needs no image
traffic, and `seed_shadow_sot.py ttl/` skips 1115 objects and nearly all the
bytes — the difference between sixteen minutes and a moment. Pass the full
set only when the image corpus itself has to move.

Nothing here REMOVES. The convergence is adds-only (`ChangeManifest(adds=...)`,
no deletes), with two consequences that have both been met: an object
production has DELETED stays in the shadow, and an object production still
HAS comes back even after it was deliberately deleted from the shadow through
the promotion channel. Removing something for good takes a deletion in EACH
deployment — QA promotes to the shadow, production promotes to the bucket —
or the next re-seed restores it (2026-10-29, `ttl/provenance/provenance.ttl`).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from cwva_dashboard import rson
from cwva_dashboard.promotion.transports import GcpBucketTransport, ReadOnlySource
from cwva_dashboard.sot_sync import qa_only as qa_only_mod
from cwva_dashboard.sot_sync.clone import (MAX_DELETE_FRACTION, clone_source_to_target,
                                           mirror_source_to_target, plan_mirror)

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "dashboard.rson"


def _make_include(prefixes, protected, force):
    """Which source paths to copy: the prefix filter, minus anything held
    deliberately ahead of production (unless forced)."""

    def include(rel: str) -> bool:
        if prefixes and not any(rel.startswith(p) for p in prefixes):
            return False
        if not force and qa_only_mod.is_protected(rel, protected):
            return False
        return True

    return include


def _by_folder(paths) -> str:
    counts: dict[str, int] = {}
    for p in paths:
        top = "/".join(p.split("/")[:2]) if p.startswith("ttl/") else p.split("/")[0]
        counts[top] = counts.get(top, 0) + 1
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none"


def _print_plan(plan, mirror: bool, list_limit: int = 60) -> None:
    print(f"\nproduction {plan.source_objects} objects, shadow {plan.target_objects}")
    print(f"  unchanged : {plan.unchanged}")
    for title, paths in (("new", plan.new), ("changed", plan.changed)):
        print(f"  {title:<10}: {len(paths)}  ({_by_folder(paths)})")
        for p in paths[:list_limit]:
            print(f"      + {p}" if title == "new" else f"      ~ {p}")
        if len(paths) > list_limit:
            print(f"      ... and {len(paths) - list_limit} more")
    if mirror:
        print(f"  DELETE    : {len(plan.delete)}  ({_by_folder(plan.delete)})")
        for p in plan.delete:  # every one, always: this is the list to read
            print(f"      - {p}")
    else:
        print(f"  shadow-only, left in place (adds-only seed): {len(plan.delete)}")
    print(f"  kept      : {len(plan.kept)} shadow-only, never deleted "
          f"({_by_folder(plan.kept)})")


def main(argv: list[str]) -> int:
    from google.cloud import storage  # optional dep: pip install -e ".[gcp]"

    cfg = rson.load(str(_CONFIG))["shadow_sot"]
    args = [a for a in argv[1:] if not a.startswith("--")]
    prefixes = args[0].split(",") if args else None
    force = "--force-qa-only" in argv
    mirror = "--mirror" in argv
    dry_run = "--dry-run" in argv
    unknown = [a for a in argv[1:] if a.startswith("--")
               and a not in ("--force-qa-only", "--mirror", "--dry-run")]
    if unknown:
        print(f"error: unknown option(s) {unknown}")
        return 2

    # Paths deliberately ahead of production are NOT overwritten. Re-seeding is
    # a routine operation, so without this a single run silently replaces an
    # ontology change being tried in QA with production's older copy.
    protected = qa_only_mod.load(cfg)
    if protected and not force:
        print(f"protected: {len(protected)} qa_only path(s) will NOT be overwritten")
        for entry in protected:
            print(f"   {entry}")
    elif protected:
        print(f"--force-qa-only: OVERWRITING {len(protected)} protected path(s)")

    try:
        prod_name = os.environ[cfg["source_bucket_env"]]
        shadow_name = os.environ[cfg["bucket_env"]]
    except KeyError as missing:
        print(f"error: {missing} is not set (bucket names come from the environment)")
        return 2

    # No hardcoded project: environment first, then whatever ADC resolves to.
    import google.auth

    credentials, project = google.auth.default()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or project
    project = project or getattr(credentials, "quota_project_id", None)
    client = storage.Client(project=project, credentials=credentials)

    source = ReadOnlySource(
        GcpBucketTransport(client.bucket(prod_name), prefix=cfg.get("source_prefix", "")),
        label="production",
    )
    shadow = GcpBucketTransport(client.bucket(shadow_name), prefix=cfg["prefix"])

    print(f"source : {prod_name} ({source.name}, writable={hasattr(source, 'converge')})")
    print(f"shadow : {shadow_name}/{cfg['prefix']}")
    print(f"filter : {','.join(prefixes) if prefixes else '(everything)'}")
    include = _make_include(prefixes, protected, force)

    if mirror or dry_run:
        if mirror and not cfg.get("prefix", "").strip("/"):
            print("error: --mirror needs a shadow prefix; it will not delete at a bucket root")
            return 2
        if mirror and protected:
            print(f"--mirror: qa_only does not apply; {len(protected)} protected "
                  "path(s) will be made equal to production like everything else")
        plan = plan_mirror(
            source.snapshot(), shadow.snapshot(),
            include=(lambda rel: not prefixes or any(rel.startswith(p) for p in prefixes)),
            keep=(None if mirror or force
                  else (lambda rel: qa_only_mod.is_protected(rel, protected))),
        )
        _print_plan(plan, mirror)
        why = plan.refusal(MAX_DELETE_FRACTION) if mirror else None
        if why:
            print(f"\nREFUSED: {why}")
            return 1
        if dry_run:
            print("\n--dry-run: nothing was written.")
            return 0
        print(f"\nmirroring: copy {len(plan.copy)}, delete {len(plan.delete)}")
        with tempfile.TemporaryDirectory(prefix="shadow-mirror-") as staging:
            report = mirror_source_to_target(
                source, shadow, staging, plan,
                progress=lambda r: print(f"  ... {r.objects} objects, {r.mb:.1f} MB, "
                                         f"{r.elapsed_s:.1f}s", flush=True))
        print("\n" + report.summary())
        print(f"deleted {len(plan.delete)} shadow-only object(s)")
        after = shadow.snapshot()
        print(f"shadow now holds {len(after)} objects")
        if report.failures:
            print("FAILURES:")
            for f in report.failures:
                print("  " + f)
            return 1
        print("\nnext: rebuild the QA sandbox from the shadow (see "
              "the refresh-after-legacy procedure), then re-freeze verify_shadow.py")
        return 0

    print(f"shadow currently holds {len(shadow.snapshot())} objects")

    with tempfile.TemporaryDirectory(prefix="shadow-seed-") as staging:
        report = clone_source_to_target(
            source,
            shadow,
            staging,
            include=include,
            batch_objects=100,
            progress=lambda r: print(
                f"  ... {r.objects} objects, {r.mb:.1f} MB, {r.elapsed_s:.1f}s"
                f" ({r.rate_mb_s:.2f} MB/s)",
                flush=True,
            ),
        )

    print("\n" + report.summary())
    print(json.dumps(report.to_dict() | {"skipped": len(report.skipped)}, indent=2))
    print(f"\nshadow now holds {len(shadow.snapshot())} objects")
    if report.failures:
        print("FAILURES:")
        for f in report.failures:
            print("  " + f)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
