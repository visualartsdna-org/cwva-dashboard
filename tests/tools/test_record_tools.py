"""record.new_work: faithful ParseRDF.printTtl mapping, staged as isomorphic TTL
in the QA content tree."""

from __future__ import annotations

import pytest
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS, XSD

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.fileops_tools import build_default_registry
from cwva_dashboard.tools.record_tools import work_namespace, SCHEMA, THE, VAD

from conftest import TEST_DOMAIN

WORK = work_namespace(TEST_DOMAIN)

FULL = dict(
    type="Watercolor",
    label="Mysterious Creature",
    description="Through the trees lurks a creature.",
    height=9,
    width=12,
    units="inch",
    recorded_date="2026-05-25",
    completed_date="2026-05-17",
    has_paper="the:StrathmoreWatercolorColdPressBlock",
    has_artist_profile="work:817ca809-9beb-411b-b434-d8699298e65e",
    image="IMG_1525.JPG",
)


@pytest.fixture
def env(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    return build_default_registry(domain=TEST_DOMAIN), FileOps(sb), sb


def _make(reg, ops, **overrides):
    args = {**FULL, **overrides}
    dr = reg.dispatch("record.new_work", args, ops)
    assert dr.ok, dr.error
    return dr.result


def _graph(sb, result):
    return Graph().parse(sb.root / result["path"], format="turtle")


def test_registered(env):
    reg, _, _ = env
    assert "record.new_work" in reg.names()


def test_new_work_maps_core_fields(env):
    reg, ops, sb = env
    res = _make(reg, ops, guid="abc-123")
    assert res["guid"] == "abc-123"
    assert res["path"] == "content/ttl/data/abc-123.ttl"  # placement map (§3.6)

    g = _graph(sb, res)
    subj = WORK["abc-123"]
    assert (subj, RDF.type, VAD.Watercolor) in g
    assert (subj, RDFS.label, Literal("Mysterious Creature")) in g
    assert (subj, SCHEMA.identifier, Literal("abc-123")) in g
    assert (subj, SCHEMA.datePublished, Literal("2026-05-25", datatype=XSD.date)) in g
    assert (subj, VAD.hasPaper, URIRef("http://visualartsdna.org/thesaurus/StrathmoreWatercolorColdPressBlock")) in g
    assert (subj, SCHEMA.image, URIRef("http://visualartsdna.org/images/IMG_1525.JPG")) in g


def test_quantitative_value_bnodes(env):
    reg, ops, sb = env
    g = _graph(sb, _make(reg, ops, guid="q1"))
    subj = WORK["q1"]
    h = g.value(subj, SCHEMA.height)
    assert (h, RDF.type, SCHEMA.QuantitativeValue) in g
    assert (h, SCHEMA.unitCode, Literal("INH")) in g
    assert (h, SCHEMA.value, Literal("9", datatype=XSD.float)) in g
    assert (h, RDFS.label, Literal("9 inches")) in g


def test_guid_minted_when_omitted(env):
    reg, ops, sb = env
    res = _make(reg, ops)
    assert len(res["guid"]) == 36  # uuid4
    assert (sb.root / res["path"]).exists()


def test_optional_fields_omitted_when_absent(env):
    reg, ops, sb = env
    g = _graph(sb, _make(reg, ops, guid="o1"))  # no note/location
    subj = WORK["o1"]
    assert g.value(subj, URIRef("http://www.w3.org/2004/02/skos/core#note")) is None
    assert g.value(subj, SCHEMA.location) is None


def test_qrcode_is_derived_not_supplied(env):
    """D1: qrcode is derived from guid + image base, always present, and is NOT
    an input parameter (supplying it is an unknown_param)."""
    reg, ops, sb = env
    g = _graph(sb, _make(reg, ops, guid="o2"))
    subj = WORK["o2"]
    assert g.value(subj, VAD.qrcode) == URIRef(
        "http://visualartsdna.org/images/qrc_o2.jpg"
    )
    dr = reg.dispatch("record.new_work", {**FULL, "guid": "o3", "qrcode": "x"}, ops)
    assert not dr.ok and dr.error["code"] == "unknown_param"


def test_work_on_site_is_not_written_and_not_a_param(env):
    """Q2: updateWorkOnSite (#9) is the single writer of vad:workOnSite; the
    record tool neither writes it nor accepts it."""
    reg, ops, sb = env
    g = _graph(sb, _make(reg, ops, guid="o4"))
    assert g.value(WORK["o4"], VAD.workOnSite) is None
    dr = reg.dispatch(
        "record.new_work", {**FULL, "guid": "o5", "work_on_site": "http://x"}, ops
    )
    assert not dr.ok and dr.error["code"] == "unknown_param"


def test_bad_units_is_structured_error(env):
    reg, ops, _ = env
    dr = reg.dispatch("record.new_work", {**FULL, "units": "furlongs"}, ops)
    assert not dr.ok  # now caught by the units enum at dispatch
    assert dr.error["code"] == "not_in_enum"


# --- affordance step 4: closed sets enforced (or suggested) at dispatch ------


def test_bad_date_format_is_rejected_at_dispatch(env):
    reg, ops, _ = env
    dr = reg.dispatch("record.new_work", {**FULL, "recorded_date": "May 25 2026"}, ops)
    assert not dr.ok and dr.error["code"] == "bad_format"


def test_entity_type_is_a_strict_enum(env):
    """Entity type is dispatch-enforced (real data conforms to the closed set)."""
    reg, ops, _ = env
    dr = reg.dispatch(
        "record.new_entity", {**ENTITY, "type": "Criticism"}, ops
    )  # Criticism is a topic, not an entity type
    assert not dr.ok and dr.error["code"] == "not_in_enum"


def test_work_type_suggested_set_is_not_enforced(env):
    """F1: work/digital type is x-enum-suggested (render hint), NOT dispatch-
    enforced — real data exceeds the form set (NFT/Proof; the Lindenmayer casing
    fork), so a value outside the suggested set must still be accepted."""
    reg, ops, _ = env
    dr = reg.dispatch("record.new_work", {**FULL, "guid": "nft1", "type": "NFT"}, ops)
    assert dr.ok, dr.error


def test_output_is_valid_parseable_ttl(env):
    reg, ops, sb = env
    res = _make(reg, ops, guid="p1")
    # rdflib round-trips it; the record is a single subject with 2 QV bnodes.
    g = _graph(sb, res)
    assert len(list(g.subjects(RDF.type, VAD.Watercolor))) == 1
    assert res["triples"] == len(g)


# The oracle's actual output for one real record (support/ParseRDF.printTtl,
# from ~/cwva-py/main/sample-data). Embedded so the parity check is CI-safe.
ORACLE_SAMPLE = """
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .
work:9ab1a6d0-fcac-4396-bb6f-60d2464b18be
    a vad:Watercolor ;
    rdfs:label "Mysterious Creature" ;
    schema:identifier "9ab1a6d0-fcac-4396-bb6f-60d2464b18be" ;
    schema:description \"\"\"Through the trees lurks a creature.\"\"\" ;
    skos:note \"\"\"A study with tube watercolors and palette knife.\"\"\" ;
    schema:datePublished "2026-05-25"^^xs:date ;
    schema:dateCreated "2026-05-17"^^xs:date ;
    vad:hasPaper the:StrathmoreWatercolorColdPressBlock ;
    vad:hasArtistProfile work:817ca809-9beb-411b-b434-d8699298e65e ;
    vad:qrcode <http://visualartsdna.org/images/qrc_9ab1a6d0-fcac-4396-bb6f-60d2464b18be.jpg> ;
    schema:image <http://visualartsdna.org/images/IMG_1525.JPG> ;
    schema:height [ a schema:QuantitativeValue ; rdfs:label "9 inches" ;
        schema:unitCode "INH" ; schema:value "9"^^xs:float ] ;
    schema:width [ a schema:QuantitativeValue ; rdfs:label "12 inches" ;
        schema:unitCode "INH" ; schema:value "12"^^xs:float ] ;
    .
"""


def test_parity_isomorphic_with_oracle_output(env):
    """The ported record is graph-for-graph identical to the Groovy oracle's
    output for the same fields (bnode-safe isomorphic compare)."""
    from rdflib.compare import graph_diff

    reg, ops, sb = env
    res = _make(
        reg, ops,
        guid="9ab1a6d0-fcac-4396-bb6f-60d2464b18be",
        note="A study with tube watercolors and palette knife.",
        has_artist_profile="work:817ca809-9beb-411b-b434-d8699298e65e",
    )
    generated = _graph(sb, res)
    oracle = Graph().parse(data=ORACLE_SAMPLE, format="turtle")

    _both, only_oracle, only_generated = graph_diff(oracle, generated)
    assert len(only_oracle) == 0, only_oracle.serialize(format="turtle")

    # ONE deliberate difference, and not a parity break. The oracle's store is
    # an inference model and `vad:hasPaper` declares
    # `rdfs:domain vad:CreativeWork`, so the Groovy got that type free at entry
    # and its serializer never had to write it. This dashboard has no reasoner,
    # so it asserts what the oracle only ever entailed. Spelled out as the
    # exact triple rather than relaxed to a count, so a SECOND divergence
    # still fails.
    subj = WORK["9ab1a6d0-fcac-4396-bb6f-60d2464b18be"]
    assert set(only_generated) == {(subj, RDF.type, VAD.CreativeWork)}, \
        only_generated.serialize(format="turtle")


def test_a_work_is_dual_typed_leaf_and_CreativeWork(env):
    """The leaf says what KIND of thing it is; `vad:CreativeWork` says THAT IT
    IS ONE. They are siblings under `vad:ArtRealization`, so the second is not
    entailed by the first and has to be written."""
    reg, ops, sb = env
    g = _graph(sb, _make(reg, ops, guid="cw1"))
    subj = WORK["cw1"]
    assert (subj, RDF.type, VAD.Watercolor) in g
    assert (subj, RDF.type, VAD.CreativeWork) in g
    assert set(g.objects(subj, RDF.type)) == {VAD.Watercolor, VAD.CreativeWork}


# --- record.new_entity (#3 Entity) ---------------------------------------

ENTITY = dict(
    type="Article",  # a real entity type (Criticism is a topic, not an entity type)
    label="On Saint Mark's",
    topic=["the:Criticism"],
    definition="A critical reading of the watercolor.",
    recorded_date="2026-06-01",
)


def _make_entity(reg, ops, **overrides):
    dr = reg.dispatch("record.new_entity", {**ENTITY, **overrides}, ops)
    assert dr.ok, dr.error
    return dr.result


def test_entity_registered(env):
    reg, _, _ = env
    assert "record.new_entity" in reg.names()


def test_entity_always_sets_the_scheme(env):
    reg, ops, sb = env
    g = _graph(sb, _make_entity(reg, ops, guid="e1"))
    subj = WORK["e1"]
    assert (subj, RDF.type, THE.Article) in g
    assert (subj, THE.topic, THE.Criticism) in g  # media stays a topic
    assert (subj, SKOS.definition, Literal("A critical reading of the watercolor.")) in g
    assert (subj, SKOS.inScheme, THE.entities) in g


def test_an_entity_carries_EXACTLY_ONE_rdf_type(env):
    """The leaf and nothing above it.

    Seventy entities in the store carry four — the leaf plus `the:Entity`
    (a real superclass: `the:AI rdfs:subClassOf the:Entity`), `skos:Concept`
    (entailed from `skos:inScheme`, whose SKOS domain it is) and
    `rdfs:Resource`. All three are ANCESTRY, materialized by the old server's
    inference model, and the ontology says them already.

    Note this is the opposite action to the work forms, where
    `vad:CreativeWork` is written explicitly: there it is a SIBLING of the leaf
    under `vad:ArtRealization`, so nothing entails it. Same leaf rule, opposite
    consequence, because the facts differ.
    """
    reg, ops, sb = env
    g = _graph(sb, _make_entity(reg, ops, guid="et1"))
    assert set(g.objects(WORK["et1"], RDF.type)) == {THE.Article}


def test_a_new_entity_does_NOT_carry_the_deprecated_FLAG(env):
    """`the:conceptsExtracted` was the pre-DTS workflow boolean and the Groovy
    wrote it on every entity (EntityEntry.groovy:134). DTS's six stamps
    replaced it on 2026-09-30 — "follow the new audit stamp rules" — but it
    went on being written, so a new entity carried `false` forever.

    The browser renders it as `derived: false` (the ontology labels it
    "derived"), one row above DTS's own `ops:derived` and contradicting it
    (Rick, 2026-10-02)."""
    reg, ops, sb = env
    g = _graph(sb, _make_entity(reg, ops, guid="e1"))

    assert (WORK["e1"], THE.conceptsExtracted, None) not in g


def test_entity_multi_topic_images_tags_notes(env):
    reg, ops, sb = env
    g = _graph(sb, _make_entity(
        reg, ops, guid="e2",
        topic=["the:Criticism", "the:Composition"],
        images=["a.jpg", "b.jpg"],
        tags=["work:817ca809-9beb-411b-b434-d8699298e65e"],
        notes=[{"type": "editorialNote", "text": "seen at gallery"}, {"text": "plain note"}],
    ))
    subj = WORK["e2"]
    assert set(g.objects(subj, THE.topic)) == {THE.Criticism, THE.Composition}
    assert URIRef("http://visualartsdna.org/images/a.jpg") in set(g.objects(subj, SCHEMA.image))
    # durable instance-linkage tag (never a pipeline artifact)
    assert (subj, THE.tag, WORK["817ca809-9beb-411b-b434-d8699298e65e"]) in g
    assert (subj, SKOS.editorialNote, Literal("seen at gallery")) in g
    assert (subj, SKOS.note, Literal("plain note")) in g


def test_entity_optional_documents(env):
    reg, ops, sb = env
    g = _graph(sb, _make_entity(reg, ops, guid="e3",
                                md_document="x.md",  # bare name -> documents base (Q4)
                                pdf_document="http://elsewhere.org/y.pdf"))  # full URL kept
    subj = WORK["e3"]
    assert (subj, THE.mdDocument, URIRef("http://visualartsdna.org/documents/x.md")) in g
    assert (subj, THE.pdfDocument, URIRef("http://elsewhere.org/y.pdf")) in g


def test_the_gdoc_source_bnode_is_no_longer_written(env):
    """`the:document` held a Google Docs link as a bnode labelled "gdoc source".
    Removed 2026-09-07: those reference links are not dependable enough to
    record. The parameter is gone from the schema, so passing one is now an
    unknown parameter rather than a silently-written triple."""
    reg, ops, _ = env
    dr = reg.dispatch(
        "record.new_entity",
        {**ENTITY, "guid": "e3b", "document": "http://docs.google.com/d/abc"}, ops,
    )
    assert not dr.ok and dr.error["code"] == "unknown_param"


def test_dbpedia_is_no_longer_accepted(env):
    """The wikipedia link covers the same referent in human-readable form; a
    dbpedia URI can live in primary_site (schema:sameAs) if one is wanted."""
    reg, ops, _ = env
    dr = reg.dispatch(
        "record.new_entity",
        {**ENTITY, "guid": "e3c", "dbpedia": "http://dbpedia.org/page/Colour"}, ops,
    )
    assert not dr.ok and dr.error["code"] == "unknown_param"


def test_entity_guid_minted(env):
    reg, ops, sb = env
    res = _make_entity(reg, ops)
    assert len(res["guid"]) == 36 and (sb.root / res["path"]).exists()


# --- record.new_digital (#2 RDF Digital) ---------------------------------

DIGITAL = dict(
    type="LindenmayerSystemImage",  # Q6: canonical casing (lower m)
    label="Recursive Fern",
    description="An L-system fern.",
    note="Rendered at 4k.",
    height=1080,
    width=1920,
    depth=0,
    units="pixel",
    recorded_date="2026-06-10",
    completed_date="2026-06-09",
    has_artist_profile="work:817ca809-9beb-411b-b434-d8699298e65e",
    image="fern.png",
)


def _make_digital(reg, ops, **overrides):
    dr = reg.dispatch("record.new_digital", {**DIGITAL, **overrides}, ops)
    assert dr.ok, dr.error
    return dr.result


def test_digital_registered(env):
    reg, _, _ = env
    assert "record.new_digital" in reg.names()


def test_digital_core_and_three_dimensions(env):
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="d1"))
    subj = WORK["d1"]
    assert (subj, RDF.type, VAD.LindenmayerSystemImage) in g
    assert (subj, SKOS.note, Literal("Rendered at 4k.")) in g
    # three QuantitativeValue dimensions (digital adds depth).
    dims = {g.value(subj, p) for p in (SCHEMA.height, SCHEMA.width, SCHEMA.depth)}
    assert None not in dims and len(dims) == 3
    depth = g.value(subj, SCHEMA.depth)
    assert (depth, SCHEMA.unitCode, Literal("E37")) in g  # pixel


def test_digital_optional_3d_and_background(env):
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="d2",
                                 image="fern.png", image3d="fern.glb", background="the:Black"))
    subj = WORK["d2"]
    assert (subj, SCHEMA.image, URIRef("http://visualartsdna.org/images/fern.png")) in g
    assert (subj, VAD.image3d, URIRef("http://visualartsdna.org/images/fern.glb")) in g
    assert (subj, VAD.background, THE.Black) in g


def test_a_digital_work_is_dual_typed_even_with_no_3d_or_background(env):
    """The four Blender compositions among the thirteen untyped works are
    exactly this case: `vad:background` and `vad:image3d` are the digital
    form's only `rdfs:domain vad:CreativeWork` properties and both are
    optional, so an entailed type would have been absent here."""
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="dcw1"))
    subj = WORK["dcw1"]
    assert g.value(subj, VAD.image3d) is None
    assert g.value(subj, VAD.background) is None
    assert (subj, RDF.type, VAD.LindenmayerSystemImage) in g
    assert (subj, RDF.type, VAD.CreativeWork) in g


def test_an_entity_is_NOT_a_CreativeWork(env):
    """Entities are not works: they are `skos:inScheme the:entities` and typed
    in the thesaurus namespace. Dual-typing is scoped to the work forms."""
    reg, ops, sb = env
    g = _graph(sb, _make_entity(reg, ops, guid="ecw1"))
    assert (WORK["ecw1"], RDF.type, VAD.CreativeWork) not in g


def test_digital_omits_3d_when_absent(env):
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="d3"))
    assert g.value(WORK["d3"], VAD.image3d) is None


# --- identity & namespaces (CE_DESIGN §13): work: is sovereign, vad:/the: commons

def test_domain_derives_work_namespace_and_image_base_keeps_commons(tmp_path):
    from cwva_dashboard.tools.record_tools import build_record_tools
    from cwva_dashboard.tools.registry import ToolRegistry

    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    reg = ToolRegistry()
    for t in build_record_tools("http://debbiesDomain.art"):
        reg.register(t)

    dr = reg.dispatch(
        "record.new_work",
        {**FULL, "guid": "d1", "has_artist_profile": "work:xyz"},
        ops,
    )
    assert dr.ok, dr.error
    subj = URIRef("http://debbiesDomain.art/work/d1")
    assert dr.result["uri"] == str(subj)  # sovereign work: under the deployer's domain
    g = Graph().parse(sb.root / dr.result["path"], format="turtle")

    # image base derives from the domain too
    assert (subj, SCHEMA.image, URIRef("http://debbiesDomain.art/images/IMG_1525.JPG")) in g
    # a work: CURIE resolves under the deployer's domain
    assert (subj, VAD.hasArtistProfile, URIRef("http://debbiesDomain.art/work/xyz")) in g
    # vad:/the: are commons — NEVER derived from domain
    assert (subj, RDF.type, VAD.Watercolor) in g
    assert (subj, VAD.hasPaper,
            URIRef("http://visualartsdna.org/thesaurus/StrathmoreWatercolorColdPressBlock")) in g


# --- schema:video (2026-09): a schema.org VideoObject blank node, entirely
# optional, with label/name/thumbnail DERIVED from the filename.

def test_digital_omits_video_when_absent(env):
    """The default digital record has no video, so the property is ABSENT — not
    an empty VideoObject. Optionality is the whole contract here."""
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="v0"))
    assert g.value(WORK["v0"], SCHEMA.video) is None


def test_digital_video_blank_node_shape(env):
    reg, ops, sb = env
    g = _graph(sb, _make_digital(
        reg, ops, guid="v1",
        video="LastSupperOrbit.mp4",
        video_description="Video of the sculpture in a modelviewer presentation.",
        video_duration="PT34S",
        video_upload_date="2026-08-17",
    ))
    bn = g.value(WORK["v1"], SCHEMA.video)
    assert bn is not None
    # schema:VideoObject and nothing else: rdfs:Resource is entailed of every
    # node, so stating it would be noise in the file.
    assert list(g.objects(bn, RDF.type)) == [SCHEMA.VideoObject]
    base = "http://visualartsdna.org/images/"
    assert (bn, SCHEMA.contentUrl, URIRef(base + "LastSupperOrbit.mp4")) in g
    assert (bn, SCHEMA.thumbnailUrl,
            URIRef(base + "LastSupperOrbit_thumbnail.jpg")) in g
    assert (bn, SCHEMA.duration,
            Literal("PT34S", datatype=XSD.duration)) in g
    assert (bn, SCHEMA.uploadDate,
            Literal("2026-08-17", datatype=XSD.date)) in g


def test_digital_video_title_derived_from_camelcase_filename(env):
    """label and name are DERIVED, never typed: the user picks a file, not a
    title, so the two can never disagree."""
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="v2", video="LastSupperOrbit.mp4"))
    bn = g.value(WORK["v2"], SCHEMA.video)
    assert (bn, RDFS.label, Literal("Last Supper Orbit")) in g
    assert (bn, SCHEMA.name, Literal("Last Supper Orbit")) in g


def test_digital_video_upload_date_defaults_to_today(env):
    from datetime import date

    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="v3", video="Orbit.webm"))
    bn = g.value(WORK["v3"], SCHEMA.video)
    assert (bn, SCHEMA.uploadDate,
            Literal(date.today().isoformat(), datatype=XSD.date)) in g


def test_digital_video_omits_duration_when_unknown(env):
    """No probe and no typed value -> no schema:duration. Omitting a fact is
    correct; a guessed duration would be a wrong fact in the record."""
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="v4", video="Orbit.mp4"))
    bn = g.value(WORK["v4"], SCHEMA.video)
    assert g.value(bn, SCHEMA.duration) is None
    # The DESCRIPTION is different in kind, and since 2026-09-16 is derived
    # rather than omitted (Rick: "I'm more concerned about the video object
    # metadata being missing than not being specific enough"). A duration can
    # only be measured; a description can be written from what the record
    # already says, without claiming anything about the footage.
    assert "Video of" in str(g.value(bn, SCHEMA.description))


def test_digital_video_duration_is_enforced_at_dispatch(env):
    """The manual fallback field is a CLOSED format, not free text: rdflib will
    happily serialize an ill-formed xs:duration and the parse gate would pass
    it, so dispatch is the boundary that says no."""
    reg, ops, _ = env
    dr = reg.dispatch(
        "record.new_digital",
        {**DIGITAL, "guid": "v5", "video": "Orbit.mp4", "video_duration": "34 seconds"},
        ops,
    )
    assert not dr.ok
    assert dr.error["code"] == "bad_format"


def test_digital_video_field_offers_only_playable_kinds(env):
    """Offered == enforced: the picker's kind must be `video`, so it lists what
    the browser can play rather than every image in the drop folder."""
    reg, _, _ = env
    from cwva_dashboard.inbox import DEFAULT_EXTENSIONS

    schema = next(t for t in reg.schemas() if t["name"] == "record.new_digital")
    spec = schema["inputSchema"]["properties"]["video"]
    assert spec["x-file-kind"] == "video"
    assert set(DEFAULT_EXTENSIONS["video"]) == {".mp4", ".webm", ".ogg", ".ogv"}


# --- record.list_referents: background images, sourced from CONTENT ----------
#
# Backgrounds are not thesaurus concepts. They are ordinary entity records
# (`a the:Image` with `the:topic the:Background`), independent of any work and
# reusable across many, so their candidates come from the record store.

BACKGROUND_STORE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .
work:bg1 a the:Image ; rdfs:label "Studio Wall" ; the:topic the:Background .
work:bg2 a the:Image ; rdfs:label "Blue Sky" ; the:topic the:Background .
work:p1  a the:Image ; rdfs:label "A Portrait" ; the:topic the:Portrait .
work:c1  a the:Collection ; rdfs:label "Unmoored Background Collection" ;
    the:topic the:Background .
"""


@pytest.fixture
def store(env):
    reg, ops, sb = env
    ops.write_text("content/ttl/data/bgs.ttl", BACKGROUND_STORE, make_parents=True)
    return reg, ops, sb


def _referents(reg, ops, name="backgrounds"):
    dr = reg.dispatch("record.list_referents", {"referent": name}, ops)
    assert dr.ok, dr.error
    return dr.result["candidates"]


def test_backgrounds_are_offered_as_CURIE_and_label(store):
    reg, ops, _ = store
    got = _referents(reg, ops)

    assert {c["value"] for c in got} == {"work:bg1", "work:bg2"}
    assert [c["label"] for c in got] == ["Blue Sky", "Studio Wall"]  # sorted


def test_an_image_with_another_topic_is_not_a_background(store):
    reg, ops, _ = store
    assert "work:p1" not in {c["value"] for c in _referents(reg, ops)}


def test_a_background_COLLECTION_is_not_a_background(store):
    """Real data has three: `Unmoored Background Collection` and friends carry
    `the:topic the:Background` but are `the:Collection`, not `the:Image`. They
    group backgrounds; they are not one. The type condition is what separates
    them, which is why the referent needs both conditions and not just topic."""
    reg, ops, _ = store
    assert "work:c1" not in {c["value"] for c in _referents(reg, ops)}


def test_an_unknown_referent_is_refused(store):
    reg, ops, _ = store
    dr = reg.dispatch("record.list_referents", {"referent": "nonsense"}, ops)
    assert not dr.ok and dr.error["code"] == "not_in_enum"


def test_the_offered_set_IS_the_gate_condition(store):
    """One table, two readers. The picker cannot offer what the gate refuses."""
    from cwva_dashboard.referents import REFERENTS

    reg, ops, sb = store
    from rdflib import Graph

    g = Graph().parse(sb.root / "content/ttl/data/bgs.ttl", format="turtle")
    ref = REFERENTS["backgrounds"]
    offered = {c["value"] for c in _referents(reg, ops)}
    accepted = {
        f"work:{str(s).rsplit('/', 1)[-1]}"
        for s in g.subjects()
        if ref.satisfied_by(g, s)
    }
    assert offered == accepted


# --- the conditional rule: a 3D object needs a background -------------------


def test_a_3D_object_requires_a_background(env):
    """Conditional on another field, so JSON Schema cannot state it — and it
    belongs in the TOOL, not only in the route: a rule the form enforces and the
    tool does not is a rule the agent does not have."""
    reg, ops, _ = env
    dr = reg.dispatch(
        "record.new_digital", {**DIGITAL, "guid": "b1", "image3d": "fern.glb"}, ops
    )
    assert not dr.ok
    assert dr.error["code"] == "missing_required"
    assert "background is required" in dr.error["message"]


def test_a_3D_object_with_a_background_is_accepted(env):
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="b2",
                                 image3d="fern.glb", background="work:bg1"))
    assert (WORK["b2"], VAD.background, WORK["bg1"]) in g


def test_a_background_without_a_3D_object_is_still_allowed(env):
    """The rule is one-directional: a background alone is not an error."""
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="b3", background="work:bg1"))
    assert (WORK["b3"], VAD.background, WORK["bg1"]) in g


def test_neither_is_the_ordinary_case(env):
    reg, ops, sb = env
    g = _graph(sb, _make_digital(reg, ops, guid="b4"))
    assert g.value(WORK["b4"], VAD.background) is None


# --- record.new_entity: note kinds are a REAL enum ---------------------------

ENTITY_FOR_NOTES = dict(
    type="Article",
    label="Colour and Light",
    topic=["the:Criticism"],
    definition="An essay about colour.",
    recorded_date="2026-09-07",
)


def test_a_note_kind_outside_the_set_is_refused_at_dispatch(env):
    """`validate_args` did not recurse into object items, so the form offered
    six kinds and nothing enforced them — any caller that was not the form could
    mint `skos:<anything>`."""
    reg, ops, _ = env
    dr = reg.dispatch(
        "record.new_entity",
        {**ENTITY_FOR_NOTES, "guid": "n1", "notes": [{"type": "evilNote", "text": "x"}]},
        ops,
    )
    assert not dr.ok and dr.error["code"] == "not_in_enum"


def test_a_note_without_text_is_refused(env):
    reg, ops, _ = env
    dr = reg.dispatch(
        "record.new_entity",
        {**ENTITY_FOR_NOTES, "guid": "n2", "notes": [{"type": "note"}]}, ops,
    )
    assert not dr.ok and dr.error["code"] == "missing_param"


def test_valid_notes_become_skos_properties(env):
    reg, ops, sb = env
    dr = reg.dispatch(
        "record.new_entity",
        {**ENTITY_FOR_NOTES, "guid": "n3", "notes": [
            {"type": "scopeNote", "text": "For the newsletter."},
            {"type": "note", "text": "Second."},
        ]},
        ops,
    )
    assert dr.ok, dr.error
    g = _graph(sb, dr.result)
    assert (WORK["n3"], SKOS.scopeNote, Literal("For the newsletter.")) in g
    assert (WORK["n3"], SKOS.note, Literal("Second.")) in g


# --- collision detection is CASE-INSENSITIVE ---------------------------------
#
# As IRIs, `.../Sunset.jpg` and `.../sunset.JPG` are genuinely different, and on
# Linux or in a GCS bucket they are two files. On Windows and default macOS they
# are ONE — so ingesting the second overwrites the first work's image while an
# exact-match check reports nothing. CE targets Linux *and* Windows, so the
# answer must not depend on which one is running.
#
# The real store already contains the case in point: `Sunset.jpg` ("Sunset") and
# `sunset.JPG` ("Just past 6 pm") are two different paintings.

TAKEN_STORE = """@prefix schema: <https://schema.org/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:w1 schema:image <http://visualartsdna.org/images/fileAbc123.JPG> .
work:w2 vad:image3d <http://visualartsdna.org/images/Mesh.GLB> .
"""

IMG = "http://visualartsdna.org/images/"


@pytest.fixture
def taken(env):
    reg, ops, sb = env
    ops.write_text("content/ttl/data/taken.ttl", TAKEN_STORE, make_parents=True)
    return reg, ops, sb


def _taken(reg, ops, name):
    dr = reg.dispatch("record.check_uniqueness", {"files": [IMG + name]}, ops)
    assert dr.ok, dr.error
    return dr.result


@pytest.mark.parametrize(
    "candidate",
    ["fileAbc123.JPG", "fileAbc123.jpg", "FileAbc123.JPG", "FILEABC123.JPG"],
)
def test_a_case_variant_of_a_used_filename_is_TAKEN(taken, candidate):
    reg, ops, _ = taken
    assert _taken(reg, ops, candidate)["files_taken"] == [IMG + candidate]


def test_the_existing_spelling_is_reported(taken):
    """With case the whole point, "already in use" without showing WHAT it
    clashes with is a puzzle rather than a message."""
    reg, ops, _ = taken
    res = _taken(reg, ops, "fileabc123.jpg")

    assert res["taken_uris"][IMG + "fileabc123.jpg"] == IMG + "fileAbc123.JPG"


def test_it_holds_for_every_asset_property_not_just_image(taken):
    """Predicate-agnostic and case-insensitive together — a .glb collides the
    same way a .jpg does."""
    reg, ops, _ = taken
    assert _taken(reg, ops, "mesh.glb")["files_taken"] == [IMG + "mesh.glb"]


def test_a_genuinely_different_name_is_still_free(taken):
    reg, ops, _ = taken
    assert _taken(reg, ops, "fileAbc124.jpg")["files_taken"] == []
    assert _taken(reg, ops, "fileAbc123.png")["files_taken"] == []


# --- a record does not collide with ITSELF ----------------------------------
#
# `Edit form` re-submits the same guid, so the record being rewritten already
# cites its own files — `exclude_subject` is what stops that reading as a
# clash. It worked for `vad:image`, which sits on the work, and failed for
# `schema:video`, which hangs a VideoObject blank node off the work and puts
# `schema:contentUrl` on THAT: the statement's subject is a blank node, matches
# no exclusion, and the user is told to rename a file in a record they are in
# the middle of correcting (Rick, 2026-09-27).

NESTED_STORE = """@prefix schema: <https://schema.org/> .
@prefix work: <http://visualartsdna.org/work/> .
work:w3 schema:image <http://visualartsdna.org/images/Still.jpg> ;
        schema:video [ a schema:VideoObject ;
                       schema:contentUrl <http://visualartsdna.org/images/Clip.mp4> ] .
"""

W3 = "http://visualartsdna.org/work/w3"


@pytest.fixture
def nested(env):
    reg, ops, sb = env
    ops.write_text("content/ttl/data/nested.ttl", NESTED_STORE, make_parents=True)
    return reg, ops, sb


def _nested(reg, ops, name, exclude=""):
    dr = reg.dispatch(
        "record.check_uniqueness",
        {"files": [IMG + name], "exclude_subject": exclude},
        ops,
    )
    assert dr.ok, dr.error
    return dr.result["files_taken"]


@pytest.mark.parametrize("name", ["Still.jpg", "Clip.mp4"])
def test_its_own_files_are_free_to_the_record_that_cites_them(nested, name):
    reg, ops, _ = nested
    assert _nested(reg, ops, name, exclude=W3) == []


@pytest.mark.parametrize("name", ["Still.jpg", "Clip.mp4"])
def test_another_record_still_collides_with_both(nested, name):
    """The exclusion must be for one record, not for the property: a DIFFERENT
    work reusing that video overwrites this one's file just the same."""
    reg, ops, _ = nested
    assert _nested(reg, ops, name, exclude=W3 + "9") == [IMG + name]
    assert _nested(reg, ops, name) == [IMG + name]


# --- record.resolve_tags -----------------------------------------------------
#
# Tags are free text: a tag may name any record OR any thesaurus concept, so
# there is no picker and a typo produces a reference to nothing that nothing
# downstream complains about. Real data: 175 of 186 tag triples point at content
# records and 11 at concepts, so looking in content alone reports every concept
# tag as missing.

TAG_CONTENT = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .
work:c1 a the:Collection ; rdfs:label "Unmoored Collection" .
work:w9 a the:Work ; rdfs:label "Tension Icosahedron" .
"""

TAG_VOCAB = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:pigment a skos:Concept ; rdfs:label "pigment" .
the:unlabelled a skos:Concept ; skos:prefLabel "Still life notes" .
the:bare a skos:Concept .
"""


@pytest.fixture
def tagstore(env):
    reg, ops, sb = env
    ops.write_text("content/ttl/data/c.ttl", TAG_CONTENT, make_parents=True)
    ops.write_text("metacontent/vocab/v.ttl", TAG_VOCAB, make_parents=True)
    return reg, ops, sb


def _resolve(reg, ops, tags):
    dr = reg.dispatch("record.resolve_tags", {"tags": tags}, ops)
    assert dr.ok, dr.error
    return dr.result


def test_a_content_record_tag_resolves_to_its_label(tagstore):
    """The label is the useful half: `work:c1` tells a reviewer nothing about
    whether they tagged the right thing."""
    reg, ops, _ = tagstore
    got = _resolve(reg, ops, ["work:c1"])["tags"][0]

    assert got["found"] and got["label"] == "Unmoored Collection"
    assert got["types"] == ["Collection"]


def test_a_THESAURUS_tag_resolves_too(tagstore):
    """11 of the 186 real tags point at concepts, not records. Searching content
    alone would report every one of them as missing."""
    reg, ops, _ = tagstore
    got = _resolve(reg, ops, ["the:pigment"])["tags"][0]

    assert got["found"] and got["label"] == "pigment"


def test_a_tag_pointing_at_nothing_is_reported_not_raised(tagstore):
    reg, ops, _ = tagstore
    res = _resolve(reg, ops, ["work:nosuch"])

    assert res["tags"][0]["found"] is False
    assert res["missing"] == ["work:nosuch"]


def test_a_referent_without_rdfs_label_falls_back(tagstore):
    """Real: `the:StillLifeBottleAndPitcher_20260210` exists and has no
    rdfs:label. An empty label would read as "not found"."""
    reg, ops, _ = tagstore
    got = _resolve(reg, ops, ["the:unlabelled"])["tags"][0]
    assert got["found"] and got["label"] == "Still life notes"  # skos:prefLabel

    bare = _resolve(reg, ops, ["the:bare"])["tags"][0]
    assert bare["found"] and bare["label"] == "bare"  # local name, never empty


def test_order_is_preserved_so_the_review_lists_them_as_typed(tagstore):
    reg, ops, _ = tagstore
    res = _resolve(reg, ops, ["the:pigment", "work:nosuch", "work:c1"])

    assert [t["value"] for t in res["tags"]] == ["the:pigment", "work:nosuch", "work:c1"]


def test_no_tags_resolves_to_nothing_rather_than_failing(tagstore):
    reg, ops, _ = tagstore
    res = _resolve(reg, ops, [])

    assert res["tags"] == [] and res["missing"] == []
