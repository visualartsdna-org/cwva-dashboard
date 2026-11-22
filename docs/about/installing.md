# Installing

These steps set up the dashboard beside cwva-py, in one folder, with the collection kept in a folder of its own: the usual setup. The [git](#keeping-the-collection-in-git) and [cloud](#advanced-a-google-cloud-bucket) alternatives follow.

```
~/cwva-py/
├── main/          cwva-py
├── dashboard/     the dashboard
├── content/       your collection: data, images, documents...
├── metacontent/   the ontology and thesaurus
└── inbox/         the drop folder: where you put files for the forms
```

## 1. Get the code

```bash
cd ~/cwva-py
git clone https://github.com/visualartsdna-org/cwvaServer-py.git main   # if you do not have cwva-py yet
git clone https://github.com/visualartsdna-org/cwva-dashboard.git dashboard
```

Set up cwva-py as its own README describes, in its local mode (`"cloud": null`), serving `~/cwva-py/content` and `~/cwva-py/metacontent`.

## 2. Install the dashboard

```bash
cd ~/cwva-py/dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -e ~/cwva-py/main     # cwva-py, which the dashboard builds on
pip install -e .                  # the dashboard
mkdir -p ~/cwva-py/inbox          # the drop folder
```

Add `".[dev]"` instead of `.` if you will run the tests.

## 3. Make your configuration

```bash
cp config/examples/folder.rson config/config.rson
```

Open `config/config.rson` and set **`domain`** to your own web address, such as `http://janedoe-art.com`: every record you make is identified under it, and it is very hard to change once records exist, which is why the example leaves it blank and the dashboard will not start until it is set. Set `host` to the same, and list your websites under `sites` if you have any. Everything else has a sensible default; [Configuration](configuration.md) explains each setting.

## 4. Bring the collection into the sandbox

```bash
python scripts/sync_shadow_to_qa.py --adopt
```

This copies the collection into a new sandbox and starts its history; it only reads from your folder. If the collection has no ontology or thesaurus yet, they are fetched from the reference VisualArtsDNA server now, and wait as drafts to be published with your first change.

A collection made with cwva-py before the dashboard may need two small repairs, explained in [Bringing in an existing collection](existing-collection.md).

## 5. Start it

```bash
uvicorn cwva_dashboard.main:create_app --factory --port 8100
```

Open `http://localhost:8100`. The dashboard listens on this computer only.

Then press **Preview Staged** on the hub: it shows what is waiting (the ontology and thesaurus, for a new collection). Approve it, and refresh cwva-py.

## 6. Check it

```bash
python scripts/gate_baseline.py
```

It runs every check the dashboard applies before publishing, over the whole collection, and should end with `baseline clean`. If it reports missing images or unknown concepts, the collection itself has them, and the dashboard will not publish those records until they are fixed.

## Trying the sample collection first

cwva-py comes with a small sample collection: six watercolours by a fictional artist. To try the dashboard on it without touching anything real:

```bash
mkdir -p ~/cwva-py/sample/inbox
cp -r ~/cwva-py/main/sample-data/content ~/cwva-py/sample/
export CWVA_DASHBOARD_CONFIG=config/examples/sample.rson
python scripts/sync_shadow_to_qa.py --adopt
uvicorn cwva_dashboard.main:create_app --factory --port 8100
```

It has its own folder and its own sandbox, and every page says SAMPLE. Its profile has no entry form yet: open its red card and choose the fields, as [Bringing in an existing collection](existing-collection.md) describes. Unset `CWVA_DASHBOARD_CONFIG` to go back to your own.

## Keeping the collection in git

Start from `config/examples/git.rson` instead. The collection is then a git checkout (`~/cwva-py/content` in the example, with `model/` and `vocab/` inside it, so point cwva-py's `model` and `vocab` there too). Every change you publish becomes a commit; with `"transport": "git_remote"` it is also pushed. Only the collection's own folders are committed, anything else in the checkout is left as it is, and a folder the repository ignores (cwva-py ignores `images/`, too large for git) is copied into place but not committed.

## Advanced: a Google Cloud bucket

Start from `config/examples/gcp.rson`, and install the cloud extra:

```bash
pip install -e ".[gcp]"
gcloud auth application-default login
export GCP_BUCKET=<your bucket>     # put this in ~/.bashrc
```

The bucket is laid out the way cwva-py's cloud mode reads it (`ttl/data`, `ttl/model`, `images`...), and the dashboard reads its name from the environment variable the configuration names, never from a file.

Next: [Bringing in an existing collection](existing-collection.md).
