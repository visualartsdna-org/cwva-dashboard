"""`dts.reset`: back to "entity created", including the in-flight caches.

Rick, 2026-10-01: "Yes, have reset clear the derive.json too." A reset used to
leave `.qa/dts/<guid>/derive.json` behind, so the entity was back in queue 1
with the proposals of the run that was reset still sitting where the curation
screen reads them. A reset that leaves the previous run's answers has not reset
the entity.

Tested against a tmp sandbox. The behaviour was first confirmed against the
live one, which reset a record that was already distributed — restored from the
QA git, and the reason this file exists.
"""

from __future__ import annotations

import json

import pytest
from rdflib import Graph, URIRef

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.dts_tools import _STAGE_CACHES, _reset

W = "http://visualartsdna.org/work/"
GUID = "abc-123"
SUBJECT = W + GUID
PATH = f"ttl/data/{GUID}.ttl"

ENTITY = """@prefix ops: <http://visualartsdna.org/operations/> .
@prefix prov: <http://www.w3.org/ns/prov#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

work:abc-123 a the:AI ; rdfs:label "A criticism" ;
    skos:inScheme the:entities ;
    the:mdDocument <http://visualartsdna.org/documents/Doc.md> ;
    the:summary "a summary DTS wrote" ;
    vad:hasCriticism the:SomeConcept ;
    the:grounding [ rdfs:label "ground verified" ;
        the:concept the:SomeConcept ;
        the:phrase "the critic wrote this" ] ;
    ops:status [ rdfs:label "tagged" ;
        ops:derived [ ops:at "2026-10-01T10:00:00+00:00"^^xsd:dateTime ;
                      prov:wasAttributedTo ops:claude-opus-5-5 ] ;
        ops:derivationCurated [ ops:at "2026-10-01T10:01:00+00:00"^^xsd:dateTime ] ;
        ops:tagged [ ops:at "2026-10-01T10:02:00+00:00"^^xsd:dateTime ] ] .
"""


@pytest.fixture
def ops(tmp_path):
    fileops = FileOps(Sandbox.open(tmp_path / "stage", create=True))
    fileops.write_text(PATH, ENTITY, make_parents=True)
    for stage in _STAGE_CACHES:
        fileops.write_text(f".qa/dts/{GUID}/{stage}.json",
                           json.dumps({"marker": f"{stage} run that was reset"}),
                           make_parents=True)
    return fileops


def _graph(fileops):
    return Graph().parse(data=fileops.read_text(PATH), format="turtle")


# -- the caches --------------------------------------------------------------


def test_EVERY_stage_cache_is_cleared(ops):
    out = _reset(ops, path=PATH, subject=SUBJECT)

    assert len(out["cleared"]) == len(_STAGE_CACHES)
    for stage in _STAGE_CACHES:
        with pytest.raises(FileNotFoundError):
            ops.read_text(f".qa/dts/{GUID}/{stage}.json")


def test_the_caches_are_found_by_GUID_not_named_by_the_caller(ops):
    """A reset that had to be TOLD where they are would miss them exactly when
    it is run by hand, which is the only way it is ever run."""
    out = _reset(ops, path=PATH, subject=SUBJECT)

    assert f".qa/dts/{GUID}/derive.json" in out["cleared"]


def test_a_reset_with_NO_caches_still_succeeds(tmp_path):
    """The ordinary case after a reset, and after a run that never cached."""
    fileops = FileOps(Sandbox.open(tmp_path / "stage", create=True))
    fileops.write_text(PATH, ENTITY, make_parents=True)

    out = _reset(fileops, path=PATH, subject=SUBJECT)

    assert out["cleared"] == []
    assert out["removed"] > 0


def test_resetting_TWICE_clears_nothing_the_second_time(ops):
    _reset(ops, path=PATH, subject=SUBJECT)

    out = _reset(ops, path=PATH, subject=SUBJECT)

    assert out["cleared"] == []


def test_the_cache_is_TRASHED_not_hard_deleted(ops):
    """`FileOps` has no delete, which is CE_DESIGN §2.3 enforced in code rather
    than asked for. The copy costs nothing and the trash expires on a converged
    promotion."""
    _reset(ops, path=PATH, subject=SUBJECT)

    trashed = list((ops._sb.root / ".qa" / "trash").glob("*derive.json"))
    assert trashed, "the cache went to the trash"
    assert "run that was reset" in trashed[0].read_text()


def test_ANOTHER_entitys_caches_are_untouched(ops):
    """The guid comes from the entity file's own name, so a reset is scoped to
    one entity. Clearing `.qa/dts/` wholesale would throw away a run in flight
    on a different record."""
    other = ".qa/dts/other-999/derive.json"
    ops.write_text(other, '{"marker": "a different entity, mid-flight"}',
                   make_parents=True)

    _reset(ops, path=PATH, subject=SUBJECT)

    assert "mid-flight" in ops.read_text(other)


# -- and the record itself ---------------------------------------------------


def test_the_status_node_goes(ops):
    from cwva_dashboard.dts.state import state_of

    _reset(ops, path=PATH, subject=SUBJECT)

    assert state_of(_graph(ops), URIRef(SUBJECT)) == "derived", "queue 1 again"


def test_the_summary_the_grounding_and_the_PLACEMENTS_go(ops):
    THE = "http://visualartsdna.org/thesaurus/"
    VAD = "http://visualartsdna.org/model/"

    _reset(ops, path=PATH, subject=SUBJECT)
    g = _graph(ops)

    assert (None, URIRef(THE + "summary"), None) not in g
    assert (None, URIRef(THE + "grounding"), None) not in g
    assert (None, URIRef(VAD + "hasCriticism"), None) not in g


def test_what_the_ENTITY_FORM_owns_SURVIVES(ops):
    """A reset undoes DTS, not the record. The label, the document and the
    scheme were there before any stage ran."""
    THE = "http://visualartsdna.org/thesaurus/"
    SKOS = "http://www.w3.org/2004/02/skos/core#"

    _reset(ops, path=PATH, subject=SUBJECT)
    g = _graph(ops)

    assert (None, URIRef(THE + "mdDocument"), None) in g
    assert (None, URIRef(SKOS + "inScheme"), None) in g
    assert any(str(o) == "A criticism" for o in g.objects())
