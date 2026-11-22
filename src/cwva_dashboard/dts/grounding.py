"""The grounding node: why this concept, from these words, in that document.

Rick's requirement (PLAN_CA_v2.1) is that grounding stops being a Turtle
comment and becomes data a UI can act on — open the source document, find the
phrase, show the sentences around it. The plan sketches the node twice, on a
derived concept and on a tagged entity, and **the two sketches disagree**. This
module is the reconciliation.

**One shape, and the rule is which end the node hangs from.** A grounding
always relates three things: a concept, a phrase, and the document that
phrase came from. Two of them are named explicitly and the third is whatever
the node is attached to —

    the:FacetedSurface the:grounding [        # on the CONCEPT, from derivation
        rdfs:label    "ground verified" ;
        the:phrase    "faceted, mirrored male figures" ;
        the:srcEntity work:<criticism entity> ;
        the:match     the:unique ;
    ] .

    work:<criticism entity> the:grounding [   # on the ENTITY, from tagging
        rdfs:label    "ground verified" ;
        the:phrase    "read eucharistically" ;
        the:concept   the:EucharisticSymbolism ;
    ] .

so nothing is stated twice and neither node needs its neighbour to be read.

**`the:match` is derivation-only, and that is not an omission.** It answers
"what does this new term sit near, so a curator can see whether we already
have it". A tagging pass chooses from concepts that already exist, so the
question does not arise.

**The context is NOT stored.** The plan wants the surrounding sentences on
screen; storing them would copy a slice of the document into every concept and
let the copy drift from the document. The phrase is stored, and
`documents.context_around` recovers the context from the source on demand.

**`rdfs:comment` from the sketch is dropped** — it was Rick explaining the node
to me, not a triple the record wants.

**Not-found groundings are written, labelled.** A phrase the model quoted that
is not in the document is the single most useful thing on a curation screen,
and the agent's own output already reports it (`[NOT FOUND]`). Suppressing it
would hide exactly the case the mechanism exists to catch.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rdflib import BNode, Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDFS, XSD

from ..concepts.matcher import score
from .documents import verify_phrase

__all__ = ["Neighbour", "neighbours", "attach_grounding", "THE",
           "NEIGHBOUR_THRESHOLD", "NEIGHBOUR_CAP", "VERIFIED", "NOT_FOUND"]

THE = Namespace("http://visualartsdna.org/thesaurus/")

VERIFIED = "ground verified"
NOT_FOUND = "ground not found"

#: How near is worth showing. **Measured, not chosen** (2026-09-29, against the
#: 1,432 labelled thesaurus subjects in the QA store): at the Groovy's 0.45 the
#: median concept has 100 neighbours, at 0.55 it has 17, at 0.70 it has 2 and
#: often none. The scales differ — `rapidfuzz.ratio` is not `similarity x 0.8`
#: — so the Groovy's number could not simply be carried over, and a stored list
#: of a hundred near-misses per concept is not a UI.
#:
#: Dedup keeps its own, higher threshold (CE_DESIGN §6, 0.9): "is this the same
#: concept" and "what is this near" are different questions, and one scoring
#: function answering both at two thresholds is what keeps the numbers a
#: curator reads comparable with the number the dedup decision was made on.
NEIGHBOUR_THRESHOLD = 0.70
NEIGHBOUR_CAP = 5


@dataclass(frozen=True)
class Neighbour:
    """An existing concept the proposed one sits near."""

    uri: str
    label: str
    distance: float
    #: Which branch produced the score, kept because Rick asked for it (round
    #: 3) and because it is the distinction the curator is being asked to
    #: make: "these two strings are nearly identical" is not "these two share
    #: most of their words".
    match_type: str = "fuzzy"


@dataclass
class Grounding:
    """One concept's evidence, ready to be written on either end."""

    phrase: str
    verified: bool
    concept_uri: str = ""
    src_entity: str = ""
    neighbours: list = field(default_factory=list)

    @property
    def label(self) -> str:
        return VERIFIED if self.verified else NOT_FOUND


def _match_type(a: str, b: str) -> str:
    """Name the branch, the way `LoadConceptMatch.groovy` tiered them."""
    from ..concepts.matcher import normalize

    na, nb = normalize(a), normalize(b)
    if a.strip() == b.strip():
        return "exact"
    if na == nb:
        return "normalized"
    if set(na.split()) == set(nb.split()):
        return "token"
    return "fuzzy"


def neighbours(label: str, thesaurus: dict, *,
               threshold: float = NEIGHBOUR_THRESHOLD,
               cap: int = NEIGHBOUR_CAP) -> list:
    """The nearest existing concepts to a proposed label.

    ``thesaurus`` is ``{uri: {labels}}`` — the CE_DESIGN §6 label set,
    `prefLabel ∪ altLabel ∪ rdfs:label`, **on both sides**. The Groovy compared
    its source against all three and its candidates against `rdfs:label` only,
    so a concept named in a `skos:altLabel` could never be matched against.
    Symmetry finds matches it never could, which is the point: against the real
    store, "Faceted surface" scores 1.000 against `the:LowPolySurface` through
    an altLabel, and the Groovy would have called it unique.
    """
    scored = []
    for uri, names in (thesaurus or {}).items():
        best, best_name = 0.0, ""
        for name in names:
            s = score(label, name)
            if s > best:
                best, best_name = s, name
        if best >= threshold:
            scored.append(Neighbour(uri=str(uri), label=best_name, distance=round(best, 4),
                                    match_type=_match_type(label, best_name)))
    scored.sort(key=lambda n: (-n.distance, n.uri))
    return scored[:cap]


def ground(phrase: str, document: str, *, concept_uri: str = "",
           src_entity: str = "", thesaurus: dict | None = None,
           label: str = "") -> Grounding:
    """Verify a phrase against the source and find the neighbourhood.

    Both halves are the dashboard's work, not the agent's (§9.6): one is a
    string check over a document the dashboard already holds, the other is the
    single shared matcher.
    """
    checked = verify_phrase(document, phrase)
    near = neighbours(label, thesaurus) if (thesaurus and label) else []
    return Grounding(phrase=str(phrase), verified=checked.verified,
                     concept_uri=str(concept_uri), src_entity=str(src_entity),
                     neighbours=near)


def attach_grounding(g: Graph, subject, grounding: Grounding) -> BNode:
    """Write one grounding node under ``subject``.

    Which end is named follows from what the node hangs from: a node on the
    concept names the source entity, a node on the entity names the concept.
    Stating both would put the same fact in two places, which is the
    denormalisation the status label is already allowed as an exception.

    ``subject`` may be a BLANK NODE — entity-side groundings hang under
    `ops:status` (2026-10-02). It is taken as-is when it is already an rdflib
    term, because `URIRef(str(bnode))` does not fail: it mints a URIRef from
    the blank node's internal id, so the triple is written, parses, serializes,
    and attaches the evidence to a subject that exists nowhere else in the
    graph.
    """
    subj = subject if isinstance(subject, (URIRef, BNode)) else URIRef(str(subject))
    node = BNode()
    g.add((subj, THE.grounding, node))
    g.add((node, RDFS.label, Literal(grounding.label)))
    g.add((node, THE.phrase, Literal(grounding.phrase)))

    if grounding.src_entity and str(subj) != str(grounding.src_entity):
        g.add((node, THE.srcEntity, URIRef(str(grounding.src_entity))))
    if grounding.concept_uri and str(subj) != str(grounding.concept_uri):
        g.add((node, THE.concept, URIRef(str(grounding.concept_uri))))

    # `the:unique` is the EMPTY case said out loud, exactly as the Groovy
    # printed "X is unique". An absent predicate would be indistinguishable
    # from a match list nobody computed.
    if not grounding.neighbours:
        if grounding.src_entity:  # derivation only — tagging asks no such question
            g.add((node, THE.match, THE.unique))
        return node
    for near in grounding.neighbours:
        m = BNode()
        g.add((node, THE.match, m))
        g.add((m, THE.concept, URIRef(near.uri)))
        g.add((m, THE.distance, Literal(near.distance, datatype=XSD.float)))
        g.add((m, THE.matchType, Literal(near.match_type)))
    return node
