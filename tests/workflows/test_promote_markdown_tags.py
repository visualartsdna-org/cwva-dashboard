"""#15 Annotate Document Instances: conceptQueue the:tag → TCAP typed properties
on instances, conceptsExtracted flip, evidence preservation, tag TTL not
promoted."""

from __future__ import annotations

from rdflib import Graph, Literal, Namespace
from rdflib.namespace import RDFS

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN

VAD = Namespace("http://visualartsdna.org/model/")
THE = Namespace("http://visualartsdna.org/thesaurus/")
WORK = Namespace("http://visualartsdna.org/work/")

ONTOLOGY = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix vad: <http://visualartsdna.org/model/> .
vad:Technique a owl:Class .
vad:WatercolorTechnique a owl:Class ; rdfs:subClassOf vad:Technique .
vad:hasTechnique a owl:ObjectProperty ; rdfs:range vad:Technique .
vad:hasWatercolorTechnique a owl:ObjectProperty ; rdfs:range vad:WatercolorTechnique .
"""
THESAURUS = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:watercolorTechnique a skos:Concept, vad:WatercolorTechnique .
the:wash a skos:Concept ; skos:broader the:watercolorTechnique .
"""
# a criticism instance pending extraction (conceptsExtracted false), with a
# durable instance-linkage the:tag that the pipeline must NOT consume
INSTANCE = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .
work:c1 a the:Criticism ; rdfs:label "A reading" ;
    the:conceptsExtracted false ; skos:inScheme the:entities ;
    the:tag work:relatedWork .
"""
# scaffolding tags in the conceptQueue (the pipeline's authority)
QUEUE_TAGS = """
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .
work:c1 the:tag the:wash .
"""


def _env(tmp_path, instance=INSTANCE):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    ops.write_text("metacontent/model/cwva.ttl", ONTOLOGY, make_parents=True)
    ops.write_text("metacontent/vocab/thesaurus.ttl", THESAURUS, make_parents=True)
    ops.write_text("content/ttl/data/c1.ttl", instance, make_parents=True)
    ops.write_text("conceptQueue/c1.ttl", QUEUE_TAGS, make_parents=True)
    return build_default_registry(domain=TEST_DOMAIN), ops, sb


def _run(reg, ops, **kw):
    dr = reg.dispatch("concept.promote_markdown_tags", kw, ops)
    assert dr.ok, dr.error
    return dr.result


def test_tool_registered(tmp_path):
    reg, _, _ = _env(tmp_path)
    assert "concept.promote_markdown_tags" in reg.names()


def test_places_typed_property_flips_flag_and_writes_evidence(tmp_path):
    reg, ops, sb = _env(tmp_path)
    res = _run(reg, ops)
    assert len(res["processed"]) == 1 and res["skipped"] == []

    inst = Graph().parse(sb.root / "content/ttl/data/c1.ttl", format="turtle")
    # TCAP typed property placed on the instance
    assert (WORK.c1, VAD.hasWatercolorTechnique, THE.wash) in inst
    # conceptsExtracted flipped false -> true
    assert (WORK.c1, THE.conceptsExtracted, Literal(True)) in inst
    assert (WORK.c1, THE.conceptsExtracted, Literal(False)) not in inst
    # instance-level the:tag (durable linkage) is untouched
    assert (WORK.c1, THE.tag, WORK.relatedWork) in inst

    # consumed tags preserved as evidence (non-converged area)
    ev = Graph().parse(sb.root / "evidence/c1.ttl", format="turtle")
    assert (WORK.c1, THE.tag, THE.wash) in ev
    # the scaffolding tag TTL never entered the SOT mirror
    assert not (sb.root / "content/ttl/data/c1.ttl").read_text().count("the:tag the:wash")


def test_skip_if_concepts_extracted_true(tmp_path):
    done = INSTANCE.replace("the:conceptsExtracted false", "the:conceptsExtracted true")
    reg, ops, sb = _env(tmp_path, instance=done)
    res = _run(reg, ops)
    assert res["processed"] == [] and res["skipped"] == [str(WORK.c1)]
    # untouched: no typed property added
    inst = Graph().parse(sb.root / "content/ttl/data/c1.ttl", format="turtle")
    assert (WORK.c1, VAD.hasWatercolorTechnique, THE.wash) not in inst


def test_reannotate_reprocesses_done_instances(tmp_path):
    done = INSTANCE.replace("the:conceptsExtracted false", "the:conceptsExtracted true")
    reg, ops, sb = _env(tmp_path, instance=done)
    res = _run(reg, ops, reannotate=True)
    assert len(res["processed"]) == 1
    inst = Graph().parse(sb.root / "content/ttl/data/c1.ttl", format="turtle")
    assert (WORK.c1, VAD.hasWatercolorTechnique, THE.wash) in inst


# -- the deprecated flag is read, never written (2026-10-02) ----------------


def test_a_DTS_TAGGED_entity_is_SKIPPED(tmp_path):
    """DTS-made entities carry no `conceptsExtracted` at all, so skip-if-done
    reading only the flag would re-place concepts DTS had already placed."""
    from rdflib import Graph, URIRef

    from cwva_dashboard.dts.state import write_stamp
    from cwva_dashboard.workflows.annotate import _already_annotated

    subject = URIRef("http://visualartsdna.org/work/e1")
    g = Graph()
    for stage in ("derived", "derivationCurated", "tagged", "taggingCurated"):
        write_stamp(g, subject, stage)

    assert _already_annotated(g, subject)


def test_a_MID_FLIGHT_DTS_entity_is_NOT_skipped():
    """Stamped `tagged` but not curated: the placement has not happened."""
    from rdflib import Graph, URIRef

    from cwva_dashboard.dts.state import write_stamp
    from cwva_dashboard.workflows.annotate import _already_annotated

    subject = URIRef("http://visualartsdna.org/work/e1")
    g = Graph()
    for stage in ("derived", "derivationCurated", "tagged"):
        write_stamp(g, subject, stage)

    assert not _already_annotated(g, subject)


def test_the_LEGACY_flag_still_skips():
    """59 records carry it and the workflow must go on honouring them."""
    from rdflib import Graph, Literal, URIRef
    from cwva_dashboard.workflows.annotate import THE, _already_annotated

    subject = URIRef("http://visualartsdna.org/work/e1")
    g = Graph()
    g.add((subject, THE.conceptsExtracted, Literal(True)))

    assert _already_annotated(g, subject)


def test_an_entity_with_NEITHER_is_not_skipped():
    from rdflib import Graph, URIRef
    from cwva_dashboard.workflows.annotate import _already_annotated

    assert not _already_annotated(
        Graph(), URIRef("http://visualartsdna.org/work/e1"))
