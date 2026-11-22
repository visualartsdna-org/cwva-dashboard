"""Which concepts the model is shown, and which scheme a new one joins.

Both are questions the concept agent answered with one hardcoded table in
which every category resolved to a watercolor scheme. The store is
bi-material and these two criticisms are of a tensegrity sculpture, so that
table would have shown the model the wrong neighbourhood and filed the
results in the wrong place.
"""

from __future__ import annotations

from rdflib import Graph

from cwva_dashboard.dts.thesaurus import (
    format_for_prompt,
    read_label_index,
    read_scoped,
    resolve_broader,
    scheme_for_concept,
    schemes_for,
)

P = {"the": "http://visualartsdna.org/thesaurus/"}

STORE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .

the:tensegrityTerms a skos:ConceptScheme ; rdfs:label "Tensegrity Terms" .
the:digitalArtTerms a skos:ConceptScheme ; rdfs:label "Digital Art Terms" .

the:StructuralAndAnalyticalTerms a skos:Concept ;
    rdfs:label "Structural and Analytical Terms" ;
    skos:inScheme the:tensegrityTerms .
the:IconographicProgram a skos:Concept ;
    rdfs:label "Iconographic program" ;
    skos:inScheme the:digitalArtTerms .
the:Buckling a skos:Concept ;
    rdfs:label "Buckling" ;
    skos:altLabel "Elastic instability" ;
    skos:broader the:StructuralAndAnalyticalTerms ;
    skos:inScheme the:tensegrityTerms .
the:Unplaced a skos:Concept ; rdfs:label "Unplaced parent" .
"""

TABLE = {
    "schemes_by_topic": {
        "the:Digital": {"context": ["the:tensegrityTerms", "the:digitalArtTerms"],
                        "formal": "the:digitalArtTerms",
                        "production": "the:tensegrityTerms"},
    },
    "default": {"context": ["the:visualArtTerms"], "formal": "the:visualArtTerms"},
}


def _g():
    return Graph().parse(data=STORE, format="turtle")


# -- which schemes the material lives in -------------------------------------


def test_the_TOPIC_picks_the_schemes():
    """Derived from the record. A flag would be a second place for the same
    fact to be wrong."""
    chosen = schemes_for(["the:Criticism", "the:Digital"], TABLE, prefixes=P)

    assert chosen["topic"] == "the:Digital"
    assert "the:tensegrityTerms" in chosen["context"]


def test_an_UNKNOWN_topic_falls_back_to_the_general_scheme():
    """Deliberately not one of the material schemes: a concept filed under the
    wrong material is harder to find than one filed under none."""
    chosen = schemes_for(["the:Watercolour"], TABLE, prefixes=P)

    assert chosen["topic"] == "" and chosen["formal"] == "the:visualArtTerms"


def test_the_context_list_is_what_the_model_is_SHOWN():
    scoped = read_scoped(_g(), ["the:tensegrityTerms"], prefixes=P)

    assert [c.label for c in scoped] == ["Buckling", "Structural and Analytical Terms"]
    assert "Elastic instability" in format_for_prompt(scoped)
    assert "Broader: Structural and Analytical Terms" in format_for_prompt(scoped)


def test_DEDUP_is_not_scoped_by_scheme():
    """"Do we already have this concept" is not a question about schemes, so
    the index covers every labelled concept including unplaced ones."""
    index = read_label_index(_g())

    assert "http://visualartsdna.org/thesaurus/Unplaced" in index
    assert index["http://visualartsdna.org/thesaurus/Buckling"] == {
        "Buckling", "Elastic instability"}


# -- which scheme a NEW concept joins ----------------------------------------


def test_a_new_concept_INHERITS_its_broader_terms_scheme():
    """78% of the real store already does this, and it is what puts "Load
    path" in `tensegrityTerms` while "Golden apple motif" goes to
    `digitalArtTerms` — a per-category table files both in one."""
    scheme, how = scheme_for_concept(
        _g(), broader_label="Structural and Analytical Terms",
        fallback="the:digitalArtTerms", prefixes=P)

    assert scheme.endswith("tensegrityTerms")
    assert "inherited" in how


def test_a_broader_term_given_by_URI_works_too():
    scheme, _how = scheme_for_concept(
        _g(), broader_uri="http://visualartsdna.org/thesaurus/IconographicProgram",
        fallback="the:tensegrityTerms", prefixes=P)

    assert scheme.endswith("digitalArtTerms")


def test_a_broader_term_with_NO_scheme_falls_back_to_the_table():
    scheme, how = scheme_for_concept(_g(), broader_label="Unplaced parent",
                                     fallback="the:digitalArtTerms", prefixes=P)

    assert scheme.endswith("digitalArtTerms") and "table" in how


def test_an_ORPHAN_falls_back_too():
    scheme, how = scheme_for_concept(_g(), fallback="the:digitalArtTerms", prefixes=P)

    assert scheme.endswith("digitalArtTerms") and "table" in how


def test_the_rule_that_DECIDED_is_reported():
    """A placement nobody can account for is one nobody will trust."""
    _s, how = scheme_for_concept(_g(), broader_label="Iconographic program",
                                 fallback="the:tensegrityTerms", prefixes=P)

    assert how


def test_an_UNKNOWN_broader_label_does_not_resolve():
    assert resolve_broader(_g(), label="A term nobody has") == ""
