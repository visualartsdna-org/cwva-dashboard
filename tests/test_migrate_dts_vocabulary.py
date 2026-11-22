"""The DTS vocabulary migration: status to `ops:`, grounding declared in `the:`.

An operator script, so what is tested is the part that decides — which terms
move and which do not, that the two ontology blocks are Turtle, and that a
re-run changes nothing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, OWL

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate_dts_vocabulary import (  # noqa: E402
    GROUNDING_SECTION,
    MOVED,
    STAYS,
    STATUS_SECTION,
    add_grounding,
    add_status,
    rewrite,
    target_iri,
)

THE = "http://visualartsdna.org/thesaurus/"
OPS = "http://visualartsdna.org/operations/"


# -- which terms move --------------------------------------------------------


def test_the_STATUS_terms_move_to_ops():
    for term in ("status", "at", "derived", "derivationCurated", "tagged",
                 "taggingCurated", "summarized", "summaryCurated"):
        assert str(target_iri(THE + term)) == OPS + term


def test_the_GROUNDING_terms_do_NOT_move():
    """Rick, 2026-10-01: "I definitely want to keep grounding terms in the:".
    A grounding is about a concept, so it is thesaurus vocabulary that was
    undeclared rather than misplaced."""
    for term in STAYS:
        assert str(target_iri(THE + term)) == THE + term


def test_the_two_sets_are_DISJOINT():
    """One term in both lists would be moved and declared in two namespaces,
    and the second declaration would look authoritative."""
    assert not (set(MOVED) & set(STAYS))


def test_a_CONTENT_predicate_is_left_alone():
    """`the:summary` and `the:tag` are what the record SAYS; only the machinery
    moves. Sweeping the whole namespace would have taken them too."""
    for term in ("summary", "tag", "topic", "mdDocument", "conceptsExtracted"):
        assert str(target_iri(THE + term)) == THE + term


# -- the rewrite -------------------------------------------------------------


RECORD = f"""@prefix ops: <{OPS}> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <{THE}> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

work:e1 a the:AI ;
    the:summary "kept verbatim" ;
    the:tag the:Tensegrity ;
    the:status [ rdfs:label "derived" ;
        the:derived [ the:at "2026-10-01T10:00:00+00:00"^^xsd:dateTime ;
                      prov:wasAttributedTo ops:claude-opus-5-5 ] ] ;
    the:grounding [ rdfs:label "ground verified" ;
        the:concept the:Tensegrity ;
        the:phrase "metaphor and mechanics coincide" ;
        the:match the:unique ] .
"""


def _g():
    return Graph().parse(data=RECORD, format="turtle")


def test_the_status_node_and_its_stamps_are_rewritten():
    g = _g()

    rewrite(g)

    assert (None, URIRef(OPS + "status"), None) in g
    assert (None, URIRef(THE + "status"), None) not in g
    assert (None, URIRef(OPS + "derived"), None) in g
    assert (None, URIRef(OPS + "at"), None) in g


def test_the_GROUNDING_survives_the_rewrite_untouched():
    """The whole point of the split: one pass moves the stamps and leaves the
    evidence where it is."""
    g = _g()

    rewrite(g)

    assert (None, URIRef(THE + "grounding"), None) in g
    assert (None, URIRef(THE + "phrase"), None) in g
    assert (None, URIRef(THE + "concept"), None) in g
    assert (None, URIRef(THE + "match"), URIRef(THE + "unique")) in g


def test_the_OBJECT_the_unique_is_not_mistaken_for_a_status_term():
    """`the:unique` is the only grounding term that appears in OBJECT position,
    and `the:at` would match it under a careless prefix test."""
    g = _g()

    rewrite(g)

    assert (None, None, URIRef(OPS + "unique")) not in g


def test_content_predicates_are_UNCHANGED():
    g = _g()

    rewrite(g)

    assert any(str(o) == "kept verbatim" for o in g.objects())
    assert (None, URIRef(THE + "tag"), None) in g


def test_the_triple_COUNT_does_not_change():
    """A rewrite, not an edit."""
    g = _g()
    before = len(g)

    rewrite(g)

    assert len(g) == before


def test_rewriting_TWICE_changes_nothing_the_second_time():
    g = _g()
    rewrite(g)
    snapshot = Graph().parse(data=g.serialize(format="turtle"), format="turtle")

    assert rewrite(g) == 0
    assert isomorphic(g, snapshot)


def test_a_record_with_no_status_is_UNTOUCHED():
    plain = Graph().parse(data=f'<http://x/a> <{THE}summary> "v" .',
                          format="turtle")

    assert rewrite(plain) == 0


# -- the operations section --------------------------------------------------


OPERATIONS = f"""@prefix ops:    <{OPS}> .
@prefix owl:    <http://www.w3.org/2002/07/owl#> .
@prefix prov:   <http://www.w3.org/ns/prov#> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd:    <http://www.w3.org/2001/XMLSchema#> .

ops:Role a owl:Class ; rdfs:label "Role" .
"""


def test_the_status_section_PARSES_onto_a_real_ontology():
    """The section is a paste in a Python string; the one thing that must be
    true of it is that the result is Turtle."""
    g = Graph().parse(data=add_status(OPERATIONS), format="turtle")

    assert (URIRef(OPS + "Status"), RDF.type, OWL.Class) in g
    assert (URIRef(OPS + "Stamp"), RDF.type, OWL.Class) in g


def test_every_MOVED_term_is_DECLARED():
    """The defect this migration exists to fix was eight terms in use with
    nothing defining them. Shipping the move without the declarations would
    reproduce it one namespace over."""
    g = Graph().parse(data=add_status(OPERATIONS), format="turtle")

    for term in MOVED:
        assert (URIRef(OPS + term), RDF.type, None) in g, f"ops:{term} undeclared"
        assert (URIRef(OPS + term), RDFS.comment, None) in g, f"ops:{term} unexplained"


def test_a_stamp_is_reachable_from_a_status_by_DOMAIN_and_RANGE():
    g = Graph().parse(data=add_status(OPERATIONS), format="turtle")
    stage = URIRef(OPS + "derived")

    assert (stage, RDFS.domain, URIRef(OPS + "Status")) in g
    assert (stage, RDFS.range, URIRef(OPS + "Stamp")) in g


def test_ops_status_has_NO_domain():
    """Omitted rather than guessed: any record a workflow touches may carry
    one, and a wrong rdfs:domain is an inference a reasoner will make and
    nothing will flag."""
    g = Graph().parse(data=add_status(OPERATIONS), format="turtle")

    assert (URIRef(OPS + "status"), RDFS.domain, None) not in g
    assert (URIRef(OPS + "status"), RDFS.range, URIRef(OPS + "Status")) in g


def test_adding_the_status_section_TWICE_adds_it_once():
    once = add_status(OPERATIONS)

    assert add_status(once) == once
    assert once.count(STATUS_SECTION) == 1


# -- the grounding section ---------------------------------------------------


ENTITY = f"""@prefix owl:   <http://www.w3.org/2002/07/owl#> .
@prefix rdf:   <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs:  <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos:  <http://www.w3.org/2004/02/skos/core#> .
@prefix the:   <{THE}> .
@prefix xsd:   <http://www.w3.org/2001/XMLSchema#> .

the:Entity a owl:Class ; rdfs:label "Entity" .
"""


def test_the_grounding_section_PARSES_onto_a_real_ontology():
    g = Graph().parse(data=add_grounding(ENTITY), format="turtle")

    assert (URIRef(THE + "Grounding"), RDF.type, OWL.Class) in g
    assert (URIRef(THE + "Match"), RDF.type, OWL.Class) in g


def test_every_STAYING_term_is_DECLARED_in_the_thesaurus():
    g = Graph().parse(data=add_grounding(ENTITY), format="turtle")

    for term in STAYS:
        assert (URIRef(THE + term), RDF.type, None) in g, f"the:{term} undeclared"
        assert (URIRef(THE + term), RDFS.comment, None) in g, f"the:{term} unexplained"


def test_the_phrase_is_a_DatatypeProperty_on_a_Grounding():
    """The shape Rick asked for: `the:phrase a DatatypeProperty ; domain
    the:Grounding ; range xsd:string`."""
    g = Graph().parse(data=add_grounding(ENTITY), format="turtle")
    phrase = URIRef(THE + "phrase")
    XSD_STRING = URIRef("http://www.w3.org/2001/XMLSchema#string")

    assert (phrase, RDF.type, OWL.DatatypeProperty) in g
    assert (phrase, RDFS.domain, URIRef(THE + "Grounding")) in g
    assert (phrase, RDFS.range, XSD_STRING) in g


def test_the_two_AMBIGUOUS_properties_have_no_domain():
    """`the:grounding` hangs on an entity or on a concept depending on which
    end is already named, and `the:concept` sits on both a grounding and a
    match. Naming one domain for either would have a reasoner conclude the
    other, so both are omitted and the ontology says why."""
    g = Graph().parse(data=add_grounding(ENTITY), format="turtle")

    for term in ("grounding", "concept"):
        assert (URIRef(THE + term), RDFS.domain, None) not in g
        comment = str(g.value(URIRef(THE + term), RDFS.comment))
        assert "No domain" in comment, f"the:{term} omits a domain without saying so"


def test_the_unique_is_an_INSTANCE_so_the_match_range_stays_honest():
    """`the:match` points either at a near-match node or at `the:unique`, so
    the range only holds if the empty case is itself a Match."""
    g = Graph().parse(data=add_grounding(ENTITY), format="turtle")

    assert (URIRef(THE + "unique"), RDF.type, URIRef(THE + "Match")) in g
    assert (URIRef(THE + "match"), RDFS.range, URIRef(THE + "Match")) in g


def test_adding_the_grounding_section_TWICE_adds_it_once():
    once = add_grounding(ENTITY)

    assert add_grounding(once) == once
    assert once.count(GROUNDING_SECTION) == 1


# -- the two halves agree with the code that writes them ---------------------


def test_the_MOVED_set_is_exactly_what_state_py_WRITES():
    """The migration and the writer must not drift: a stage added to STAGES and
    not to MOVED would be written in `ops:` by the code and left in `the:` by a
    re-run of this script, which is a silent half-migration."""
    from cwva_dashboard.dts.state import STAGES

    assert set(MOVED) == {"status", "at"} | set(STAGES)


def test_the_STAYS_set_is_exactly_what_grounding_py_WRITES():
    """Derived from the writer the same way, for the same reason."""
    import inspect

    from cwva_dashboard.dts import grounding as mod

    source = inspect.getsource(mod)
    written = {name for name in STAYS if f"THE.{name}" in source}

    assert written == set(STAYS), f"declared but never written: {set(STAYS) - written}"
