# Running

## Starting it

```bash
cd ~/cwva-py/dashboard
source .venv/bin/activate
uvicorn cwva_dashboard.main:create_app --factory --port 8100
```

Open `http://localhost:8100`. The dashboard listens on this computer only; it is not meant to be reached from the network. Stopping it (Ctrl-C) also stops its cwva-py view, if one is running.

## The routine

**Before you start work**, bring the sandbox up to date if the collection was changed anywhere else: a record edited by hand in the folder, a commit made in the repository, cwva-py's own tools. Press **Refresh** on the hub. Refresh replaces anything not yet published, so it asks first, and it is why the **Drafts** count should be zero before you do it.

**While you work**, records you save are drafts. Look at them in the **cwva-py view**, check the **Workflows** board for what each work still needs, and leave related records staged until they are ready together.

**To publish**, approve at the review, or use **Preview Staged** to publish everything waiting. Then refresh cwva-py (from **Monitoring**, or by restarting it) so it shows the change.

## When the collection was changed elsewhere

At the moment you approve, the dashboard checks that the collection has not changed since the sandbox last caught up. If it has, publishing stops with a **drift** error and nothing is written: the dashboard will not overwrite changes it has not seen. The cure is Refresh, which pulls those changes in but also discards your unpublished work, so look at each draft on the Drafts page first, refresh, and enter the work again. The habit that avoids it is refreshing before you start, not after.

Files the dashboard does not manage never count as a change: cwva-py writing thumbnails, your notes beside the collection, anything outside the folders the configuration names.

## The scripts

Everything the dashboard does is on its pages; the scripts in `scripts/` set up, check and repair an installation. Those that act on a collection take `--config` to name one, and the operations reference (`OPERATIONS.md` in the repository) lists every script with what it touches and whether it can lose anything. The ones you will meet:

| Script | What it is for |
|---|---|
| `sync_shadow_to_qa.py --adopt` | create (or rebuild) the sandbox from the collection |
| `gate_baseline.py` | run every check over the sandbox |
| `split_aggregate.py --file …` | separate a file holding several records |
| `backup_qa.py` | back up the sandbox's history now |

## A second instance, for trying things

Someone working on the dashboard itself can run a second, practice copy beside the real one: its own configuration (extending the first and naming only a different sandbox, source of truth, port and banner), started with `CWVA_DASHBOARD_CONFIG` pointing at it, on another port. The two must never share a sandbox, because publishing sends everything waiting in a sandbox, and each should carry an `environment` banner so a page always says which it is. The developer's tools for keeping a practice copy in step with the real collection (`seed_shadow_sot.py --mirror`, `verify_shadow.py`) work with a bucket practice copy and are described in `OPERATIONS.md`.

Next: [Backups](backups.md).
