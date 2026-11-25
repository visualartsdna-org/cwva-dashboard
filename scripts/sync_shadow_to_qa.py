"""Sync a SOT into its QA tree — gate item B2, and the way a sandbox is born.

The dashboard's opening move for a dev/test cycle: pull the shadow's content
into the sandbox at ``sandbox.stage_root``, initializing the QA git repo on
first run. Re-runnable; a second run against an unchanged shadow reports no
drift.

    export GCP_TEST_BUCKET=<disposable>   # holds shadow-sot/
    python scripts/sync_shadow_to_qa.py            # sync, report, leave uncommitted
    python scripts/sync_shadow_to_qa.py --adopt    # ...and commit as the baseline
    python scripts/sync_shadow_to_qa.py --dry-run  # report the plan, touch nothing

**Which SOT** comes from the config, so the same script seeds the PRODUCTION
instance's sandbox (2026-09-26). A config naming a `sot` block uses it; one that
does not falls back to `shadow_sot`:

    python scripts/sync_shadow_to_qa.py --config config/production.rson --adopt

Safety: the source is opened as a ``ReadOnlySource`` — no ``converge`` method —
**whichever target it is**. This script reads; it cannot write to a bucket even
by mistake, and that holds for production as much as for the shadow. The
dashboard's production instance can distribute; this cannot. Everything it
writes lands under ``sandbox.stage_root``, outside the project tree (CLAUDE.md:
the QA repo never nests with this repo).

Without ``--adopt`` the sync is left **uncommitted** in the QA working tree: the
first look at real content is the operator's to inspect, and adopting an
unexamined SOT state as a baseline is exactly the assumption the first-sync
checkpoint exists to prevent.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from cwva_dashboard import config as cfgmod
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.sot_sync.runner import sync_into_qa
from cwva_dashboard.sot_sync.sync import adopt_external

# No --config and no CWVA_DASHBOARD_CONFIG: this installation's own config
# (config/config.rson, else the developer's dashboard.rson), resolved by
# load_config.
_CONFIG = cfgmod.DEFAULT_CONFIG_PATH
_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# First-sync expectations (project plan Phase 4.6 §5 / 4.7 D2). Deviation is a
# finding, not a number to update: these are what the storage policy predicts
# for the frozen shadow, so a mismatch means the policy or the shadow moved.
#
# They are calibrated to THE SHADOW and are only checked against it. Production
# is live and its counts move with the work, so asserting a number there would
# report a finding on every successful sync — which is how a check teaches its
# reader to ignore it.
# Re-measured 2026-11-19 on the fresh sandbox built after the first mirror.
EXPECT_GIT_CONTENT = 791
EXPECT_POINTER_MANAGED = 1185


def main(argv: list[str]) -> int:
    from cwva_dashboard.promotion.targets import TargetError, build_transport, describe

    adopt = "--adopt" in argv
    dry_run = "--dry-run" in argv
    config_path = str(_CONFIG)
    if "--config" in argv:
        config_path = argv[argv.index("--config") + 1]
    elif os.environ.get("CWVA_DASHBOARD_CONFIG"):
        config_path = os.environ["CWVA_DASHBOARD_CONFIG"]

    try:
        config_path = cfgmod.resolve_config_path(config_path)
    except cfgmod.NoConfig as exc:
        print(f"error: {exc}")
        return 2
    cfg = cfgmod.load_config(config_path)
    # The target this config names: `sot` if it has one (the production
    # instance), the shadow otherwise. Same precedence the promotion driver and
    # the active layout use, so a sandbox is seeded from the SOT it will later
    # be compared against.
    shadow_cfg = cfg.get("sot") or cfgmod.shadow_sot(cfg)
    is_shadow = "sot" not in cfg
    qa_root = cfgmod.sandbox_root(cfg)
    exts = cfgmod.git_content_extensions(cfg)

    # Any kind of target (promotion/targets.py), opened READ-ONLY: a folder, a
    # git checkout or a bucket. A folder or checkout is scoped to the folders
    # the layout manages, so whatever else lives there is not imported.
    client = None
    if shadow_cfg.get("transport") == "gcp_bucket":
        import google.auth
        from google.cloud import storage  # optional dep: pip install -e ".[gcp]"

        credentials, project = google.auth.default()
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or project
        client = storage.Client(project=project, credentials=credentials)
    try:
        shadow = build_transport(shadow_cfg, cfgmod.active_layout(cfg), read_only=True,
                                 client=client)
    except TargetError as exc:
        print(f"error: {exc}")
        return 2

    print(f"config : {config_path}")
    print(f"source : {describe(shadow_cfg)} ({shadow.name})")
    print(f"qa     : {qa_root}")
    print(f"layout : verbatim — the QA tree adopts the target's layout (§3.6)")

    existing = sorted(p for p in qa_root.iterdir()) if qa_root.is_dir() else []
    print(f"qa currently holds {len(existing)} top-level entries")

    if dry_run:
        objects = shadow.snapshot()
        print(f"\nDRY RUN — would sync {len(objects)} objects; nothing written.")
        return 0

    report, result = sync_into_qa(
        shadow,
        qa_root,
        git_content_extensions=exts,
        project_root=_PROJECT_ROOT,
    )

    print("\n" + report.summary())
    print(json.dumps(report.to_dict(), indent=2))

    findings = []
    if not is_shadow:
        print("\nfirst-sync expectations are calibrated to the shadow and are "
              "not checked against a live SOT")
    if is_shadow and report.git_content != EXPECT_GIT_CONTENT:
        findings.append(
            f"git content {report.git_content} != expected {EXPECT_GIT_CONTENT}"
        )
    if is_shadow and report.pointer_managed != EXPECT_POINTER_MANAGED:
        findings.append(
            f"pointer-managed {report.pointer_managed} != expected {EXPECT_POINTER_MANAGED}"
        )
    if report.pointer_managed != report.sidecars:
        findings.append(
            f"{report.pointer_managed} pointer-managed files but {report.sidecars} "
            "sidecars — every managed binary must have a .ptr"
        )

    if findings:
        print("\nDEVIATION from the first-sync expectations — each is a finding:")
        for f in findings:
            print(f"  - {f}")
    elif is_shadow:
        print("\nsplit matches the first-sync expectations")

    label = "shadow" if is_shadow else "source of truth"
    if adopt:
        sha = adopt_external(QAGit(root=qa_root),
                             message=f"qa: adopt {label} baseline")
        print(f"\nadopted as baseline: {sha[:12]}")

    # A new collection has no ontology or thesaurus, and no form works without
    # them. As cwva-py does on first start: fetch them from the reference
    # server, but ONLY into empty folders. They land as drafts, after the
    # baseline, so the first distribution puts them into the source of truth.
    ref = cfg.get("reference_model")
    if ref and not dry_run:
        from cwva_dashboard.reference_model import fetch_reference_model
        from cwva_dashboard.sandbox.fileops import FileOps
        from cwva_dashboard.sandbox.paths import Sandbox

        fo = FileOps(Sandbox.open(qa_root), git_content_extensions=exts)
        got = fetch_reference_model(ref, fo, cfgmod.active_layout(cfg))
        for w in got.written:
            print(f"reference: {w['path']} ({w['triples']:,} triples from {w['url']})"
                  " — a draft; distribute it with Preview Staged")
        for e in got.errors:
            findings.append(f"reference model: {e}")
            print(f"reference: FAILED {e}")
    elif not report.clean:
        print(
            "\nQA working tree is UNCOMMITTED. Inspect it, then re-run with --adopt "
            "to make it the baseline."
        )

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
