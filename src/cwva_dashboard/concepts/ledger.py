"""Hygiene ledger — the only recorded workflow state (CE_DESIGN §6, §7.1).

A small TTL container in the sandbox holding **dismissals**: "open item X of
kind K is intentionally not an obligation — stop reporting it." Open items =
standing-query results − dismissals. The same container will later hold
unresolved concept-dup pairs (§6); dismissals are keyed by ``(kind, item_key)``.

Deterministic node ids make re-dismissing idempotent. The ledger is TTL so it is
greppable and survives refresh (it lives under ``.qa/`` — QA-internal, never
converged to SOT).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from rdflib import RDF, Graph, Literal, Namespace, URIRef

__all__ = ["HygieneLedger", "HL", "LEDGER_PATH"]

HL = Namespace("urn:cwva:hygiene#")
LEDGER_PATH = ".qa/hygiene_ledger.ttl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _node(kind: str, item_key: str) -> URIRef:
    digest = hashlib.sha1(f"{kind}\n{item_key}".encode("utf-8")).hexdigest()[:16]
    return HL[f"d-{digest}"]


def _tie_node(subject: str, concept: str) -> URIRef:
    digest = hashlib.sha1(f"tie\n{subject}\n{concept}".encode("utf-8")).hexdigest()[:16]
    return HL[f"t-{digest}"]


@dataclass
class HygieneLedger:
    graph: Graph

    @classmethod
    def from_ttl(cls, text: str = "") -> "HygieneLedger":
        g = Graph()
        if text.strip():
            g.parse(data=text, format="turtle")
        return cls(g)

    def dismiss(self, kind: str, item_key: str, reason: str = "") -> None:
        """Record (or refresh) a dismissal. Idempotent per (kind, item_key)."""
        node = _node(kind, item_key)
        self.graph.set((node, RDF.type, HL.Dismissal))
        self.graph.set((node, HL.kind, Literal(kind)))
        self.graph.set((node, HL.itemKey, Literal(item_key)))
        self.graph.set((node, HL.at, Literal(_now())))
        if reason:
            self.graph.set((node, HL.reason, Literal(reason)))

    def undismiss(self, kind: str, item_key: str) -> bool:
        node = _node(kind, item_key)
        if (node, RDF.type, HL.Dismissal) not in self.graph:
            return False
        for p, o in list(self.graph.predicate_objects(node)):
            self.graph.remove((node, p, o))
        return True

    def dismissed(self, kind: str) -> set[str]:
        """The item keys dismissed for a given kind (standing-query id)."""
        out: set[str] = set()
        for node in self.graph.subjects(HL.kind, Literal(kind)):
            for key in self.graph.objects(node, HL.itemKey):
                out.add(str(key))
        return out

    def dismissals_at(self, kind: str) -> dict[str, str]:
        """``{item key: when}`` for a kind. The workflow board's manual ticks
        are dismissals, and a tick's DATE is part of what it records."""
        out: dict[str, str] = {}
        for node in self.graph.subjects(HL.kind, Literal(kind)):
            at = self.graph.value(node, HL.at)
            for key in self.graph.objects(node, HL.itemKey):
                out[str(key)] = str(at) if at is not None else ""
        return out

    def is_dismissed(self, kind: str, item_key: str) -> bool:
        return item_key in self.dismissed(kind)

    # -- TCAP ties (§6 tie policy: record to force a structural fix) ---------

    def record_tie(self, subject: str, concept: str, candidates: list[str]) -> None:
        """Record an unresolved TCAP tie (>1 surviving typed property). A tie is
        a vocabulary-modeling defect; the workflow-panel surfaces it as an open
        item pointing at the thesaurus/ontology, not the code. Idempotent per
        (subject, concept)."""
        node = _tie_node(subject, concept)
        self.graph.set((node, RDF.type, HL.Tie))
        self.graph.set((node, HL.subject, URIRef(subject)))
        self.graph.set((node, HL.concept, URIRef(concept)))
        self.graph.set((node, HL.candidates, Literal(",".join(candidates))))
        self.graph.set((node, HL.at, Literal(_now())))

    def ties(self) -> list[dict]:
        out: list[dict] = []
        for node in self.graph.subjects(RDF.type, HL.Tie):
            cand = self.graph.value(node, HL.candidates)
            out.append(
                {
                    "subject": str(self.graph.value(node, HL.subject)),
                    "concept": str(self.graph.value(node, HL.concept)),
                    "candidates": str(cand).split(",") if cand else [],
                }
            )
        return out

    def to_ttl(self) -> str:
        self.graph.bind("hl", HL)
        return self.graph.serialize(format="turtle")
