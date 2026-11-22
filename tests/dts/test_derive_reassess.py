"""Re-assessment at curation time: the store moves, the document does not.

Curating a batch moves the store underneath the proposals — Rick curated one
Three Graces criticism, minting `the:ThreeGraces`, and the other document's
proposal for the same concept was still `proposed` from derive time, so the
submit hit the mint-collision guard (2026-10-01).
"""

from __future__ import annotations

from rdflib import Graph

from cwva_dashboard.dts.derive import Proposal, reassess
from cwva_dashboard.dts.tag import Tag, reassess_tags

THE = "http://visualartsdna.org/thesaurus/"

STORE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .

the:ThreeGraces a skos:Concept ; rdfs:label "Three Graces" ; skos:altLabel "Charites" .
the:Parent a skos:Concept ; rdfs:label "Parent term" .
"""


def _index(graph):
    from cwva_dashboard.dts.thesaurus import read_label_index

    return read_label_index(graph)


def _store():
    return Graph().parse(data=STORE, format="turtle")


def _proposal(**kw):
    base = {"label": "Three Graces", "grounding_phrase": "the critic wrote this",
            "grounded": True, "broader_label": "Parent term",
            "source_speaker": "critic", "status": "proposed"}
    return Proposal(**{**base, **kw})


# -- what the store can change -----------------------------------------------


def test_a_concept_minted_SINCE_the_model_answered_becomes_a_duplicate():
    g = _store()
    p = _proposal()

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "duplicate"
    assert p.duplicate_of == THE + "ThreeGraces"
    assert "the store already has" in " ".join(p.notes)


def test_an_ALT_LABEL_collision_counts_too():
    g = _store()
    p = _proposal(label="Charites")

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "duplicate"


def test_a_concept_the_store_does_NOT_have_stays_proposed():
    g = _store()
    p = _proposal(label="Something new")

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "proposed" and not p.duplicate_of


def test_a_STALE_duplicate_finding_is_CLEARED():
    """The store can lose a concept as well as gain one, and a note nobody can
    verify is worse than none."""
    g = _store()
    p = _proposal(label="Something new", status="duplicate",
                  duplicate_of=THE + "Gone", duplicate_label="Gone",
                  notes=["the store already has 'Gone' at 0.95"])

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "proposed"
    assert not p.duplicate_of
    assert not any("store already has" in n for n in p.notes)


def test_an_unresolvable_parent_makes_it_an_ORPHAN():
    g = _store()
    p = _proposal(label="Something new", broader_label="A term nobody has")

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "orphan" and p.orphan


# -- what the DOCUMENT settled, and re-assessment must not touch -------------


def test_an_UNGROUNDED_finding_SURVIVES_reassessment():
    """It was made when the document was readable. Re-deriving it against a
    file that may now be absent would replace a finding with a guess."""
    g = _store()
    p = _proposal(label="Something new", grounded=False, status="ungrounded",
                  notes=["the quoted phrase is not in the document"])

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "ungrounded"
    assert "not in the document" in " ".join(p.notes)


def test_a_USER_SOURCED_finding_SURVIVES_reassessment():
    g = _store()
    p = _proposal(label="Something new", source_speaker="user",
                  status="user_sourced",
                  notes=["grounded in the ARTIST's own words, not the critic's"])

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "user_sourced"


def test_but_a_DUPLICATE_still_wins_over_a_document_finding():
    """A concept the store already has cannot be created whatever else is true
    of it, so that finding has to be the one on the screen."""
    g = _store()
    p = _proposal(status="user_sourced", source_speaker="user")

    reassess([p], label_index=_index(g), thesaurus=g)

    assert p.status == "duplicate"


# -- tags ---------------------------------------------------------------------


def test_a_tag_whose_concept_VANISHED_becomes_unknown():
    t = Tag(uri=THE + "Gone", label="Gone", grounded=True, status="proposed")

    reassess_tags([t], known_uris={THE + "ThreeGraces"})

    assert t.status == "unknown" and not t.known


def test_a_tag_whose_concept_APPEARED_stops_being_unknown():
    """The derivation that created it may have been curated minutes ago."""
    t = Tag(uri=THE + "ThreeGraces", label="Three Graces", status="unknown",
            notes=["no such concept in the store"])

    reassess_tags([t], known_uris={THE + "ThreeGraces"})

    assert t.status == "proposed" and t.known
    assert not any("no such concept" in n for n in t.notes)


def test_a_derived_here_tag_keeps_its_status():
    t = Tag(uri=THE + "ThreeGraces", label="Three Graces", status="unknown",
            derived_here=True, notes=["no such concept in the store"])

    reassess_tags([t], known_uris={THE + "ThreeGraces"})

    assert t.status == "derived_here"
