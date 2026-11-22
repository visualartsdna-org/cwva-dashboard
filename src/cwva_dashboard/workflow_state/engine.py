"""The standing-query engine — one computation, two renderings (CE_DESIGN §7.1).

``evaluate`` runs the definitions against their sources and returns a
:class:`WorkflowState` with the three panel groups: pipeline queues (fs counts),
open obligations (SPARQL results minus ledger dismissals), and the in-flight
workflow (stub until Phase 6). ``WorkflowState.narrate`` renders the same result
as the agent's opening summary — the panel and the prose are the same numbers.

The engine is pure: it takes a graph (for SPARQL), a ``count_fn`` (for fs), and
a ledger (for dismissals). The tool layer supplies those from FileOps; tests
supply them directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .definitions import StandingQuery

__all__ = ["evaluate", "WorkflowState", "OpenItem", "QueueCount"]

# count_fn(dir, extensions) -> int
CountFn = Callable[[str, "list[str] | None"], int]


@dataclass
class QueueCount:
    id: str
    label: str
    count: int
    resolving_action: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "count": self.count,
            "resolving_action": self.resolving_action,
        }


@dataclass
class OpenItem:
    definition_id: str
    key: str
    label: str
    severity: str
    resolving_action: str | None
    summary: str  # the definition's short phrase, for grouped narration

    def to_dict(self) -> dict:
        return {
            "definition_id": self.definition_id,
            "key": self.key,
            "label": self.label,
            "severity": self.severity,
            "resolving_action": self.resolving_action,
        }


@dataclass
class WorkflowState:
    pipeline_queues: list[QueueCount] = field(default_factory=list)
    open_obligations: list[OpenItem] = field(default_factory=list)
    in_flight: dict | None = None

    def narrate(self) -> str:
        """The agent's opening state summary — same numbers as the panel."""
        parts: list[str] = []
        for q in self.pipeline_queues:
            if q.count:
                parts.append(f"{q.count} {q.label}")
        # group obligations by definition for a compact phrase
        counts: dict[str, tuple[int, str]] = {}
        for o in self.open_obligations:
            n, _ = counts.get(o.definition_id, (0, o.summary))
            counts[o.definition_id] = (n + 1, o.summary)
        for n, summary in counts.values():
            parts.append(f"{n} {summary}")
        return "; ".join(parts) if parts else "nothing pending"

    def to_dict(self) -> dict:
        return {
            "pipeline_queues": [q.to_dict() for q in self.pipeline_queues],
            "open_obligations": [o.to_dict() for o in self.open_obligations],
            "in_flight": self.in_flight,
            "summary": self.narrate(),
        }


def evaluate(
    definitions,
    *,
    graph=None,
    count_fn: CountFn | None = None,
    ledger=None,
    in_flight: dict | None = None,
) -> WorkflowState:
    state = WorkflowState(in_flight=in_flight)
    for d in definitions:
        if d.source == "fs":
            n = count_fn(d.params.get("dir", "."), d.params.get("extensions")) if count_fn else 0
            state.pipeline_queues.append(
                QueueCount(id=d.id, label=d.summary, count=n, resolving_action=d.resolving_action)
            )
        elif d.source == "sparql":
            if graph is None or not d.query:
                continue
            dismissed = ledger.dismissed(d.id) if ledger is not None else set()
            for row in graph.query(d.query):
                key = str(row.item)
                if key in dismissed:
                    continue
                label = str(row.label) if getattr(row, "label", None) is not None else key
                state.open_obligations.append(
                    OpenItem(
                        definition_id=d.id,
                        key=key,
                        label=label,
                        severity=d.severity,
                        resolving_action=d.resolving_action,
                        summary=d.summary,
                    )
                )
        elif d.source == "ledger":
            # Hygiene-ledger items as obligations. TCAP ties (§6 tie policy) land
            # here — a vocabulary defect to repair, not a data problem.
            if ledger is None or d.params.get("kind") != "tie":
                continue
            dismissed = ledger.dismissed(d.id) if ledger is not None else set()
            for tie in ledger.ties():
                key = f"{tie['subject']}|{tie['concept']}"
                if key in dismissed:
                    continue
                concept = tie["concept"].rsplit("/", 1)[-1]
                state.open_obligations.append(
                    OpenItem(
                        definition_id=d.id,
                        key=key,
                        label=f"TCAP tie on {concept} — investigate thesaurus/ontology",
                        severity=d.severity,
                        resolving_action=d.resolving_action,
                        summary=d.summary,
                    )
                )
        # git / audit sources are declared but not evaluated here yet.
    return state
