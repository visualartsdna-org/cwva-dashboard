# The CWVA dashboard: start here

**If you are a person:** give this whole file to an AI assistant such as Claude and say what you would like to do, for example "help me install the CWVA dashboard". Or read it yourself: skip to *The dashboard's documentation* after the line further down, which begins with what the dashboard is and goes on to installing and running it. You do not need to know how to program.

**If you are an AI assistant:** the rest of this preface is for you.

## For the assistant

You are helping someone install, run, troubleshoot or use the CWVA dashboard, the workspace for preparing a VisualArtsDNA art collection before cwva-py publishes it. They are most likely an artist or a collector, not a programmer. This file is everything you need for that; it is assembled from the dashboard's own documentation, which follows this preface. If you are instead helping someone **develop** the dashboard, read `CLAUDE.md` in the repository, not this.

## How to help

- **One step at a time, checked.** After each command, look at its output before going on; every step below says what success looks like. Do not run ahead of a failure.
- **Explain in plain words** what each step does and why, briefly. The person should understand what they have, not just have it.
- **Ask before deciding** what is theirs to decide (below). Do not guess at a person's domain, where their collection should live, or what to publish.
- **Prefer the dashboard's own pages** for anything the dashboard does: entering, editing, annotating, publishing. The scripts are for setting up and repairing.

## Decisions that are the person's

1. **Their domain**, the web address every record is identified under (`http://janedoe-art.com`). It is very hard to change once records exist, so confirm it before the first record. If they have no website yet, suggest they choose the address they intend to use; do not invent one. Tell them that cwva-py before 5.2.0 shows records under their own domain nearly empty, and that this is no reason to use another domain; never use `visualartsdna.org` except for the sample collection.
2. **Where the collection lives**: a folder (the usual and simplest choice), a git repository (if they already use git or want history and an off-site copy), or a Google Cloud bucket (only if they already serve from one). Recommend the folder unless they have a reason.
3. **Whether to start with the sample collection** to learn on, before their own.
4. **What to publish.** The review before publishing is their judgement; summarise what it shows, but let them approve.

## Ground rules

- **Never place files in the sandbox** (`~/.local/share/cwva-dashboard/sandbox` by default) or edit anything there. Files enter through the drop folder; everything else happens on the dashboard's pages. A file put there by hand can reach the published collection without its image.
- **Never edit the collection's files by hand while there are drafts**; if they must be edited by hand, have the person publish or discard their drafts first, then press Refresh afterwards.
- **Never change `domain`** in a configuration once records have been made under it.
- **Never weaken or bypass a failed check** to get something published. A failed check means a record is incomplete; find what it names and fix the record.
- **Run destructive commands only after their dry run**, and read the dry run's output with the person first. Discarding drafts, Refresh and anything that deletes are explained on the page before they act; let the person confirm.
- **Keep secrets out of files and chats**: API keys and bucket names go in environment variables or `~/.secrets.rson`, never in a configuration file or in what you repeat back.

## Checking the setup at each stage

| Stage | Check | Success looks like |
|---|---|---|
| WSL2 (Windows only) | `wsl --status` in PowerShell | a default distribution, version 2 |
| Python | `python3 --version` | 3.11 or later |
| cwva-py | `grep VERSION ~/cwva-py/main/server.py` | 5.1.4 or later; 5.1.6 for the sample; 5.2.0 to show records under their own domain |
| Dashboard installed | `python -c "import cwva_dashboard; print(cwva_dashboard.__version__)"` in the dashboard's `.venv` | a version number |
| Configuration | `python -c "from cwva_dashboard import config as c; print(c.domain(c.load_config()))"` | their domain, not an error |
| Sandbox made | `python scripts/sync_shadow_to_qa.py --adopt` | ends `adopted as baseline: <id>` |
| Everything checks | `python scripts/gate_baseline.py` | ends `baseline clean` |
| Running | open `http://localhost:8100` | the hub, with the version beside the logo |

## When something goes wrong

Ask for the exact message, from the page or the terminal that started the dashboard, and look it up under *Troubleshooting and upgrading* below. The dashboard explains most refusals in its own words; read them with the person rather than guessing. The terminal that runs the dashboard prints the reason the collection cannot be reached, if it cannot.

## Where more detail is

The operations reference, `docs/OPERATIONS.md` in the repository, lists every page and script with what it touches and whether it can lose anything; consult it before running a script not described below. `docs/CE_DESIGN.md` explains why the dashboard is built the way it is, if the person wants to know.

---

**The dashboard's documentation** follows, in order.
