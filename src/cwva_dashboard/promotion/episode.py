"""The unsaved work session, and how leaving one puts the sandbox back.

**The commit point is Approve & distribute.** Everything before it — the form,
the submit, the review you are reading — is uncommitted, and leaving without
approving must leave the record as it was. Rick, 2026-09-18: "in every form I've
ever used, if I exit the form without explicitly saving, when I come back the
record state is the original state, not some state I never explicitly saved."

That was not true here. A submit wrote the record into QA immediately; the
review stop gated the SOT, not the sandbox. So annotating a work, seeing the
review, changing your mind and going to the dashboard left the work annotated —
and the only sign was the record itself, read later, disagreeing with what you
thought you had done. The behaviour was defensible and nobody would ever guess
it.

**What an episode is.** The span from a workflow's first write to its approval.
It opens with a snapshot of the working tree, survives as many submit → back →
submit rounds as the user needs (each one builds on the last, which is what
makes "go back and fix it" work), and ends one of two ways:

- **approved** — the change converged, the snapshot is dropped;
- **abandoned** — the tree goes back to the snapshot.

Abandoning is EXPLICIT: a button on the review, or answering the challenge when
you navigate off it. Deliberately not inferred — a closed tab sends no signal,
and reverting on a guess would delete a record nobody asked to delete. What an
abandoned-but-not-discarded session leaves behind is what it always left behind:
uncommitted work, listed in every preview, cleared by Discard Work in Progress.
Starting a different piece of work drops the old restore point without applying
it, for the same reason.

**Three things the restore has to cover**, and git alone covers one:

1. modified records — restored from the snapshot;
2. created records, QR codes, sidecars — deleted, because "as it was" for a
   thing that did not exist is not existing;
3. binaries — gitignored, so git holds only the `.ptr`. `PointerManager`
   reconciles: a sidecar restored to an older sha pulls its bytes back from the
   attic, and a sidecar that has gone takes its binary with it.

Trusted-orchestrator machinery, never a registry tool — it restores the
sandbox wholesale, which is not a capability the confined worker may hold.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Episode", "EpisodeStore", "EPISODE_REF"]

EPISODE_REF = "refs/qa/episode"


@dataclass
class Episode:
    workflow: str
    subject: str
    snapshot: str
    untracked: list = field(default_factory=list)
    started: float = 0.0

    def to_dict(self) -> dict:
        return {"workflow": self.workflow, "subject": self.subject,
                "snapshot": self.snapshot, "untracked": sorted(self.untracked),
                "started": self.started}

    @classmethod
    def from_dict(cls, d: dict) -> "Episode":
        return cls(
            workflow=str(d.get("workflow", "")),
            subject=str(d.get("subject", "")),
            snapshot=str(d.get("snapshot", "")),
            untracked=list(d.get("untracked", [])),
            started=float(d.get("started", 0.0)),
        )

    def key(self) -> tuple:
        return (self.workflow, self.subject)


class EpisodeStore:
    """The one open episode, on disk.

    On disk rather than in memory because a restart must not cost the user the
    ability to undo — `app.state.drafts` learned that the other way round. Under
    `.qa/`, which is gitignored and therefore never promotable: this is QA's own
    bookkeeping and has no business converging anywhere.

    One at a time, which is CE v1's single-active-workflow rule (CE_DESIGN) made
    literal rather than assumed.
    """

    def __init__(self, qa, pointers=None, state_path: str = ".qa/episode.json"):
        self.qa = qa
        self.pointers = pointers
        self.path = Path(qa.root) / state_path

    # -- state ---------------------------------------------------------------
    def open(self) -> Episode | None:
        try:
            return Episode.from_dict(json.loads(self.path.read_text()))
        except (OSError, ValueError):
            return None

    def _write(self, ep: Episode) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(ep.to_dict(), indent=2))

    def _forget(self) -> None:
        self.path.unlink(missing_ok=True)
        self.qa.drop_ref(EPISODE_REF)

    # -- lifecycle -----------------------------------------------------------
    def begin(self, workflow: str, subject: str = "") -> dict:
        """Open an episode, or continue the one already open for this work.

        Continuing is the whole reason the snapshot is not taken per submit: a
        user who submits, reads the review, goes back and submits again is doing
        ONE piece of work, and its restore point is where they started — not
        where their second thoughts started.
        """
        current = self.open()
        if current is not None and current.key() == (workflow, subject):
            return {"began": False, "continued": True,
                    "episode": current.to_dict(), "superseded": {}}

        superseded = {}
        if current is not None:
            # A DIFFERENT piece of work, with the last one neither approved nor
            # discarded. Its restore point is dropped, not applied: reverting it
            # here would delete a record the user never asked to delete, on the
            # strength of a guess about what they meant by starting something
            # else. Abandoning is explicit (Rick, 2026-09-18) — the button and
            # the leave-page challenge — and what is left staged is still shown
            # in every preview and cleared by Discard Work in Progress.
            superseded = {"workflow": current.workflow, "subject": current.subject}
            self._forget()

        ep = Episode(
            workflow=workflow, subject=subject,
            snapshot=self.qa.snapshot(EPISODE_REF),
            untracked=self.qa.untracked_paths(),
            started=time.time(),
        )
        self._write(ep)
        return {"began": True, "continued": False,
                "episode": ep.to_dict(), "superseded": superseded}

    def approved(self) -> None:
        """The work is in the SOT. There is nothing to go back to."""
        self._forget()

    def forget(self) -> None:
        """Drop the restore point WITHOUT applying it.

        For the operations that wipe the tree themselves — refresh, discard work
        in progress. They leave nothing this could put back, and a snapshot that
        outlives its tree is worse than none: pressing Discard on a review page
        left open from before would `git checkout` the old snapshot and
        RESURRECT the very files the user had just discarded. Found by
        enumerating this (Rick, 2026-09-18), not by it happening.
        """
        self._forget()

    def abandon(self) -> dict:
        """Put the sandbox back to the snapshot. Never raises.

        Ordering matters and is the reverse of how the damage was done: restore
        the tracked files first so every sidecar says what it used to, delete
        what the episode created second, and only then reconcile binaries —
        which reads sidecars to decide what to pull back from the attic and what
        to delete for having lost one.
        """
        ep = self.open()
        if ep is None:
            return {"abandoned": False, "reason": "nothing open"}

        removed: list[str] = []
        reverted: list[str] = []
        try:
            if ep.snapshot:
                # Asked first: after the restore there is nothing to compare.
                reverted = self.qa.diff_names(ep.snapshot)
                self.qa.restore_tree_from(ep.snapshot)
            started = set(ep.untracked)
            for rel in self.qa.untracked_paths():
                if rel in started:
                    continue  # not this episode's; it was already here
                target = Path(self.qa.root) / rel
                try:
                    target.unlink()
                    removed.append(rel)
                except OSError:
                    pass
            binaries = (self.pointers.reconcile(Path(self.qa.root))
                        if self.pointers is not None else {})
        except Exception as exc:  # noqa: BLE001 - a failed undo must be reported
            return {"abandoned": False, "reason": f"{type(exc).__name__}: {exc}",
                    "workflow": ep.workflow, "subject": ep.subject}
        finally:
            self._forget()

        return {"abandoned": True, "workflow": ep.workflow, "subject": ep.subject,
                "removed": sorted(removed), "reverted": sorted(reverted),
                "restored": binaries.get("restored", []),
                "binaries_removed": binaries.get("removed", [])}
