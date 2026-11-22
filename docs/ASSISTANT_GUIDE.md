# The CWVA dashboard: a guide for an AI assistant

You are helping someone install, run, troubleshoot or use the CWVA dashboard, the workspace for preparing a VisualArtsDNA art collection before cwva-py publishes it. They are most likely an artist or a collector, not a programmer. This file is everything you need for that; it is assembled from the dashboard's own documentation, which follows this preface. If you are instead helping someone **develop** the dashboard, read `CLAUDE.md` in the repository, not this.

## How to help

- **One step at a time, checked.** After each command, look at its output before going on; every step below says what success looks like. Do not run ahead of a failure.
- **Explain in plain words** what each step does and why, briefly. The person should understand what they have, not just have it.
- **Ask before deciding** what is theirs to decide (below). Do not guess at a person's domain, where their collection should live, or what to publish.
- **Prefer the dashboard's own pages** for anything the dashboard does: entering, editing, annotating, publishing. The scripts are for setting up and repairing.

## Decisions that are the person's

1. **Their domain**, the web address every record is identified under (`http://janedoe-art.com`). It is very hard to change once records exist, so confirm it before the first record. If they have no website yet, suggest they choose the address they intend to use; do not invent one, and never use `visualartsdna.org` except for the sample collection.
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
| cwva-py | `grep VERSION ~/cwva-py/main/server.py` | 5.1.4 or later |
| Dashboard installed | `python -c "import cwva_dashboard; print(cwva_dashboard.__version__)"` in the dashboard's `.venv` | a version number |
| Configuration | `python -c "from cwva_dashboard import config as c; print(c.domain(c.load_config()))"` | their domain, not an error |
| Sandbox made | `python scripts/sync_shadow_to_qa.py --adopt` | ends `adopted as baseline: <id>` |
| Everything checks | `python scripts/gate_baseline.py` | ends `baseline clean` |
| Running | open `http://localhost:8100` | the hub, with the version beside the logo |

## When something goes wrong

Ask for the exact message, from the page or the terminal that started the dashboard, and look it up under *Troubleshooting and upgrading* below. The dashboard explains most refusals in its own words; read them with the person rather than guessing. The terminal that runs the dashboard prints the reason the collection cannot be reached, if it cannot.

## Where more detail is

The operations reference, `OPERATIONS.md` in the repository, lists every page and script with what it touches and whether it can lose anything; consult it before running a script not described below. `CE_DESIGN.md` explains why the dashboard is built the way it is, if the person wants to know.

---

The dashboard's documentation follows, in order.

# Start here

## What the dashboard is

The CWVA dashboard is a workspace for preparing visual-arts data before it is published. It is the companion to **cwva-py**, the server that publishes a VisualArtsDNA collection on the web: cwva-py shows the collection, and the dashboard is where the collection is made and kept in order.

### What it is for

A VisualArtsDNA collection is a set of records, one per artwork and one per supporting thing (an artist, a document, a background, a proof of existence), written in RDF and described with a shared ontology and thesaurus. Keeping such a collection is a lot of small, exacting steps: entering a new work with its images and dimensions, annotating it with the paints and techniques used, recording where the original is kept, attaching a written criticism and deriving concepts from it, proving the image existed on a given date. The dashboard puts each of those steps behind a form, checks the result, and publishes it only when you say so.

### How it fits with cwva-py

There are three parts, and it helps to keep them apart:

- **The source of truth** is where the published data lives. Usually that is a plain **folder**: the one cwva-py serves on your own computer. It can also be a **git repository**, which gives the collection a history and a copy elsewhere, or, for larger installations, a **cloud storage bucket**. cwva-py reads it, and so do the people who browse the collection.
- **cwva-py** serves the source of truth as a website: the gallery, each work's page, the thesaurus, a SPARQL endpoint. It only reads.
- **The dashboard** keeps its own private working copy of the source of truth, called the **sandbox**. Everything you do happens there first. When a change is ready, you **distribute** it, and the dashboard writes it to the source of truth; cwva-py then refreshes and shows it.

So the order of events for a new watercolour is: enter it in the dashboard, check it (in the dashboard, and in cwva-py through the dashboard's own read-only view of the sandbox), distribute it, and refresh the published server.

### What it is not

It is not a website editor and not a general file manager. Files enter through one place (the drop folder), and data leaves through one place (distribution). It does not publish anything you have not reviewed, and it does not change the published data in place: a mistake is undone in the dashboard and the corrected state distributed again.

### Where the AI comes in

Some steps use an AI model: deriving concepts from a written criticism, tagging it, and summarising it. The model proposes and you decide; nothing it writes is distributed without passing the same review as anything else. The model is reached through a configured provider, and it never holds any capability the dashboard has not given it: it cannot read or write outside the sandbox, run commands, or reach the network on its own. An agent that can drive the dashboard's workflows is planned; it will use exactly the operations a person uses.

### One dashboard, one collection

An installation is one dashboard working on one collection, set up by one configuration file. Someone developing the dashboard itself can run a second, practice copy beside the real one (see [Running](#a-second-instance-for-trying-things)), and then every page carries a banner saying which is which; an ordinary installation needs neither.

### Working with an AI assistant

If you would like help from an AI assistant such as Claude to install, run or use the dashboard, give it the assistant guide: one file holding these pages, with instructions for the assistant on how to help safely and what to ask you.

## Key ideas

A handful of ideas explain almost everything the dashboard does. Once they are familiar, the rest of the interface follows from them.

### The sandbox: everything happens there first

The sandbox is the dashboard's private working copy of the published data. Every form, edit and annotation writes into it, and nothing in it is public until you distribute it. You never put files into the sandbox yourself, and you do not need to know where it is: the dashboard keeps it, records its history, and confines everything that works in it so that nothing can reach outside.

### The drop folder: how files come in

Images, documents and other files enter through the **drop folder**, a folder of your own named in the configuration. Put a file there and the entry forms offer it. When a form uses it, the dashboard copies it into the sandbox; it never moves, renames or deletes anything in your folder. Names are tidied on the way in: spaces are removed and the extension lower-cased (`Lepers Hearth.JPG` becomes `LepersHearth.jpg`), because the name becomes part of the web address the record cites. The review tells you when a name was changed.

### Drafts: what is written but not yet distributed

A record you have saved in the sandbox but not distributed is a **draft**. The Drafts card on the hub counts them, and the Drafts page lists each one by name, with what changed since it was last distributed and a way back into the form that made it. Drafts are normal: several related records are often made one at a time and distributed together.

### The review: the one way out

Every change reaches the published data through the same step. You see a **review** of exactly what will change, record by record, and the dashboard's **checks** have already run. Then you choose one of three:

- **Approve & distribute** writes the change to the source of truth.
- **Leave it staged** keeps it as a draft and lets you carry on; you can distribute it later, with others, from **Preview Staged**.
- **Discard** throws this session's changes away and puts the sandbox back as it was.

Distribution is all of the drafts at once: what is approved is everything waiting in the sandbox, which is why the Drafts card matters.

### Checks: what is verified before anything is published

Before a review is shown, the dashboard checks the change. Every file must parse as RDF. A record of a kind that has a declared shape must fit it: a provenance names exactly one work and its owner, a proof carries a consistent set of hashes, an artist profile has a usable form template (a work's required fields are enforced earlier, by its entry form). Every reference must lead somewhere: an image the record names must exist, a paint or paper must be in the thesaurus, a provenance must point at a real work, and no two works may share a storage number. A failed check stops the review and says what is wrong; it is never bypassed. The checks are about whether the data is well formed and consistent, not about whether you meant it; that judgement is yours, at the review.

### Undoing

Because the sandbox keeps a history of everything distributed, a distribution can be undone: the sandbox is put back to before it, and that earlier state is distributed again. Today that is an operator's task, done with a script rather than from a page. **Refresh** goes the other way: it pulls the published data into the sandbox, replacing anything not yet distributed, and is how the dashboard catches up after the data was changed somewhere else. Refresh asks first, because it can throw work away.

### Seeing it before it is public

The **cwva-py view** runs cwva-py itself over your sandbox, drafts included, on your own machine. It is the published site as it will look after you distribute, and it cannot change anything: the operating system prevents it from writing to the sandbox at all.

### Profiles: what you make, and the form for it

An **artist profile** is what an artist makes in one medium (watercolours on paper, say, or Blender compositions), and it carries the **template** for that medium's entry form: which fields the form shows, in what order, and the units of measure. Each profile becomes a card on the hub. A profile made by cwva-py on its own, before the dashboard, has no template yet; its card says so and opens the profile editor, where you choose the fields once.

### Records describe one thing

Each record is a small file about one thing: one artwork, one artist, one document, one provenance. They point at each other: a work names its artist profile, a criticism names the work it is about, a provenance names the work it records. The dashboard's forms, checks and reports all rely on that, which is why an edit preserves what its form does not show and never rewrites a record wholesale.

## A tour of the dashboard

The hub is the page the dashboard opens on. Across the top are the logo, which always brings you back here, the version number, and five destinations: **Content**, **Monitoring**, **Tools**, **Files** and **About**.

### Content

Where the collection is made. Its first section, **Content Management**, holds the cards you use most. Each card has a small handle in its corner: drag it to arrange the cards the way you work, and the arrangement is kept.

- **One card per artist profile**, such as a watercolour profile or a Blender profile. A profile is what an artist makes in one medium, and its card opens the entry form for a new work in it, with the fields that medium needs. A red card is a profile with no form yet: open it to choose its fields.
- **Edit Record** opens any existing work or entity and lets you change its fields, including replacing its image or document under the same name.
- **Update workOnSite** reads the artist's websites and records which works appear on them.
- **Annotate Work** attaches concepts from the thesaurus to a work: the paints, papers and techniques used.
- **Entity** creates a supporting record, such as a written criticism of a work with its markdown document.
- **Proof** loads a proof of existence for an image, from its OriginStamp certificate.
- **DTS** is concept derivation, tagging and summarising: from a criticism's text, it proposes concepts, places them, and drafts a summary, each step reviewed by you.
- **Drafts** counts what is written and not yet distributed.
- **Workflows** shows each work in progress against the steps of its workflow (entry, annotation, criticism, concepts, proof) with what is done, what is next, and how long it has waited.
- **cwva-py view** starts the published site's own server over your sandbox, so you can see a change before distributing it.
- **New artist**, **Edit artist** and **New artist profile** set up who makes the work and in what medium; the profile cards come from these.

Below them, **Immediate Actions**:

- **Preview Staged** reviews and distributes everything waiting in the sandbox.
- **Refresh** pulls the published data into the sandbox, after asking, because it discards anything not distributed. Use it after changing the collection's files by hand.

### Monitoring

The servers that publish the collection, each on its own card, with **Status**, **Refresh** and **Metrics**. Refresh tells a server to reload the published data, which is the last step after distributing. Each card shows when that server was last refreshed. For a collection on your own computer that is usually one server, your cwva-py.

### Tools

- **SPARQL** queries everything in the sandbox, drafts and provenance included, without changing anything.
- **Print Registry** lists one artist profile's works, with image, QR code, year and description, ready to print.
- **Storage Report** lists the works in a storage arrangement by their storage number (Disposition Identifier), with a thumbnail of each: the list to take to the boxes.
- **Generate Certificate** makes a printable Certificate of Authenticity for a work from its record.

### Files

Utilities for a file of your own. None of them stores anything.

- **Syntax Check RDF/JSON** says whether a Turtle, RDF/XML, N-Triples, N3, TriG, N-Quads, JSON-LD or JSON file is well formed, and if not, where the first error is.
- **Markdown to HTML** shows a markdown file as a web page, in a new tab.
- **Scale Image** and **Convert Image** resize an image or change its format, and give the result back as a download.

### About

These pages.

# Installing and running

## Requirements

### Operating system

**Linux, or Windows 11 through WSL2.** The dashboard confines everything that works in the sandbox using Landlock, a feature of the Linux kernel (5.13 or later; every current distribution has it, and so does WSL2). It will not run its confined parts where Landlock is missing rather than run them unconfined. macOS and native Windows are planned for later releases.

On Windows, WSL2 is installed with `wsl --install` from an administrator terminal, then a restart; after that, the commands on these pages are typed into the Ubuntu terminal it adds.

### Software

- **Python 3.11 or later.**
- **cwva-py**, the VisualArtsDNA server, version 5.1.4 or later, checked out beside the dashboard. It is what shows your collection; the dashboard uses parts of it and can run it over your work in progress.
- **git**, which keeps the sandbox's history (and, if you choose, your collection's).
- **ffmpeg** (optional): with it, a video's duration is read from the file; without it, you type it in.

The Python packages the dashboard needs (RDFLib, pySHACL, FastAPI, Pillow and a few others) are installed with it.

### Where your collection lives

The dashboard publishes to a **source of truth**, and you choose which kind:

- **A folder** (the usual choice): the folder cwva-py serves on your computer, laid out as cwva-py's README describes (`content/data`, `content/images`, `metacontent/model` and so on). Nothing else is needed.
- **A git repository**: the same, kept in git, so every change you publish becomes a commit, and a pushed copy can live elsewhere.
- **A Google Cloud Storage bucket** (advanced): for a collection served from the cloud, as visualartsdna.org is. This needs a Google Cloud account and credentials.

A new collection can start empty: the ontology and thesaurus are fetched from the reference VisualArtsDNA server the first time.

### For the AI-assisted steps

Concept derivation, tagging and summarising call an AI model, by default Anthropic's Claude, and need an API key for it (see [Configuration](#configuration)). Everything else works without one.

### Disk

The sandbox holds a full copy of the collection, images included, so allow about twice the size of the collection's folder.

## Installing

These steps set up the dashboard beside cwva-py, in one folder, with the collection kept in a folder of its own: the usual setup. The [git](#keeping-the-collection-in-git) and [cloud](#advanced-a-google-cloud-bucket) alternatives follow.

```
~/cwva-py/
├── main/          cwva-py
├── dashboard/     the dashboard
├── content/       your collection: data, images, documents...
├── metacontent/   the ontology and thesaurus
└── inbox/         the drop folder: where you put files for the forms
```

### 1. Get the code

```bash
cd ~/cwva-py
git clone https://github.com/visualartsdna-org/cwvaServer-py.git main   # if you do not have cwva-py yet
git clone https://github.com/visualartsdna-org/cwva-dashboard.git dashboard
```

Set up cwva-py as its own README describes, in its local mode (`"cloud": null`), serving `~/cwva-py/content` and `~/cwva-py/metacontent`.

### 2. Install the dashboard

```bash
cd ~/cwva-py/dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ~/cwva-py/main     # cwva-py, which the dashboard builds on
pip install -e .                  # the dashboard
mkdir -p ~/cwva-py/inbox          # the drop folder
```

Add `".[dev]"` instead of `.` if you will run the tests.

### 3. Make your configuration

```bash
cp config/examples/folder.rson config/config.rson
```

Open `config/config.rson` and set **`domain`** to your own web address, such as `http://janedoe-art.com`: every record you make is identified under it, and it is very hard to change once records exist, which is why the example leaves it blank and the dashboard will not start until it is set. Set `host` to the same, and list your websites under `sites` if you have any. Everything else has a sensible default; [Configuration](#configuration) explains each setting.

### 4. Bring the collection into the sandbox

```bash
python scripts/sync_shadow_to_qa.py --adopt
```

This copies the collection into a new sandbox and starts its history; it only reads from your folder. If the collection has no ontology or thesaurus yet, they are fetched from the reference VisualArtsDNA server now, and wait as drafts to be published with your first change.

A collection made with cwva-py before the dashboard may need two small repairs, explained in [Bringing in an existing collection](#bringing-in-an-existing-collection).

### 5. Start it

```bash
uvicorn cwva_dashboard.main:create_app --factory --port 8100
```

Open `http://localhost:8100`. The dashboard listens on this computer only.

Then press **Preview Staged** on the hub: it shows what is waiting (the ontology and thesaurus, for a new collection). Approve it, and refresh cwva-py.

### 6. Check it

```bash
python scripts/gate_baseline.py
```

It runs every check the dashboard applies before publishing, over the whole collection, and should end with `baseline clean`. If it reports missing images or unknown concepts, the collection itself has them, and the dashboard will not publish those records until they are fixed.

### Trying the sample collection first

cwva-py comes with a small sample collection: six watercolours by a fictional artist. To try the dashboard on it without touching anything real:

```bash
mkdir -p ~/cwva-py/sample/inbox
cp -r ~/cwva-py/main/sample-data/content ~/cwva-py/sample/
export CWVA_DASHBOARD_CONFIG=config/examples/sample.rson
python scripts/sync_shadow_to_qa.py --adopt
uvicorn cwva_dashboard.main:create_app --factory --port 8100
```

It has its own folder and its own sandbox, and every page says SAMPLE. Its profile has no entry form yet: open its red card and choose the fields, as [Bringing in an existing collection](#bringing-in-an-existing-collection) describes. Unset `CWVA_DASHBOARD_CONFIG` to go back to your own.

### Keeping the collection in git

Start from `config/examples/git.rson` instead. The collection is then a git checkout (`~/cwva-py/content` in the example, with `model/` and `vocab/` inside it, so point cwva-py's `model` and `vocab` there too). Every change you publish becomes a commit; with `"transport": "git_remote"` it is also pushed. Only the collection's own folders are committed, anything else in the checkout is left as it is, and a folder the repository ignores (cwva-py ignores `images/`, too large for git) is copied into place but not committed.

### Advanced: a Google Cloud bucket

Start from `config/examples/gcp.rson`, and install the cloud extra:

```bash
pip install -e ".[gcp]"
gcloud auth application-default login
export GCP_BUCKET=<your bucket>     # put this in ~/.bashrc
```

The bucket is laid out the way cwva-py's cloud mode reads it (`ttl/data`, `ttl/model`, `images`...), and the dashboard reads its name from the environment variable the configuration names, never from a file.

## Bringing in an existing collection

A collection made with cwva-py alone, before the dashboard, works in the dashboard after the first sync, but two things written by hand for cwva-py are often shaped differently from what the dashboard's editors expect. Both are repaired once, in the dashboard, and published like any other change.

### Profiles without an entry form

An artist profile drives an entry form through its **template**: the fields the form shows, their order, and the units of measure. A profile written for cwva-py has none, so its card on the hub is red and reads "has no entry form yet". Open it: the profile editor shows the fields this kind of work can have, with the ones every work needs already ticked. Tick the others it should show (paper, dimensions, location and so on), set their order and the units, and save. The review that follows publishes the profile with its new form, and the card becomes an ordinary one.

### Several records in one file

The dashboard edits one record per file, named after the record's identifier (`817ca809-….ttl`). A file holding several records, such as an artist and their profile written together, cannot be opened by the editors. The script that separates them keeps every statement exactly as it was:

```bash
python scripts/split_aggregate.py --file content/data/artists.ttl --dry-run
python scripts/split_aggregate.py --file content/data/artists.ttl
```

The first line shows what it would write; the second writes one file per record into the sandbox and moves the original to the sandbox's trash. Review and publish the result with **Preview Staged**, where it reads as files added and one removed, with no statements changed.

Not every file with several subjects should be split: a file of annotations about records kept elsewhere, or output a workflow regenerates, is fine as it is. The script only touches the file you name.

### Images and documents

Records name their images by web address (`<domain>/images/<name>`), and the image must be in the collection's images folder under that name. The check run before publishing reports any that are missing. Names written by hand may contain spaces or upper-case extensions; existing names are left exactly as they are, and only a file arriving through the drop folder is tidied.

## Configuration

The dashboard's settings live in `config/`, in **RSON**: JSON that allows `#` comments, the same format cwva-py uses. Nothing about your collection is built into the code. Paths beginning `~` are expanded to your home folder.

### Your file: `config/config.rson`

You make it by copying one of the examples, and it **extends** `config/base.rson`, the settings every installation shares: it names only what is yours, and anything it leaves out comes from the base. It is yours alone and is not part of the dashboard's repository, so an upgrade never overwrites it.

| Example | The collection is kept |
|---|---|
| `examples/folder.rson` | in a folder, the one cwva-py serves (the usual choice) |
| `examples/git.rson` | in a git repository, committed (and optionally pushed) on every change |
| `examples/gcp.rson` | in a Google Cloud Storage bucket (advanced) |
| `examples/sample.rson` | in a separate folder holding cwva-py's sample collection, for trying things |

The dashboard looks for its configuration in this order: a `--config` given to a script, then the environment variable `CWVA_DASHBOARD_CONFIG`, then `config/config.rson`. Finding none, it says how to make one.

#### Who you are

- **`domain`**, required: the base of every identifier the dashboard makes, such as `http://janedoe-art.com`. A work is `<domain>/work/<guid>` and an image `<domain>/images/<name>`. There is deliberately no default: a wrong domain makes records that look valid and are very hard to correct, so the dashboard will not start without one.
- **`host`**: where your published site answers, normally the same as the domain.
- **`sites`**: your own websites, if any. **Update workOnSite** reads them to record which works appear there.
- **`artist_profile`** (optional): the artist profile the generic entry forms start with.

#### Where your collection is: `sot`

The source of truth, and where in it each kind of record lives (`mirror_layout`). The examples carry the right layout for each kind; you normally change only the path.

- **Folder**: `{"transport": "files", "path": "~/cwva-py"}`, with cwva-py's own layout under it (`content/data`, `content/images`, `metacontent/model`...).
- **Git**: `{"transport": "git_local", "path": "~/cwva-py/content"}`, or `"git_remote"` with `"remote"` and `"branch"` to push as well. The checkout must exist; its own folders (`data`, `images`, `model`...) are the layout.
- **Bucket**: `{"transport": "gcp_bucket", "bucket_env": "GCP_BUCKET", "prefix": ""}`; the bucket's name is read from that environment variable.

For a folder or a repository, only the folders the layout names belong to the dashboard: anything else there (cwva-py's code, its thumbnails, your notes) is left alone, never copied into the sandbox and never mistaken for a change made elsewhere.

#### Where things are

- **`inbox.path`**: your **drop folder**, where you put images, documents and other files for the forms to use. The kinds of file it accepts are listed in `base.rson`.
- **`sandbox.stage_root`**: the sandbox, the dashboard's private working copy. The default, `~/.local/share/cwva-dashboard/sandbox`, is fine; it must be outside the dashboard's own folder.
- **`reference_model`**: the server a new collection's ontology and thesaurus are fetched from, once, into empty folders (`https://visualartsdna.org`).

#### Servers and previews

- **`instances.targets`**: the cwva-py servers on the **Monitoring** page, each with a name, a tag and its address; usually just your own, `http://localhost:8081`. Refreshing a server is authorised by a phrase both the server and the dashboard read from `~/.secrets.rson`, as `{"secrets": {"phrase": "..."}}`: set it once, as cwva-py's README describes.
- **`viewer`**: the **cwva-py view**: where cwva-py is checked out, which Python runs it (by default cwva-py's own `.venv`), and its port (8091; not the one your normal cwva-py uses).

#### Optional

- **`environment`**: a banner across every page, `{"label": "...", "colour": "..."}`. An installation with one dashboard needs none; it is for telling two apart.
- **`developer`**: shows developer extras on the hub, such as the QA Backup card. Off unless you are working on the dashboard itself.

### The settings in `base.rson`

You rarely need to change these, and doing so in your own file (rather than in the base) keeps an upgrade from undoing it:

- **`sandbox`**: how long discarded files are kept (`trash_keep_days`), and which file types the sandbox's history stores in full (`git_content_extensions`); every other type, such as images, is stored once and tracked by a small reference file.
- **`inbox.extensions`**: the kinds of file the drop folder offers, by group.
- **`entry_forms`**: for the generic forms, which branch of the ontology a work's type is chosen from. Adding a kind of work is an ontology change, not a configuration one.
- **`quotas`**: limits on the confined worker's file use, against a runaway process.
- **`dts`**: limits for concept derivation and tagging, so a run produces something a person can review.
- **`date_format`**: how dates are shown. They are always stored as ISO dates.

### The other files in `config/`

- **`ai_profiles.rson`**: which AI provider and model answers each AI task, with time and size limits. The API key is read from the environment (`ANTHROPIC_API_KEY` for the default provider) or, failing that, from `~/.secrets.rson`; it is never written anywhere else.
- **`workflows.rson`** with **`sparql/board/`**: the workflows on the **Workflows** board and the query that says when each step is done.
- **`standing_queries.rson`** with **`sparql/`**: the standing checks counted on the hub.
- **`shapes/`**: the SHACL shapes records are checked against before publishing.

### Environment variables

| Variable | What it is |
|---|---|
| `CWVA_DASHBOARD_CONFIG` | a configuration other than `config/config.rson` |
| `ANTHROPIC_API_KEY` | the AI provider's key, if not in `~/.secrets.rson` |
| `GCP_BUCKET` | a bucket source of truth's name (the variable `bucket_env` names) |
| `GOOGLE_APPLICATION_CREDENTIALS` | a service-account key file, if not using `gcloud` credentials |

## Running

### Starting it

```bash
cd ~/cwva-py/dashboard
source .venv/bin/activate
uvicorn cwva_dashboard.main:create_app --factory --port 8100
```

Open `http://localhost:8100`. The dashboard listens on this computer only; it is not meant to be reached from the network. Stopping it (Ctrl-C) also stops its cwva-py view, if one is running.

### The routine

**Before you start work**, bring the sandbox up to date if the collection was changed anywhere else: a record edited by hand in the folder, a commit made in the repository, cwva-py's own tools. Press **Refresh** on the hub. Refresh replaces anything not yet published, so it asks first, and it is why the **Drafts** count should be zero before you do it.

**While you work**, records you save are drafts. Look at them in the **cwva-py view**, check the **Workflows** board for what each work still needs, and leave related records staged until they are ready together.

**To publish**, approve at the review, or use **Preview Staged** to publish everything waiting. Then refresh cwva-py (from **Monitoring**, or by restarting it) so it shows the change.

### When the collection was changed elsewhere

At the moment you approve, the dashboard checks that the collection has not changed since the sandbox last caught up. If it has, publishing stops with a **drift** error and nothing is written: the dashboard will not overwrite changes it has not seen. The cure is Refresh, which pulls those changes in but also discards your unpublished work, so look at each draft on the Drafts page first, refresh, and enter the work again. The habit that avoids it is refreshing before you start, not after.

Files the dashboard does not manage never count as a change: cwva-py writing thumbnails, your notes beside the collection, anything outside the folders the configuration names.

### The scripts

Everything the dashboard does is on its pages; the scripts in `scripts/` set up, check and repair an installation. Those that act on a collection take `--config` to name one, and the operations reference (`OPERATIONS.md` in the repository) lists every script with what it touches and whether it can lose anything. The ones you will meet:

| Script | What it is for |
|---|---|
| `sync_shadow_to_qa.py --adopt` | create (or rebuild) the sandbox from the collection |
| `gate_baseline.py` | run every check over the sandbox |
| `split_aggregate.py --file …` | separate a file holding several records |
| `backup_qa.py` | back up the sandbox's history now |

### A second instance, for trying things

Someone working on the dashboard itself can run a second, practice copy beside the real one: its own configuration (extending the first and naming only a different sandbox, source of truth, port and banner), started with `CWVA_DASHBOARD_CONFIG` pointing at it, on another port. The two must never share a sandbox, because publishing sends everything waiting in a sandbox, and each should carry an `environment` banner so a page always says which it is. The developer's tools for keeping a practice copy in step with the real collection (`seed_shadow_sot.py --mirror`, `verify_shadow.py`) work with a bucket practice copy and are described in `OPERATIONS.md`.

## Backups

Most of what the sandbox holds can be rebuilt from your collection at any time: that is what Refresh and a new sync do. Three things cannot, because they exist only in the sandbox.

- **The history.** Every change you publish is recorded in the sandbox's history, and undoing one depends on it. The collection holds only its current state.
- **Replaced files.** When an image or document is replaced, the collection holds the new one; the old one is kept in the sandbox so that undoing the replacement can put it back.
- **The ledger.** The workflow board's ticks ("external website updated") and "not needed" marks, and the dismissals of standing checks, each with its date. Nothing in the records says when the website was updated.

### Automatic

After every successful publish, the dashboard bundles those three and stores them with the collection, in an `operational` folder: `qa.bundle` (the history), `qa-attic.tar.gz` (the replaced files) and `qa-ledger.ttl` (the ledger). The folder is set apart: it is never copied back into a sandbox and never counted as a change to the collection. A backup that fails is reported on the page after publishing, but never undoes the publish, which has already happened.

Where it lands depends on where the collection is:

- **A folder**: `operational/` beside the collection's own folders (`~/cwva-py/operational/` in the usual setup). That is **the same disk** as the sandbox, so it protects against mistakes, not against losing the disk: back up the whole `~/cwva-py` folder somewhere else from time to time, as you would any precious files.
- **A git repository**: `operational/` inside the checkout, kept out of the repository's history (a bundle in every commit would grow it without end) and so not pushed. The repository's own history, and a pushed copy if you use one, cover the collection; the ledger and replaced files are local, as with a folder.
- **A bucket**: `operational/` in the bucket, off this computer.

### On demand

```bash
python scripts/backup_qa.py --status   # what would be backed up
python scripts/backup_qa.py
```

The backup page (`/backup`) shows how many replaced files are waiting in the sandbox. While that number is zero, the history and the ledger are the only things a lost disk would cost.

### Restoring

- **The history**: `git clone qa.bundle` gives the sandbox's full history back.
- **Replaced files**: unpack `qa-attic.tar.gz` inside the sandbox's `.qa` folder; it recreates `.qa/attic`.
- **The ledger**: copy `qa-ledger.ttl` to the sandbox as `.qa/hygiene_ledger.ttl`.

Without them, a new sandbox made from the collection (`sync_shadow_to_qa.py --adopt`) still has every record; what it lacks is the ability to undo the changes made before it.

### What is not backed up

Anything in the sandbox not yet published. Drafts are deliberately not copied anywhere until you approve them, so a draft lives only on the computer it was made on.

## Troubleshooting and upgrading

### Something is refused at the review

**A check failed.** The review lists which, and what it found. The common ones:

- **An image or document is missing.** The record names a file the sandbox does not have. Usually it was picked in a form but never arrived from the drop folder, or its name differs in case (`Sunset.jpg` and `sunset.JPG` are one file on Windows and two on Linux). Pick the file again in Edit Record.
- **A concept is not in the thesaurus.** A paint, paper or technique the record names has no entry. Add it to the vocabulary, or choose another.
- **A provenance problem**: a storage number (Disposition Identifier) used twice, a second first-provenance record for one work, or a provenance pointing at a work that is not there. These come from records edited outside the forms; the message names the records involved.

A failed check is never something to switch off. Each time one has failed on real data, the record really was incomplete.

### The dashboard will not start: "no configuration yet"

There is no `config/config.rson`. Copy an example to it and set your domain ([Installing](#3-make-your-configuration)). "missing `domain`" means the copy exists but its domain is still blank.

### A profile's card is red

The profile has no entry form yet, or something in it the dashboard cannot use; hovering over the card shows why. Open it to give it a form ([Bringing in an existing collection](#bringing-in-an-existing-collection)).

### "Drift": publishing stopped with nothing written

The collection changed since the sandbox last caught up, and the dashboard will not overwrite changes it has not seen. See [Running](#when-the-collection-was-changed-elsewhere): review your drafts, Refresh, and enter the work again.

### "No promotion target configured"

The dashboard cannot reach your collection, and the terminal that started it printed why, in a line beginning `[dashboard] cannot reach the source of truth`. For a folder, check `sot.path`; for a git repository, that the path is a checkout; for a bucket, that its environment variable is set in that terminal. If the sandbox has never been made, run the first sync ([Installing](#4-bring-the-collection-into-the-sandbox)).

### The ontology or thesaurus did not arrive

The first sync fetches them from `reference_model` only into empty folders, and says so in its output, or says why it failed: usually no network at that moment. Run the sync again; it fetches only what is still missing.

### "Still loading" or "quota exceeded"

The first query after a restart reads every record in the sandbox, and that can exceed the per-minute file limit the confined worker has. What was read is kept, so try again in a minute; after that, queries are quick. If it happens in ordinary use, raise `quotas.max_ops_per_minute` in the configuration.

### A banner is missing

Only an installation that runs two dashboards labels them, through `environment`; with one, there is no banner. If you do run two and a page has none, treat it as the real collection until you know otherwise. Reports and converted documents never carry one: they are documents, not pages of the dashboard.

### The cwva-py view will not start

The page says why. "Port already in use": another cwva-py, or another dashboard's view, is on that port; each needs its own `viewer.port`. "No cwva-py": `viewer.cwva_py` does not point at a cwva-py checkout. "Needs Landlock": the view runs only where it can be confined, which means Linux or WSL2. Its log, at the bottom of the page, shows anything cwva-py itself reported.

### A video's duration has to be typed

ffmpeg is not installed, so the dashboard cannot read the duration from the file. Install it, or type the duration.

### An error mentioning "PermissionError"

Something in the confined worker tried to read a file outside the sandbox. That is the confinement working, and it means a fault in the dashboard rather than in your data: report it, with the page and what you were doing.

### Upgrading

```bash
cd ~/cwva-py/dashboard
git pull
source .venv/bin/activate
pip install -e .          # ".[gcp]" if your collection is in a bucket
```

Then restart the dashboard. Your `config/config.rson` is yours and an upgrade never touches it; new settings arrive with sensible values in `config/base.rson`, which yours extends, so there is usually nothing to do. Check the release notes for anything that changes a record's shape or needs a script run once. After upgrading, `python scripts/gate_baseline.py` confirms the sandbox still passes every check. The version is shown beside the logo.

Upgrade cwva-py the same way, in `~/cwva-py/main`, and restart its servers.
