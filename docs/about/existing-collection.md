# Bringing in an existing collection

A collection made with cwva-py alone, before the dashboard, works in the dashboard after the first sync, but two things written by hand for cwva-py are often shaped differently from what the dashboard's editors expect. Both are repaired once, in the dashboard, and published like any other change.

## Profiles without an entry form

An artist profile drives an entry form through its **template**: the fields the form shows, their order, and the units of measure. A profile written for cwva-py has none, so its card on the hub is red and reads "has no entry form yet". Open it: the profile editor shows the fields this kind of work can have, with the ones every work needs already ticked. Tick the others it should show (paper, dimensions, location and so on), set their order and the units, and save. The review that follows publishes the profile with its new form, and the card becomes an ordinary one.

## Several records in one file

The dashboard edits one record per file, named after the record's identifier (`817ca809-….ttl`). A file holding several records, such as an artist and their profile written together, cannot be opened by the editors. The script that separates them keeps every statement exactly as it was:

```bash
python scripts/split_aggregate.py --file content/data/artists.ttl --dry-run
python scripts/split_aggregate.py --file content/data/artists.ttl
```

The first line shows what it would write; the second writes one file per record into the sandbox and moves the original to the sandbox's trash. Review and publish the result with **Preview Staged**, where it reads as files added and one removed, with no statements changed.

Not every file with several subjects should be split: a file of annotations about records kept elsewhere, or output a workflow regenerates, is fine as it is. The script only touches the file you name.

## Images and documents

Records name their images by web address (`<domain>/images/<name>`), and the image must be in the collection's images folder under that name. The check run before publishing reports any that are missing. Names written by hand may contain spaces or upper-case extensions; existing names are left exactly as they are, and only a file arriving through the drop folder is tidied.

Next: [Configuration](configuration.md).
