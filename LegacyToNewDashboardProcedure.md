# Switching back from the legacy dashboard to this one

**Status: live 2026-09-27.** Both instances run, the production sandbox is seeded, and the artist/profile import has been distributed to the real SOT. The *One-time setup* below is done; it stays here because it is how a sandbox is rebuilt if one is ever lost.

## The two instances

| | QA | Production |
|---|---|---|
| Port | 8100 | 8102 |
| SOT target | shadow (`GCP_TEST_BUCKET`, prefix `shadow-sot`) | production (`GCP_BUCKET`) |
| Sandbox | `~/.local/share/cwva-dashboard/sandbox` | its own, e.g. `sandbox-prod` |
| Banner | green, "QA" | amber, "PRODUCTION" |

They must not share a sandbox. A promotion unit is *everything uncommitted in the QA tree* (law 4), so a shared sandbox means approving anything in the production instance converges the QA instance's staged work to production. Separate sandboxes also mean separate QA git repos, separate audit logs, separate drafts, and separate episode restore points — all of which are singular by design.

**The legacy Groovy dashboard also writes to the production SOT.** It still does things this dashboard cannot, so production has two publishers. That is the reason this procedure exists: the new dashboard's sandbox is a working copy, and a working copy that has fallen behind its source cannot distribute.

## One-time setup

The production instance needs its own sandbox seeded before it can do anything; until then the promotion routes answer 503 rather than half-working.

```
export GCP_BUCKET=<production>
python scripts/sync_shadow_to_qa.py --config config/production.rson --dry-run
python scripts/sync_shadow_to_qa.py --config config/production.rson --adopt
```

The dry run reports what would be pulled and writes nothing. The source is opened as a `ReadOnlySource` whichever target it is, so **this script can never write to a bucket** — the dashboard's production instance can distribute; the seeding script cannot.

Then run it:

```
CWVA_DASHBOARD_CONFIG=config/production.rson \
  uvicorn cwva_dashboard.main:create_app --factory --port 8102
```

### Before the first run of either instance, once

The audit log is named after its sandbox (`audit-sandbox.jsonl`, `audit-sandbox-prod.jsonl`). To keep the QA instance's existing history on its chain rather than starting a new one:

```
mv ~/.local/share/cwva-dashboard/audit.jsonl \
   ~/.local/share/cwva-dashboard/audit-sandbox.jsonl
```

Do this while nothing is running. If you skip it, nothing breaks — the QA instance simply starts a fresh log beside the old one.

### Splitting `artists.ttl`, once per instance

Production keeps its artists and artist profiles in one hand-maintained `artists.ttl`, and the editors are file-based: a file holding seven named subjects has no single record to edit, so Edit artist and Edit artist profile refuse it. Splitting it into one file per GUID is a re-filing, not a content change.

```
python scripts/split_aggregate.py --config config/production.rson \
    --file ttl/data/artists.ttl --dry-run
python scripts/split_aggregate.py --config config/production.rson \
    --file ttl/data/artists.ttl
```

**But a plain re-filing does not achieve the goal.** None of production's four artist profiles carries an `ops:template`, so re-filing them yields four records `read_profile` refuses — dead cards and no entry forms. QA holds the same four GUIDs with templates built through the form builder, and all four read cleanly against production's model and the shapes. So the records are imported from QA instead:

```
python scripts/split_aggregate.py --config config/production.rson \
    --file ttl/data/artists.ttl --from config/dashboard.rson --dry-run
```

An import changes the graph on purpose, so the script does not assert isomorphism — it prints the per-record difference and lists **every statement that would be lost**, never truncated. Against the real data that is `+237 −13`: the 237 are the templates, and the 13 are four measurement-system prose notes with their `rdf:type`, plus a `skos:member` block on the Lindenmayer profile that QA never had. Decide about those thirteen before running it without `--dry-run`; anything you want to keep is re-added in QA and imported again.

Then review it at **Preview Staged** and distribute. Approving a change that converges an artist or an artist profile rebuilds the registry, so the cards' forms work straight away — no restart. A pure re-filing reads there as `files +7 ~0 -1, ±triples +0/-0`; an import shows the triple delta you just approved on the command line. The original goes to `.qa/trash`, and the QA git history records it as one legible migration commit on top of the adopted baseline.

**The other multi-subject files stay as they are.** `art.ttl`, `archivo.ttl` and `digitalRspates.ttl` hold 47 grandfathered works that are never edited; `annotations.ttl` holds triples about records that live elsewhere; `conceptQueue.ttl` and `workOnSite_*.ttl` are system output. The editor's rule of skipping multi-subject files is doing the right thing for all of them. Annotating a grandfathered work is safe — the annotator writes a sibling `<guid>.ttl` and leaves the aggregate untouched.

### Bringing the operations ontology to production, once

Production has **no `ttl/model/operations.ttl`** and is already using the vocabulary: the four artist profiles imported from QA carry `ops:template`, `ops:field`, `ops:order` and `ops:required` with nothing defining any of them (measured 2026-09-30). The ontology is one of the paths QA holds deliberately ahead (`shadow_sot.qa_only`), so it has never travelled — the profiles work because the reader parses them structurally, not because the terms resolve.

The same script that moves provenance agents into `ops:` brings it over, and the order matters: refresh first, because approving against a stale sandbox aborts on drift and the cure for drift is the refresh that would discard the migration.

```
# 1. in the production instance (:8102), Refresh — before anything is staged
# 2. then, from the project:
python scripts/migrate_agent_iris.py --config config/production.rson \
    --ontology-from config/dashboard.rson --dry-run
python scripts/migrate_agent_iris.py --config config/production.rson \
    --ontology-from config/dashboard.rson
# 3. Preview Staged on :8102, then Approve & distribute
```

Against the real data that is the 96-triple ontology plus three triples in each of the two `workonsite_*.ttl` files. It is idempotent, so a second run reports nothing to do.

### What a shadow re-seed does and does not do

`seed_shadow_sot.py` is **adds-only**. It brings production's objects over and removes nothing the shadow already holds, so the shadow accumulates everything QA has ever promoted to it — which is correct for its purpose (realistic drift, orphans and legacy quirks to drive the dashboard against) and surprising the first time it matters. "Refresh from production" never subtracts.

Measured 2026-10-01: production held 375 `ttl/data` objects and the shadow 388, the difference being records created in QA while exercising the entry forms. To remove something from the shadow, delete it in QA and promote: deletions are part of the exit channel (law 4), previewed at the review stop like any other change.

## The procedure

### Before you leave the new dashboard for legacy

1. Open **Drafts**. It must read zero. Anything staged is either distributed or discarded now — a refresh will destroy it, and that is why this step is first rather than last.

### In legacy

2. Do the work and publish to production as usual. Nothing on this side needs to know about the new dashboard.

### When you come back — before you start anything

3. Open the production dashboard on :8102 and confirm the amber PRODUCTION banner. If the banner is missing, stop: an unlabelled window is either the QA instance or a production window whose banner failed to render, and those are not the same thing.
4. Check **Drafts** again. If it is not empty, resolve it before going further — distribute it or discard it.
5. **Refresh** — the card on the hub, which shows what would be lost and asks before doing it. Four things happen: work in progress is discarded, the SOT is pulled into QA, gitignored binaries are reconciled against their restored sidecars, and the pulled state is **adopted** as a new baseline commit.
6. Confirm: Drafts reads zero, and the queue counts reflect what legacy published. Concepts or ontology changes legacy added are now visible to the forms and to TCAP, because refresh reloads the ontology and rebuilds the registries.

Only then start working.

### The QA instance needs a step production does not: re-seed the shadow first

Steps 3–6 above are the **production** instance. The QA instance's SOT is the *shadow*, and distributing to production leaves the shadow untouched — so its Refresh would faithfully pull the shadow exactly as it was yesterday. Written down because it had to be asked for (Rick, 2026-11-02: "Remind of the steps in QA to do the refresh"), and because the asymmetry is invisible from the hub: both instances have the same Refresh card.

```bash
echo "$GCP_BUCKET / $GCP_TEST_BUCKET"     # 1. both must be set
#    2. QA :8100 — Drafts must read zero, FIRST, not last
python scripts/seed_shadow_sot.py ttl/    # 3. production -> shadow
python scripts/verify_shadow.py --compare  # 4. expect findings; re-freeze after
#    5. QA :8100 hub -> the Refresh card
python scripts/gate_baseline.py           # 6. confirm
```

**Scope the seed to the prefixes that changed.** A records-and-ontology change is entirely under `ttl/`, and naming it skips 1,114 image objects and essentially all of the bytes: the 2026-11-02 pass moved 687 objects in **209 s**, against 960 s for the full tree. A full re-seed is for when images or documents moved.

**Step 4 WILL report findings, and that is the script asking for maintenance, not failing.** The shadow legitimately grew. Read them, confirm they are the records you just distributed and nothing else, then re-freeze the baseline — `BASELINE_OBJECTS`, `BASELINE_BYTES`, the changed prefix in `BASELINE_TREE`, and `RESEEDED_AT`/`RESEEDED_PREFIXES`. **A partial seed moves the boundary for the seeded prefixes only**, which is why that boundary is per-path: `--compare` classifies a shadow-only object by its `time_created` against the moment its path was last cloned, so bumping one date for everything would reclassify months of ordinary drift as clone defects. Leave `CONTENT_FROZEN_AT` alone unless the seed was full.

### Starting QA fresh from production: mirror, then rebuild the sandbox

Nothing from QA survives this (Rick, 2026-11-19: "Prod should be copied over QA in its entirety"). Two halves, because QA lives in two places: the shadow bucket, and the sandbox on disk with its git history, trash, attic and ledger. A Refresh alone would make the files match but keep all of the second.

```bash
#    1. stop the QA dashboard (:8100). Anything staged there is about to go.
python scripts/seed_shadow_sot.py --mirror --dry-run   # 2. read EVERY deletion
python scripts/seed_shadow_sot.py --mirror             # 3. shadow == production
mv ~/.local/share/cwva-dashboard/sandbox \
   ~/.local/share/cwva-dashboard/sandbox.old-$(date +%Y%m%d)   # 4. aside, not deleted
python scripts/sync_shadow_to_qa.py --adopt            # 5. a new sandbox, new git
python scripts/gate_baseline.py                        # 6. confirm
python scripts/verify_shadow.py --compare              # 7. then re-freeze the baseline
#    8. start QA :8100; delete sandbox.old-* once it looks right
```

The mirror copies only what is new or changed, so it is quick over the whole tree, and it mirrors `operational/` too: the shadow's QA backups are replaced by production's, because after a clone the old QA history describes a tree that no longer exists. `qa_only` does not apply. It refuses if production lists nothing or more than a quarter of the shadow would go — a guard against the wrong bucket, not a way of keeping anything. Step 5's first-sync expectations (`EXPECT_GIT_CONTENT`, `EXPECT_POINTER_MANAGED`) were calibrated to the old shadow and will report a difference; that is the shadow having moved, so update them. The audit log (`audit-sandbox.jsonl`) sits beside the sandbox, not in it, and carries on: it is the record of what was done, including this. First measured 2026-11-18: 20 shadow-only objects (test records such as "junk", a second "Fairy Pool 3", two DTS vocabulary files) against 13 new and 7 changed from production.

**A shadow object that DISAPPEARS is not a seed defect** — the seed cannot delete. It means something left through the exit channel, which is the only way out (law 4), and the count of shadow-only objects falling is the healthy direction.

## Why the order matters

**Drift is detected only at Approve, never at preview.** `run_promotion` returns at the preview stop, and the pre-push drift check lives in `apply_unit`, which preview never reaches. So if you work first and refresh later, the sequence is: do the work, gates pass, the preview looks correct, press **Approve & distribute**, and get a `DriftError` with nothing written.

**And the only cure for drift is a refresh, which discards exactly the work you just did.** You would do the work and then lose it to the fix. That is why the refresh belongs at the start of the session rather than in the recovery path.

**The adopt in step 5 is not cosmetic.** Without it, everything the refresh pulls stays uncommitted and the next promotion sweeps it all up. That is not hypothetical: after the shadow was seeded with production's images in September 2026, the next annotation's promotion unit carried 1,093 sidecar additions, and approving it would have pushed 3.7 GB of images back to the bucket they came from — and reverting that annotation later would then have deleted every image from QA.

## If you forget, and hit DriftError

Nothing was written. The QA tree is untouched and the SOT is untouched — the drift check runs before any commit and any push, so an abort is safe. What you have lost is only the ability to distribute that work without first refreshing.

Before refreshing, open **Drafts → Review** on each draft. That page shows the record's triples as written and its difference from the last distributed version, which is the accurate record of what you are about to lose. Read it, refresh, and re-enter the work through the ordinary form.

Do not copy files into the sandbox by hand to preserve them. Content enters through the drop folder (law 12), and a file placed by hand has no `.ptr` sidecar — for a binary that means the record reaches the SOT while the image never follows.

## The gap that made this urgent, now closed

**Closed 2026-09-26.** Refresh has a hub card, a page that lists the drafts and uncommitted files it would destroy, and a confirmation — the same confirm-first shape as Discard Work in Progress. `GET /refresh` shows, `POST /refresh` does, and `/api/refresh` remains for scripts, both running the same implementation.

**Open question: should the production instance refresh automatically on startup?** It would make "open the window" and "be current" the same act, which fits how the two dashboards will be used. But it would also discard drafts at startup without asking, so it must only do so when Drafts is already empty, and say plainly what it is refusing to do when they are not.
