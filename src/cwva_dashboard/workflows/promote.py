"""Promotion workflow — compose staged QA content to SOT (CE_DESIGN §3).

``run_promotion`` is the orchestration that ties the Phase 3–4 machinery into one
pipeline: **gates → preview → apply → refresh**. It runs in the trusted
orchestrator (git + transport), not the confined worker. The staged content (a
new record, a scrape TTL, a merge/demote rewrite) is already in the QA content
tree; this composes it into a promotion unit and drives it out through the single
gated exit.

Sequence:
1. **Manifest** from the QA git diff against the pre-work stamp.
2. **Gates** — parse (always), plus SHACL shapes and/or SPARQL assertions when
   supplied. Failing gates stop the workflow before any SOT write.
3. **Preview** — isomorphic change summary; the ``on_preview`` callback is the
   user-review gate (auto-approve by default).
4. **Apply** — drift-checked QA commit + transport convergence.
5. **Refresh** — SOT→QA sync (canonical rebuild), the post-promotion step.

Returns a :class:`PromotionRunResult` recording where it stopped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..promotion import gates as _gates
from ..promotion.apply import ApplyResult, apply_unit
from ..promotion.binaries import content_manifest
from ..promotion.preview import ChangePreview, build_preview
from ..promotion.qa_git import QAGit
from ..promotion.transports import Transport
from ..promotion.unit import PromotionStatus, PromotionUnit
from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, is_managed_binary
from ..sot_sync.sync import SyncResult, refresh

__all__ = ["run_promotion", "PromotionRunResult"]

AuditFn = Callable[[str, dict, str], None]
PreviewGate = Callable[[ChangePreview], bool]


@dataclass
class PromotionRunResult:
    status: str  # "converged" | "empty" | "gates_failed" | "rejected" | "previewed"
    unit: PromotionUnit
    preview: ChangePreview | None = None
    applied: ApplyResult | None = None
    refreshed: SyncResult | None = None
    backup: dict | None = None
    #: What the post-convergence trash prune did, or None when it is switched
    #: off. Reported rather than silent: a deletion nobody can see is a deletion
    #: nobody can question.
    pruned: dict | None = None

    @property
    def ok(self) -> bool:
        return self.status == "converged"


def run_promotion(
    qa: QAGit,
    transport: Transport,
    *,
    workflow: str,
    base_commit: str,
    description: str = "",
    provenance: dict | None = None,
    shapes=None,
    assertions=None,
    git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    image_base: str | None = None,
    image_dir: str | None = None,
    document_base: str | None = None,
    document_dir: str | None = None,
    vocab_dirs: list[str] | None = None,
    content_dirs: list[str] | None = None,
    provenance_dir: str | None = None,
    expected_stamp: str | None = None,
    on_preview: PreviewGate | None = None,
    preview_only: bool = False,
    refresh_after: bool = True,
    backup_after: bool = True,
    trash_dir: str = ".qa/trash",
    trash_keep_days: int = 0,
    audit: AuditFn | None = None,
) -> PromotionRunResult:
    manifest = qa.manifest_since(base_commit)
    unit = PromotionUnit(
        workflow=workflow,
        description=description,
        base_commit=base_commit,
        manifest=manifest,
        provenance=provenance or {},
    )

    def _emit(outcome: str) -> None:
        if audit:
            audit("workflow.promote", {"workflow": workflow, "unit": unit.id}, outcome)

    if manifest.is_empty():
        _emit("empty")
        return PromotionRunResult("empty", unit)

    # --- gates ---
    # PRESENT paths only: a deleted file cannot be parsed and is not part of
    # what is published. Deletions still converge — they are in the manifest —
    # they are simply not content to gate.
    rdf_files = [qa.root / p for p in manifest.present_paths() if _gates.rdf_format(p)]
    unit.add_gate(_gates.parse_gate(rdf_files))
    # Build the manifest graph once if any gate over it is active.
    want_graph = (shapes is not None or assertions
                  or (image_base and image_dir) or vocab_dirs or content_dirs)
    data = _gates.load_graph(rdf_files) if (want_graph and rdf_files) else None
    if shapes is not None and data is not None:
        unit.add_gate(_gates.shacl_gate(data, shapes))
    if assertions and data is not None:
        unit.add_gate(_gates.sparql_assertions_gate(data, assertions))
    # Asset references in the promoted RDF must resolve to a managed asset
    # (file or sidecar) — a dangling or malformed schema:image/qrcode/image3d
    # does not reach SOT. Armed when the caller supplies the instance's image
    # base + dir (domain + placement map); a shape authored but never passed to
    # run_promotion is the never-armed state, so it arms here, not on a flag.
    if image_base and image_dir and data is not None:
        unit.add_gate(
            _gates.asset_reference_gate(
                data,
                qa.root,
                image_base=image_base,
                image_dir=image_dir,
                document_base=document_base,
                document_dir=document_dir,
                git_content=git_content_extensions,
            )
        )
    # Vocabulary references (vad:hasPaper) must resolve to a declared concept.
    # Needs the vocab loaded from the QA tree (not in the manifest), so it arms
    # only when the caller supplies the reference dirs (placement map). Same
    # arm-don't-flag reasoning as above.
    if (vocab_dirs or content_dirs) and data is not None:
        # `content_dirs` arms the content-sourced referents (vad:background is
        # an entity record, not a concept). Unarmed, a referenced background
        # cannot be found and reports as dangling — loud rather than silent,
        # which is the right direction for a gate to fail in.
        unit.add_gate(
            _gates.vocabulary_reference_gate(
                data, qa.root, vocab_dirs, content_dirs=content_dirs
            )
        )
    if provenance_dir and data is not None:
        unit.add_gate(_gates.provenance_gate(
            data, qa.root, provenance_dir, content_dirs=content_dirs))
    # Binaries are pushed by translating <x>.ptr -> <x>, so the sidecar is what
    # decides a binary change is promotable. Verify that trust here, against the
    # same content manifest apply() converges (CE_DESIGN §3.4). Conditional like
    # the gates above: a unit with no managed binary has nothing to certify.
    to_sot = content_manifest(manifest, git_content_extensions)
    if any(
        is_managed_binary(p, git_content_extensions) for p in (*to_sot.adds, *to_sot.modifies)
    ):
        unit.add_gate(_gates.pointer_gate(qa.root, to_sot, git_content=git_content_extensions))
    unit.settle_gate_status()
    if not unit.gates_passed():
        _emit("gates_failed")
        return PromotionRunResult("gates_failed", unit)

    # --- preview + user-review gate ---
    preview = build_preview(qa, manifest, base_commit)
    # A human-driven UX cannot answer a synchronous callback: the request that
    # builds the preview has to return so a person can look at it. `preview_only`
    # is that stop — gates and preview run for real, convergence does not happen,
    # and the caller resumes with a second run once approved (see
    # promotion/driver.py). Distinct from "rejected" so the audit log does not
    # record a decision nobody made.
    if preview_only:
        _emit("previewed")
        return PromotionRunResult("previewed", unit, preview=preview)
    if on_preview is not None and not on_preview(preview):
        _emit("rejected")
        return PromotionRunResult("rejected", unit, preview=preview)

    # --- apply (the single gated exit) ---
    applied = apply_unit(
        unit,
        qa,
        transport,
        expected_stamp=expected_stamp,
        git_content_extensions=git_content_extensions,
        audit=audit,
    )

    # --- refresh (SOT -> QA canonical rebuild) ---
    refreshed = (
        refresh(qa, transport, git_content_extensions=git_content_extensions, audit=audit)
        if refresh_after
        else None
    )

    # --- back up what SOT cannot give back ---
    #
    # AFTER the refresh, so the bundle carries the adopt commit too, and after
    # convergence for the obvious reason: a promotion is exactly the moment new
    # history exists worth keeping. The QA git is the only copy of it, and law 6
    # rollback depends on it being there.
    #
    # **A failed backup must never fail the promotion.** The content has already
    # reached SOT by this point; raising here would report a successful publish
    # as an error and invite a re-run that has nothing left to do. It is
    # recorded in the result and audited, so a run of failures is visible rather
    # than silent — the quiet failure being the one that matters, since nobody
    # notices a backup that never happened until they need it.
    backup = None
    if backup_after:
        from ..backup import run_backup

        try:
            backup = run_backup(qa.root, transport).to_dict()
        except NotImplementedError as exc:
            backup = {"ok": False, "error": str(exc)}
        except Exception as exc:
            backup = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if audit:
            audit("qa.backup", {"unit": unit.id, **{
                k: backup.get(k) for k in ("ok", "commits", "bundle_bytes", "attic_files",
                                       "ledger_bytes")
            }}, "ok" if backup.get("ok") else "error:backup")

    # The trash exists so that nothing the user typed is hard-deleted by a path
    # they did not aim at (CE_DESIGN §2.3) — but insurance with no expiry is
    # sediment. Convergence is where it ends: the work the draft belonged to is
    # now definitively in the SOT (Rick, 2026-09-17).
    #
    # Same rule as the backup above, for the same reason: this cannot fail the
    # promotion. The content has already reached SOT, and reporting a successful
    # publish as an error invites a re-run with nothing to do.
    pruned = None
    if trash_keep_days and trash_keep_days > 0:
        from ..trash import prune as _prune_trash

        pruned = _prune_trash(qa.root, trash_dir, trash_keep_days).to_dict()
        if audit and (pruned["removed"] or not pruned["ok"]):
            audit("qa.trash_pruned", {"unit": unit.id, **pruned},
                  "ok" if pruned["ok"] else "error:prune")

    _emit("converged")
    assert unit.status is PromotionStatus.CONVERGED
    return PromotionRunResult("converged", unit, preview=preview, applied=applied,
                              refreshed=refreshed, backup=backup, pruned=pruned)
