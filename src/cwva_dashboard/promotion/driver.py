"""Human-driven promotion: gates → preview → **stop** → approve → converge.

Gate item **A0**. `run_promotion` was complete and tested but reachable only
from the scenario harness, which supplies an *auto-approving* ``on_preview``
because episodes are unattended. A UX route that reused that callback would
converge without anyone looking — and the change preview **is** the review gate
until the browser lands (Phase 7), so that route would silently delete the only
review the system has. This module is the driver that keeps the stop.

**Why two phases rather than a blocking callback.** ``on_preview`` is
synchronous, but the request that builds a preview must *return* for a human to
read it. Parking a worker thread on an Event until someone clicks would hold a
thread hostage to a person. Instead:

1. :meth:`PromotionDriver.preview` runs the real gates and builds the real
   preview with ``preview_only=True``. Nothing is committed, nothing converges.
2. The operator looks, then calls :meth:`approve` or :meth:`reject`.
3. :meth:`approve` re-runs the *same* path and converges — but only after
   confirming the recomputed preview is **identical** to the approved one.

That last check is the point, and it is why this is not merely a UI convenience:
between preview and approval the QA tree can change (another edit, a stray
write, an interrupted workflow). Converging a manifest the human never saw is
precisely the failure the review gate exists to prevent, so a mismatch aborts
with ``stale`` instead of converging. It is the same shape as the pre-push drift
check that guards the SOT side — this one guards the QA side.

**Not a registry tool, deliberately** (law 1 + PROJECT_PLAN 4.7 §6): promotion
is the single gated exit and lives in the trusted orchestrator. The agent gets
here the same way the human does — by asking the orchestrator — never by holding
a tool that converges.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, PointerManager
from .episode import EpisodeStore
from ..workflows.promote import PromotionRunResult, run_promotion

__all__ = ["PromotionDriver", "PendingPromotion", "PromotionDriverError"]


class PromotionDriverError(RuntimeError):
    pass


def _fingerprint(result: PromotionRunResult) -> str:
    """A stable digest of *what the human is being asked to approve*.

    Covers the file manifest and the semantic summary — the two things the
    preview shows. Deliberately not the unit id (fresh per run) and not a
    timestamp: two runs over an unchanged tree must agree, or every approval
    would fail as stale.
    """
    p = result.preview
    m = result.unit.manifest
    payload = {
        "base": result.unit.base_commit,
        "adds": sorted(m.adds),
        "modifies": sorted(m.modifies),
        "deletes": sorted(m.deletes),
        "triples_added": getattr(p, "triples_added", 0),
        "triples_removed": getattr(p, "triples_removed", 0),
        "subjects_added": sorted(getattr(p, "subjects_added", [])),
        "subjects_removed": sorted(getattr(p, "subjects_removed", [])),
        "subjects_modified": sorted(getattr(p, "subjects_modified", [])),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


@dataclass
class PendingPromotion:
    """One promotion awaiting a human decision. Holds no unit state of its own —
    the QA tree is the state, and the run is recomputed on approval."""

    token: str
    workflow: str
    base_commit: str
    fingerprint: str
    description: str = ""
    gates: list[dict] = field(default_factory=list)
    preview_summary: str = ""
    manifest: dict = field(default_factory=dict)
    # Opaque payload owned by whoever created the promotion — the driver never
    # interprets it. RDF Entry stores the submitted field values and the paths
    # it minted, so "Edit Form" can repopulate and clean up. Keeping it opaque
    # is what stops promotion from growing per-workflow knowledge.
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "token": self.token,
            "workflow": self.workflow,
            "base_commit": self.base_commit,
            "description": self.description,
            "gates": self.gates,
            "preview": self.preview_summary,
            "manifest": self.manifest,
            "fingerprint": self.fingerprint[:12],
        }


class PromotionDriver:
    """Owns pending promotions for one dashboard instance (CE v1: single user,
    single active workflow, so an in-process map is the whole store)."""

    def __init__(
        self,
        qa,
        transport,
        *,
        git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
        image_base: str | None = None,
        documents_base: str | None = None,
        layout=None,
        vocab_dirs: list[str] | None = None,
        content_dirs: list[str] | None = None,
        shapes=None,
        trash_dir: str = ".qa/trash",
        trash_keep_days: int = 0,
        audit=None,
    ):
        self.qa = qa
        self.transport = transport
        self.git_content_extensions = git_content_extensions
        self.image_base = image_base
        self.documents_base = documents_base
        self.layout = layout
        self.vocab_dirs = vocab_dirs
        self.content_dirs = content_dirs
        # The SHACL shapes, or None. This argument existed and was passed as
        # None from here for the whole of Phase 4 — the gate was written, tested
        # and never armed in the running app, which is the same "gates passed
        # means no gates ran" trap the fixtures hit. It is armed by `create_app`
        # now, and a test asserts that it is.
        self.shapes = shapes
        # Post-convergence trash pruning. Defaults to OFF here and is armed by
        # `create_app` from config: a driver built in a test should not quietly
        # delete a fixture's files because the clock says they are old.
        self.trash_dir = trash_dir
        self.trash_keep_days = trash_keep_days
        self.audit = audit
        # The unsaved work session (episode.py). Leaving a review without
        # approving puts the sandbox back, which is what every form the user has
        # ever met already does and what this one did not.
        self.episodes = EpisodeStore(
            qa,
            pointers=PointerManager(qa.root, git_content=git_content_extensions),
        )
        self._pending: dict[str, PendingPromotion] = {}
        self.last_adopted: list[str] = []
        self._lock = threading.Lock()

    # -- the unsaved work session -------------------------------------------
    def begin_episode(self, workflow: str, subject: str = "") -> dict:
        """Called by a writer BEFORE it writes. Snapshots the tree once per
        piece of work, and abandons a different one left open."""
        return self.episodes.begin(workflow, subject)

    def abandon_episode(self) -> dict:
        return self.episodes.abandon()

    def open_episode(self) -> dict:
        ep = self.episodes.open()
        return ep.to_dict() if ep is not None else {}

    # -- the shared gate/preview path, run identically in both phases --------
    def _reconcile_binaries(self) -> None:
        """Mint sidecars for binaries that arrived without going through fileops.

        A managed binary is gitignored, so the **`.ptr` sidecar is the only thing
        the git-derived manifest can see**. `fileops` mints one on write and sync
        rebuilds them after a pull, but a file dropped into the sandbox by hand
        (`cp`, a file manager, an editor's save-as) has neither — so it is
        invisible to promotion. It passes the asset-reference gate, because the
        real file is genuinely present locally, and then simply never converges:
        the record lands on SOT referencing an image that will never be there.

        Found on the first real approve (2026-08-25): an image placed by hand was
        referenced by the promoted work and silently left behind. Reconciling
        here makes what is in the tree match what will be promoted, and the
        preview stop is what keeps that honest — a stray binary shows up in the
        change for a human to reject, rather than vanishing without a trace.
        """
        out = PointerManager(
            self.qa.root, git_content=self.git_content_extensions
        ).rebuild_sidecars(self.qa.root)
        # REPORTED, not silent. This runs on every preview, so merely LOOKING at
        # a change can create files — a sidecar for a binary that arrived
        # without one. That is the point (a binary with no sidecar never
        # converges), but a preview that quietly modifies the tree it is
        # previewing is a thing the user has to be able to see. Rick enumerated
        # it, 2026-09-18.
        self.last_adopted = sorted(out.get("updated", []))
        return out

    def _run(self, *, workflow: str, description: str, preview_only: bool,
             on_preview=None, expected_stamp=None) -> PromotionRunResult:
        self._reconcile_binaries()
        return run_promotion(
            self.qa,
            self.transport,
            workflow=workflow,
            base_commit=self.qa.head(),
            description=description,
            shapes=self.shapes,
            image_base=self.image_base,
            image_dir=self.layout.dir("image") if self.layout else None,
            document_base=self.documents_base,
            document_dir=self.layout.dir("document") if self.layout else None,
            vocab_dirs=self.vocab_dirs,
            content_dirs=self.content_dirs,
            provenance_dir=self.layout.dir("provenance_ttl") if self.layout else None,
            trash_dir=self.trash_dir,
            trash_keep_days=self.trash_keep_days,
            git_content_extensions=self.git_content_extensions,
            expected_stamp=expected_stamp,
            on_preview=on_preview,
            preview_only=preview_only,
            audit=self.audit,
        )

    def take(self, token: str) -> PendingPromotion | None:
        """Claim a pending promotion, removing it. Used by callers that are
        abandoning it deliberately (Edit Form) and need its context back."""
        with self._lock:
            return self._pending.pop(token, None)

    def preview(self, *, workflow: str, description: str = "", context: dict | None = None) -> dict:
        """Phase 1: run gates and build the preview. Converges nothing.

        Returns the preview payload plus a token. ``status`` is ``empty`` (no
        changes), ``gates_failed`` (with the failing gates — no token, because
        there is nothing approvable), or ``previewed``.
        """
        result = self._run(
            workflow=workflow, description=description, preview_only=True
        )
        gates = [g.to_dict() for g in result.unit.gates]

        if result.status in ("empty", "gates_failed"):
            return {
                "status": result.status,
                "gates": gates,
                "adopted": list(self.last_adopted),
                "failing": [g.name for g in result.unit.failing_gates()],
            }

        adopted = list(self.last_adopted)
        pending = PendingPromotion(
            token=uuid.uuid4().hex,
            workflow=workflow,
            base_commit=result.unit.base_commit,
            fingerprint=_fingerprint(result),
            description=description,
            gates=gates,
            preview_summary=result.preview.summary() if result.preview else "",
            manifest=result.unit.manifest.counts,
            context=dict(context or {}),
        )
        with self._lock:
            self._pending[pending.token] = pending
        return {"status": "previewed", "adopted": adopted, **pending.to_dict()}

    def approve(self, token: str, *, expected_stamp: str | None = None) -> dict:
        """Phase 2: converge — but only this exact change.

        Re-runs gates and preview, and refuses with ``stale`` if the recomputed
        fingerprint differs from the approved one. Convergence happens on no
        other path.
        """
        with self._lock:
            pending = self._pending.get(token)
        if pending is None:
            raise PromotionDriverError(f"unknown or already-decided token {token!r}")

        seen: dict[str, Any] = {}

        def _gate(preview) -> bool:
            # Approval is scoped to what was reviewed: recompute and compare.
            return seen["fingerprint"] == pending.fingerprint

        # Recompute the fingerprint from a fresh preview_only pass, so the
        # comparison happens before anything is committed.
        check = self._run(
            workflow=pending.workflow, description=pending.description,
            preview_only=True,
        )
        seen["fingerprint"] = _fingerprint(check) if check.preview else ""
        if check.status != "previewed" or seen["fingerprint"] != pending.fingerprint:
            with self._lock:
                self._pending.pop(token, None)
            return {
                "status": "stale",
                "reason": (
                    "the QA tree changed since this preview; nothing was converged. "
                    "Re-preview and review the current change."
                ),
                "was": pending.fingerprint[:12],
                "now": seen["fingerprint"][:12],
            }

        result = self._run(
            workflow=pending.workflow,
            description=pending.description,
            preview_only=False,
            on_preview=_gate,
            expected_stamp=expected_stamp,
        )
        with self._lock:
            self._pending.pop(token, None)
        if result.status == "converged":
            # Saved. There is nothing to go back to, and keeping a restore point
            # for converged work would let a later abandon undo what is already
            # in the SOT — which is rollback's job, with rollback's blast radius.
            self.episodes.approved()

        return {
            "status": result.status,
            "unit": result.unit.id,
            "gates": [g.to_dict() for g in result.unit.gates],
            "preview": result.preview.summary() if result.preview else "",
            "stamp": getattr(result.applied, "stamp", None),
            # WHAT IT TOUCHED. The caller needs this to decide whether the
            # dashboard's own view of itself is now stale — a converged artist
            # profile is a different form behind a card, and the registry that
            # builds that form was assembled before the promotion ran.
            "paths": sorted(result.unit.manifest.all_paths()),
            "refreshed": bool(result.refreshed),
            "backup": result.backup,
        }

    def reject(self, token: str) -> dict:
        """Abandon a pending promotion. Nothing was written, so nothing is undone
        — QA keeps the uncommitted work and SOT was never touched. (After
        convergence the remedy is rollback, not this.)"""
        with self._lock:
            pending = self._pending.pop(token, None)
        if pending is None:
            raise PromotionDriverError(f"unknown or already-decided token {token!r}")
        if self.audit:
            self.audit(
                "workflow.promote",
                {"workflow": pending.workflow, "token": token[:12]},
                "rejected",
            )
        return {"status": "rejected", "workflow": pending.workflow}

    def pending(self) -> list[dict]:
        with self._lock:
            return [p.to_dict() for p in self._pending.values()]

    # -- work in progress ----------------------------------------------------
    def work_in_progress(self) -> dict:
        """What is uncommitted in QA right now — the change a promotion *would*
        pick up.

        A promotion unit is **everything uncommitted since the base commit**
        (law 4), so abandoned form submissions accumulate: each one leaves a
        record behind, and the next promotion sweeps up all of them. That is
        correct behaviour and the preview does list the files, but in a
        dev loop it means one entry's mistake rides along with the next entry's
        change. This reports the pile so it can be seen, and
        :meth:`discard_work_in_progress` empties it.
        """
        self._reconcile_binaries()
        manifest = self.qa.manifest_since(self.qa.head())
        return {
            "head": self.qa.head(),
            "adds": sorted(manifest.adds),
            "modifies": sorted(manifest.modifies),
            "deletes": sorted(manifest.deletes),
            "counts": manifest.counts,
            "clean": manifest.is_empty(),
        }

    def discard_work_in_progress(self) -> dict:
        """Throw away everything uncommitted, restoring QA to HEAD.

        **Destructive and deliberately narrow.** It touches the QA working tree
        only: history is never rewritten (rollback depends on it being
        immutable, law 6) and SOT is never contacted — nothing here can reach a
        transport. Converged work is unaffected; undoing *that* is rollback,
        which is a different operation with a different blast radius.

        Two steps, because one is not enough under the binary policy:

        1. ``restore_to(HEAD)`` resets tracked files, removing the new ``.ttl``
           records and ``.ptr`` sidecars.
        2. ``reconcile()`` then deletes managed binaries whose sidecar just
           disappeared. Without it the QR JPEGs and ingested images would stay
           as orphans — present on disk, invisible to git, and silently swept
           into some later manifest. That is the same sidecar-is-the-only-
           visible-artifact property that produced the hand-placed-binary bug.

        Any pending promotion token is invalidated: the tree it described is
        gone. The approve path would catch that as ``stale`` anyway (the
        fingerprint would not match), but dropping the tokens here makes the
        outcome a plain "nothing pending" rather than a confusing conflict.
        """
        before = self.work_in_progress()
        if before["clean"]:
            return {"discarded": False, "reason": "nothing to discard", **before}

        # The restore point goes first: it points at a tree that is about to
        # stop existing, and applying it afterwards would put back what this is
        # throwing away.
        self.episodes.forget()

        self.qa.stage_all()  # capture untracked files so the reset removes them
        self.qa.restore_to(self.qa.head())
        pointers = PointerManager(
            self.qa.root, git_content=self.git_content_extensions
        ).reconcile(self.qa.root)

        with self._lock:
            dropped = len(self._pending)
            self._pending.clear()

        if self.audit:
            self.audit(
                "qa.discard_wip",
                {"counts": before["counts"], "tokens_dropped": dropped},
                "ok",
            )
        return {
            "discarded": True,
            "adds": before["adds"],
            "modifies": before["modifies"],
            "deletes": before["deletes"],
            "counts": before["counts"],
            "binaries_removed": pointers.get("removed", []),
            "tokens_dropped": dropped,
            "head": self.qa.head(),
        }
