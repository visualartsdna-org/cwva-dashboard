# Configuration

The dashboard's settings live in `config/`, in **RSON**: JSON that allows `#` comments, the same format cwva-py uses. Nothing about your collection is built into the code. Paths beginning `~` are expanded to your home folder.

## Your file: `config/config.rson`

You make it by copying one of the examples, and it **extends** `config/base.rson`, the settings every installation shares: it names only what is yours, and anything it leaves out comes from the base. It is yours alone and is not part of the dashboard's repository, so an upgrade never overwrites it.

| Example | The collection is kept |
|---|---|
| `examples/folder.rson` | in a folder, the one cwva-py serves (the usual choice) |
| `examples/git.rson` | in a git repository, committed (and optionally pushed) on every change |
| `examples/gcp.rson` | in a Google Cloud Storage bucket (advanced) |
| `examples/sample.rson` | in a separate folder holding cwva-py's sample collection, for trying things |

The dashboard looks for its configuration in this order: a `--config` given to a script, then the environment variable `CWVA_DASHBOARD_CONFIG`, then `config/config.rson`. Finding none, it says how to make one.

### Who you are

- **`domain`**, required: the base of every identifier the dashboard makes, such as `http://janedoe-art.com`. A work is `<domain>/work/<guid>` and an image `<domain>/images/<name>`. There is deliberately no default: a wrong domain makes records that look valid and are very hard to correct, so the dashboard will not start without one, or with one that could not be the base of an identifier: it must be `http://` or `https://`, a lower-case host name, a port only if needed, and nothing after it. cwva-py shows records under your own domain completely from version 5.2.0.
- **`host`**: where your published site answers, normally the same as the domain.
- **`sites`**: your own websites, if any. **Update workOnSite** reads them to record which works appear there.
- **`artist_profile`** (optional): the artist profile the generic entry forms start with.

### Where your collection is: `sot`

The source of truth, and where in it each kind of record lives (`mirror_layout`). The examples carry the right layout for each kind; you normally change only the path.

- **Folder**: `{"transport": "files", "path": "~/cwva-py"}`, with cwva-py's own layout under it (`content/data`, `content/images`, `metacontent/model`...).
- **Git**: `{"transport": "git_local", "path": "~/cwva-py/content"}`, or `"git_remote"` with `"remote"` and `"branch"` to push as well. The checkout must exist; its own folders (`data`, `images`, `model`...) are the layout.
- **Bucket**: `{"transport": "gcp_bucket", "bucket_env": "GCP_BUCKET", "prefix": ""}`; the bucket's name is read from that environment variable.

For a folder or a repository, only the folders the layout names belong to the dashboard: anything else there (cwva-py's code, its thumbnails, your notes) is left alone, never copied into the sandbox and never mistaken for a change made elsewhere.

### Where things are

- **`inbox.path`**: your **drop folder**, where you put images, documents and other files for the forms to use. The kinds of file it accepts are listed in `base.rson`.
- **`sandbox.stage_root`**: the sandbox, the dashboard's private working copy. The default, `~/.local/share/cwva-dashboard/sandbox`, is fine; it must be outside the dashboard's own folder.
- **`reference_model`**: the server a new collection's ontology and thesaurus are fetched from, once, into empty folders (`https://visualartsdna.org`).

### Servers and previews

- **`instances.targets`**: the cwva-py servers on the **Monitoring** page, each with a name, a tag and its address; usually just your own, `http://localhost:8081`. Refreshing a server is authorised by a phrase both the server and the dashboard read from `~/.secrets.rson`, as `{"secrets": {"phrase": "..."}}`: set it once, as cwva-py's README describes.
- **`viewer`**: the **cwva-py view**: where cwva-py is checked out, which Python runs it (by default cwva-py's own `.venv`), and its port (8091; not the one your normal cwva-py uses).

### Optional

- **`environment`**: a banner across every page, `{"label": "...", "colour": "..."}`. An installation with one dashboard needs none; it is for telling two apart.
- **`developer`**: shows developer extras on the hub, such as the QA Backup card. Off unless you are working on the dashboard itself.

## The settings in `base.rson`

You rarely need to change these, and doing so in your own file (rather than in the base) keeps an upgrade from undoing it:

- **`sandbox`**: how long discarded files are kept (`trash_keep_days`), and which file types the sandbox's history stores in full (`git_content_extensions`); every other type, such as images, is stored once and tracked by a small reference file.
- **`inbox.extensions`**: the kinds of file the drop folder offers, by group.
- **`entry_forms`**: for the generic forms, which branch of the ontology a work's type is chosen from. Adding a kind of work is an ontology change, not a configuration one.
- **`quotas`**: limits on the confined worker's file use, against a runaway process.
- **`dts`**: limits for concept derivation and tagging, so a run produces something a person can review.
- **`date_format`**: how dates are shown. They are always stored as ISO dates.

## The other files in `config/`

- **`ai_profiles.rson`**: which AI provider and model answers each AI task, with time and size limits. The API key is read from the environment (`ANTHROPIC_API_KEY` for the default provider) or, failing that, from `~/.secrets.rson`; it is never written anywhere else.
- **`workflows.rson`** with **`sparql/board/`**: the workflows on the **Workflows** board and the query that says when each step is done.
- **`standing_queries.rson`** with **`sparql/`**: the standing checks counted on the hub.
- **`shapes/`**: the SHACL shapes records are checked against before publishing.

## Environment variables

| Variable | What it is |
|---|---|
| `CWVA_DASHBOARD_CONFIG` | a configuration other than `config/config.rson` |
| `ANTHROPIC_API_KEY` | the AI provider's key, if not in `~/.secrets.rson` |
| `GCP_BUCKET` | a bucket source of truth's name (the variable `bucket_env` names) |
| `GOOGLE_APPLICATION_CREDENTIALS` | a service-account key file, if not using `gcloud` credentials |

Next: [Running](running.md).
