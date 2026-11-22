"""The grounding node — one shape, reconciled from the plan's two sketches.

The plan sketches it twice, on a derived concept and on a tagged entity, and
the sketches disagree about which end is named. The rule here is that a
grounding relates three things, two of them named explicitly and the third
being whatever the node hangs from.
"""

from __future__ import annotations

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS, XSD

from cwva_dashboard.dts.grounding import (
    NEIGHBOUR_CAP,
    NEIGHBOUR_THRESHOLD,
    NOT_FOUND,
    THE,
    VERIFIED,
    attach_grounding,
    ground,
    neighbours,
)

DOC = "The critic notes faint tension cables and merged silhouettes throughout."
ENTITY = "http://visualartsdna.org/work/e1"
CONCEPT = "http://visualartsdna.org/thesaurus/TensionCable"

THESAURUS = {
    "http://visualartsdna.org/thesaurus/TensionCables": {"Tension cables"},
    "http://visualartsdna.org/thesaurus/StructuralOrganization": {"Structural organization"},
    # A concept whose PREF label is unrelated and whose ALT label is the hit.
    "http://visualartsdna.org/thesaurus/LowPolySurface": {"Low poly surface",
                                                          "Faceted surface"},
    "http://visualartsdna.org/thesaurus/Verisimilitude": {"Verisimilitude"},
}


def _node(g, subject):
    return g.value(URIRef(subject), THE.grounding)


# -- which end is named ------------------------------------------------------


def test_on_a_CONCEPT_the_node_names_the_SOURCE_ENTITY():
    g = Graph()
    attach_grounding(g, CONCEPT, ground("faint tension cables", DOC,
                                        src_entity=ENTITY))
    node = _node(g, CONCEPT)

    assert str(g.value(node, THE.srcEntity)) == ENTITY
    assert g.value(node, THE.concept) is None, "the subject IS the concept"


def test_on_an_ENTITY_the_node_names_the_CONCEPT():
    g = Graph()
    attach_grounding(g, ENTITY, ground("merged silhouettes", DOC,
                                       concept_uri=CONCEPT))
    node = _node(g, ENTITY)

    assert str(g.value(node, THE.concept)) == CONCEPT
    assert g.value(node, THE.srcEntity) is None, "the subject IS the source"


def test_nothing_is_stated_TWICE():
    """A node that named both ends would put the same fact in two places, on
    whichever end it hangs from."""
    g = Graph()
    attach_grounding(g, CONCEPT, ground("faint tension cables", DOC,
                                        concept_uri=CONCEPT, src_entity=ENTITY))

    assert g.value(_node(g, CONCEPT), THE.concept) is None


# -- verified, and not -------------------------------------------------------


def test_a_verified_phrase_is_LABELLED_verified():
    g = Graph()
    attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC, src_entity=ENTITY))

    assert str(g.value(_node(g, CONCEPT), RDFS.label)) == VERIFIED


def test_a_NOT_FOUND_grounding_is_WRITTEN_not_suppressed():
    """The most useful thing on a curation screen: the model quoted something
    that is not in the document."""
    g = Graph()
    attach_grounding(g, CONCEPT, ground("words never written", DOC, src_entity=ENTITY))
    node = _node(g, CONCEPT)

    assert str(g.value(node, RDFS.label)) == NOT_FOUND
    assert str(g.value(node, THE.phrase)) == "words never written"


def test_the_CONTEXT_is_not_stored():
    """Storing the surrounding sentences copies the document into every
    concept and lets the copy drift. The phrase is stored; the context is
    recovered from the source on demand."""
    g = Graph()
    attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC, src_entity=ENTITY))

    assert "throughout" not in g.serialize(format="turtle")


# -- the neighbourhood -------------------------------------------------------


def test_nothing_near_is_said_OUT_LOUD_as_unique():
    """An absent predicate is indistinguishable from a match list nobody
    computed. The Groovy printed "X is unique" for the same reason."""
    g = Graph()
    attach_grounding(g, CONCEPT, ground("merged silhouettes", DOC, src_entity=ENTITY,
                                        thesaurus=THESAURUS, label="Orbit camera"))

    assert g.value(_node(g, CONCEPT), THE.match) == THE.unique


def test_a_near_concept_carries_distance_AND_TYPE():
    """Rick, round 3. "Nearly identical strings" is not "shares most of its
    words", and that is precisely the distinction a curator is asked to make."""
    g = Graph()
    attach_grounding(g, CONCEPT, ground("faint tension cables", DOC, src_entity=ENTITY,
                                        thesaurus=THESAURUS, label="Tension cable"))
    match = g.value(_node(g, CONCEPT), THE.match)

    assert str(g.value(match, THE.concept)).endswith("TensionCables")
    assert g.value(match, THE.distance).datatype == XSD.float
    assert str(g.value(match, THE.matchType)) in {"exact", "normalized", "token", "fuzzy"}


def test_the_label_set_is_SYMMETRIC_so_an_altLabel_can_match():
    """CE_DESIGN §6. The Groovy compared its source against three label
    properties and its candidates against `rdfs:label` only, so a concept
    named in an altLabel could never be matched against."""
    found = neighbours("Faceted surface", THESAURUS)

    assert [n.uri for n in found] == ["http://visualartsdna.org/thesaurus/LowPolySurface"]
    assert found[0].distance == 1.0


def test_the_list_is_CAPPED_and_ordered_by_distance():
    """The node is stored data, and forty near-misses per concept is not a UI."""
    many = {f"http://visualartsdna.org/thesaurus/C{i}": {f"Tension cable {i}"}
            for i in range(20)}

    found = neighbours("Tension cable", many)

    assert len(found) == NEIGHBOUR_CAP
    assert [n.distance for n in found] == sorted((n.distance for n in found), reverse=True)


def test_the_threshold_is_LOWER_than_dedup_deliberately():
    """Two different questions: "is this the same concept" (0.9) and "what is
    this near". One scoring function at two thresholds keeps the numbers a
    curator reads comparable with the number dedup decided on."""
    from cwva_dashboard.concepts.matcher import DEFAULT_THRESHOLD

    assert NEIGHBOUR_THRESHOLD < DEFAULT_THRESHOLD


def test_tagging_asks_NO_neighbourhood_question():
    """A tagging pass chooses from concepts that already exist, so "what else
    is this near" does not arise — and an absent `the:match` there is not an
    omission."""
    g = Graph()
    attach_grounding(g, ENTITY, ground("merged silhouettes", DOC, concept_uri=CONCEPT))

    assert g.value(_node(g, ENTITY), THE.match) is None


def test_a_BLANK_NODE_subject_is_taken_as_is():
    """`URIRef(str(bnode))` does not fail — it mints a URIRef from the blank
    node's internal id, so the grounding is written, parses, serializes, and
    attaches to a subject that exists nowhere else in the graph. It cost the
    whole first run of the move under `ops:status` (2026-10-02)."""
    from rdflib import BNode, Graph

    from cwva_dashboard.dts.grounding import Grounding, attach_grounding

    g = Graph()
    parent = BNode()

    attach_grounding(g, parent, Grounding(phrase="some words", verified=True))

    assert (parent, THE.grounding, None) in g, "attached to the blank node itself"
    assert not any(str(s).startswith("n") and len(str(s)) > 30
                   for s in g.subjects() if isinstance(s, URIRef)), \
        "no URIRef minted from a blank node id"
