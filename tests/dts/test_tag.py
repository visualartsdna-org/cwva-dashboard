"""Stage 2 — tagging, where the agent proposes concepts and the ontology
decides the property.

The division is decision D: an agent that proposed `vad:hasProcess
the:FacetedSurface` directly would be asserting an answer TCAP derives, and
the two could disagree silently. So this stage returns concept URIs and the
phrases they were read from, and nothing about placement.
"""

from __future__ import annotations

import json

import pytest

from cwva_dashboard.dts.tag import Tag, assess_tags, parse_tags

DOC = ("The figures read as one mass from several angles; the critic notes "
       "merged silhouettes and faint tension cables throughout the orbit.")
THE = "http://visualartsdna.org/thesaurus/"
KNOWN = {THE + "SilhouetteMerging", THE + "TensionCables"}


def _reply(*items):
    return json.dumps(list(items))


# -- parsing -----------------------------------------------------------------


def test_a_tag_array_parses_into_typed_tags():
    tags = parse_tags(_reply(
        {"uri": THE + "TensionCables", "label": "Tension cables",
         "confidence": "high", "groundingPhrase": "faint tension cables"}))

    assert len(tags) == 1
    assert tags[0].uri.endswith("TensionCables")
    assert tags[0].confidence == "high"


def test_a_CODE_FENCE_is_stripped():
    """Models still occasionally wrap JSON in a fence despite being asked not
    to, and the agent stripped them for the same reason."""
    fenced = "```json\n" + _reply({"uri": THE + "X", "label": "X"}) + "\n```"

    assert len(parse_tags(fenced)) == 1


def test_a_tag_with_NO_URI_is_not_a_tag():
    assert parse_tags(_reply({"label": "Nameless"})) == []


def test_a_reply_that_is_not_an_ARRAY_is_refused():
    """Law 8 wants structure asserted. A stage that silently accepted a string
    would report zero tags rather than a broken reply."""
    with pytest.raises(ValueError) as exc:
        parse_tags('{"uri": "x"}')

    assert "array" in str(exc.value)


# -- the two checks the dashboard makes --------------------------------------


def test_a_concept_the_store_does_not_have_is_UNKNOWN():
    """Tagging chooses from what exists. A concept nobody has is a reference
    to nothing that the gate would have to catch."""
    tags = assess_tags(parse_tags(_reply(
        {"uri": THE + "Invented", "label": "Invented",
         "groundingPhrase": "merged silhouettes"})),
        document=DOC, known_uris=KNOWN)

    assert tags[0].status == "unknown"
    assert not tags[0].include_by_default, "and it cannot be ticked"


def test_a_phrase_that_is_not_in_the_document_is_UNGROUNDED():
    tags = assess_tags(parse_tags(_reply(
        {"uri": THE + "TensionCables", "label": "Tension cables",
         "groundingPhrase": "words the critic never wrote"})),
        document=DOC, known_uris=KNOWN)

    assert tags[0].status == "ungrounded"
    assert tags[0].include_by_default, "but a curator may still judge it"


def test_a_grounded_known_concept_is_PROPOSED():
    tags = assess_tags(parse_tags(_reply(
        {"uri": THE + "SilhouetteMerging", "label": "Silhouette merging",
         "groundingPhrase": "merged silhouettes"})),
        document=DOC, known_uris=KNOWN)

    assert tags[0].status == "proposed" and tags[0].grounded


def test_quoting_NOTHING_is_ungrounded_too():
    tags = assess_tags([Tag(uri=THE + "TensionCables", label="T")],
                       document=DOC, known_uris=KNOWN)

    assert tags[0].status == "ungrounded"
    assert "quoted nothing" in " ".join(tags[0].notes)


def test_the_counts_name_every_class():
    tags = assess_tags(parse_tags(_reply(
        {"uri": THE + "SilhouetteMerging", "groundingPhrase": "merged silhouettes"},
        {"uri": THE + "TensionCables", "groundingPhrase": "never written"},
        {"uri": THE + "Invented", "groundingPhrase": "merged silhouettes"})),
        document=DOC, known_uris=KNOWN)
    from cwva_dashboard.dts.tag import TaggingResult

    counts = TaggingResult(entity="e", document="d", tags=tags).counts()

    assert counts == {"proposed": 1, "derived_here": 0, "ungrounded": 1,
                      "unknown": 1, "user_sourced": 0}


# -- a concept derived from THIS document does not compete for a slot --------


DERIVED_STORE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

the:LoadPath a skos:Concept ;
    rdfs:label "Load path" ;
    the:grounding [ rdfs:label "ground verified" ;
                    the:phrase "merged silhouettes" ;
                    the:srcEntity work:e1 ] .
the:FromElsewhere a skos:Concept ;
    rdfs:label "From elsewhere" ;
    the:grounding [ rdfs:label "ground verified" ;
                    the:phrase "something else" ;
                    the:srcEntity work:e2 ] .
"""

E1 = "http://visualartsdna.org/work/e1"


def _store():
    from rdflib import Graph

    return Graph().parse(data=DERIVED_STORE, format="turtle")


def test_the_concepts_THIS_document_produced_are_found():
    """From the data: a derived concept's grounding names its source entity,
    so the store itself says which document produced it."""
    from cwva_dashboard.dts.tag import derived_here

    found = derived_here(_store(), E1)

    assert [t.label for t in found] == ["Load path"]
    assert found[0].grounding_phrase == "merged silhouettes"
    assert found[0].derived_here


def test_a_concept_from_ANOTHER_document_is_not_auto_tagged():
    from cwva_dashboard.dts.tag import derived_here

    assert derived_here(_store(), "http://visualartsdna.org/work/e9") == []


def test_a_derived_concept_is_TICKED_by_default():
    """It is discussed in the document by construction — that is what
    derivation means. Under a tag limit the model ranked four of them against
    250 pre-existing terms and dropped all four."""
    from cwva_dashboard.dts.tag import assess_tags, derived_here

    tags = assess_tags(derived_here(_store(), E1), document=DOC,
                       known_uris={THE + "LoadPath"})

    assert tags[0].status == "derived_here"
    assert tags[0].include_by_default


def test_it_carries_its_DERIVATION_grounding_forward():
    """The tag is evidenced by the same words the concept was."""
    from cwva_dashboard.dts.tag import assess_tags, derived_here

    tags = assess_tags(derived_here(_store(), E1), document=DOC,
                       known_uris={THE + "LoadPath"})

    assert tags[0].grounded, "the phrase is in the document"
