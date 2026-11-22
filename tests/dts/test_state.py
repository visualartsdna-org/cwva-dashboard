"""The DTS status node: stamps, queue membership, and the reset.

The state model is the part of DTS that everything else keys off, and its
rules came out of rounds 4-6 of the design review rather than out of code —
so these tests are where those decisions are written down executably.
"""

from __future__ import annotations

import re

import pytest
from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, XSD

from cwva_dashboard.dts.state import (
    PROV,
    STAGES,
    OPS,
    THE,
    agent_iri,
    clear_status,
    curator_iri,
    label_for,
    queue_of,
    read_stamps,
    state_of,
    status_node,
    write_stamp,
)

DOMAIN = "http://visualartsdna.org"
E = URIRef(f"{DOMAIN}/work/g1")


@pytest.fixture
def g():
    graph = Graph()
    graph.add((E, RDFS.label, Literal("Criticism Three Graces claude")))
    return graph


def _advance(graph, upto: str, **kw):
    for stage in STAGES:
        write_stamp(graph, E, stage, **kw)
        if stage == upto:
            return


# -- an entity with no status node is queue 1 --------------------------------


def test_an_untouched_entity_is_PENDING_DERIVATION(g):
    """`entityCreated` is inferred, not stamped (Rick, round 6): the entity's
    existence is the evidence."""
    assert status_node(g, E) is None
    assert state_of(g, E) == "derived"
    assert queue_of(g, E) == "pending derivation"
    assert label_for(read_stamps(g, E)) == "entity created"


def test_the_stages_advance_one_queue_at_a_time(g):
    expected = [
        "pending derivation", "pending derivation curation",
        "pending tagging", "pending tagging curation",
        "pending summarization", "pending summary curation",
    ]
    seen = []
    for stage in STAGES:
        seen.append(queue_of(g, E))
        write_stamp(g, E, stage)

    assert seen == expected
    assert queue_of(g, E) == "complete"
    assert state_of(g, E) == "complete"


# -- the rules key off the STAMPS, never the label ---------------------------


def test_a_DRIFTED_LABEL_changes_no_queue(g):
    """The label is a denormalisation. If a rule read it, a wrong label would
    silently empty or fill a queue."""
    _advance(g, "derived")
    node = status_node(g, E)
    g.set((node, RDFS.label, Literal("summaryCurated")))  # a lie

    assert state_of(g, E) == "derivationCurated"
    assert queue_of(g, E) == "pending derivation curation"


def test_the_label_names_what_LAST_happened(g):
    _advance(g, "tagged")

    assert str(g.value(status_node(g, E), RDFS.label)) == "tagged"


def test_the_label_is_RECOMPUTED_not_appended(g):
    _advance(g, "tagged")
    node = status_node(g, E)

    assert len(list(g.objects(node, RDFS.label))) == 1


# -- state and provenance are ONE structure (Rick, round 4) ------------------


def test_a_stamp_carries_WHEN_and_BY_WHOM(g):
    model = agent_iri("claude-sonnet-5")
    write_stamp(g, E, "derived", by=model, at="2026-09-29T10:00:00+00:00")

    stamp = read_stamps(g, E)["derived"]
    assert stamp.at == "2026-09-29T10:00:00+00:00"
    assert stamp.by == str(model)
    assert stamp.when.year == 2026


def test_the_moment_is_a_dateTime_not_a_date(g):
    """Deliberate deviation from the review's sketch: all six stages are
    normally done in one sitting, so a date cannot order them."""
    write_stamp(g, E, "derived")
    node = status_node(g, E)
    record = g.value(node, OPS.derived)

    assert g.value(record, OPS.at).datatype == XSD.dateTime


def test_the_curator_is_named_by_ROLE_not_by_ADDRESS(g):
    """These records converge to a published catalogue."""
    who = curator_iri()
    _advance(g, "derived")
    write_stamp(g, E, "derivationCurated", by=who)

    assert read_stamps(g, E)["derivationCurated"].by == (
        "http://visualartsdna.org/operations/user")
    # No address anywhere in what would be published (`@prefix` aside).
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", g.serialize(format="turtle"))


def test_an_attribution_is_a_REFERENCE_and_declares_nothing(g):
    """The record cites `ops:claude-sonnet-5`; the operations ontology says
    what that is, the same way a record cites `the:Prestress` without inlining
    its definition.

    It used to inline two triples per agent "so it stays self-describing when
    read alone" — written before the ontology existed. The cost only showed
    later: the record became a four-subject file, which fails the
    one-named-subject rule, so Edit Record would not open a DTS-processed
    entity and Drafts listed it as "<guid>.ttl (4 subjects)" with no way back
    in. And the declaration for the curator said `prov:SoftwareAgent`, while
    the ontology says `prov:Agent, prov:Person` (2026-10-02)."""
    model = agent_iri("claude-sonnet-5")

    write_stamp(g, E, "derived", by=model)

    assert (E, None, None) in g
    assert (model, RDF.type, None) not in g, "the record declares no agent"
    assert (model, RDFS.label, None) not in g
    assert len({s for s in g.subjects() if isinstance(s, URIRef)}) == 1


def test_a_stamped_record_has_ONE_named_subject(g):
    """The rule Edit Record and the Drafts index both depend on, asserted on
    the shape DTS actually writes."""
    for stage in ("derived", "derivationCurated", "tagged"):
        write_stamp(g, E, stage, by=agent_iri("claude-opus-5-5"))

    assert {s for s in g.subjects() if isinstance(s, URIRef)} == {E}


# -- no re-runs, and no stages out of order ----------------------------------


def test_stamping_OUT_OF_ORDER_is_refused(g):
    """A record claiming "tagged" with nothing derived would sit in a queue
    whose work was never done."""
    with pytest.raises(ValueError) as exc:
        write_stamp(g, E, "tagged")

    assert "waiting for derived" in str(exc.value)


def test_RE_STAMPING_is_refused_with_the_error_path_named(g):
    """DTS runs once per entity; recovery is reset-and-start-again, not a
    quiet overwrite that loses when it first happened."""
    write_stamp(g, E, "derived", at="2026-09-29T10:00:00+00:00")

    with pytest.raises(ValueError) as exc:
        write_stamp(g, E, "derived")

    assert "2026-09-29T10:00:00+00:00" in str(exc.value)
    assert "reset" in str(exc.value)


def test_resuming_DAYS_LATER_is_ordinary(g):
    """State is per entity, not per session, which is what makes a workflow
    stoppable and resumable (Rick, decision C)."""
    write_stamp(g, E, "derived", at="2026-09-01T10:00:00+00:00")
    reloaded = Graph().parse(data=g.serialize(format="turtle"), format="turtle")

    write_stamp(reloaded, E, "derivationCurated", at="2026-09-29T10:00:00+00:00")

    assert set(read_stamps(reloaded, E)) == {"derived", "derivationCurated"}


# -- reset -------------------------------------------------------------------


def test_reset_removes_the_WHOLE_node_including_the_stamp_nodes(g):
    _advance(g, "tagged")
    before = len(g)

    removed = clear_status(g, E)

    assert status_node(g, E) is None
    assert len(g) == before - removed
    assert not any(isinstance(s, BNode) for s in g.subjects())
    assert state_of(g, E) == "derived"  # back in queue 1


def test_reset_leaves_the_RECORD_alone(g):
    _advance(g, "derived")
    g.add((E, THE.summary, Literal("a summary DTS did not write here")))

    clear_status(g, E)

    assert str(g.value(E, RDFS.label)) == "Criticism Three Graces claude"
    assert g.value(E, THE.summary) is not None


def test_reset_on_an_untouched_entity_is_a_no_op(g):
    assert clear_status(g, E) == 0
