"""The workflow board engine, against the SHIPPED definitions.

The queries are config, so testing the engine with hand-made queries would test
nothing that runs. These load `config/workflows.rson` and ask it about records
shaped like the real ones: Lepers' Hearth and its two criticism entities.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from rdflib import Graph

from cwva_dashboard.workflow_state.board import (
    BoardConfig, evaluate_board, load_workflows, tick_kind)

CONFIG = Path(__file__).resolve().parents[2] / "config" / "workflows.rson"
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)

PREFIXES = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix ops: <http://visualartsdna.org/operations/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .
"""

FRESH = """
work:w1 a vad:CreativeWork, vad:Watercolor ; rdfs:label "Lepers' Hearth" ;
    vad:hasPaper the:Fabriano ; schema:image <http://x/LepersHearth.jpg> ;
    schema:dateCreated "2026-11-04"^^xs:date .
"""

ANNOTATED = FRESH + """
work:w1 vad:hasWatercolorPaint the:UltramarineLCS .
"""

ENTITY = """
work:e1 skos:inScheme the:entities ; the:tag work:w1 ;
    the:mdDocument <http://x/Crit.md> ; schema:datePublished "2026-11-05"^^xs:date .
"""

DTS_PART = """
work:e1 ops:status [ rdfs:label "tagged" ;
    ops:derived [ ops:at "2026-11-06T10:00:00+00:00"^^xs:dateTime ] ;
    ops:tagged [ ops:at "2026-11-07T10:00:00+00:00"^^xs:dateTime ] ] .
"""

DTS_DONE = """
work:e1 ops:status [ rdfs:label "curation complete" ;
    ops:summaryCurated [ ops:at "2026-11-08T10:00:00+00:00"^^xs:dateTime ] ] .
"""

LEGACY = """
work:old a vad:Watercolor ; rdfs:label "Spirited Tree" ; schema:image <http://x/t.jpg> ;
    schema:dateCreated "2026-06-07"^^xs:date .
"""


@pytest.fixture(scope="module")
def config() -> BoardConfig:
    return load_workflows(CONFIG)


def _graph(*parts) -> Graph:
    g = Graph()
    g.parse(data=PREFIXES + "".join(parts), format="turtle")
    return g


def _row(config, *parts, ticks=None, wf="A", **kw):
    board = evaluate_board(config, _graph(*parts), ticks=ticks, now=NOW,
                           include_finished=True, **kw)
    rows = next(w for w in board["workflows"] if w["id"] == wf)["rows"]
    return rows[0] if rows else None


def _states(row):
    return {k: c["state"] for k, c in row["cells"].items()}


def test_the_shipped_config_loads_both_first_workflows(config):
    assert [w.id for w in config.workflows] == ["A", "B"]
    assert all(s.query or s.manual or s.id == "criticism"
               for w in config.workflows for s in w.steps)
    # the only hand-ticked step, by agreement: nothing in the data records it
    assert {s.id for w in config.workflows for s in w.steps if s.manual} == {"website"}


def test_a_fresh_entry_has_three_ready_steps_at_once(config):
    """Why it is a grid and not a kanban: several steps can be next."""
    row = _row(config, FRESH)
    s = _states(row)
    assert s["entry"] == "done"
    assert {k for k, v in s.items() if v == "ready"} == {"website", "annotate", "criticism"}
    assert s["onsite"] == s["entity"] == s["dts"] == "blocked"
    assert row["cells"]["entry"]["at"].startswith("2026-11-04")
    assert row["last"] == "entry" and set(row["next"]) == {"website", "annotate", "criticism"}
    assert row["age_days"] == pytest.approx(13.5)
    assert row["stalled"] is True


def test_a_blocked_cell_names_what_it_waits_for(config):
    assert _row(config, FRESH)["cells"]["onsite"]["waiting_on"] == ["website"]


def test_annotation_is_read_from_a_concept_the_entry_form_does_not_set(config):
    assert _states(_row(config, FRESH))["annotate"] == "ready"  # hasPaper alone
    assert _states(_row(config, ANNOTATED))["annotate"] == "done"


def test_the_entity_implies_the_criticism_it_records(config):
    row = _row(config, FRESH, ENTITY)
    assert row["cells"]["entity"]["state"] == "done"
    assert row["cells"]["entity"]["records"] == ["http://visualartsdna.org/work/e1"]
    assert row["cells"]["criticism"] == {**row["cells"]["criticism"],
                                         "state": "done", "source": "implied"}
    assert row["cells"]["dts"]["state"] == "ready"


def test_dts_part_way_is_under_way_with_what_last_happened(config):
    c = _row(config, FRESH, ENTITY, DTS_PART)["cells"]["dts"]
    assert c["state"] == "started" and c["note"] == "tagged"
    assert c["at"].startswith("2026-11-07")


def test_dts_complete_is_dated_by_the_curated_summary(config):
    c = _row(config, FRESH, ENTITY, DTS_DONE)["cells"]["dts"]
    assert c["state"] == "done" and c["at"].startswith("2026-11-08")


def test_dts_is_not_done_while_a_second_criticism_is_unprocessed(config):
    second = ENTITY.replace("work:e1", "work:e2")
    assert _states(_row(config, FRESH, ENTITY, DTS_DONE, second))["dts"] != "done"


def test_the_website_tick_is_dated_and_unblocks_on_site(config):
    ticks = {tick_kind("A", "website"): {"http://visualartsdna.org/work/w1":
                                         "2026-11-10T09:00:00+00:00"}}
    row = _row(config, FRESH, ticks=ticks)
    assert row["cells"]["website"] == {**row["cells"]["website"],
                                       "state": "done", "source": "manual"}
    assert row["cells"]["onsite"]["state"] == "ready"
    assert row["last"] == "website"


def test_on_site_evidence_completes_the_website_step_without_a_tick(config):
    row = _row(config, FRESH, "work:w1 vad:workOnSite <https://visualartsdna.org> .")
    assert row["cells"]["onsite"]["state"] == "done"
    assert row["cells"]["website"]["source"] == "implied"


def test_a_finished_work_is_hidden_unless_asked_for(config):
    everything = (ANNOTATED, ENTITY, DTS_DONE,
                  "work:w1 vad:workOnSite <https://visualartsdna.org> .")
    assert _row(config, *everything)["finished"] is True
    board = evaluate_board(config, _graph(*everything), now=NOW)
    assert board["workflows"][0]["rows"] == []


def test_works_before_the_horizon_are_not_tracked(config):
    board = evaluate_board(config, _graph(FRESH, LEGACY), now=NOW)
    assert [r["label"] for r in board["workflows"][0]["rows"]] == ["Lepers' Hearth"]


def test_the_disposition_rides_along(config):
    row = _row(config, FRESH,
               dispositions={"http://visualartsdna.org/work/w1": "2026.223"})
    assert row["disposition"] == "2026.223"


BLENDER = """
work:b1 a vad:CreativeWork, vad:BlenderComposition ; rdfs:label "Torso" ;
    schema:image <http://x/t.jpg> ; schema:dateCreated "2026-11-16"^^xs:date .
"""


def test_blender_proof_initiated_then_anchored(config):
    pending = "work:p1 a vad:ProofEvent ; vad:assetOf work:b1 ."
    s = _states(_row(config, BLENDER, pending, wf="B"))
    assert s["proof"] == "done" and s["anchor"] == "ready"

    anchored = pending + (' work:p1 vad:transaction "0xfe" ; '
                          'vad:timestamp "2026-11-17T01:00:00-04:00"^^xs:dateTime .')
    assert _states(_row(config, BLENDER, anchored, wf="B"))["anchor"] == "done"
    # a second asset still waiting keeps it open: image AND image3d
    both = anchored + " work:p2 a vad:ProofEvent ; vad:assetOf work:b1 ."
    assert _states(_row(config, BLENDER, both, wf="B"))["anchor"] == "ready"


def test_a_watercolor_is_not_in_the_blender_workflow(config):
    board = evaluate_board(config, _graph(FRESH), now=NOW)
    assert next(w for w in board["workflows"] if w["id"] == "B")["rows"] == []


def test_a_bad_dependency_fails_at_load(tmp_path):
    (tmp_path / "workflows.rson").write_text(
        '{"workflows": [{"id": "X", "members_query": "", "steps": ['
        '{"id": "a", "depends_on": ["nope"]}]}]}')
    with pytest.raises(ValueError, match="nope"):
        load_workflows(tmp_path / "workflows.rson")


def test_a_missing_file_is_an_empty_board(tmp_path):
    assert load_workflows(tmp_path / "absent.rson").workflows == ()


def _skip(step, work="http://visualartsdna.org/work/w1", wf="A"):
    from cwva_dashboard.workflow_state.board import skip_kind
    return {skip_kind(wf, step): {work: "2026-11-18T09:00:00+00:00"}}


def test_a_dismissed_step_is_not_needed_and_lets_the_work_finish(config):
    """Fairy Pool 5 and 6: watercolors that will never be annotated."""
    everything = (FRESH, ENTITY, DTS_DONE,
                  "work:w1 vad:workOnSite <https://visualartsdna.org> .")
    row = _row(config, *everything, skips=_skip("annotate"))
    assert row["cells"]["annotate"] == {**row["cells"]["annotate"],
                                        "state": "skipped", "source": "dismissed"}
    assert row["finished"] is True
    assert evaluate_board(config, _graph(*everything), skips=_skip("annotate"),
                          now=NOW)["workflows"][0]["rows"] == []


def test_a_dismissed_step_unblocks_its_dependents_but_implies_nothing(config):
    row = _row(config, FRESH, skips=_skip("criticism"))
    assert row["cells"]["criticism"]["state"] == "skipped"
    assert row["cells"]["entity"]["state"] == "ready"
    # skipping the entity does not claim the criticism was generated
    row = _row(config, FRESH, skips=_skip("entity"))
    assert row["cells"]["criticism"]["state"] == "ready"


def test_the_data_outranks_a_dismissal(config):
    row = _row(config, ANNOTATED, skips=_skip("annotate"))
    assert row["cells"]["annotate"]["state"] == "done"
