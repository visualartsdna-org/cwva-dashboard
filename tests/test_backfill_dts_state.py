"""The pre-DTS backfill: stamp what the old flow finished, and nothing else.

The queue rules key off the stamps and nothing else, which is right and has
one consequence: every entity predating DTS reads as pending derivation. The
design record settles that they are complete; this says so in the vocabulary
the queues read.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDFS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from backfill_dts_state import (  # noqa: E402
    BACKFILL_NOTE,
    evidence_of_prior_processing,
    stamp_complete,
)

from cwva_dashboard.dts.state import OPS, STAGES, PROV, read_stamps, state_of  # noqa: E402

STORE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:old a the:AI ; rdfs:label "Old criticism" ; the:conceptsExtracted true .
work:summarized a the:AI ; rdfs:label "Has a summary" ;
    the:summary "the old summarizer wrote this" .
work:unproven a the:AI ; rdfs:label "No evidence" ;
    the:conceptsExtracted false .
"""

W = "http://visualartsdna.org/work/"


def _g():
    return Graph().parse(data=STORE, format="turtle")


# -- what counts as evidence -------------------------------------------------


def test_conceptsExtracted_TRUE_is_evidence():
    """The retired predicate takes a new job: what the old workflow set when
    it finished."""
    assert evidence_of_prior_processing(_g(), URIRef(W + "old"))


def test_a_SUMMARY_is_evidence_on_its_own():
    """Only the old summarizer wrote one."""
    assert evidence_of_prior_processing(_g(), URIRef(W + "summarized"))


def test_conceptsExtracted_FALSE_is_NOT_evidence():
    """`false` is what `record.new_entity` writes on a brand-new record, so
    treating the predicate's presence as evidence would stamp every new
    entity complete the moment it was created."""
    assert not evidence_of_prior_processing(_g(), URIRef(W + "unproven"))


# -- the stamp ---------------------------------------------------------------


def test_it_stamps_ALL_SIX_stages():
    g = _g()
    subject = URIRef(W + "old")

    stamp_complete(g, subject, when="2026-09-30T10:00:00+00:00")

    assert set(read_stamps(g, subject)) == set(STAGES)
    assert state_of(g, subject) == "complete"


def test_the_stamp_has_NO_AGENT():
    """A backfill did not derive, tag or summarize anything — it records that
    a previous workflow did. Inventing an agent for work this code never did
    would be a provenance lie."""
    g = _g()
    subject = URIRef(W + "old")

    stamp_complete(g, subject, when="2026-09-30T10:00:00+00:00")

    assert all(not s.by for s in read_stamps(g, subject).values())
    assert (None, PROV.wasAttributedTo, None) not in g


def test_it_says_what_it_MEANS():
    """A reader finding six identical timestamps deserves to know why."""
    g = _g()
    subject = URIRef(W + "old")

    stamp_complete(g, subject, when="2026-09-30T10:00:00+00:00")
    node = g.value(subject, OPS.status)

    assert str(g.value(node, RDFS.comment)) == BACKFILL_NOTE


def test_the_label_reads_as_complete():
    g = _g()
    subject = URIRef(W + "old")

    stamp_complete(g, subject, when="2026-09-30T10:00:00+00:00")
    node = g.value(subject, OPS.status)

    assert str(g.value(node, RDFS.label)) == "summaryCurated"


def test_an_entity_with_a_status_node_is_MID_FLIGHT_and_left_alone():
    """A backfill that overwrote one would destroy the record of a run in
    progress. The script skips them; this asserts the condition it skips on."""
    from cwva_dashboard.dts.state import status_node, write_stamp

    g = _g()
    subject = URIRef(W + "old")
    write_stamp(g, subject, "derived")

    assert status_node(g, subject) is not None
    assert state_of(g, subject) == "derivationCurated", "still mid-flight"


# -- two grounds for the same stamp -----------------------------------------


def test_the_two_notes_are_DISTINCT():
    """"The old workflow said so" and "the curator said so" are different
    answers to "why is this complete", so collapsing them would make the
    second unanswerable."""
    from backfill_dts_state import ASSERTED_NOTE, BACKFILL_NOTE

    assert BACKFILL_NOTE != ASSERTED_NOTE
    assert "pre-DTS flow" in BACKFILL_NOTE and "curator" not in BACKFILL_NOTE
    assert "curator's assertion" in ASSERTED_NOTE
    assert "no evidence" in ASSERTED_NOTE


def test_a_note_is_carried_onto_the_stamp():
    from backfill_dts_state import ASSERTED_NOTE

    g = _g()
    subject = URIRef(W + "unproven")

    stamp_complete(g, subject, when="2026-10-01T10:00:00+00:00",
                   note=ASSERTED_NOTE)
    node = g.value(subject, OPS.status)

    assert str(g.value(node, RDFS.comment)) == ASSERTED_NOTE
    assert state_of(g, subject) == "complete"
