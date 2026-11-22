"""Editing a work's VIDEO — CE_DESIGN §14.7, the debt the composite shape left.

Edit Record types a field from the shape of the DATA, and a `schema:video` node
carries an `rdfs:label`, so it landed in the labelled-blank-node branch and
rendered as a one-line text box reading "Last Supper Orbit". Measured
2026-09-14, on a real record:

  * the video FILE could not be changed at all — the filename lives in
    `schema:contentUrl`, which that box never showed;
  * editing the label left `schema:name` behind, so the node ended up labelled
    one thing and named another.

The property map knows this shape. The editor asks it now.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from rdflib import Graph, Namespace, URIRef

from conftest import TEST_DOMAIN
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.edit_tools import read_instance, write_instance
from cwva_dashboard.tools.record_tools import build_record_tools

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

SCHEMA = Namespace("https://schema.org/")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")
KINDS = {
    "https://schema.org/video": {"kind": "video", "subtree": "images"},
    "https://schema.org/image": {"kind": "image", "subtree": "images"},
}
IMG_BASE = f"{TEST_DOMAIN}/images/"


@pytest.fixture
def record(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    tool = next(t for t in build_record_tools(TEST_DOMAIN)
                if t.name == "record.new_digital")
    res = tool.handler(
        ops, units="inch", guid="g1", type="BlenderComposition", label="Orbit",
        description="d", note="n", image="orbit.jpg", has_artist_profile="work:p1",
        recorded_date="2026-09-16", completed_date="2026-09-16",
        height=4, width=3, depth=2,
        video="LastSupperOrbit.mp4", video_description="a turntable",
        video_duration="PT34S", video_upload_date="2026-01-02",
    )
    return ops, res["path"], tmp_path / "stage"


def _video_node(root, path):
    g = Graph().parse(data=(root / path).read_text(), format="turtle")
    subj = URIRef(f"{TEST_DOMAIN}/work/g1")
    bn = g.value(subj, SCHEMA.video)
    return g, bn


def _save(ops, path, **edits):
    inst = read_instance(ops, path, KINDS)
    values = {f["predicate"]: f["value"] for f in inst["fields"]
              if f["mode"] == "editable"}
    values.update(edits)
    return write_instance(ops, path, values, KINDS, image_base=IMG_BASE,
                          derived={"https://schema.org/video": {"duration": "PT12S"}})


def test_the_video_offers_its_FILENAME_not_its_title(record):
    """A file field over the drop folder, like every other file reference —
    which is what makes the file changeable at all."""
    ops, path, _root = record

    field = next(f for f in read_instance(ops, path, KINDS)["fields"]
                 if f["predicate"] == "https://schema.org/video")

    assert field["kind"] == "file"
    assert field["file_kind"] == "video"
    assert field["value"] == "LastSupperOrbit.mp4"
    assert field["mode"] == "editable"
    assert "title, thumbnail and duration are read from the file" in field["warning"]


def test_replacing_the_file_rebuilds_THE_WHOLE_NODE(record):
    ops, path, root = record

    _save(ops, path, **{"https://schema.org/video": "NewClip.mp4"})

    g, bn = _video_node(root, path)
    assert str(g.value(bn, SCHEMA.contentUrl)).endswith("NewClip.mp4")
    assert str(g.value(bn, SCHEMA.thumbnailUrl)).endswith("NewClip_thumbnail.jpg")
    assert (bn, SCHEMA.video, None) not in g  # one node, not a nest


def test_LABEL_AND_NAME_move_together(record):
    """The defect that was measurable: they are two views of the filename, and
    the old editor changed one of them."""
    ops, path, root = record

    _save(ops, path, **{"https://schema.org/video": "NewClip.mp4"})

    g, bn = _video_node(root, path)
    assert str(g.value(bn, RDFS.label)) == "New Clip"
    assert str(g.value(bn, SCHEMA.name)) == "New Clip"


def test_what_the_USER_said_survives_the_rebuild(record):
    """The description they typed, and the uploadDate — which records when this
    work's video entered the record, not when the file was last swapped."""
    ops, path, root = record

    _save(ops, path, **{"https://schema.org/video": "NewClip.mp4"})

    g, bn = _video_node(root, path)
    assert str(g.value(bn, SCHEMA.description)) == "a turntable"
    assert str(g.value(bn, SCHEMA.uploadDate)) == "2026-01-02"


def test_the_duration_is_RE_READ_not_carried_over(record):
    """A stale duration is worse than none: a player told the wrong length is a
    defect the record vouches for. The trusted layer probes; this takes its
    answer."""
    ops, path, root = record

    _save(ops, path, **{"https://schema.org/video": "NewClip.mp4"})

    g, bn = _video_node(root, path)
    assert str(g.value(bn, SCHEMA.duration)) == "PT12S", "the probed value, not PT34S"


def test_an_UNCHANGED_video_keeps_its_own_duration(record):
    """Saving a record for an unrelated reason must not disturb the video — and
    on a machine with no ffmpeg the probe answers nothing at all."""
    ops, path, root = record
    inst = read_instance(ops, path, KINDS)
    values = {f["predicate"]: f["value"] for f in inst["fields"]
              if f["mode"] == "editable"}
    values["http://www.w3.org/2000/01/rdf-schema#label"] = "Renamed Work"

    write_instance(ops, path, values, KINDS, image_base=IMG_BASE)  # no derived

    g, bn = _video_node(root, path)
    assert str(g.value(bn, SCHEMA.duration)) == "PT34S"
    assert str(g.value(bn, SCHEMA.contentUrl)).endswith("LastSupperOrbit.mp4")
    assert str(g.value(bn, RDFS.label)) == "Last Supper Orbit"


def test_clearing_the_video_removes_the_NODE(record):
    """Not an empty VideoObject left behind — the same rule the entry form
    follows when no video is given."""
    ops, path, root = record

    _save(ops, path, **{"https://schema.org/video": ""})

    g, bn = _video_node(root, path)
    assert bn is None
    assert (None, SCHEMA.contentUrl, None) not in g


# -- the description becomes editable (§14.7, deferred once) ------------------
#
# It was preserved across a file swap and had nowhere to be typed, so the only
# way to set one was to enter the work again. A composite renders a small group
# of fields now: the file, plus what the shape marks as the user's to say.


def _parts(ops, path):
    field = next(f for f in read_instance(ops, path, KINDS)["fields"]
                 if f["predicate"] == "https://schema.org/video")
    return {p["key"]: p for p in field.get("parts") or []}


def test_the_composite_offers_the_description_as_its_own_field(record):
    ops, path, _root = record

    part = _parts(ops, path)["description"]

    assert part["value"] == "a turntable"
    assert part["name"] != "https://schema.org/video"  # its own form name


def test_the_description_can_be_changed_WITHOUT_touching_the_file(record):
    """The file is the thing you must not have to re-pick to fix a sentence."""
    ops, path, root = record
    name = _parts(ops, path)["description"]["name"]

    _save(ops, path, **{name: "A slow turntable orbit of the whole scene."})

    g, bn = _video_node(root, path)
    assert str(g.value(bn, SCHEMA.description)) == (
        "A slow turntable orbit of the whole scene.")
    assert str(g.value(bn, SCHEMA.contentUrl)).endswith("LastSupperOrbit.mp4")
    assert str(g.value(bn, SCHEMA.uploadDate)) == "2026-01-02"


def test_what_the_user_TYPES_beats_what_the_file_swap_would_keep(record):
    ops, path, root = record
    name = _parts(ops, path)["description"]["name"]

    _save(ops, path, **{"https://schema.org/video": "NewClip.mp4",
                        name: "Typed while replacing the file."})

    g, bn = _video_node(root, path)
    assert str(g.value(bn, SCHEMA.description)) == "Typed while replacing the file."


def test_clearing_the_description_falls_back_to_the_DERIVED_one(record):
    """There is no way to have no description at all, deliberately: the concern
    was always that it be MISSING, never that it be unspecific."""
    ops, path, root = record
    name = _parts(ops, path)["description"]["name"]

    _save(ops, path, **{name: "   "})

    g, bn = _video_node(root, path)
    described = str(g.value(bn, SCHEMA.description))
    assert described and described != "a turntable"
    assert "Orbit" in described


def test_a_save_that_touches_NEITHER_leaves_the_node_alone(record):
    """The untouched rule has to account for the parts as well as the file, or
    a description edit is silently dropped — and an unrelated save must not
    re-derive the node."""
    ops, path, root = record
    before, _ = _video_node(root, path)

    _save(ops, path, **{"http://www.w3.org/2000/01/rdf-schema#label": "Orbit II"})

    after, bn = _video_node(root, path)
    assert str(after.value(bn, SCHEMA.description)) == "a turntable"
    assert str(after.value(bn, SCHEMA.duration)) == "PT34S"  # not re-probed
