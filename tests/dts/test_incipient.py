"""Queue 0: the entity a criticism document implies.

Rick, 2026-10-01: "since you know how to create that entity for an AI Criticism
document, add an option to generate the incipient entity. From the markdown you
can differentiate Digital Sculpture vs Watercolor."

Everything here is derived from data the dashboard already holds — no model
call — and everything it cannot work out is left for the editor rather than
invented.
"""

from __future__ import annotations

from rdflib import Graph

from cwva_dashboard.dts.incipient import (
    CRITICISM_TOPIC,
    WORK_MATCH_THRESHOLD,
    detect_material,
    detect_source,
    match_work,
    propose_entity,
)

P = {"the": "http://visualartsdna.org/thesaurus/"}

#: Two materials with a discriminating term each, plus one shared term that
#: must vote for neither.
STORE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .

the:digitalArtTerms a skos:ConceptScheme .
the:watercolorPainting a skos:ConceptScheme .

the:Tensegrity a skos:Concept ; rdfs:label "Tensegrity" ;
    skos:inScheme the:digitalArtTerms .
the:LowPoly a skos:Concept ; rdfs:label "Low poly surface" ;
    skos:inScheme the:digitalArtTerms .
the:ColdPress a skos:Concept ; rdfs:label "Cold pressed paper" ;
    skos:inScheme the:watercolorPainting .
the:Composition a skos:Concept ; rdfs:label "Composition" ;
    skos:inScheme the:digitalArtTerms, the:watercolorPainting .
"""

TABLE = {
    "schemes_by_topic": {
        "the:Digital": {"context": ["the:digitalArtTerms"]},
        "the:Watercolor": {"context": ["the:watercolorPainting"]},
    },
}

CHATGPT = """# Art criticism sculpture

## Prompt:

Write an art criticism of this digital sculpture viewed in modelviewer.

## Response:

## Art Criticism - *Prestress: The Three Graces*

The tensegrity reads as one mass. Composition holds throughout.
"""

CLAUDE_WATERCOLOR = """# A painting review

## User:

Provide an art criticism of this watercolor, 15x11 on cold pressed paper.

## Assistant:

The cold pressed paper carries the wash. Composition holds throughout.
"""

WORKS = {"http://visualartsdna.org/work/d52": "Prestress Three Graces",
         "http://visualartsdna.org/work/abc": "Thistle"}


def _g():
    return Graph().parse(data=STORE, format="turtle")


# -- which assistant wrote it ------------------------------------------------


def test_the_EXPORT_HEADINGS_say_which_assistant():
    """More reliable than the filename: a file can be renamed, and the drop
    folder's names are the user's own."""
    assert detect_source(CHATGPT) == "chatGpt"
    assert detect_source(CLAUDE_WATERCOLOR) == "claude"


def test_the_FILENAME_is_the_fallback():
    assert detect_source("# no turns here", "ChatGPT-something.md") == "chatGpt"


def test_an_unrecognisable_export_names_nobody():
    assert detect_source("# nothing", "notes.md") == ""


# -- which material ----------------------------------------------------------


def test_the_ARTISTS_OWN_WORDS_decide_the_material():
    """They say what the work is when they ask for the criticism, and that
    beats any amount of counting."""
    topic, evidence = detect_material(CHATGPT, _g(), TABLE, P)

    assert topic == "the:Digital"
    assert evidence[0][0] == "the artist's own words"


def test_it_tells_WATERCOLOR_from_digital_sculpture():
    topic, _evidence = detect_material(CLAUDE_WATERCOLOR, _g(), TABLE, P)

    assert topic == "the:Watercolor"


def test_VOCABULARY_is_the_fallback_when_the_prompt_does_not_say():
    silent = ("## Prompt:\n\nReview this.\n\n## Response:\n\n"
              "The tensegrity and the low poly surface read as one mass.\n")

    topic, _evidence = detect_material(silent, _g(), TABLE, P)

    assert topic == "the:Digital"


def test_a_SHARED_term_votes_for_neither():
    """"Composition" is in both schemes, so counting it would make every
    document a tie."""
    neutral = "## Prompt:\n\nReview this.\n\n## Response:\n\nComposition holds.\n"

    topic, evidence = detect_material(neutral, _g(), TABLE, P)

    assert topic == ""
    assert all(hits == 0 for _t, hits, _s in evidence)


def test_a_NECK_AND_NECK_document_is_left_for_a_person():
    """Better to leave the material than to file a criticism under one on a
    coincidence."""
    both = ("## Prompt:\n\nReview this.\n\n## Response:\n\n"
            "The tensegrity meets the cold pressed paper.\n")

    topic, _evidence = detect_material(both, _g(), TABLE, P)

    assert topic == ""


# -- which work --------------------------------------------------------------


def test_a_work_named_in_a_HEADING_is_matched():
    """A criticism names its subject in a heading; the document's own title is
    often generic ("Art criticism sculpture") and the prompt says "this digital
    sculpture" without naming it."""
    uri, label, sc = match_work(CHATGPT, WORKS)

    assert label == "Prestress Three Graces"
    assert uri.endswith("d52") and sc >= WORK_MATCH_THRESHOLD


def test_a_document_naming_NO_work_names_nothing():
    """The nearest label was `Thistle` at 0.73 on a real document — the matcher
    sits near 0.59 for unrelated strings, so a sub-threshold best is noise
    wearing a number, and offering it invites a reviewer to accept it."""
    uri, label, sc = match_work(CLAUDE_WATERCOLOR, WORKS)

    assert uri == "" and label == ""
    assert sc < WORK_MATCH_THRESHOLD


# -- the proposal ------------------------------------------------------------


def test_the_topics_follow_the_STORES_OWN_pattern():
    """A watercolour criticism carries [Criticism, Watercolor]; a digital
    sculpture carries [Criticism, Digital, Sculpture] — read off the 60 real
    records, not invented."""
    digital = propose_entity(document="d.md", text=CHATGPT, graph=_g(),
                             works=WORKS, table=TABLE, prefixes=P)
    water = propose_entity(document="w.md", text=CLAUDE_WATERCOLOR, graph=_g(),
                           works=WORKS, table=TABLE, prefixes=P)

    assert digital.topics == [CRITICISM_TOPIC, "the:Digital", "the:Sculpture"]
    assert water.topics == [CRITICISM_TOPIC, "the:Watercolor"]


def test_the_label_names_the_WORK_and_the_SOURCE():
    out = propose_entity(document="d.md", text=CHATGPT, graph=_g(), works=WORKS,
                         table=TABLE, prefixes=P)

    assert out.label == "Prestress Three Graces Criticism chatGpt"


def test_the_label_falls_back_to_the_TITLE_when_no_work_matched():
    """A label naming the wrong work is worse than one naming none."""
    out = propose_entity(document="w.md", text=CLAUDE_WATERCOLOR, graph=_g(),
                         works=WORKS, table=TABLE, prefixes=P)

    assert "Thistle" not in out.label
    assert out.label.endswith("claude")


def test_the_definition_is_the_first_human_turn():
    out = propose_entity(document="d.md", text=CHATGPT, graph=_g(), works=WORKS,
                         table=TABLE, prefixes=P)

    assert out.definition.startswith("Write an art criticism")


def test_a_document_with_NO_human_turn_is_NOT_ready():
    """It cannot describe itself, and an entity with an empty definition is
    worse than none."""
    out = propose_entity(document="x.md", text="# Just prose.\n\nNo turns.",
                         graph=_g(), works=WORKS, table=TABLE, prefixes=P)

    assert not out.ready
    assert any("no human turn" in " ".join(s) for _k, _n, s in out.evidence)


def test_every_guess_carries_its_EVIDENCE():
    """A proposal nobody can account for is one nobody can correct with
    confidence."""
    out = propose_entity(document="d.md", text=CHATGPT, graph=_g(), works=WORKS,
                         table=TABLE, prefixes=P)
    kinds = {kind for kind, _n, _s in out.evidence}

    assert {"source", "work"} <= kinds
    assert any("artist" in k for k in kinds)
