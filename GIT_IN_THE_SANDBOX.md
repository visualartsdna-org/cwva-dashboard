# Git in the sandbox — cost/benefit

The QA content tree is a git repository (`promotion/qa_git.py`). This is an
assessment of whether that is paying for itself, written 2026-09-12 from
measurements of the running system and from the bugs it actually produced.

**Verdict: keep it.** Git earns its place on one decisive benefit — the change
set for a promotion is *derived* rather than tracked — and the alternatives all
reintroduce the failure this project keeps meeting: a hand-maintained list that
falls behind the data. But the dominant cost is real, it is a *usability* cost
rather than a technical one, and it is worth attacking directly.

---

## What it costs

### Measured

```
commits                    13
tracked files           1,648   (1,173 of them .ptr sidecars)
.git                      9.6 MB
working tree              3.7 GB   (1,174 files gitignored: the binaries)
manifest_since()          0.02 s
status                    0.01 s
```

Storage and speed are **not** the cost. `.git` is 0.25% of the tree, and the
operation promotion depends on returns in 20 ms.

### Code that exists only because of git

```
promotion/qa_git.py        389 lines
sandbox/pointers.py        307     the .ptr sidecar scheme
promotion/binaries.py       46     .ptr -> real bytes at convergence
promotion/rollback.py      119
                           ───
                           861 lines, plus 6 test modules
```

`pointers.py` is the honest bulk of it: sidecars, the attic, `reconcile`,
`rebuild_sidecars`, `migrate_to_pointer_management`. **That entire subsystem
exists because git is unsuitable for binaries.** A 3.7 GB image store cannot go
into a history that cannot be rewritten (law 6), so the binaries are ignored and
a tracked stand-in is invented for each. It works, but it is the single largest
piece of incidental complexity in the project, and every binary bug this year
has been in or near it — the sidecar-less hand-placed image, the manifest that
could not see a binary, the pointer gate.

### The dominant cost: law 4 follows from the manifest being a git diff

"A promotion unit sweeps up everything uncommitted" is not a policy someone
chose. It is what `git diff --cached` *means*. Everything downstream follows,
and it has surprised the user more than any other behaviour in the system:

- annotating one work while 1,093 synced `.ptr` sidecars sat uncommitted put all
  1,093 in the unit — and since convergence translates `<x>.ptr` → `<x>`, that
  was 3.7 GB about to be pushed back where it came from, with the annotation's
  commit containing 1,093 unrelated files (so reverting the annotation would
  have deleted every image from QA);
- superseded `workOnSite_*.ttl` snapshots, a vocabulary edit and two renames all
  queued themselves behind an unrelated edit;
- `refresh()` pulling SOT and never adopting it meant the pulled state *was*
  work-in-progress as far as the manifest could tell.

None of those are git bugs. They are the cost of a change set defined by "what
differs from HEAD" in a tree that more than one process writes to.

### The unpriced cost: the history has to be backed up, and nothing does

Choosing git for rollback authority creates a **durability obligation that did
not exist before**. Law 6 says rollback happens in the QA git and never in place
against SOT — so the ability to undo a promotion depends on that history being
present. It lives on one WSL2 disk, and:

```
commits                    13
remotes configured          0        <- nothing is pushed anywhere
.git                      9.6 MB
git bundle --all           1.4 MB    <- what a full backup costs
```

The asymmetry is what makes this easy to miss. **Published content is safe
twice over** — it is in the shadow bucket and, once promoted upstream, in
production. What is *not* safe anywhere is the **authority to undo it**. Losing
the disk does not lose a single record; it loses every `revert` target, and
rollback silently degrades from "walk it back" to "reconstruct it by hand".

Two things in the tree are genuinely irreplaceable, and it is worth being exact
about which:

| | recoverable from SOT? |
|---|---|
| content (TTL, documents) | **yes** — that is what SOT holds |
| `.ptr` sidecars | **yes** — `rebuild_sidecars()` regenerates them from the binaries |
| **commit history** | **no** — exists only here |
| **`.qa/attic`** (superseded binaries) | **no** — SOT holds the *replacement*, by definition |

The attic is empty today (0 files), so the exposure is currently history alone.
It stops being empty the first time a work's image is replaced, and then it holds
bytes that exist in no bucket and no production store — the rollback reserve for
a binary swap.

And it is a category the obvious backup does not cover: a Storage Transfer
Service schedule protects buckets, and **this is not a bucket**. So the cost is
not size — 1.4 MB — it is that the durability of the undo mechanism is a
separate problem requiring separate machinery, and until that machinery exists,
law 6 is a promise backed by one disk.

Cheapest remedies, in order of effort:

- `git bundle create qa.bundle --all` into the backup bucket occasionally —
  1.4 MB, no remote to configure, restores with `git clone qa.bundle`;
- a bare-clone push to a private remote, which makes it continuous rather than
  occasional;
- neither protects `.qa/attic`, which is gitignored — it needs copying
  alongside, or the attic needs a home in a bucket.

### Smaller costs, each one a real incident

- **`manifest_since()` stages everything.** Asking what changed mutates the
  index. A preview left 1,093 files staged, so `git ls-files` reported them as
  tracked before any commit — a question with a side effect.
- **Rename detection had to be turned off.** Git saw
  `workOnSite_visualartsdna.org.ttl → workonsite_visualartsdna_org.ttl` as a rename;
  the manifest wants add/modify/delete, so it passes `--no-renames`. Correct,
  and then the *deleted* path reached the content gates and crashed the preview
  with `FileNotFoundError`, because `all_paths()` included deletes.
- **Two ways to say "undo".** `reset_hard` + `clean_untracked` (refresh) and
  `restore_to` (rollback) are different enough to need separate reasoning.

---

## What it buys

### The change set is derived, not tracked (the decisive one)

Promotion needs to know what to publish. Git answers from the filesystem, so no
component has to remember what it wrote. Every hand-maintained equivalent in this
project has drifted: the picker/gate requirement tables, the collision check's
field list, the updateWorkOnSite page copy, `OPERATIONS.md` until a test pinned
it. A manually tracked manifest would join that list, and its failure mode is
silent — a file that is not on the list simply never reaches SOT.

### Rollback without touching the SOT in place (law 6)

Revert in QA, then converge the reverted state. Deletions travel as deletions.
Without history there is nothing to revert *to*, and rollback becomes
"reconstruct the previous state", which is only possible if something else kept
it — i.e. reinventing a history.

### Detecting out-of-band change

`manifest_since(HEAD)` after a sync is the drift report. `adopt_external` marks
"QA ≡ SOT" so later drift means something. This is how a second machine editing
the shadow becomes visible rather than silently overwritten.

### Cheap, correct undo during development

Concretely useful this month: reverting a test annotation on the live tree was
`git restore`, not a restore-from-backup. The record editor's
"overwrite the file, it is versioned in git" design rests entirely on this.

### Per-unit provenance

One commit per promotion, with the workflow in the message. The QA history is a
readable record of what was published and when — 13 commits that explain
themselves.

---

## Alternatives, and why they are worse

| approach | what breaks |
|---|---|
| **Write-log manifest** (derive the change set from the audit log) | The audit log is append-only and hash-chained, so this is tempting. But trusted-side writes — inbox ingest, the promotion tail — do not pass through the registry, so the log is *incomplete by design*. A manifest from it would miss exactly the files that matter most. |
| **Snapshot directories** (copy the tree per unit) | 3.7 GB per snapshot. Solves rollback, gives no change set, and the binary problem gets worse rather than better. |
| **Explicit manifest per workflow** (each writer declares what it wrote) | Removes law 4's surprise, and reintroduces the drift failure with a silent mode: a forgotten path never publishes. This project's whole recurring lesson argues against it. |
| **No history** | Rollback becomes unimplementable, and the record editor's overwrite-in-place becomes unsafe. |

---

## What to do about the dominant cost

The coupling is worth attacking without giving up the derived manifest:

1. **Adopt eagerly after any non-user write.** `refresh()` now does this. The
   same argument applies anywhere the dashboard writes on its own behalf — the
   workOnSite snapshots are the next candidate: they are system output, and
   there is no reason they should queue behind a user's edit.
2. **Show the manifest count where a user will read it.** Already on the review
   page, and it is the tell: an annotation should read `modifies: 1`. A large
   number means something else is riding along.
3. **Consider per-workflow staging** — commit the system's own output as its own
   unit the moment it is produced, leaving the working tree holding only what a
   human did. This keeps the manifest derived while narrowing what "uncommitted"
   can mean.

The first two are done. The third is the real fix and has not been built.

And separately from the coupling: **back the history up**. It is 1.4 MB as a
bundle and it is the thing law 6 rests on.

*Done, 2026-09-13.* `scripts/backup_qa.py` and the QA Backup card write a git
bundle — plus the attic as its own archive, since it is gitignored and the
bundle cannot carry it — to the target's `operational/` prefix. That prefix is
excluded from sync: without the exclusion the next refresh would pull the backup
into the tree it is a backup of and make it content. The write is a deliberate,
narrow carve-out from law 1 (`Transport.put_operational`, separate from
`converge` so nothing in the content path can reach it): a repository cannot
back itself up into itself.
