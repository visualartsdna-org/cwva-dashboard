"""Standing-query engine: fs counts + SPARQL obligations − dismissals, and the
narration = panel guarantee."""

from __future__ import annotations

from rdflib import Graph

from cwva_dashboard.concepts.ledger import HygieneLedger
from cwva_dashboard.workflow_state.definitions import DEFAULT_STANDING_QUERIES
from cwva_dashboard.workflow_state.engine import evaluate

CONTENT = """
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix schema: <https://schema.org/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix work: <http://visualartsdna.org/work/> .

# w1 has a site link; w2 does not (an obligation).
work:w1 schema:image <http://x/1.jpg> ; rdfs:label "Linked" ; vad:workOnSite <http://visualartsdna.org> .
work:w2 schema:image <http://x/2.jpg> ; rdfs:label "Unlinked" .

# e1 pending concept extraction; e2 done.
work:e1 the:conceptsExtracted false ; rdfs:label "Pending" .
work:e2 the:conceptsExtracted true ; rdfs:label "Done" .
"""


def _graph():
    return Graph().parse(data=CONTENT, format="turtle")


def _counts(mapping):
    return lambda d, exts: mapping.get(d, 0)


def test_pipeline_queue_counts(env=None):
    ws = evaluate(
        DEFAULT_STANDING_QUERIES,
        graph=_graph(),
        count_fn=_counts({"conceptQueue": 3, "conceptQueue/processed": 7}),
    )
    q = {x.id: x.count for x in ws.pipeline_queues}
    assert q["concept_queue"] == 3
    assert q["concept_queue_processed"] == 7


def test_sparql_obligations():
    ws = evaluate(DEFAULT_STANDING_QUERIES, graph=_graph(), count_fn=_counts({}))
    by_def = {}
    for o in ws.open_obligations:
        by_def.setdefault(o.definition_id, []).append(o.key)
    assert by_def["works_without_workonsite"] == ["http://visualartsdna.org/work/w2"]
    assert by_def["concepts_extracted_false"] == ["http://visualartsdna.org/work/e1"]


def test_dismissal_subtracts_obligation():
    ledger = HygieneLedger.from_ttl()
    ledger.dismiss("works_without_workonsite", "http://visualartsdna.org/work/w2", "on no site by choice")
    ws = evaluate(DEFAULT_STANDING_QUERIES, graph=_graph(), count_fn=_counts({}), ledger=ledger)
    keys = [o.key for o in ws.open_obligations if o.definition_id == "works_without_workonsite"]
    assert keys == []  # dismissed, no longer reported


def test_narration_matches_panel_numbers():
    ws = evaluate(
        DEFAULT_STANDING_QUERIES,
        graph=_graph(),
        count_fn=_counts({"conceptQueue": 2}),
    )
    text = ws.narrate()
    assert "2 markdowns in the concept queue" in text
    assert "1 works with no site link" in text
    assert "1 entities awaiting concept extraction" in text


def test_empty_state_narrates_nothing_pending():
    ws = evaluate(DEFAULT_STANDING_QUERIES, graph=Graph(), count_fn=_counts({}))
    assert ws.narrate() == "nothing pending"


def test_to_dict_shape():
    d = evaluate(DEFAULT_STANDING_QUERIES, graph=_graph(), count_fn=_counts({})).to_dict()
    assert set(d) == {"pipeline_queues", "open_obligations", "in_flight", "summary"}
    assert all({"definition_id", "key", "label", "resolving_action"} <= set(o) for o in d["open_obligations"])
