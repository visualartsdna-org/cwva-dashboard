"""PROOF that a profile template can replace a hand-written entry form.

`dashboardEntryFormApproach.txt` asks one question: "given a template, can the
dashboard construct the appropriate form and manage the workflow surrounding
it?" These tests answer it for the hardest of the three forms, RDF Entry, by
building both from the same inputs and comparing:

  * the generated input SCHEMA against the hand-written `record.new_work` one —
    field for field, affordance for affordance. The schema is where enforcement
    lives (`validate_args`), so matching it means the generated form offers
    exactly what the system already enforces.
  * the generated TRIPLES against what `record.new_work` writes for the same
    values — compared ISOMORPHICALLY, because both contain blank nodes.

Neither is a mock: the second parses the TTL the real tool wrote to disk.
"""

from __future__ import annotations

from rdflib import Graph, Namespace, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDF, RDFS, SKOS

import pytest

from cwva_dashboard.tools.property_map import (
    PROPERTY_MAP,
    Template,
    TemplateError,
    TemplateField,
    graph_from_template,
    picker_root,
    schema_from_template,
)
from cwva_dashboard.tools.record_tools import (
    _expand,
    _prefixes,
    build_record_tools,
    image_base,
    work_namespace,
)

from conftest import TEST_DOMAIN

SCHEMA = Namespace("https://schema.org/")
VAD = Namespace("http://visualartsdna.org/model/")

# Rick's watercolour profile, as `dashboardEntryFormApproach.txt` writes it —
# ordered, because Turtle's comma list is a SET and a form that reorders itself
# between serializations is not a form.
WATERCOLOUR = Template(
    type_default=str(VAD.Watercolor),
    fields=(
        TemplateField(str(RDF.type), order=1),
        TemplateField(str(VAD.hasArtistProfile), order=2),
        TemplateField(str(RDFS.label), order=3),
        TemplateField(str(SCHEMA.description), order=4),
        TemplateField(str(SKOS.note), order=5),
        TemplateField(str(SCHEMA.image), order=6),
        TemplateField(str(SCHEMA.location), order=7),
        TemplateField(str(VAD.hasPaper), order=8),
        TemplateField(str(SCHEMA.dateCreated), order=9),
        TemplateField(str(SCHEMA.datePublished), order=10),
        TemplateField(str(SCHEMA.height), order=11),
        TemplateField(str(SCHEMA.width), order=12),
        TemplateField(str(SCHEMA.identifier), order=13),
        TemplateField(str(VAD.qrcode), order=14),
    ),
)

VALUES = {
    "type": "Watercolor", "label": "Fairy Pool", "description": "a test",
    "note": "some note", "location": "Woodstock, GA", "image": "fairyPool.jpg",
    "has_paper": "the:TestPaper", "has_artist_profile": "work:profile-1",
    "completed_date": "2026-09-14", "recorded_date": "2026-09-14",
    "height": 12, "width": 9,
}
GUID = "11111111-2222-3333-4444-555555555555"


def _hand_written_schema():
    tool = next(t for t in build_record_tools(TEST_DOMAIN)
                if t.name == "record.new_work")
    return tool.input_schema


def _generated_schema():
    hand = _hand_written_schema()
    return schema_from_template(
        WATERCOLOUR,
        images_dir=hand["properties"]["image"]["x-file-ref"],
        data_dir=hand["properties"]["dest_dir"]["default"],
        type_enum=hand["properties"]["type"],
        defaults={"has_artist_profile":
                  hand["properties"]["has_artist_profile"].get("default", "")},
    )


# ---------------------------------------------------------------------------
# The form.
# ---------------------------------------------------------------------------

#: Fields the hand-written form asks for and a generated one does not, each
#: because something else answers them (Rick, 2026-09-14 and -16):
#:   units               — the profile's vad:measurementSystem
#:   has_artist_profile  — housekeeping, written from the profile itself
SUPPLIED = {"units", "has_artist_profile"}


def test_the_template_yields_THE_SAME_FIELDS_as_the_hand_written_form():
    """Minus what the profile answers for the artist. Those are the fields this
    approach REMOVES, and removing them is the visible half of the point."""
    hand, made = _hand_written_schema(), _generated_schema()

    assert set(made["properties"]) == set(hand["properties"]) - SUPPLIED


def test_every_field_keeps_its_AFFORDANCE():
    """The widget is chosen from these keys, so matching them means the two
    forms render the same controls: the same picker over the same vocabulary,
    the same file field over the same subtree, the same date pickers."""
    hand, made = _hand_written_schema(), _generated_schema()

    for name, spec in made["properties"].items():
        for key in ("type", "format", "enum", "x-vocabulary", "x-file-ref",
                    "x-file-kind", "x-multiline", "x-entity-ref"):
            assert spec.get(key) == hand["properties"][name].get(key), (
                f"{name}.{key}: {spec.get(key)!r} != "
                f"{hand['properties'][name].get(key)!r}"
            )


def test_the_generated_schema_is_what_VALIDATE_ARGS_would_enforce():
    """Enforcement lives in the schema. Generating the form from a template and
    writing the schema by hand would put the offered set and the enforced set
    back in two places — the failure this project keeps meeting."""
    made = _generated_schema()
    made_req = set(made["required"])
    hand_req = set(_hand_written_schema()["required"]) - SUPPLIED

    assert made["additionalProperties"] is False
    assert made_req >= hand_req, "nothing the old form demanded becomes optional"
    # The one deliberate widening: Rick chose "all required for now, until the
    # form builder gives us a checkbox" (2026-09-14). So two fields the
    # hand-written form left optional are demanded by the template — visible
    # here rather than discovered by an artist who omits a location.
    assert made_req - hand_req == {"location", "note"}


def test_a_property_the_dashboard_does_not_KNOW_is_refused():
    """A profile is stored data and stored data is hostile (law 3). A template
    may order and select; it may not invent."""
    rogue = Template(type_default=str(VAD.Watercolor),
                     fields=(TemplateField("http://evil.example/exec", order=1),))

    with pytest.raises(TemplateError, match="not in the property map"):
        schema_from_template(rogue, images_dir="images")


def test_identity_is_SUPPLIED_whatever_the_template_says():
    """Rick, 2026-09-16: the GUID, the QR and the profile are "a mandatory,
    house-keeping set" — so a template that omits them still produces a healthy
    record, and one that lists them (his four do) produces the same record. A
    profile written by hand cannot make an unresolvable work by forgetting."""
    thin = Template(
        type_default=str(VAD.Watercolor),
        fields=(TemplateField(str(RDF.type), order=1),
                TemplateField(str(RDFS.label), order=2)),
    )

    g = graph_from_template(thin, {"type": "Watercolor", "label": "x"},
                            work_ns=work_namespace(TEST_DOMAIN),
                            img_base=image_base(TEST_DOMAIN), guid=GUID,
                            units=("INH", "inches"), expand=lambda c: URIRef(c),
                            profile_uri=f"{TEST_DOMAIN}/work/prof-1")

    subj = work_namespace(TEST_DOMAIN)[GUID]
    assert (subj, SCHEMA.identifier, None) in g
    assert (subj, VAD.qrcode, None) in g
    assert (subj, VAD.hasArtistProfile, None) in g


def test_a_template_must_still_say_WHAT_IT_MAKES_and_what_to_call_it():
    """The line: machinery can supply identity, but not the class of thing being
    made or its name."""
    nameless = Template(type_default=str(VAD.Watercolor),
                        fields=(TemplateField(str(SCHEMA.image), order=1),))

    with pytest.raises(TemplateError, match="cannot omit"):
        graph_from_template(nameless, {"image": "a.jpg"},
                            work_ns=work_namespace(TEST_DOMAIN),
                            img_base=image_base(TEST_DOMAIN), guid=GUID,
                            units=("INH", "inches"), expand=lambda c: URIRef(c))


# ---------------------------------------------------------------------------
# The triples — the half a list of predicates cannot supply.
# ---------------------------------------------------------------------------

def test_the_template_writes_THE_SAME_GRAPH_as_the_record_tool(tmp_path):
    """Isomorphic, not equal: `schema:height` is a blank node in both, and two
    blank nodes are never the same node."""
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    sb = Sandbox.open(tmp_path / "stage", create=True)
    fileops = FileOps(sb)
    tool = next(t for t in build_record_tools(TEST_DOMAIN)
                if t.name == "record.new_work")
    res = tool.handler(fileops, units="inch", guid=GUID, **VALUES)
    by_hand = Graph().parse(
        data=(tmp_path / "stage" / res["path"]).read_text(), format="turtle")

    work_ns = work_namespace(TEST_DOMAIN)
    prefixes = _prefixes(work_ns)
    by_template = graph_from_template(
        WATERCOLOUR, VALUES, work_ns=work_ns, img_base=image_base(TEST_DOMAIN),
        guid=GUID, units=("INH", "inches"),
        expand=lambda curie: _expand(curie, prefixes),
        # Housekeeping is supplied by whoever knows the profile, where the
        # hand-written tool takes it as a field.
        profile_uri=str(_expand(VALUES["has_artist_profile"], prefixes)),
    )

    assert isomorphic(by_template, by_hand), (
        "\ntemplate:\n" + by_template.serialize(format="turtle")
        + "\nhand:\n" + by_hand.serialize(format="turtle")
    )


def test_the_measurement_system_supplies_the_unit(tmp_path):
    """Same template, a profile that measures in metres, and the record says so
    — without a units field on the form."""
    work_ns = work_namespace(TEST_DOMAIN)
    g = graph_from_template(
        WATERCOLOUR, VALUES, work_ns=work_ns, img_base=image_base(TEST_DOMAIN),
        guid=GUID, units=("MTR", "meters"),
        expand=lambda c: _expand(c, _prefixes(work_ns)),
    )

    labels = {str(o) for _s, _p, o in g.triples((None, RDFS.label, None))}
    assert "12 meters" in labels
    assert "MTR" in {str(o) for _s, _p, o in g.triples((None, SCHEMA.unitCode, None))}


# ---------------------------------------------------------------------------
# The type picker (Rick, 2026-09-14): templateType is the DEFAULT, and the
# picker offers the immediate parent's subclasses — so a watercolour profile can
# still record the mixed-media piece it turned into.
# ---------------------------------------------------------------------------

MODEL = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
vad:ArtForm a owl:Class .
vad:PaintingForm a owl:Class ; rdfs:subClassOf vad:ArtForm .
vad:SculptureForm a owl:Class ; rdfs:subClassOf vad:ArtForm .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:OilPainting a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:MixedMedia a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:BlenderComposition a owl:Class ; rdfs:subClassOf vad:SculptureForm .
"""


def test_the_picker_starts_at_the_templates_IMMEDIATE_PARENT():
    from cwva_dashboard.tools.record_tools import subclass_closure

    model = Graph().parse(data=MODEL, format="turtle")

    root = picker_root(model, str(VAD.Watercolor))

    assert root == str(VAD.PaintingForm)
    offered = subclass_closure(model, root, include_root=True)
    assert "MixedMedia" in offered and "OilPainting" in offered
    assert "BlenderComposition" not in offered, "not the whole ontology"


def test_a_type_outside_the_model_has_no_picker_root():
    model = Graph().parse(data=MODEL, format="turtle")

    assert picker_root(model, str(VAD.NotAThing)) is None


# ---------------------------------------------------------------------------
# vad:dependsOn — the cross-field rule "all required" cannot express.
# ---------------------------------------------------------------------------

DIGITALish = Template(
    type_default=str(VAD.BlenderComposition),
    fields=(
        TemplateField(str(RDF.type), order=1),
        TemplateField(str(RDFS.label), order=2),
        TemplateField(str(SCHEMA.identifier), order=3),
        TemplateField(str(VAD.qrcode), order=4),
        TemplateField(str(VAD.image3d), order=5, required=False),
        TemplateField(str(VAD.background), order=6, depends_on=str(VAD.image3d)),
    ),
)


def _build(values):
    work_ns = work_namespace(TEST_DOMAIN)
    return graph_from_template(
        DIGITALish, values, work_ns=work_ns, img_base=image_base(TEST_DOMAIN),
        guid=GUID, units=("INH", "inches"),
        expand=lambda c: _expand(c, _prefixes(work_ns)),
    )


def test_a_dependent_field_is_required_ONLY_when_its_trigger_is_filled():
    """A 3D image needs a background to be rendered against; without the 3D
    image the background means nothing. Required-for-everything cannot say that,
    which is why the template carries the rule."""
    base = {"type": "BlenderComposition", "label": "Piece"}

    _build(base)  # no image3d, no background — fine

    with pytest.raises(TemplateError, match="background is required when image3d"):
        _build({**base, "image3d": "thing.glb"})

    g = _build({**base, "image3d": "thing.glb", "background": "work:bg-1"})
    assert (None, VAD.background, None) in g


def test_the_dependency_names_a_PROPERTY_not_a_field_name():
    """`vad:dependsOn vad:image3d` — the template speaks RDF, and the field name
    is an implementation detail of the form."""
    dep = next(f for f in DIGITALish.fields if f.predicate == str(VAD.background))

    assert dep.depends_on == str(VAD.image3d)
    assert PROPERTY_MAP[dep.depends_on].field == "image3d"


# ---------------------------------------------------------------------------
# The eighth shape: schema:video, where ONE filename becomes a whole node.
#
# Four of the VideoObject's properties are determined by the file rather than
# asked for — rdfs:label and schema:name from its CamelCase, the thumbnail URL
# by the cwva-py naming convention (a file the dashboard deliberately does not
# create), and uploadDate from the day it was entered. The duration is read from
# the file by the trusted layer, since a registry tool cannot exec.
#
# This proves RDF DIGITAL, not just the video node: if the template can express
# the harder of the two forms, the shape table is complete for both.
# ---------------------------------------------------------------------------

DIGITAL = Template(
    type_default=str(VAD.BlenderComposition),
    fields=(
        TemplateField(str(RDF.type), order=1),
        TemplateField(str(VAD.hasArtistProfile), order=2),
        TemplateField(str(RDFS.label), order=3),
        TemplateField(str(SCHEMA.description), order=4),
        TemplateField(str(SKOS.note), order=5),
        TemplateField(str(SCHEMA.image), order=6),
        TemplateField(str(VAD.image3d), order=7, required=False),
        TemplateField(str(VAD.background), order=8, depends_on=str(VAD.image3d)),
        TemplateField(str(SCHEMA.video), order=9, required=False),
        TemplateField(str(SCHEMA.dateCreated), order=10),
        TemplateField(str(SCHEMA.datePublished), order=11),
        TemplateField(str(SCHEMA.height), order=12),
        TemplateField(str(SCHEMA.width), order=13),
        TemplateField(str(SCHEMA.depth), order=14),
        TemplateField(str(SCHEMA.identifier), order=15),
        TemplateField(str(VAD.qrcode), order=16),
    ),
)

DIGITAL_VALUES = {
    "type": "BlenderComposition", "label": "Orbit", "description": "a render",
    "has_artist_profile": "work:profile-1",
    "note": "assumptions", "image": "orbit.jpg", "image3d": "orbit.glb",
    "background": "work:bg-1", "video": "LastSupperOrbit.mp4",
    "video_description": "a turntable", "video_duration": "PT34S",
    "video_upload_date": "2026-09-14",
    "completed_date": "2026-09-14", "recorded_date": "2026-09-14",
    "height": 4, "width": 3, "depth": 2,
}


def _digital_hand_schema():
    tool = next(t for t in build_record_tools(TEST_DOMAIN)
                if t.name == "record.new_digital")
    return tool.input_schema


def _digital_generated_schema():
    hand = _digital_hand_schema()
    return schema_from_template(
        DIGITAL, images_dir=hand["properties"]["image"]["x-file-ref"],
        data_dir=hand["properties"]["dest_dir"]["default"],
        type_enum=hand["properties"]["type"],
    )


def test_the_video_field_offers_only_what_the_browser_can_play():
    """`x-file-kind: video` is what narrows the picker — the MP4 lives in the
    same images/ subtree as the stills, so the subtree alone cannot."""
    made = _digital_generated_schema()

    assert made["properties"]["video"]["x-file-kind"] == "video"
    assert made["properties"]["video"]["x-file-ref"] == \
        _digital_hand_schema()["properties"]["video"]["x-file-ref"]


def test_the_composite_asks_for_a_FILE_and_two_extras_and_nothing_else():
    """Not for the label, the name, the thumbnail URL or the upload date: each
    is determined by the file or by the day. A form that asked for them would be
    asking the artist to restate what the system already knows."""
    made = _digital_generated_schema()

    video_fields = {k for k in made["properties"] if k.startswith("video")}
    assert video_fields == {"video", "video_description", "video_duration",
                            "video_upload_date"}
    for absent in ("video_title", "video_name", "video_thumbnail"):
        assert absent not in made["properties"]


def test_RDF_DIGITAL_regenerates_field_for_field():
    hand, made = _digital_hand_schema(), _digital_generated_schema()

    assert set(made["properties"]) == set(hand["properties"]) - SUPPLIED
    for name, spec in made["properties"].items():
        for key in ("type", "format", "enum", "x-vocabulary", "x-file-ref",
                    "x-file-kind", "x-multiline", "x-entity-ref"):
            assert spec.get(key) == hand["properties"][name].get(key), \
                f"{name}.{key}"


def test_the_template_writes_THE_SAME_DIGITAL_GRAPH_including_the_video(tmp_path):
    from cwva_dashboard.sandbox.fileops import FileOps
    from cwva_dashboard.sandbox.paths import Sandbox

    sb = Sandbox.open(tmp_path / "stage", create=True)
    tool = next(t for t in build_record_tools(TEST_DOMAIN)
                if t.name == "record.new_digital")
    res = tool.handler(FileOps(sb), units="inch", guid=GUID, **DIGITAL_VALUES)
    by_hand = Graph().parse(
        data=(tmp_path / "stage" / res["path"]).read_text(), format="turtle")

    work_ns = work_namespace(TEST_DOMAIN)
    by_template = graph_from_template(
        DIGITAL, DIGITAL_VALUES, work_ns=work_ns, img_base=image_base(TEST_DOMAIN),
        guid=GUID, units=("INH", "inches"),
        expand=lambda c: _expand(c, _prefixes(work_ns)),
        profile_uri=str(_expand(DIGITAL_VALUES["has_artist_profile"],
                                _prefixes(work_ns))),
    )

    assert isomorphic(by_template, by_hand), (
        "\ntemplate:\n" + by_template.serialize(format="turtle")
        + "\nhand:\n" + by_hand.serialize(format="turtle")
    )


def test_the_derived_parts_of_the_video_node_come_from_the_FILENAME(tmp_path):
    """Named explicitly so a future change to `video_title` or the thumbnail
    convention fails here rather than quietly writing a different node."""
    work_ns = work_namespace(TEST_DOMAIN)
    g = graph_from_template(
        DIGITAL, DIGITAL_VALUES, work_ns=work_ns, img_base=image_base(TEST_DOMAIN),
        guid=GUID, units=("INH", "inches"),
        expand=lambda c: _expand(c, _prefixes(work_ns)),
        profile_uri=str(_expand(DIGITAL_VALUES["has_artist_profile"],
                                _prefixes(work_ns))),
    )
    bn = g.value(work_ns[GUID], SCHEMA.video)

    # de-camelCased for reading, while the thumbnail keeps the file's own stem
    assert str(g.value(bn, RDFS.label)) == "Last Supper Orbit"
    assert str(g.value(bn, SCHEMA.name)) == "Last Supper Orbit"
    assert str(g.value(bn, SCHEMA.thumbnailUrl)).endswith(
        "LastSupperOrbit_thumbnail.jpg")
    assert str(g.value(bn, SCHEMA.contentUrl)).endswith("LastSupperOrbit.mp4")
    assert (bn, RDF.type, SCHEMA.VideoObject) in g


def test_no_video_means_NO_NODE_AT_ALL(tmp_path):
    """Not an empty VideoObject. A digital work without a video omits the
    property, which is what the entry form does today."""
    work_ns = work_namespace(TEST_DOMAIN)
    without = {k: v for k, v in DIGITAL_VALUES.items() if not k.startswith("video")}

    g = graph_from_template(
        DIGITAL, without, work_ns=work_ns, img_base=image_base(TEST_DOMAIN),
        guid=GUID, units=("INH", "inches"),
        expand=lambda c: _expand(c, _prefixes(work_ns)),
    )

    assert (None, SCHEMA.video, None) not in g


def test_dependsOn_ON_BOTH_FIELDS_is_a_MUTUAL_dependency(tmp_path):
    """Rick's refinement (2026-09-16): a 3D object and its background need each
    other, and neither is required alone.

    It needs no new construct — `ops:dependsOn` on both fields, each naming the
    other, already means exactly this. Recorded as a test because it is now what
    the Blender profile relies on, and because "mutual" is the kind of property
    that reads as obvious until someone makes one side unconditional and the
    other side silently stops mattering.
    """
    mutual = Template(
        type_default=str(VAD.BlenderComposition),
        fields=(
            TemplateField(str(RDF.type), order=1),
            TemplateField(str(RDFS.label), order=2),
            TemplateField(str(SCHEMA.identifier), order=3),
            TemplateField(str(VAD.qrcode), order=4),
            TemplateField(str(VAD.image3d), order=5, depends_on=str(VAD.background)),
            TemplateField(str(VAD.background), order=6, depends_on=str(VAD.image3d)),
        ),
    )
    work_ns = work_namespace(TEST_DOMAIN)

    def build(**extra):
        return graph_from_template(
            mutual, {"type": "BlenderComposition", "label": "Piece", **extra},
            work_ns=work_ns, img_base=image_base(TEST_DOMAIN), guid=GUID,
            units=("MTR", "meters"),
            expand=lambda c: _expand(c, _prefixes(work_ns)),
        )

    # neither: a digital work with no 3D object at all is perfectly good
    g = build()
    assert (None, VAD.image3d, None) not in g

    # either one alone: refused, and the message names the MISSING half
    with pytest.raises(TemplateError, match="background is required when image3d"):
        build(image3d="thing.glb")
    with pytest.raises(TemplateError, match="image3d is required when background"):
        build(background="work:bg-1")

    # both: fine
    g = build(image3d="thing.glb", background="work:bg-1")
    assert (None, VAD.image3d, None) in g and (None, VAD.background, None) in g

    # and neither is unconditionally required, so the SCHEMA cannot demand them
    schema = schema_from_template(mutual, images_dir="images")
    assert "image3d" not in schema["required"]
    assert "background" not in schema["required"]
