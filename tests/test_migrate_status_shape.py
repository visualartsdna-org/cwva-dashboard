"""The status-shape migration, and the one case where it removes the old flag.

`the:conceptsExtracted` is the pre-DTS workflow boolean. Rick, 2026-10-02: "I'm
not concerned with its historical use, it can remain in past records" — so the
first cut of this script, which dropped 148 triples from 85 records, went
further than the instruction and was reverted.

What is removed is the combination that contradicts itself: `false` on a record
whose own status node says all six stages completed. The browser renders that as
`derived false` on a finished criticism.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from migrate_status_shape import (  # noqa: E402
    drop_contradicted_flag,
    drop_inline_agents,
    move_grounding,
    relabel_status,
)

from cwva_dashboard.dts.state import STAGES, status_node, write_stamp  # noqa: E402

THE = "http://visualartsdna.org/thesaurus/"
OPS = "http://visualartsdna.org/operations/"
W = "http://visualartsdna.org/work/"
FLAG = URIRef(THE + "conceptsExtracted")
E = URIRef(W + "e1")

BASE = """@prefix ops: <http://visualartsdna.org/operations/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:e1 a the:AI ; rdfs:label "A criticism" .
"""


def _g(flag=None, stamps=()):
    g = Graph().parse(data=BASE, format="turtle")
    if flag is not None:
        g.add((E, FLAG, Literal(flag)))
    for stage in stamps:
        write_stamp(g, E, stage)
    return g


# -- what goes ---------------------------------------------------------------


def test_FALSE_on_a_COMPLETE_run_is_removed():
    """The self-contradiction: the record says concepts were not extracted
    while its own stamps say the whole run finished."""
    g = _g(flag=False, stamps=STAGES)

    assert drop_contradicted_flag(g) == 1
    assert (None, FLAG, None) not in g


# -- what stays --------------------------------------------------------------


def test_TRUE_on_a_complete_run_STAYS():
    """`true` agrees with "extraction happened", and it is the evidence
    `backfill_dts_state.py` read to stamp those 59 records complete. Removing
    it would destroy the reason the stamp is there."""
    g = _g(flag=True, stamps=STAGES)

    assert drop_contradicted_flag(g) == 0
    assert (None, FLAG, None) in g


def test_FALSE_with_NO_run_STAYS():
    """13 real entities, none carrying a single `vad:*` placement — a
    background image, an HDR, two architecture diagrams, a legend. The flag is
    a true statement about them, and it is what the `concepts_extracted_false`
    standing query lists."""
    g = _g(flag=False)

    assert drop_contradicted_flag(g) == 0
    assert (None, FLAG, None) in g


def test_FALSE_on_a_HALF_FINISHED_run_STAYS():
    """Mid-flight is not a contradiction: the run really has not extracted
    anything yet."""
    g = _g(flag=False, stamps=("derived", "derivationCurated"))

    assert drop_contradicted_flag(g) == 0
    assert (None, FLAG, None) in g


def test_a_record_with_NO_flag_is_untouched():
    assert drop_contradicted_flag(_g(stamps=STAGES)) == 0


def test_running_TWICE_removes_it_once():
    g = _g(flag=False, stamps=STAGES)
    drop_contradicted_flag(g)

    assert drop_contradicted_flag(g) == 0


# -- the other three steps ---------------------------------------------------


def test_the_label_becomes_CURATION_COMPLETE():
    g = _g(stamps=STAGES)

    relabel_status(g)

    assert str(g.value(status_node(g, E), RDFS.label)) == "curation complete"


def test_a_HALF_FINISHED_run_is_labelled_by_its_LAST_STAGE():
    g = _g(stamps=("derived", "derivationCurated"))

    relabel_status(g)

    assert str(g.value(status_node(g, E), RDFS.label)) == "derivationCurated"


def test_grounding_moves_under_the_status_node():
    g = _g(stamps=STAGES)
    node = BNode()
    g.add((E, URIRef(THE + "grounding"), node))
    g.add((node, URIRef(THE + "phrase"), Literal("some words")))

    assert move_grounding(g) == 1
    assert (E, URIRef(THE + "grounding"), None) not in g
    assert (status_node(g, E), URIRef(THE + "grounding"), None) in g


def test_grounding_on_a_record_with_NO_status_is_LEFT():
    """There is no run for it to belong to, and inventing a status node to
    hold it would assert that one happened."""
    g = _g()
    g.add((E, URIRef(THE + "grounding"), BNode()))

    assert move_grounding(g) == 0


def test_a_CONCEPT_side_grounding_is_left_alone():
    """Those are about the concept, which is why that vocabulary stayed in
    `the:`. A concept has no status node, so the rule skips it by construction
    — asserted so a future change to the rule cannot sweep them up."""
    g = _g(stamps=STAGES)
    concept = URIRef(THE + "Prestress")
    g.add((concept, URIRef(THE + "grounding"), BNode()))

    move_grounding(g)

    assert (concept, URIRef(THE + "grounding"), None) in g


def test_inline_agent_declarations_go_but_the_ATTRIBUTION_stays():
    g = _g(stamps=("derived",))
    agent = URIRef(OPS + "claude-opus-5-5")
    g.add((agent, RDF.type, URIRef("http://www.w3.org/ns/prov#SoftwareAgent")))
    g.add((agent, RDFS.label, Literal("claude-opus-5-5 (DTS)")))

    assert drop_inline_agents(g) == 2
    assert (agent, None, None) not in g
    assert len({s for s in g.subjects() if isinstance(s, URIRef)}) == 1
