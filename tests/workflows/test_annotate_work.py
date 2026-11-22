"""#6 Annotate Work: pick thesaurus concepts → TCAP typed properties on the work
TTL; ties recorded in the hygiene ledger."""

from __future__ import annotations

from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDFS

from cwva_dashboard.concepts.ledger import HygieneLedger
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
vad:PaintingTechnique a owl:Class ; rdfs:subClassOf vad:Technique .
vad:WatercolorTechnique a owl:Class ; rdfs:subClassOf vad:PaintingTechnique .
vad:hasTechnique a owl:ObjectProperty ; rdfs:range vad:Technique .
vad:hasWatercolorTechnique a owl:ObjectProperty ; rdfs:range vad:WatercolorTechnique .
"""

# In a SCHEME, because that is the only way a concept reaches the picker — and
# therefore the only way a user can tick or untick one. A concept outside every
# scheme is invisible to the form, which is what `the:offScheme` is here to
# prove: replacement must not touch it.
THESAURUS = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:TechniqueScheme a skos:ConceptScheme ; rdfs:label "Techniques" .
the:watercolorTechnique a skos:Concept, vad:WatercolorTechnique ;
    rdfs:label "watercolor technique" ; skos:inScheme the:TechniqueScheme .
the:wash a skos:Concept ; rdfs:label "wash" ;
    skos:broader the:watercolorTechnique ; skos:inScheme the:TechniqueScheme .
the:offScheme a skos:Concept, vad:WatercolorTechnique ;
    rdfs:label "in no scheme" .
"""

WORK_RECORD = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix work: <http://visualartsdna.org/work/> .
work:w1 rdfs:label "Study" .
"""


def _env(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    ops.write_text("metacontent/model/cwva.ttl", ONTOLOGY, make_parents=True)
    ops.write_text("metacontent/vocab/thesaurus.ttl", THESAURUS, make_parents=True)
    ops.write_text("content/ttl/data/w1.ttl", WORK_RECORD, make_parents=True)
    # WITH the model, as `create_app` builds it: the annotation predicates are
    # resolved from it once, so the page does not build the materialized store
    # merely to tick boxes.
    model = Graph().parse(data=ONTOLOGY, format="turtle")
    return build_default_registry(domain=TEST_DOMAIN, model=model), ops, sb


def _env_without_model(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    ops.write_text("metacontent/model/cwva.ttl", ONTOLOGY, make_parents=True)
    ops.write_text("metacontent/vocab/thesaurus.ttl", THESAURUS, make_parents=True)
    ops.write_text("content/ttl/data/w1.ttl", WORK_RECORD, make_parents=True)
    return build_default_registry(domain=TEST_DOMAIN), ops, sb


def test_tool_registered(tmp_path):
    reg, _, _ = _env(tmp_path)
    assert "concept.annotate_work" in reg.names()


def test_annotate_places_most_specific_property(tmp_path):
    reg, ops, sb = _env(tmp_path)
    dr = reg.dispatch("concept.annotate_work", {"subject": "work:w1", "concepts": ["the:wash"]}, ops)
    assert dr.ok, dr.error
    assert dr.result["placed"] == [
        {"property": str(VAD.hasWatercolorTechnique), "concept": str(THE.wash)}
    ]
    # the typed property is merged into the work record, label preserved
    g = Graph().parse(sb.root / "content/ttl/data/w1.ttl", format="turtle")
    assert (WORK.w1, VAD.hasWatercolorTechnique, THE.wash) in g
    assert (WORK.w1, RDFS.label, None) in g


def test_non_thesaurus_concepts_are_filtered(tmp_path):
    reg, ops, sb = _env(tmp_path)
    # a work: concept is not a thesaurus concept -> dropped by the interactive filter
    dr = reg.dispatch(
        "concept.annotate_work",
        {"subject": "work:w1", "concepts": ["the:wash", "work:somethingElse"]},
        ops,
    )
    assert dr.ok
    assert len(dr.result["placed"]) == 1  # only the: concept annotated


TIE_ONTOLOGY = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix vad: <http://visualartsdna.org/model/> .
vad:VisualAnalysis a owl:Class .
vad:Composition a owl:Class ; rdfs:subClassOf vad:VisualAnalysis .
vad:ArtCriticism a owl:Class ; rdfs:subClassOf vad:VisualAnalysis .
vad:hasComposition a owl:ObjectProperty ; rdfs:range vad:Composition .
vad:hasCriticism a owl:ObjectProperty ; rdfs:range vad:ArtCriticism .
"""

# broken hierarchy: the concept reaches two unrelated typed branches -> tie
TIE_THESAURUS = """
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:Composition a skos:Concept, vad:Composition .
the:Criticism a skos:Concept, vad:ArtCriticism .
the:CrowdHingeBand a skos:Concept ; skos:broader the:Composition, the:Criticism .
"""


def test_tie_is_recorded_in_ledger_and_one_property_placed(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    ops.write_text("metacontent/model/cwva.ttl", TIE_ONTOLOGY, make_parents=True)
    ops.write_text("metacontent/vocab/thesaurus.ttl", TIE_THESAURUS, make_parents=True)
    ops.write_text("content/ttl/data/w1.ttl", WORK_RECORD, make_parents=True)
    reg = build_default_registry(domain=TEST_DOMAIN)

    dr = reg.dispatch("concept.annotate_work", {"subject": "work:w1", "concepts": ["the:CrowdHingeBand"]}, ops)
    assert dr.ok
    # adjudicated: exactly one property placed (never the tied pair)
    assert len(dr.result["placed"]) == 1
    assert len(dr.result["ties"]) == 1
    assert set(dr.result["ties"][0]["candidates"]) == {str(VAD.hasComposition), str(VAD.hasCriticism)}
    # the tie is recorded in the hygiene ledger for structural repair
    ledger = HygieneLedger.from_ttl(ops.read_text(".qa/hygiene_ledger.ttl"))
    ties = ledger.ties()
    assert len(ties) == 1
    assert ties[0]["subject"] == str(WORK.w1)
    assert ties[0]["concept"] == str(THE.CrowdHingeBand)


# -- Editing an annotation (Rick, 2026-09-18) ---------------------------------


def _dispatch(reg, ops, name, **args):
    return reg.dispatch(name, args, ops)


def test_current_annotations_reads_the_record_WITHOUT_the_store(tmp_path, monkeypatch):
    """Ticking the current concepts used to ask the placement rule itself, which
    needs the RDFS-materialized store — 25 seconds on Rick's data, and the
    reason opening the page took sixteen. It asks the record and the model now.

    Monkeypatched IN PROCESS on purpose: through the app the handler runs in the
    forked worker, where a patch here would be invisible and this test would
    pass whatever the code did.
    """
    import cwva_dashboard.workflows.annotate as mod

    reg, ops, _sb = _env(tmp_path)
    _dispatch(reg, ops, "concept.annotate_work",
              subject="work:w1", concepts=["the:wash"])

    monkeypatch.setattr(mod, "_load_store", _boom)
    got = _dispatch(reg, ops, "concept.current_annotations", subject="work:w1")

    assert got.ok, got.error
    assert got.result["concepts"] == ["the:wash"]


def _boom(*_a, **_k):
    raise AssertionError("ticking the current concepts must not build the store")


def test_annotating_again_REPLACES_the_selection(tmp_path):
    reg, ops, _sb = _env(tmp_path)
    _dispatch(reg, ops, "concept.annotate_work",
              subject="work:w1", concepts=["the:wash", "the:watercolorTechnique"])

    got = _dispatch(reg, ops, "concept.annotate_work",
                    subject="work:w1", concepts=["the:wash"])

    g = Graph().parse(data=ops.read_text("content/ttl/data/w1.ttl"), format="turtle")
    objects = set(g.objects(WORK.w1, None))
    assert THE.wash in objects
    assert THE.watercolorTechnique not in objects
    assert got.result["discarded"] == [
        {"property": str(VAD.hasWatercolorTechnique),
         "concept": str(THE.watercolorTechnique)}
    ]


def test_replace_LEAVES_A_TAG_ALONE(tmp_path):
    """`the:tag` is range-less in the thesaurus, so no tag can be an annotation.
    The rule is structural: nothing here lists tags as an exception."""
    reg, ops, _sb = _env(tmp_path)
    ops.write_text(
        "content/ttl/data/w1.ttl",
        WORK_RECORD + "@prefix the: <http://visualartsdna.org/thesaurus/> .\n"
        "work:w1 the:tag the:wash .\n",
    )

    _dispatch(reg, ops, "concept.annotate_work",
              subject="work:w1", concepts=["the:watercolorTechnique"])

    g = Graph().parse(data=ops.read_text("content/ttl/data/w1.ttl"), format="turtle")
    assert (WORK.w1, THE.tag, THE.wash) in g


def test_replace_can_be_turned_OFF_for_the_batch_path(tmp_path):
    """#15 consumes one queue file at a time and knows nothing about what
    another contributed, so it stays additive."""
    reg, ops, _sb = _env(tmp_path)
    _dispatch(reg, ops, "concept.annotate_work",
              subject="work:w1", concepts=["the:watercolorTechnique"])

    _dispatch(reg, ops, "concept.annotate_work",
              subject="work:w1", concepts=["the:wash"], replace=False)

    g = Graph().parse(data=ops.read_text("content/ttl/data/w1.ttl"), format="turtle")
    objects = set(g.objects(WORK.w1, None))
    assert THE.wash in objects and THE.watercolorTechnique in objects


def test_with_NO_MODEL_ticking_falls_back_to_the_store(tmp_path):
    """Ticking and discarding must agree. An empty predicate set would tick
    nothing and discard everything — a data-loss trap wearing the shape of an
    empty form — so both paths ask the same function, which falls back."""
    reg, ops, _sb = _env_without_model(tmp_path)
    _dispatch(reg, ops, "concept.annotate_work",
              subject="work:w1", concepts=["the:wash"])

    got = _dispatch(reg, ops, "concept.current_annotations", subject="work:w1")

    assert got.result["concepts"] == ["the:wash"]


def test_replacement_LEAVES_ALONE_what_the_picker_never_OFFERED(tmp_path):
    """Rick's record lost `vad:hasPaper the:FabrianoArtisticoGranaFinaColdPress`
    this way (2026-09-18). The paper is in `ArtMaterialScheme`, his picker was
    narrowed to two other schemes, and replacement read "absent from the
    selection" as "the user removed it".

    A concept the form never showed is a concept the user had no ability to
    keep. Here `the:offScheme` is in no scheme at all, so the picker cannot show
    it and replacement must not touch it.
    """
    reg, ops, _sb = _env(tmp_path)
    _dispatch(reg, ops, "concept.annotate_work", subject="work:w1",
              concepts=["the:offScheme", "the:wash"])
    g = Graph().parse(data=ops.read_text("content/ttl/data/w1.ttl"), format="turtle")
    assert THE.offScheme in set(g.objects(WORK.w1, None)), "placed in the first place"

    _dispatch(reg, ops, "concept.annotate_work", subject="work:w1",
              concepts=["the:wash"])

    g = Graph().parse(data=ops.read_text("content/ttl/data/w1.ttl"), format="turtle")
    objects = set(g.objects(WORK.w1, None))
    assert THE.offScheme in objects, "not offered, so not discardable"
    assert THE.wash in objects


def test_current_annotations_reports_what_is_OUTSIDE_the_picker(tmp_path):
    """It has no checkbox, so it can be neither ticked nor removed. Said out
    loud, because a concept on the record that the page does not show is
    exactly the thing a user goes looking for later."""
    reg, ops, _sb = _env(tmp_path)
    _dispatch(reg, ops, "concept.annotate_work", subject="work:w1",
              concepts=["the:offScheme", "the:wash"])

    got = _dispatch(reg, ops, "concept.current_annotations", subject="work:w1")

    assert got.result["concepts"] == ["the:wash"]
    assert got.result["outside"] == ["the:offScheme"]
