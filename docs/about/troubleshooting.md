# Troubleshooting and upgrading

## Something is refused at the review

**A check failed.** The review lists which, and what it found. The common ones:

- **An image or document is missing.** The record names a file the sandbox does not have. Usually it was picked in a form but never arrived from the drop folder, or its name differs in case (`Sunset.jpg` and `sunset.JPG` are one file on Windows and two on Linux). Pick the file again in Edit Record.
- **A concept is not in the thesaurus.** A paint, paper or technique the record names has no entry. Add it to the vocabulary, or choose another.
- **A provenance problem**: a storage number (Disposition Identifier) used twice, a second first-provenance record for one work, or a provenance pointing at a work that is not there. These come from records edited outside the forms; the message names the records involved.

A failed check is never something to switch off. Each time one has failed on real data, the record really was incomplete.

## The dashboard will not start: "no configuration yet"

There is no `config/config.rson`. Copy an example to it and set your domain ([Installing](installing.md#3-make-your-configuration)). "missing `domain`" means the copy exists but its domain is still blank. A message that `domain` cannot be used says what to write instead. If you already made records under a refused domain, ask for help before changing it: records keep the identifier they were made with.

## A work's page is nearly empty in cwva-py

If your domain is not `http://visualartsdna.org`, cwva-py before 5.2.0 does not find your records by their own address. The records are correct; upgrade cwva-py.

## A work is missing from cwva-py's gallery

The gallery shows only records that say they are works; see [Works need two types](existing-collection.md#works-need-two-types).

## A profile's card is red

The profile has no entry form yet, or something in it the dashboard cannot use; hovering over the card shows why. Open it to give it a form ([Bringing in an existing collection](existing-collection.md)).

## "Drift": publishing stopped with nothing written

The collection changed since the sandbox last caught up, and the dashboard will not overwrite changes it has not seen. See [Running](running.md#when-the-collection-was-changed-elsewhere): review your drafts, Refresh, and enter the work again.

## "No promotion target configured"

The dashboard cannot reach your collection, and the terminal that started it printed why, in a line beginning `[dashboard] cannot reach the source of truth`. For a folder, check `sot.path`; for a git repository, that the path is a checkout; for a bucket, that its environment variable is set in that terminal. If the sandbox has never been made, run the first sync ([Installing](installing.md#4-bring-the-collection-into-the-sandbox)).

## The ontology or thesaurus did not arrive

The first sync fetches them from `reference_model` only into empty folders, and says so in its output, or says why it failed: usually no network at that moment. Run the sync again; it fetches only what is still missing.

## "Still loading" or "quota exceeded"

The first query after a restart reads every record in the sandbox, and that can exceed the per-minute file limit the confined worker has. What was read is kept, so try again in a minute; after that, queries are quick. If it happens in ordinary use, raise `quotas.max_ops_per_minute` in the configuration.

## A banner is missing

Only an installation that runs two dashboards labels them, through `environment`; with one, there is no banner. If you do run two and a page has none, treat it as the real collection until you know otherwise. Reports and converted documents never carry one: they are documents, not pages of the dashboard.

## The cwva-py view will not start

The page says why. "Port already in use": another cwva-py, or another dashboard's view, is on that port; each needs its own `viewer.port`. "No cwva-py": `viewer.cwva_py` does not point at a cwva-py checkout. "Needs Landlock": the view runs only where it can be confined, which means Linux or WSL2. Its log, at the bottom of the page, shows anything cwva-py itself reported.

## A video's duration has to be typed

ffmpeg is not installed, so the dashboard cannot read the duration from the file. Install it, or type the duration.

## An error mentioning "PermissionError"

Something in the confined worker tried to read a file outside the sandbox. That is the confinement working, and it means a fault in the dashboard rather than in your data: report it, with the page and what you were doing.

## Upgrading

```bash
cd ~/cwva-py/dashboard
git pull
source .venv/bin/activate
pip install -e .          # ".[gcp]" if your collection is in a bucket
```

Then restart the dashboard. Your `config/config.rson` is yours and an upgrade never touches it; new settings arrive with sensible values in `config/base.rson`, which yours extends, so there is usually nothing to do. Check `CHANGELOG.md` for anything that changes a record's shape or needs a script run once. After upgrading, `python scripts/gate_baseline.py` confirms the sandbox still passes every check. The version is shown beside the logo.

Upgrade cwva-py the same way, in `~/cwva-py/main`, and restart its servers.

Next, once written: *Using it*. Using the dashboard with an AI assistant: see [the assistant guide](../../START_HERE.md).
