"""TCAP navigation — the most-specific-property query (ALGORITHM.md, TCAP_README).

TCAP (Thesaurus Class Annotation Pattern): ontology classes annotated onto
thesaurus concepts within the ``skos:broader`` hierarchy. This module is the
**single shared algorithm** both annotation consumers call (ALGORITHM.md):

- #6 Annotate Work — interactive picker → :func:`annotate`.
- #15 Annotate Document Instances — batch tags → :func:`annotate`.

Given a subject and a concept, it finds the most specific object property whose
range matches the concept's effective type, and emits ``subject property concept``.

Two hard dependencies, both from TCAP_README:
1. **Materialized RDFS inference** — the query relies on types inferred from
   property usage (``rdfs:range``) and on ``rdfs:subClassOf`` transitivity. Run
   :func:`materialize_rdfs` (owlrl) on the graph first; without it the query
   silently returns *different* results. Callers/tests must ensure the store is
   materialized.
2. **The ``owl:ObjectProperty`` filter** in both branches — present in the real
   Groovy, absent from the printed handoff query (erratum). It restricts
   candidates to declared object properties.

**Ties** (>1 surviving triple) are a vocabulary-modeling defect, never normal
(the CrowdHingeBand precedent). The port adjudicates deterministically to unblock
(AI adjudication arrives in Phase 5) and records the tie for structural repair —
tied triples are never surfaced as data.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import owlrl
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS

__all__ = [
    "TCAP_QUERY",
    "materialize_rdfs",
    "navigate",
    "annotate",
    "NavResult",
    "AnnotateResult",
    "Tie",
]

# The canonical most-specific-property query (SPARQL handoff + the
# owl:ObjectProperty erratum). It is **Jena-calibrated**: rdflib mishandles
# NOT EXISTS with a property path bound to an outer variable (?rtX subClassOf+
# ?rt), so the cross-branch specificity filter silently no-ops on rdflib
# (TCAP_README point 2). This constant is the spec of record and is what the
# Fuseki QA store will run directly (Phase 7); :func:`navigate` implements the
# same algorithm in Python for correct results on rdflib until then.
TCAP_QUERY = """
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
CONSTRUCT { ?w ?op ?cpt . } WHERE {
  {
    # Branch 1: direct (possibly inferred) types on the concept
    ?cpt a ?rt .
    FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
    ?op rdfs:range ?rt .
    ?op a owl:ObjectProperty .
    FILTER NOT EXISTS {
      ?rt2 rdfs:subClassOf+ ?rt .
      ?cpt a ?rt2 .
      FILTER (?rt2 != ?rt)
      ?op2 rdfs:range ?rt2 .
    }
  }
  UNION
  {
    # Branch 2: types from broader concepts (+ excludes the concept itself)
    ?cpt skos:broader+ ?rtc .
    ?rtc a ?rt .
    FILTER (?rt NOT IN (skos:Concept, rdfs:Resource))
    ?op rdfs:range ?rt .
    ?op a owl:ObjectProperty .
    FILTER NOT EXISTS {
      ?rt2 rdfs:subClassOf+ ?rt .
      ?rtc a ?rt2 .
      FILTER (?rt2 != ?rt)
      ?op2 rdfs:range ?rt2 .
    }
    FILTER NOT EXISTS {
      ?cpt skos:broader+ ?rtc2 .
      ?rtc2 skos:broader+ ?rtc .
      ?rtc2 a ?rt .
    }
  }
  # Cross-branch: exclude if a more specific property exists via either branch
  FILTER NOT EXISTS {
    {
      ?cpt a ?rtX .
      ?opX rdfs:range ?rtX .
      ?rtX rdfs:subClassOf+ ?rt .
      FILTER (?rtX != ?rt)
    }
    UNION
    {
      ?cpt skos:broader+ ?rtcX .
      ?rtcX a ?rtX .
      ?opX rdfs:range ?rtX .
      ?rtX rdfs:subClassOf+ ?rt .
      FILTER (?rtX != ?rt)
    }
  }
}
"""


def materialize_rdfs(graph: Graph) -> Graph:
    """Materialize RDFS inferences in place (types from ``rdfs:range`` usage,
    ``rdfs:subClassOf`` transitivity). Required before :func:`navigate`."""
    owlrl.DeductiveClosure(owlrl.RDFS_Semantics).expand(graph)
    return graph


Triple = tuple


@dataclass
class NavResult:
    concept: URIRef
    triples: list  # surviving (subject, property, concept) triples
    tie: bool = False

    def __post_init__(self):
        self.tie = len(self.triples) > 1


_EXCLUDED_TYPES = {SKOS.Concept, RDFS.Resource}


def _effective_types(graph: Graph, concept: URIRef) -> set:
    """Types the concept effectively has: its own (direct + RDFS-inferred) plus
    those of every ``skos:broader`` ancestor — the union Branch 1 and Branch 2
    of the query draw from. Excludes the generic skos:Concept / rdfs:Resource."""
    types = set(graph.objects(concept, RDF.type))
    for anc in graph.transitive_objects(concept, SKOS.broader):
        if anc != concept:
            types |= set(graph.objects(anc, RDF.type))
    return {t for t in types if isinstance(t, URIRef) and t not in _EXCLUDED_TYPES}


def _matching_object_properties(graph: Graph, rt: URIRef) -> list:
    """Object properties whose range is exactly ``rt`` (the owl:ObjectProperty
    filter — the erratum)."""
    return sorted(
        (op for op in graph.subjects(RDFS.range, rt) if (op, RDF.type, OWL.ObjectProperty) in graph),
        key=str,
    )


def _strict_subclass(graph: Graph, sub: URIRef, sup: URIRef) -> bool:
    return sub != sup and sup in graph.transitive_objects(sub, RDFS.subClassOf)


def navigate(graph: Graph, subject, concept) -> NavResult:
    """Most specific typed property for one (subject, concept). The graph must be
    RDFS-materialized (:func:`materialize_rdfs`) — types inferred from property
    usage are a hard dependency. Implements TCAP_QUERY in Python (see that
    constant for why): among the concept's effective types that have a matching
    object property, keep only the most specific (no candidate type is a stricter
    subclass); emit ``subject property concept`` per survivor. More than one
    survivor is a **tie** — a vocabulary-modeling defect, not a normal result."""
    subject, concept = URIRef(subject), URIRef(concept)
    # candidate type -> its matching object properties
    candidates = {}
    for rt in _effective_types(graph, concept):
        ops = _matching_object_properties(graph, rt)
        if ops:
            candidates[rt] = ops
    # specificity / cross-branch filter: drop a type if a stricter candidate type exists
    survivors = [
        rt for rt in candidates
        if not any(_strict_subclass(graph, other, rt) for other in candidates if other != rt)
    ]
    triples = sorted(
        ((subject, op, concept) for rt in survivors for op in candidates[rt]),
        key=lambda t: str(t[1]),
    )
    return NavResult(concept=concept, triples=triples)


@dataclass
class Tie:
    concept: URIRef
    candidates: list  # all surviving triples
    adjudicated: object  # the deterministically-picked triple


@dataclass
class AnnotateResult:
    placed: list = field(default_factory=list)  # typed-property triples to write
    ties: list = field(default_factory=list)  # Tie records → ledger + open item
    unmatched: list = field(default_factory=list)  # concepts that produced no property


def _adjudicate(triples: list):
    """Deterministic tie-break to unblock the workflow (AI adjudication is the
    Phase-5 upgrade). Picks the property whose range is most specific; ties on
    that fall back to the lexically-first property URI — stable across runs."""
    return sorted(triples, key=lambda t: str(t[1]))[0]


def annotate(graph: Graph, subject, concepts) -> AnnotateResult:
    """Emit the most-specific typed properties for a subject over a list of
    concepts (the shared #6/#15 step). ``graph`` must be RDFS-materialized. Ties
    are adjudicated (one triple placed) and recorded for structural repair; a
    concept yielding nothing is reported as unmatched (not silently dropped)."""
    result = AnnotateResult()
    for concept in concepts:
        nav = navigate(graph, subject, concept)
        if not nav.triples:
            result.unmatched.append(URIRef(concept))
        elif nav.tie:
            pick = _adjudicate(nav.triples)
            result.ties.append(Tie(concept=URIRef(concept), candidates=nav.triples, adjudicated=pick))
            result.placed.append(pick)
        else:
            result.placed.append(nav.triples[0])
    return result
