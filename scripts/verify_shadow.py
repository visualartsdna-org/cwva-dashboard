"""Verify the shadow SOT against its frozen baseline — READ-ONLY.

The companion to ``seed_shadow_sot.py``: that script writes the shadow, this one
only ever *looks* at it. Answers the question the plan's §5 numbers assert but
could not otherwise re-derive: is the shadow still its frozen baseline (content
2026-07-19, metacontent 2026-09-04), and is every difference from production
drift rather than a clone defect?

    export GCP_BUCKET=<production>        # listed, never fetched, never written
    export GCP_TEST_BUCKET=<disposable>   # holds shadow-sot/
    python scripts/verify_shadow.py            # shadow vs frozen baseline
    python scripts/verify_shadow.py --compare  # also diff against production

Safety: this script calls ``list_blobs`` and reads object metadata (name, size,
timestamps). It never downloads content, never writes, and never constructs a
transport with a ``converge`` method. D2 (project plan Phase 4.7) froze the
shadow's content, so a difference reported here is either expected production
drift or a finding — it is never a reason for this script to repair anything.

Exit codes: 0 = matches the frozen baseline; 1 = deviation (a finding);
2 = cannot run (missing env/deps).
"""

from __future__ import annotations

import collections
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cwva_dashboard import rson
from cwva_dashboard.sot_sync import qa_only as qa_only_mod

_CONFIG = Path(__file__).resolve().parents[1] / "config" / "dashboard.rson"

# The baseline. RE-FROZEN 2026-11-02 after a deliberate PARTIAL re-seed of
# `ttl/` (687 objects, 1.95 MB, 209 s) that landed the 222 provenance records
# and 3 storage solutions, the 24 regenerated proofs with their Merkle paths,
# and cwva.ttl's rdfs:Resource domain opening. Previously re-frozen 2026-10-29
# after a FULL re-seed (1741 objects, 3.93 GB, 960 s) for the vad:ArtDomain
# ontology lift, the dual-typed works and the split provenance set.
#
# A partial re-seed is why the per-path boundary below is finally load-bearing:
# `ttl/` was taken from production on 2026-11-02, everything else on 10-29, and
# a single boundary would have to lie about one of them.
#
# Re-freezing is the maintenance this script asks for by name when it finds a
# deviation: "decide whether the baseline moved (a deliberate re-seed, which
# requires recomputing the numbers)". It moved. Left alone, the previous
# constants reported every authorized change as a finding, which trains the
# reader to ignore the check — and the check is what makes "keep the SOTs in
# step" a checkable claim rather than a hope (CE_DESIGN §13.4c).
#
# The boundary dates matter more than the counts. The whole --compare
# classification keys on an object's time_created against the freeze date, and a
# full re-seed stamps EVERY copied object with the seed date. With the old July
# boundary, the 2026-10-29 run read 1128 freshly re-seeded objects as dashboard
# promotions. That was not a bug in the classifier; it was the boundary being
# three months behind the data.
#
# Both dates are now the same instant, so the two-act freeze this file used to
# describe has collapsed into one. The per-path split is kept rather than
# deleted, because the next partial re-seed will need it again.
#
# **A deliberate promotion also moves these numbers**, and that is not drift:
# the shadow exists to be published to. Folded in below. Everything else is
# still a finding, and these numbers move only when a human deliberately
# promoted or re-seeded, never on their own. `scripts/reset_to_baseline.py`
# walks a promotion back off both sides.
# RE-FROZEN 2026-11-19 after the first `seed_shadow_sot.py --mirror`: the
# shadow was made EQUAL to production (20 QA-only objects deleted, 20 new or
# changed copied, operational/ included), so every number below is
# production's as of that moment.
#
# `operational/` is NOT counted (2026-11-19): it holds the QA backups, which
# every QA promotion rewrites and which gained a third file (the ledger), so a
# count of it reported a "finding" after every ordinary approve.
BASELINE_OBJECTS = 1_976
BASELINE_BYTES = 3_922_615_639
BASELINE_TREE = {  # top-level prefix -> object count
    "documents": 154,
    "stats": 19,
    "ttl": 694,
    "images": 1109,
}
# Objects the shadow keeps that production no longer has. A frozen snapshot
# accumulates these whenever production DELETES something, which is drift in
# production, not a defect in the shadow -- see the classification note below.
#
# 23 at the 2026-10-29 freeze, 20 now, and a DECREASE here is the healthy
# direction: it means the shadow let go of something, which only the exit
# channel can do (law 4). The three that went were `images/IMG_2056
# (1).JPG:Zone.Identifier` — the Windows alternate-data-stream file named below
# as outright junk, promoted by accident and now deleted through the channel —
# and the `Claude-DigitalSculptureArtCriticism-ThreeGraces-Copy` pair's
# counterparts. An INCREASE is the ordinary case and still not a defect:
# a frozen snapshot accumulates one whenever production deletes something.
# ZERO after the 2026-11-19 mirror, which deleted all twenty.
KNOWN_PRODUCTION_DELETIONS = 0

# Objects this dashboard PROMOTED, which production has never seen. They are in
# the shadow because a human approved them at the review stop — the shadow
# exists to be published to — so they are expected, not stray writes. Counted
# rather than named: the count is what a stray write would change, and naming
# files that grow with every acceptance run would be maintenance for its own
# sake.
#
# TWO, and they are the first objects this count has ever actually held:
# `operational/qa.bundle` and `operational/qa-attic.tar.gz`, written by
# `backup_qa.py`. They land here rather than in the deletions bin because they
# were created after the 10-29 boundary, which is the classifier working as
# designed for the first time.
#
# The split is still only as good as the boundary. A shadow-only object is
# binned by its time_created against the moment its path was last taken from
# production: older reads as "production deleted it", newer as "the dashboard
# promoted it". A FULL re-seed moves the boundary past everything and collapses
# the two cases — which is why 2026-10-29 reported all 23 as deletions when
# most were QA promotions: `images/TopVR.jpg` and `images/TopVR.glb` for the
# QA-only "Top VR" test work, `images/FairyPool52.jpg`,
# `images/IMG_FairyPool5.jpg`, and assorted QR codes. The 2026-11-02 re-seed
# was partial, so it moved the boundary for `ttl/` only and the other roots
# kept their 10-29 classification.
#
# The sum of the two counts is what guards against a stray write, which is what
# the count was always for.
# ZERO since 2026-11-19: the two were the operational/ backups, which are no
# longer counted at all, and the mirror removed everything else QA had promoted.
KNOWN_PROMOTED = 0

# The freeze boundaries, DECLARED not inferred. An earlier version derived the
# boundary as max(time_created) over the shadow, which self-destructed the first
# time a subset was re-seeded: refreshing metacontent moved the boundary to that
# day and reclassified a month of ordinary production drift as clone defects.
# Measured by hand at a re-freeze and written here as a literal, which is a
# different thing from being computed at run time.
CONTENT_FROZEN_AT = datetime(2026, 11, 19, 13, 23, tzinfo=timezone.utc)
# The subset most recently taken from production on its own, and when. Set to
# the seed's FIRST write (20:39:01) rather than its last, so an object
# production created while the seed was running reads as drift rather than as a
# clone defect. Named for the role, not the content: these were
# METACONTENT_PREFIXES = ("ttl/model/", "ttl/vocab/") when metacontent was the
# only thing ever refreshed alone, and ttl/data is not metacontent.
# The 2026-11-19 mirror covered the whole tree, so the boundary is one instant
# for every path again ("" matches everything).
RESEEDED_AT = datetime(2026, 11, 19, 13, 23, tzinfo=timezone.utc)
RESEEDED_PREFIXES = ("",)


def _frozen_at(rel: str) -> datetime:
    """The moment the shadow's copy of ``rel`` was last taken from production."""
    return (
        RESEEDED_AT
        if rel.startswith(RESEEDED_PREFIXES)
        else CONTENT_FROZEN_AT
    )


# The roots the shadow was cloned from; images/ was excluded by decision (3.7 GB,
# ~46 min per pass), which is why the image-reference class dangles by design.
# Corrected 2026-10-29. This omitted "images/" and so put all 1115 of the
# shadow's images OUTSIDE the comparison scope, where every one of them read
# as shadow-only: the 1128 "objects production lacks" that this check reported
# hours after successfully cloning 1741 objects FROM production. The constant
# predated the 2026-09-11 image seed and was never moved when images became
# cloned content.
#
# "operational/" stays out deliberately: `backup_qa.py` writes it from QA to
# the SOT, so it is not clone output and the shadow's copy is its own.
CLONED_ROOTS = ("ttl/", "documents/", "stats/", "images/")


def _fmt(n: int) -> str:
    return f"{n:,}"


def main(argv: list[str]) -> int:
    try:
        from google.cloud import storage  # optional dep: pip install -e ".[gcp]"
        import google.auth
    except ImportError:
        print("error: google-cloud-storage not installed (pip install -e '.[gcp]')")
        return 2

    cfg = rson.load(str(_CONFIG))["shadow_sot"]
    compare = "--compare" in argv

    try:
        shadow_name = os.environ[cfg["bucket_env"]]
        prod_name = os.environ[cfg["source_bucket_env"]] if compare else None
    except KeyError as missing:
        print(f"error: {missing} is not set (bucket names come from the environment)")
        return 2

    credentials, project = google.auth.default()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or project
    client = storage.Client(project=project, credentials=credentials)

    prefix = cfg["prefix"].rstrip("/") + "/"
    # Everything but operational/: backups, not content (see BASELINE_OBJECTS).
    blobs = [b for b in client.list_blobs(client.bucket(shadow_name), prefix=prefix)
             if not b.name[len(prefix):].startswith("operational/")]
    shadow = {b.name[len(prefix):]: b for b in blobs}

    total_bytes = sum(b.size or 0 for b in blobs)
    print(f"shadow : {shadow_name}/{prefix}")
    print(f"objects: {_fmt(len(shadow))} (baseline {_fmt(BASELINE_OBJECTS)})")
    print(f"bytes  : {_fmt(total_bytes)} (baseline {_fmt(BASELINE_BYTES)})")

    findings: list[str] = []
    if len(shadow) != BASELINE_OBJECTS:
        findings.append(f"object count {len(shadow)} != frozen baseline {BASELINE_OBJECTS}")
    if total_bytes != BASELINE_BYTES:
        findings.append(f"byte total {total_bytes} != frozen baseline {BASELINE_BYTES}")

    tops = collections.Counter(
        rel.split("/", 1)[0] if "/" in rel else "(root)" for rel in shadow
    )
    print("\n-- by top-level --")
    for name, expected in sorted(BASELINE_TREE.items()):
        got = tops.get(name, 0)
        flag = "" if got == expected else f"  <-- expected {expected}"
        print(f"  {name:12s} {got:5d}{flag}")
        if got != expected:
            findings.append(f"{name}/: {got} objects, expected {expected}")
    for name, got in sorted(tops.items()):
        if name not in BASELINE_TREE:
            print(f"  {name:12s} {got:5d}  <-- UNEXPECTED top-level prefix")
            findings.append(f"unexpected top-level prefix {name!r} ({got} objects)")

    # The affordance layer's inputs: absence here is why `type` and the
    # vocabulary pickers would silently fall back (project plan §5 checkpoint).
    print("\n-- affordance inputs --")
    for want in ("ttl/model/", "ttl/vocab/"):
        n = sum(1 for rel in shadow if rel.startswith(want))
        print(f"  {want:12s} {n:5d} files")
        if not n:
            findings.append(f"{want} is EMPTY — the affordance layer cannot activate")
    has_paper_vocab = "ttl/vocab/watercolorPaper.ttl"
    if has_paper_vocab not in shadow:
        findings.append(f"{has_paper_vocab} missing — the vocabulary gate has no reference graph")

    # Folder placeholders must never appear: the transport filters `dir/` objects,
    # and one entering a snapshot would make sync write a file where a directory
    # belongs. The predicate is the trailing slash, deliberately NOT zero length —
    # documents/CupsStudyCriticism.pdf is a real 0-byte file in production too.
    placeholders = [rel for rel in shadow if rel.endswith("/")]
    zero_byte = [rel for rel in shadow if (shadow[rel].size or 0) == 0 and not rel.endswith("/")]
    print(f"\nfolder placeholders present: {len(placeholders)} (expected 0)")
    if placeholders:
        findings.append(f"folder placeholders leaked into the shadow: {placeholders[:5]}")
    print(f"zero-byte real files: {len(zero_byte)} (expected 1, known: CupsStudyCriticism.pdf)")
    for rel in zero_byte:
        print(f"  {rel}")

    if compare:
        print(f"\n-- vs production ({prod_name}), name+size, metadata only --")
        prod = {b.name: b for b in client.list_blobs(client.bucket(prod_name))}
        scope = {n: b for n, b in prod.items() if n.startswith(CLONED_ROOTS)}
        print(f"content frozen {CONTENT_FROZEN_AT:%Y-%m-%d %H:%M} UTC; "
              f"{'+'.join(RESEEDED_PREFIXES)} re-seeded "
              f"{RESEEDED_AT:%Y-%m-%d %H:%M}")

        stray = sorted(set(shadow) - set(scope))
        missing = [n for n in sorted(set(scope) - set(shadow)) if not n.endswith("/")]
        differing = sorted(
            n for n in set(shadow) & set(scope)
            if (shadow[n].size or 0) != (scope[n].size or 0)
        )

        # Paths held deliberately ahead of production are their own category.
        # Without this they land in `corrupt` — "clone defect" — which is exactly
        # backwards for an intended edit, and a check that cries wolf is a check
        # that stops being read.
        protected = qa_only_mod.load(cfg)
        ahead = [n for n in differing if qa_only_mod.is_protected(n, protected)]
        differing = [n for n in differing if n not in set(ahead)]

        drifted = [n for n in missing if scope[n].time_created > _frozen_at(n)]
        defects = [n for n in missing if scope[n].time_created <= _frozen_at(n)]
        updated = [n for n in differing if scope[n].updated > _frozen_at(n)]
        corrupt = [n for n in differing if scope[n].updated <= _frozen_at(n)]

        # A QA-only path that matches production is reconciled (or not yet
        # edited) — worth saying, since "still ahead" is the actionable set.
        reconciled = [
            n for n in set(shadow) & set(scope)
            if qa_only_mod.is_protected(n, protected) and n not in set(ahead)
        ]

        # A "stray" (in the shadow, absent from production) has two very
        # different causes, and conflating them cries wolf: an object CLONED at
        # seed time that production has since DELETED is expected -- a frozen
        # snapshot preserves what production drops -- while an object created in
        # the shadow AFTER the seed window means something wrote to a frozen
        # target, which is a real finding. Discriminate by creation timestamp.
        deleted_upstream = [n for n in stray if shadow[n].time_created <= _frozen_at(n)]
        written_later = [n for n in stray if shadow[n].time_created > _frozen_at(n)]

        print(f"  in shadow, deleted from production : {len(deleted_upstream)}  (expected; frozen snapshot)")
        print(f"  in shadow, promoted by the dashboard: {len(written_later)}  "
              f"(expected {KNOWN_PROMOTED})")
        print(f"  missing, created after the seed    : {len(drifted)}  (expected drift)")
        print(f"  missing, existed BEFORE the seed   : {len(defects)}  <-- clone defect if > 0")
        print(f"  differing, updated after the seed  : {len(updated)}  (expected drift)")
        print(f"  differing, NOT updated since seed  : {len(corrupt)}  <-- clone defect if > 0")
        if protected:
            print(f"  QA-ONLY, ahead of production       : {len(ahead)}  (intended)")
            print(f"  QA-only, matching production       : {len(reconciled)}  (reconciled)")
        if len(deleted_upstream) != KNOWN_PRODUCTION_DELETIONS:
            print(f"    note: {len(deleted_upstream)} upstream deletions, baseline records "
                  f"{KNOWN_PRODUCTION_DELETIONS} — informational, not a shadow defect")
        for n in deleted_upstream[:10]:
            print(f"    [deleted upstream] {n}")
        for n in written_later[:10]:
            print(f"    [promoted] {n}")
        if len(written_later) != KNOWN_PROMOTED:
            # The COUNT is the signal. A deliberate approve is expected and
            # recorded; anything else appearing here wrote to the shadow
            # without going through the review stop.
            findings.append(
                f"{len(written_later)} object(s) in the shadow that production "
                f"lacks, expected {KNOWN_PROMOTED} promoted — investigate the "
                "difference before trusting this shadow"
            )
        for label, items in (("defect", defects), ("corrupt", corrupt)):
            for n in items[:10]:
                print(f"    [{label}] {n}")
            if items:
                findings.append(f"{len(items)} {label} object(s) vs production")

        if ahead:
            # Full names, deliberately: this is the reconcile list — the exact
            # set of QA-only changes that have not reached production yet.
            print("\n-- QA-only, still ahead of production (reconcile list) --")
            for n in ahead:
                print(f"    {n}")
                print(f"        shadow {shadow[n].size} B  |  production "
                      f"{scope[n].size} B  (updated {scope[n].updated:%Y-%m-%d})")
        for n in reconciled:
            print(f"    [qa-only, matches production] {n}")

    print()
    if findings:
        print("DEVIATION from the frozen baseline — each of these is a finding:")
        for f in findings:
            print(f"  - {f}")
        print("\nDo not 'fix' the shadow to match. Decide whether the baseline moved")
        print("(a deliberate re-seed, which requires recomputing the §5/§6 numbers)")
        print("or whether something wrote to it that should not have.")
        return 1

    print("shadow matches the frozen baseline (project plan Phase 4.7, D2).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
