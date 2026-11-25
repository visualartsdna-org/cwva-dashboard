"""RDF Digital wired from function.html (Phase 4.7, cycle 2).

Cycle 2 shares the entry route's implementation rather than copying it, so the
tests here are deliberately narrow: they pin what is genuinely DIFFERENT about
the digital form, plus the fact that the shared behaviour really is shared. The
cycle-1 defects (missing QR, sidecar-less binaries, generated artifacts in the
picker, the reload-losing message) are inherited, not re-tested here.

Differences come from the record-group extraction notes: SculptureForm types with a
BlenderComposition default, units defaulting to meter, a required note, a
third dimension, an optional image3d, a background reference,
and no paper.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from cwva_dashboard.inbox import Inbox
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import image_base

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

MODEL = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix vad: <http://visualartsdna.org/model/> .
vad:SculptureForm a owl:Class .
vad:BlenderComposition a owl:Class ; rdfs:subClassOf vad:SculptureForm .
vad:DigitalSculpture a owl:Class ; rdfs:subClassOf vad:SculptureForm .
vad:PaintingForm a owl:Class .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
"""

BACKGROUND = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .
work:bg1 a the:Image ;
    rdfs:label "Studio Wall" ;
    the:topic the:Background .
"""

# The background entity carries its OWN gated reference — `the:topic` must point
# at a declared topic concept, like any entity's does. The fixture declares them
# because production does; leaving them out made a background dangle for a
# reason that had nothing to do with backgrounds.
TOPICS = """@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:Background a skos:Concept ; skos:inScheme the:TopicScheme .
the:Portrait a skos:Concept ; skos:inScheme the:TopicScheme .
"""


@pytest.fixture
def drop_folder(tmp_path):
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "sculpt.jpg").write_bytes(b"\xff\xd8jpeg")
    (folder / "model.glb").write_bytes(b"glTF binary")
    # Not a real video — enough for the picker and the ingest path. The one test
    # that needs real bytes (the duration probe) makes its own with ffmpeg.
    (folder / "LastSupperOrbit.mp4").write_bytes(b"\x00\x00\x00 ftypisom fake")
    return folder


@pytest.fixture
def client(tmp_path, drop_folder):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    model = qa_root / "metacontent" / "model"
    model.mkdir(parents=True)
    (model / "m.ttl").write_text(MODEL)
    # A background image entity in the CONTENT store. Backgrounds are ordinary
    # records — independent of any work, reusable across many — not thesaurus
    # concepts, which is why they are sourced from here.
    data = qa_root / "content" / "ttl" / "data"
    data.mkdir(parents=True)
    (data / "bg1.ttl").write_text(BACKGROUND)
    vocab = qa_root / "content" / "ttl" / "vocab"
    vocab.mkdir(parents=True)
    (vocab / "topics.ttl").write_text(TOPICS)
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        # Kinds as configured in production: stills and 3D objects are
        # different kinds sharing one folder, not one kind with more extensions.
        inbox=Inbox(
            drop_folder,
            extensions={
                "image": (".jpg",),
                "model3d": (".glb", ".gltf"),
                "video": (".mp4", ".webm", ".ogg", ".ogv"),
            },
        ),
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"),
            image_base=image_base(TEST_DOMAIN), layout=Layout.default(),
            # ARM THE GATES, exactly as create_app does. A driver without these
            # runs no vocabulary gate at all, so "gates passed" would mean "no
            # gates ran" — and the background test below would pass for the
            # wrong reason.
            vocab_dirs=[Layout.default().dir("vocab_ttl"),
                        Layout.default().dir("tags_ttl")],
            content_dirs=[Layout.default().dir("work_ttl")],
        ),
    )
    with TestClient(app) as c:
        yield c, qa


def _options(html, field):
    m = re.search(rf'<select id="{field}" name="{field}".*?</select>', html, re.S)
    return re.findall(r'<option value="([^"]*)"', m.group(0)) if m else []


def _selected(html, field):
    m = re.search(rf'<select id="{field}".*?</select>', html, re.S)
    got = re.search(r'<option value="([^"]*)" selected>', m.group(0)) if m else None
    return got.group(1) if got else ""


def test_the_card_on_the_hub_now_resolves(client):
    """function.html has always linked to rdf/digital; before this cycle it 404'd."""
    c, _ = client
    assert 'href="rdf/digital"' in c.get("/").text
    assert c.get("/rdf/digital").status_code == 200


def test_types_come_from_SculptureForm_not_PaintingForm(client):
    """The two forms resolve different roots from the same ontology."""
    c, _ = client
    digital = _options(c.get("/rdf/digital").text, "type")
    entry = _options(c.get("/rdf/entry").text, "type")

    assert "BlenderComposition" in digital and "DigitalSculpture" in digital
    assert "Watercolor" not in digital
    assert "Watercolor" in entry and "BlenderComposition" not in entry


def test_digital_defaults_differ_from_entry(client):
    """units=meter (EXTRACTION D6/Q1), against inch for work."""
    c, _ = client
    digital = c.get("/rdf/digital").text

    assert _selected(digital, "units") == "meter"
    assert _selected(digital, "type") == "BlenderComposition"
    assert _selected(c.get("/rdf/entry").text, "units") == "inch"


def test_digital_only_fields_are_present(client):
    c, _ = client
    html = c.get("/rdf/digital").text
    for field in ("depth", "image3d", "background"):
        assert re.search(rf'id="{field}"', html), field


def test_paper_is_absent_and_note_is_required(client):
    """No hasPaper on a digital work; note is required where it is optional for
    an entry (EXTRACTION: 'note required')."""
    c, _ = client
    html = c.get("/rdf/digital").text
    schema = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_digital"
    )

    assert 'id="has_paper"' not in html
    assert "note" in schema["inputSchema"]["required"]
    assert re.search(r'for="note">note <span class="req">', html)


def test_offered_type_set_IS_the_enforced_enum(client):
    """The same contract cycle 1 carries, checked for this form's own schema."""
    c, _ = client
    html = c.get("/rdf/digital").text
    enforced = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_digital"
    )["inputSchema"]["properties"]["type"]["enum"]

    assert _options(html, "type") == enforced


def _submit(c, html, **over):
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
    data = {
        "guid": guid, "type": "BlenderComposition", "label": "Tensegrity",
        "description": "d", "note": "a note", "height": "2", "width": "3",
        "depth": "4", "units": "meter", "recorded_date": "2026-09-04",
        "completed_date": "2026-09-04",
        "has_artist_profile": "work:abc", "image": "sculpt.jpg",
    }
    data.update(over)
    return guid, c.post("/rdf/digital", data=data)


def test_submit_writes_a_digital_record_and_stops_at_review(client):
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text)

    assert r.status_code == 200
    assert "Distribute Data — review" in r.text
    ttl = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    assert "vad:BlenderComposition" in ttl
    assert "schema:depth" in ttl
    # Dropped 2026-09-06: cwva-py reads format from the extension/mimetype, so
    # the property asked the user to maintain a literal nothing consumes.
    assert "vad:fileFormat" not in ttl
    assert "vad:hasPaper" not in ttl
    assert not list((qa.root.parent / "sot").rglob("*.ttl")), "must not converge"


def test_the_shared_cycle_is_shared_not_copied(client):
    """Cycle 1's fixes are inherited: the QR is generated for a digital record
    too, and the generated RDF is shown for review. A copied route would have
    had to re-earn both."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text)

    assert (qa.root / "content/images" / f"qrc_{guid}.jpg").is_file()
    assert "Generated RDF" in r.text
    assert "Gates failed" not in r.text


def test_edit_returns_to_the_DIGITAL_form(client):
    """The pending promotion records its workflow, so an edited digital record
    must not come back as an entry form."""
    c, _ = client
    _guid, r = _submit(c, c.get("/rdf/digital").text)
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)

    edited = c.post("/rdf/entry/edit", data={"token": token})

    assert "VADNA RDF Digital" in edited.text
    assert 'action="/rdf/digital"' in edited.text
    assert re.search(r'id="label"[^>]*value="Tensegrity"', edited.text)


# -- image3d takes 3D objects, not photographs --------------------------------


def _picker(html, field):
    m = re.search(rf'<select id="{field}" name="{field}".*?</select>', html, re.S)
    return [o for o in re.findall(r'<option value="([^"]*)"', m.group(0)) if o] if m else []


def test_image3d_offers_3D_objects_and_image_offers_stills(client):
    """The two fields share the images/ subtree — production keeps meshes there
    — but must never offer each other's files."""
    c, _ = client
    html = c.get("/rdf/digital").text

    assert _picker(html, "image3d") == ["model.glb"]
    assert _picker(html, "image") == ["sculpt.jpg"]


def test_gltf_is_offered_alongside_glb(client, drop_folder):
    """glTF ships in two flavours: JSON .gltf and self-contained binary .glb."""
    c, _ = client
    (drop_folder / "scene.gltf").write_text('{"asset":{"version":"2.0"}}')

    assert _picker(c.get("/rdf/digital").text, "image3d") == ["model.glb", "scene.gltf"]


def test_the_refresh_endpoint_honours_the_kind(client):
    c, _ = client
    imgs = c.get("/api/affordance/file-ref?subtree=content/images&kind=image").json()
    objs = c.get("/api/affordance/file-ref?subtree=content/images&kind=model3d").json()

    assert [f["value"] for f in imgs["candidates"]] == ["sculpt.jpg"]
    assert [f["value"] for f in objs["candidates"]] == ["model.glb"]


def test_the_refresh_button_asks_for_its_own_kind(client):
    """A picker that refreshed without its kind would swap 3D objects for
    photographs on the first click."""
    c, _ = client
    html = c.get("/rdf/digital").text

    assert "refreshFileRef(this, &#x27;image3d&#x27;" in html or \
           "refreshFileRef(this, 'image3d'" in html
    assert "model3d" in html, "the 3D picker must pass its kind"


def test_a_selected_glb_is_INGESTED_like_any_other_asset(client, drop_folder):
    """Ingesting only `image` would leave the mesh outside the sandbox, so
    vad:image3d dangles at the gate — or reaches SOT referencing a file that
    never converged. That is the hand-placed-binary defect by another route."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text, image3d="model.glb", background="work:bg1")

    assert r.status_code == 200
    landed = qa.root / "content" / "images" / "model.glb"
    assert landed.is_file(), "the .glb must be copied into the sandbox"
    assert landed.read_bytes() == (drop_folder / "model.glb").read_bytes()
    assert (qa.root / "content" / "images" / "model.glb.ptr").is_file(), "sidecar"
    assert "Gates failed" not in r.text
    assert "vad:image3d" in (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()


def test_a_glb_is_refused_for_the_stills_field(client):
    """The kind is enforced at ingest, not merely offered: `image` will not
    accept a mesh even if something asks it to."""
    c, qa = client
    _guid, r = _submit(c, c.get("/rdf/digital").text, image="model.glb")

    # copy_into refuses the wrong kind, so nothing is ingested under that name
    assert not (qa.root / "content" / "images" / "model.glb").is_file()


# -- schema:video (2026-09) ---------------------------------------------------


def test_video_offers_only_playable_files(client):
    """A third kind sharing the same images/ subtree. Each picker must offer its
    own kind and nothing else — the mesh field must not list the MP4 either."""
    c, _ = client
    html = c.get("/rdf/digital").text

    assert _picker(html, "video") == ["LastSupperOrbit.mp4"]
    assert _picker(html, "image3d") == ["model.glb"]
    assert _picker(html, "image") == ["sculpt.jpg"]


def test_video_is_entirely_optional(client):
    """The default submission names no video, and the record must then omit
    schema:video altogether rather than carry an empty VideoObject."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text)

    assert r.status_code == 200
    ttl = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    assert "schema:video" not in ttl
    assert "Gates failed" not in r.text


def test_a_selected_video_is_INGESTED_and_recorded(client, drop_folder):
    """Same reasoning as the .glb: an un-ingested MP4 dangles at the asset gate
    (schema:contentUrl IS gated), or reaches SOT referencing a file that never
    converged."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text, video="LastSupperOrbit.mp4")

    assert r.status_code == 200
    landed = qa.root / "content" / "images" / "LastSupperOrbit.mp4"
    assert landed.is_file(), "the video must be copied into the sandbox"
    assert landed.read_bytes() == (drop_folder / "LastSupperOrbit.mp4").read_bytes()
    assert (qa.root / "content" / "images" / "LastSupperOrbit.mp4.ptr").is_file()
    assert "Gates failed" not in r.text, r.text

    ttl = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    assert "schema:video" in ttl and "schema:VideoObject" in ttl
    assert "LastSupperOrbit.mp4" in ttl
    # Derived, not typed: the title and the thumbnail name both come from the
    # filename, so the user cannot make them disagree with the file.
    assert "Last Supper Orbit" in ttl
    assert "LastSupperOrbit_thumbnail.jpg" in ttl


def test_the_missing_thumbnail_does_not_fail_the_gate(client):
    """cwva-py renders the thumbnail on demand, so at promotion time it does not
    exist. Gating it would fail every video entry — pinned at the route too,
    because this is where it would actually bite."""
    c, qa = client
    _guid, r = _submit(c, c.get("/rdf/digital").text, video="LastSupperOrbit.mp4")

    assert "Gates failed" not in r.text
    assert not (qa.root / "content" / "images" / "LastSupperOrbit_thumbnail.jpg").exists()


@pytest.mark.skipif(
    not (shutil.which("ffprobe") and shutil.which("ffmpeg")),
    reason="ffmpeg/ffprobe not installed",
)
def test_the_duration_is_probed_from_the_file_on_submit(client, drop_folder):
    """The user picks a file, not a duration. The probe runs TRUSTED-SIDE — it
    execs, and the confined worker has no exec (law 2) — and its answer reaches
    the record tool as an ordinary argument."""
    import subprocess

    c, qa = client
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
         "-i", "testsrc=duration=3:size=64x64:rate=10",
         str(drop_folder / "ProbeMe.mp4")],
        check=True, capture_output=True,
    )
    guid, r = _submit(c, c.get("/rdf/digital").text, video="ProbeMe.mp4")

    assert r.status_code == 200, r.text
    ttl = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    assert '"PT3S"^^xs:duration' in ttl


def test_a_typed_duration_wins_over_the_probe(client):
    """The manual field is the correction path, so it must not be overwritten by
    a probe — and it is what a deployment without ffmpeg relies on entirely."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text,
                      video="LastSupperOrbit.mp4", video_duration="PT34S")

    assert r.status_code == 200
    assert '"PT34S"^^xs:duration' in (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()


def test_an_unprobeable_video_simply_omits_the_duration(client):
    """The fixture MP4 is not real bytes, so ffprobe cannot answer. That must
    leave the property off — never block the entry, never guess a value."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text, video="LastSupperOrbit.mp4")

    assert r.status_code == 200
    ttl = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    assert "schema:video" in ttl and "schema:duration" not in ttl


def test_a_bad_typed_duration_is_refused_not_written(client):
    """Free text here would serialize an ill-formed xs:duration that the parse
    gate happily accepts. Dispatch refuses it and the form comes back."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text,
                      video="LastSupperOrbit.mp4", video_duration="34 seconds")

    assert r.status_code == 400
    assert "bad_format" in r.text
    assert not (qa.root / "content/ttl/data" / f"{guid}.ttl").exists()


def test_the_video_picker_asks_for_its_own_kind_on_refresh(client):
    c, _ = client
    html = c.get("/rdf/digital").text

    assert "refreshFileRef(this, &#x27;video&#x27;" in html or \
           "refreshFileRef(this, 'video'" in html


# -- collision: EVERY ingested asset, not just the image ----------------------
#
# Found in use 2026-09-06: an entry was correctly refused for a reused .jpg, but
# the .glb beside it was never checked at all. The hazard belongs to the INGEST,
# and the ingest copies in every file-ref field — so a mesh or a video could
# overwrite a published work's asset in silence while the image was guarded.


def _first_record(c, qa, **over):
    """Land one record so its assets are referenced, then return its guid."""
    guid, r = _submit(c, c.get("/rdf/digital").text, **over)
    assert r.status_code == 200, r.text
    assert (qa.root / "content/ttl/data" / f"{guid}.ttl").is_file()
    return guid


def test_a_reused_3D_object_filename_is_REFUSED(client):
    c, qa = client
    _first_record(c, qa, image3d="model.glb", background="work:bg1")

    _guid, r = _submit(c, c.get("/rdf/digital").text,
                       image="other.jpg", label="Second", image3d="model.glb", background="work:bg1")

    assert r.status_code == 409
    assert "model.glb" in r.text
    assert "already referenced by another record" in r.text


def test_a_reused_video_filename_is_REFUSED(client):
    c, qa = client
    _first_record(c, qa, video="LastSupperOrbit.mp4")

    _guid, r = _submit(c, c.get("/rdf/digital").text,
                       image="other.jpg", label="Second", video="LastSupperOrbit.mp4")

    assert r.status_code == 409
    assert "LastSupperOrbit.mp4" in r.text


def test_the_refusal_names_the_offending_FIELD(client):
    """Three pickers share one drop folder, so 'already in use' without a field
    name is a hunt through the form."""
    c, qa = client
    _first_record(c, qa, image3d="model.glb", background="work:bg1")

    _guid, r = _submit(c, c.get("/rdf/digital").text,
                       image="other.jpg", label="Second", image3d="model.glb", background="work:bg1")

    assert "(image3d)" in r.text


def test_a_reused_asset_is_NOT_ingested(client, drop_folder):
    """The check runs BEFORE the ingest, so a refused submission must not have
    already overwritten the file it was refused for."""
    c, qa = client
    first = _first_record(c, qa, image3d="model.glb", background="work:bg1")
    landed = qa.root / "content" / "images" / "model.glb"
    original = landed.read_bytes()
    (drop_folder / "model.glb").write_bytes(b"DIFFERENT BYTES")

    _guid, r = _submit(c, c.get("/rdf/digital").text,
                       image="other.jpg", label="Second", image3d="model.glb", background="work:bg1")

    assert r.status_code == 409
    assert landed.read_bytes() == original, "the first work's mesh was overwritten"
    assert first  # the first record still owns it


def test_every_colliding_file_is_reported_at_once(client):
    """Report all of them: fixing one rename at a time, one submission at a
    time, is the onerous loop the user objected to for the image alone."""
    c, qa = client
    _first_record(c, qa, image3d="model.glb", background="work:bg1",
                  video="LastSupperOrbit.mp4")

    _guid, r = _submit(c, c.get("/rdf/digital").text, label="Second",
                       image="sculpt.jpg", image3d="model.glb", background="work:bg1",
                       video="LastSupperOrbit.mp4")

    assert r.status_code == 409
    for name in ("sculpt.jpg", "model.glb", "LastSupperOrbit.mp4"):
        assert name in r.text, name


def test_the_checked_set_IS_the_ingested_set(client):
    """The structural fix, pinned. Both the collision check and the ingest read
    the file-ref fields off the SAME schema, so a field added later cannot be
    ingested without being checked — which is precisely how .glb and .mp4 got
    past the hand-written `image` check."""
    c, _ = client
    digital = next(t for t in c.get("/api/tools").json()
                   if t["name"] == "record.new_digital")
    fields = {n for n, f in digital["inputSchema"]["properties"].items()
              if "x-file-ref" in f}

    assert fields == {"image", "image3d", "video"}


# -- background: a picker, and required WHEN a 3D object is given -------------


def test_background_is_a_picker_of_background_entities(client):
    """Backgrounds are a closed, queryable set — entity records typed the:Image
    with the:topic the:Background — not free text and not thesaurus concepts."""
    c, _ = client
    html = c.get("/rdf/digital").text

    assert _picker(html, "background") == ["work:bg1"]
    assert "Studio Wall" in html, "the picker shows the background's rdfs:label"


def test_a_3D_object_without_a_background_is_REFUSED(client):
    """Conditional on another field, so it cannot be a schema `required` entry
    and the asterisk would be a lie. Checked on Create record instead."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text, image3d="model.glb")

    assert r.status_code == 400
    assert "background is required when a 3D object is given" in r.text
    assert not (qa.root / "content/ttl/data" / f"{guid}.ttl").exists()


def test_the_refusal_keeps_what_was_typed(client):
    """The remedy is one more selection, so losing the form would be absurd."""
    c, _ = client
    _guid, r = _submit(c, c.get("/rdf/digital").text,
                       image3d="model.glb", label="Unmoored Swing", note="a note")

    assert 'value="Unmoored Swing"' in r.text
    assert "do not reload the page" in r.text


def test_a_work_with_no_3D_object_needs_no_background(client):
    """The rule is conditional in both directions: an ordinary digital work
    still submits with the background left empty."""
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text)

    assert r.status_code == 200
    ttl = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    assert "vad:background" not in ttl


def test_a_3D_work_with_a_background_records_the_CURIE(client):
    c, qa = client
    guid, r = _submit(c, c.get("/rdf/digital").text,
                      image3d="model.glb", background="work:bg1")

    assert r.status_code == 200, r.text
    ttl = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    assert "vad:background work:bg1" in ttl
    assert "Gates failed" not in r.text, "the background must resolve at the gate"


def test_the_offered_backgrounds_ARE_what_the_gate_accepts(client, tmp_path):
    """The wired-form contract, at the one place it can be checked end to end:
    an entity the picker does NOT offer must not pass the gate either."""
    c, qa = client
    data = qa.root / "content" / "ttl" / "data"
    (data / "bg2.ttl").write_text(BACKGROUND.replace("bg1", "bg2")
                                  .replace("the:topic the:Background", "the:topic the:Portrait")
                                  .replace("Studio Wall", "Not A Background"))

    html = c.get("/rdf/digital").text
    assert "work:bg2" not in _picker(html, "background"), "not offered"

    _guid, r = _submit(c, html, image3d="model.glb", background="work:bg2")
    assert "Gates failed" in r.text, "and not accepted either"


def test_the_format_property_is_gone_from_form_and_record(client):
    """Dropped 2026-09-06. cwva-py makes every file-format decision from the
    file extension and its mimetype; `vad:fileFormat` was a display-only literal
    restating the filename, so the form was asking the user to get something
    right that nothing reads. Old records keep theirs harmlessly."""
    c, qa = client
    html = c.get("/rdf/digital").text
    assert "file_format" not in html
    assert "fileFormat" not in html

    guid, r = _submit(c, html)
    assert r.status_code == 200, r.text
    assert "vad:fileFormat" not in (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
