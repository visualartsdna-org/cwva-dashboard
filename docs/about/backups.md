# Backups

Most of what the sandbox holds can be rebuilt from your collection at any time: that is what Refresh and a new sync do. Three things cannot, because they exist only in the sandbox.

- **The history.** Every change you publish is recorded in the sandbox's history, and undoing one depends on it. The collection holds only its current state.
- **Replaced files.** When an image or document is replaced, the collection holds the new one; the old one is kept in the sandbox so that undoing the replacement can put it back.
- **The ledger.** The workflow board's ticks ("external website updated") and "not needed" marks, and the dismissals of standing checks, each with its date. Nothing in the records says when the website was updated.

## Automatic

After every successful publish, the dashboard bundles those three and stores them with the collection, in an `operational` folder: `qa.bundle` (the history), `qa-attic.tar.gz` (the replaced files) and `qa-ledger.ttl` (the ledger). The folder is set apart: it is never copied back into a sandbox and never counted as a change to the collection. A backup that fails is reported on the page after publishing, but never undoes the publish, which has already happened.

Where it lands depends on where the collection is:

- **A folder**: `operational/` beside the collection's own folders (`~/cwva-py/operational/` in the usual setup). That is **the same disk** as the sandbox, so it protects against mistakes, not against losing the disk: back up the whole `~/cwva-py` folder somewhere else from time to time, as you would any precious files.
- **A git repository**: `operational/` inside the checkout, kept out of the repository's history (a bundle in every commit would grow it without end) and so not pushed. The repository's own history, and a pushed copy if you use one, cover the collection; the ledger and replaced files are local, as with a folder.
- **A bucket**: `operational/` in the bucket, off this computer.

## On demand

```bash
python scripts/backup_qa.py --status   # what would be backed up
python scripts/backup_qa.py
```

The backup page (`/backup`) shows how many replaced files are waiting in the sandbox. While that number is zero, the history and the ledger are the only things a lost disk would cost.

## Restoring

- **The history**: `git clone qa.bundle` gives the sandbox's full history back.
- **Replaced files**: unpack `qa-attic.tar.gz` inside the sandbox's `.qa` folder; it recreates `.qa/attic`.
- **The ledger**: copy `qa-ledger.ttl` to the sandbox as `.qa/hygiene_ledger.ttl`.

Without them, a new sandbox made from the collection (`sync_shadow_to_qa.py --adopt`) still has every record; what it lacks is the ability to undo the changes made before it.

## What is not backed up

Anything in the sandbox not yet published. Drafts are deliberately not copied anywhere until you approve them, so a draft lives only on the computer it was made on.

Next: [Troubleshooting and upgrading](troubleshooting.md).
