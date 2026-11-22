"""The promotion unit — manifest + lifecycle (CE_DESIGN §3.1).

A promotion unit is the output set of one workflow instance: the files it added,
modified, or deleted in the QA content tree, plus the gate results that certify
conformance and the provenance that attributes it. It promotes all-or-nothing;
partial promotion is the failure mode that corrupts a SOT, so the unit is the
indivisible granule of both apply and rollback.

The change set is expressed as a file-level manifest (adds / modifies /
**deletes** — deletion is part of the exit channel, §3.3) computed from the QA
git diff. The unit carries the pre-work QA/SOT stamp (``base_commit``) that
apply re-checks before converging.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

__all__ = ["ChangeManifest", "GateResult", "PromotionStatus", "PromotionUnit",
           "LOCAL_ONLY_DIRS", "is_local_only"]

#: Directories that live in the QA tree and NEVER converge to the SOT.
#:
#: `evidence/` is the curator's working record — the tags a workflow consumed,
#: the concepts an agent proposed and a person then excluded, the orphaned
#: terms that are a thesaurus-modelling backlog. It belongs in the QA git so it
#: has history across months, and it does not belong in a published catalogue.
#:
#: **This was claimed and not implemented.** `workflows/annotate.py` has said
#: "QA git, never pushed to SOT" since #15 was built, while only `operational/`
#: was actually excluded — so every evidence file #15 wrote has been converging.
#: Fixed 2026-09-29, before DTS writes the first orphan there (Workflows2_REVIEW
#: §7.1/§10.11, promoted from a defect to a blocker when round 3 put the
#: backlog in `evidence/`).
#:
#: Excluded in the MANIFEST rather than in the transport, which is the
#: difference between "not sent" and "not part of the unit": the review stop
#: does not list it as something being distributed, the gates do not read it,
#: and a rollback reverts it in QA without touching the SOT. `operational/` is
#: excluded in the transport instead, and correctly — it is never in the QA
#: tree at all, being written to the target directly by the backup.
LOCAL_ONLY_DIRS = ("evidence",)


def is_local_only(rel: str) -> bool:
    """Does this QA-tree path stay in QA — committed, never converged?"""
    head = str(rel).strip("/").split("/", 1)[0]
    return head in LOCAL_ONLY_DIRS


class PromotionStatus(str, Enum):
    DRAFT = "draft"  # assembled, not yet gated
    GATES_PASSED = "gates_passed"
    GATES_FAILED = "gates_failed"
    COMMITTED = "committed"  # written to the QA git as a commit
    CONVERGED = "converged"  # pushed to SOT via a transport
    ROLLED_BACK = "rolled_back"


@dataclass
class ChangeManifest:
    """File-level change set, sandbox-relative POSIX paths."""

    adds: list[str] = field(default_factory=list)
    modifies: list[str] = field(default_factory=list)
    deletes: list[str] = field(default_factory=list)

    def all_paths(self) -> list[str]:
        return sorted({*self.adds, *self.modifies, *self.deletes})

    def present_paths(self) -> list[str]:
        """Paths that will EXIST after this unit — adds and modifies only.

        What the content gates read. A deleted file has nothing to parse and is
        not part of what is being published, and `all_paths()` includes deletes,
        so a gate built on it opens the deleted file and raises
        FileNotFoundError. Latent until the first promotion containing a deleted
        RDF file, which is exactly how it surfaced (2026-09-10): two superseded
        workOnSite snapshots were removed and the next preview crashed.
        """
        return sorted({*self.adds, *self.modifies})

    def is_empty(self) -> bool:
        return not (self.adds or self.modifies or self.deletes)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "adds": len(self.adds),
            "modifies": len(self.modifies),
            "deletes": len(self.deletes),
        }

    def summary(self) -> str:
        c = self.counts
        return f"+{c['adds']} ~{c['modifies']} -{c['deletes']}"

    def to_dict(self) -> dict:
        return {"adds": sorted(self.adds), "modifies": sorted(self.modifies), "deletes": sorted(self.deletes)}

    @classmethod
    def from_dict(cls, d: dict) -> "ChangeManifest":
        return cls(
            adds=list(d.get("adds", [])),
            modifies=list(d.get("modifies", [])),
            deletes=list(d.get("deletes", [])),
        )


@dataclass
class GateResult:
    """Outcome of one gate. ``ok`` is the pass/fail; ``messages`` carry
    per-item detail (parse errors, SHACL violations, failed assertions)."""

    name: str
    ok: bool
    summary: str = ""
    messages: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "summary": self.summary,
            "messages": self.messages,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GateResult":
        return cls(
            name=d["name"],
            ok=bool(d["ok"]),
            summary=d.get("summary", ""),
            messages=list(d.get("messages", [])),
            details=dict(d.get("details", {})),
        )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PromotionUnit:
    workflow: str
    description: str = ""
    manifest: ChangeManifest = field(default_factory=ChangeManifest)
    base_commit: str | None = None
    provenance: dict = field(default_factory=dict)  # actor / model identity (§8)
    gates: list[GateResult] = field(default_factory=list)
    status: PromotionStatus = PromotionStatus.DRAFT
    qa_commit: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: str = field(default_factory=_now)

    # -- gates --------------------------------------------------------------

    def add_gate(self, result: GateResult) -> None:
        self.gates.append(result)

    def gates_passed(self) -> bool:
        return bool(self.gates) and all(g.ok for g in self.gates)

    def settle_gate_status(self) -> PromotionStatus:
        """Move DRAFT -> GATES_PASSED / GATES_FAILED based on gate outcomes.
        Only meaningful before commit; later states are set by apply/rollback."""
        if self.status in (PromotionStatus.COMMITTED, PromotionStatus.CONVERGED, PromotionStatus.ROLLED_BACK):
            return self.status
        self.status = PromotionStatus.GATES_PASSED if self.gates_passed() else PromotionStatus.GATES_FAILED
        return self.status

    def failing_gates(self) -> list[GateResult]:
        return [g for g in self.gates if not g.ok]

    # -- serialization ------------------------------------------------------

    def commit_message(self) -> str:
        """Message for the QA commit that records this unit. Human summary on
        the first lines, then a machine-readable manifest block so the commit
        is both readable and replayable (CE_DESIGN §3.3)."""
        header = f"promote({self.workflow}): {self.description or self.manifest.summary()}"
        body = {
            "id": self.id,
            "workflow": self.workflow,
            "manifest": self.manifest.to_dict(),
            "base_commit": self.base_commit,
            "provenance": self.provenance,
            "gates": [{"name": g.name, "ok": g.ok} for g in self.gates],
        }
        block = json.dumps(body, indent=2, sort_keys=True, ensure_ascii=False)
        return f"{header}\n\n{self.manifest.summary()}\n\ncwva-promotion: |\n{block}\n"

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "workflow": self.workflow,
            "description": self.description,
            "created_at": self.created_at,
            "manifest": self.manifest.to_dict(),
            "base_commit": self.base_commit,
            "provenance": self.provenance,
            "gates": [g.to_dict() for g in self.gates],
            "status": self.status.value,
            "qa_commit": self.qa_commit,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PromotionUnit":
        return cls(
            id=d["id"],
            workflow=d["workflow"],
            description=d.get("description", ""),
            created_at=d.get("created_at", _now()),
            manifest=ChangeManifest.from_dict(d.get("manifest", {})),
            base_commit=d.get("base_commit"),
            provenance=dict(d.get("provenance", {})),
            gates=[GateResult.from_dict(g) for g in d.get("gates", [])],
            status=PromotionStatus(d.get("status", "draft")),
            qa_commit=d.get("qa_commit"),
        )
