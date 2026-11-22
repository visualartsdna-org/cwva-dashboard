"""TCAP navigation acceptance suite (TCAP_README): the three Most-Specific-
Property query cases + the CrowdHingeBand case, ported as fixtures verbatim, plus
the broken-hierarchy tie and the shared annotate() step.

Materialized RDFS inference is a hard dependency, so where the case relies on an
inferred type the test asserts that type exists before running the query."""

from __future__ import annotations

from rdflib import RDF, Graph, Namespace, URIRef

from cwva_dashboard.concepts.tcap_navigation import annotate, materialize_rdfs, navigate

VAD = Namespace("http://visualartsdna.org/model/")
THE = Namespace("http://visualartsdna.org/thesaurus/")
WORK = Namespace("http://visualartsdna.org/work/")

_PREFIXES = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .
"""


def _materialized(ttl: str) -> Graph:
    return materialize_rdfs(Graph().parse(data=_PREFIXES + ttl, format="turtle"))


def _predicates(triples):
    return [t[1] for t in triples]


# --- Test Case 1: concept with explicit type -----------------------------

CASE1 = """
vad:Paint a owl:Class .
vad:WatercolorPaint a owl:Class ; rdfs:subClassOf vad:Paint .
vad:hasPaint a owl:ObjectProperty ; rdfs:range vad:Paint .
vad:hasWatercolorPaint a owl:ObjectProperty ; rdfs:range vad:WatercolorPaint .
the:watercolorPaint a skos:Concept .
the:AzureBlueLCS a skos:Concept, vad:WatercolorPaint ; skos:broader the:watercolorPaint .
"""


def test_case1_explicit_type_picks_most_specific():
    g = _materialized(CASE1)
    r = navigate(g, WORK.w, THE.AzureBlueLCS)
    assert not r.tie
    assert _predicates(r.triples) == [VAD.hasWatercolorPaint]
    assert r.triples[0] == (WORK.w, VAD.hasWatercolorPaint, THE.AzureBlueLCS)


# --- Test Case 2: inherit via broader, specific property exists ----------

CASE2 = """
vad:Technique a owl:Class .
vad:PaintingTechnique a owl:Class ; rdfs:subClassOf vad:Technique .
vad:WatercolorTechnique a owl:Class ; rdfs:subClassOf vad:PaintingTechnique .
vad:hasTechnique a owl:ObjectProperty ; rdfs:range vad:Technique .
vad:hasWatercolorTechnique a owl:ObjectProperty ; rdfs:range vad:WatercolorTechnique .
the:paintingTechnique a skos:Concept, vad:PaintingTechnique .
the:watercolorTechnique a skos:Concept, vad:WatercolorTechnique ; skos:broader the:paintingTechnique .
the:wash a skos:Concept ; skos:broader the:watercolorTechnique .
work:prior vad:hasTechnique the:wash .
"""


def test_case2_inferred_type_then_most_specific_via_broader():
    g = _materialized(CASE2)
    # hard-dependency check: the type inferred from property usage must exist
    assert (THE.wash, RDF.type, VAD.Technique) in g
    r = navigate(g, WORK.w, THE.wash)
    assert not r.tie
    assert _predicates(r.triples) == [VAD.hasWatercolorTechnique]


# --- Test Case 3: inherit via broader, specific property does NOT exist ---

CASE3 = """
vad:Technique a owl:Class .
vad:PaintingTechnique a owl:Class ; rdfs:subClassOf vad:Technique .
vad:WatercolorTechnique a owl:Class ; rdfs:subClassOf vad:PaintingTechnique .
vad:hasTechnique a owl:ObjectProperty ; rdfs:range vad:Technique .
the:watercolorTechnique a skos:Concept, vad:WatercolorTechnique .
the:wash a skos:Concept ; skos:broader the:watercolorTechnique .
work:prior vad:hasTechnique the:wash .
"""


def test_case3_falls_back_to_general_property():
    g = _materialized(CASE3)
    r = navigate(g, WORK.w, THE.wash)
    assert not r.tie
    assert _predicates(r.triples) == [VAD.hasTechnique]


# --- CrowdHingeBand: after the vocabulary fix, exactly one triple ---------

_CROWD_ONTOLOGY = """
vad:VisualAnalysis a owl:Class .
vad:FormalAnalysis a owl:Class ; rdfs:subClassOf vad:VisualAnalysis .
vad:Composition a owl:Class ; rdfs:subClassOf vad:FormalAnalysis .
vad:ContextualAnalysis a owl:Class ; rdfs:subClassOf vad:VisualAnalysis .
vad:ArtHistory a owl:Class ; rdfs:subClassOf vad:ContextualAnalysis .
vad:ArtCriticism a owl:Class ; rdfs:subClassOf vad:ArtHistory .
vad:hasVisualAnalysis a owl:ObjectProperty ; rdfs:range vad:VisualAnalysis .
vad:hasComposition a owl:ObjectProperty ; rdfs:range vad:Composition .
vad:hasCriticism a owl:ObjectProperty ; rdfs:range vad:ArtCriticism .
the:Interpretation a skos:Concept, vad:VisualAnalysis .
the:Criticism a skos:Concept, vad:ArtCriticism ; skos:broader the:Interpretation .
the:SpatialCompositionStrategy a skos:Concept ; skos:broader the:Composition .
the:HorizontalFriezeBanding a skos:Concept ; skos:broader the:SpatialCompositionStrategy .
the:HumanActivityFrieze a skos:Concept ; skos:broader the:HorizontalFriezeBanding .
the:CrowdHingeBand a skos:Concept ; skos:broader the:HumanActivityFrieze .
"""

# fixed: Composition is a sibling of Criticism under Interpretation
_FIXED = "the:Composition a skos:Concept, vad:Composition ; skos:broader the:Interpretation .\n"
# broken: the false claim that composition is a kind of criticism
_BROKEN = "the:Composition a skos:Concept, vad:Composition ; skos:broader the:Criticism .\n"


def test_crowdhingeband_fixed_hierarchy_single_triple():
    g = _materialized(_CROWD_ONTOLOGY + _FIXED)
    r = navigate(g, WORK.w, THE.CrowdHingeBand)
    assert not r.tie
    assert _predicates(r.triples) == [VAD.hasComposition]


def test_crowdhingeband_broken_hierarchy_is_a_tie():
    # A tie is the symptom of the modeling defect (false skos:broader), never a
    # normal result — the port surfaces it rather than masking it.
    g = _materialized(_CROWD_ONTOLOGY + _BROKEN)
    r = navigate(g, WORK.w, THE.CrowdHingeBand)
    assert r.tie
    assert set(_predicates(r.triples)) == {VAD.hasComposition, VAD.hasCriticism}


# --- shared annotate() over multiple concepts ----------------------------


def test_annotate_places_ties_and_reports_unmatched():
    g = _materialized(_CROWD_ONTOLOGY + _BROKEN)
    res = annotate(g, WORK.w, [THE.Criticism, THE.CrowdHingeBand, THE.NotAConcept])

    placed = {(t[1], t[2]) for t in res.placed}
    # Criticism resolves cleanly to hasCriticism
    assert (VAD.hasCriticism, THE.Criticism) in placed
    # CrowdHingeBand ties -> one triple adjudicated (deterministic) + recorded
    assert len(res.ties) == 1
    assert res.ties[0].concept == URIRef(THE.CrowdHingeBand)
    assert res.ties[0].adjudicated in res.placed
    # an unknown concept yields nothing -> reported, not silently dropped
    assert URIRef(THE.NotAConcept) in res.unmatched


# A concept typed ONLY by inference (used as a property object, no explicit or
# broader-borne type) — the case where materialization changes the answer.
INFERENCE_ONLY = """
vad:Technique a owl:Class .
vad:hasTechnique a owl:ObjectProperty ; rdfs:range vad:Technique .
the:solo a skos:Concept .
work:prior vad:hasTechnique the:solo .
"""


def test_inferred_type_only_requires_materialization():
    # Without materialization the:solo has no vad:Technique type -> nothing.
    raw = Graph().parse(data=_PREFIXES + INFERENCE_ONLY, format="turtle")
    assert (THE.solo, RDF.type, VAD.Technique) not in raw
    assert navigate(raw, WORK.w, THE.solo).triples == []
    # After materialization the range-inferred type appears -> hasTechnique.
    mat = materialize_rdfs(Graph().parse(data=_PREFIXES + INFERENCE_ONLY, format="turtle"))
    assert (THE.solo, RDF.type, VAD.Technique) in mat
    assert _predicates(navigate(mat, WORK.w, THE.solo).triples) == [VAD.hasTechnique]
