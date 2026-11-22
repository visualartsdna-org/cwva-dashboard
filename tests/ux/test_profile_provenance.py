"""A work made on a profile form gets its incipient provenance (PROVENANCE_PLAN §9).

Everything in the record is derived, and a DI cannot be recomputed once it is on
a box flap, so these assert the derivation and that an id is spent once per work.
"""

from __future__ import annotations

import re
import shutil
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, XSD

from conftest import TEST_DOMAIN
from cwva_dashboard.inbox import Inbox
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion import gates
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.provenance_tools import storage_class_for
from cwva_dashboard.tools.record_tools import image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

VAD = Namespace("http://visualartsdna.org/model/")
SCHEMA = Namespace("https://schema.org/")
LAYOUT = Layout.default()

PROFILE = """@prefix vad:    <http://visualartsdna.org/model/> .
@prefix ops:    <http://visualartsdna.org/operations/> .
@prefix work:   <http://visualartsdna.org/work/> .
@prefix schema: <https://schema.org/> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

work:PROF a vad:ArtistProfile ;
    vad:artist work:painter ;
    rdfs:label "PROF profile" ;
    schema:description "a practice" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ] ;
    ops:template [
        ops:templateType vad:TYPE ;
        ops:field [ ops:property vad:hasArtistProfile ; ops:order 1 ; ops:required true ] ;
        ops:field [ ops:property rdf:type             ; ops:order 2 ; ops:required true ] ;
        ops:field [ ops:property rdfs:label           ; ops:order 3 ; ops:required true ] ;
        ops:field [ ops:property schema:dateCreated   ; ops:order 4 ; ops:required false ] ;
        ops:field [ ops:property schema:image         ; ops:order 5 ; ops:required true ] ;
        ops:field [ ops:property schema:identifier    ; ops:order 6 ; ops:required true ] ;
        ops:field [ ops:property vad:qrcode           ; ops:order 7 ; ops:required true ] ;
    ] .
"""

ARTIST = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
work:painter a vad:Painter ; rdfs:label "A Painter" ; vad:brand "example.art" .
"""

MODEL = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
vad:ArtForm a owl:Class .
vad:PaintingForm a owl:Class ; rdfs:subClassOf vad:ArtForm .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:SculptureForm a owl:Class ; rdfs:subClassOf vad:ArtForm .
vad:BlenderComposition a owl:Class ; rdfs:subClassOf vad:SculptureForm .
"""

PROV_PREFIXES = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix schema: <https://schema.org/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .
"""

SOLUTIONS = PROV_PREFIXES + """
work:box a vad:StorageSolution ; vad:storageClass "" ; vad:hasWorkType vad:Watercolor .
work:blend a vad:StorageSolution ; vad:storageClass "blender" ;
    vad:hasWorkType vad:BlenderComposition .
"""


def _existing(guid="p1", item=40, work="old", di=None):
    return PROV_PREFIXES + f"""
work:{guid} a vad:Provenance ; vad:hasArtwork work:{work} ;
    vad:hasArtworkOwner work:painter ; vad:dispositionId "{di or f'2020.{item}'}" ;
    vad:itemId {item} ; schema:startDate "2020-01-01"^^xs:date .
"""


@pytest.fixture
def env(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    data = qa_root / LAYOUT.dir("work_ttl")
    data.mkdir(parents=True)
    (data / "painter.ttl").write_text(ARTIST)
    (data / "old.ttl").write_text(
        '@prefix work: <http://visualartsdna.org/work/> .\n'
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        'work:old rdfs:label "Old" .\n')
    (data / "wc.ttl").write_text(PROFILE.replace("PROF", "wc").replace("TYPE", "Watercolor"))
    (data / "bl.ttl").write_text(
        PROFILE.replace("PROF", "bl").replace("TYPE", "BlenderComposition"))
    model = qa_root / LAYOUT.dir("model_ttl")
    model.mkdir(parents=True)
    (model / "tiny.ttl").write_text(MODEL)
    (qa_root / LAYOUT.dir("image")).mkdir(parents=True)
    prov = qa_root / LAYOUT.dir("provenance_ttl")
    prov.mkdir(parents=True)
    (prov / "solutions.ttl").write_text(SOLUTIONS)
    (prov / "p1.ttl").write_text(_existing())

    drop = tmp_path / "drop"
    drop.mkdir()
    buf = BytesIO()
    Image.new("RGB", (600, 400), (40, 80, 120)).save(buf, format="JPEG")
    (drop / "sunset.jpg").write_bytes(buf.getvalue())
    (drop / "dusk.jpg").write_bytes(buf.getvalue())

    sot = tmp_path / "sot"
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl", inbox=Inbox(drop),
        promotion_driver=PromotionDriver(
            qa, FilesTransport(sot), layout=LAYOUT, image_base=image_base(TEST_DOMAIN),
        ),
    )
    with TestClient(app) as c:
        # What is already there is the published baseline.
        prev = c.post("/api/promotion/preview", json={}).json()
        assert prev["status"] == "previewed", prev
        assert c.post("/api/promotion/approve", json={"token": prev["token"]}
                      ).json()["status"] == "converged"
        yield c, qa_root, sot


def _guid(page):
    return re.search(r'name="guid" value="([^"]+)"', page).group(1)


def _submit(c, profile="wc", *, guid=None, label="Marsh", date="2026-11-04",
            image="sunset.jpg"):
    guid = guid or _guid(c.get(f"/rdf/profile/{profile}").text)
    type_ = "Watercolor" if profile == "wc" else "BlenderComposition"
    r = c.post(f"/rdf/profile/{profile}", data={
        "guid": guid, "type": type_, "label": label, "completed_date": date, "image": image})
    assert r.status_code == 200, r.text[:600]
    return guid, r


def _provenance_of(qa_root, guid):
    """Every record in the folder citing this work, as (path, graph)."""
    work = URIRef(f"{TEST_DOMAIN}/work/{guid}")
    out = []
    for f in (qa_root / LAYOUT.dir("provenance_ttl")).glob("*.ttl"):
        g = Graph().parse(str(f), format="turtle")
        if (None, VAD.hasArtwork, work) in g:
            out.append((f, g))
    return out


def test_a_profile_submit_writes_the_incipient_record(env):
    c, qa_root, _sot = env

    guid, r = _submit(c)

    (_path, g), = _provenance_of(qa_root, guid)
    s = next(g.subjects(VAD.hasArtwork, None))
    assert (s, RDF.type, VAD.Provenance) in g
    assert g.value(s, VAD.dispositionId) == Literal("2026.41"), "the next id, the work's year"
    assert g.value(s, VAD.itemId) == Literal(41)
    assert g.value(s, VAD.hasArtworkOwner) == URIRef(f"{TEST_DOMAIN}/work/painter")
    assert g.value(s, SCHEMA.startDate) == Literal("2026-11-04", datatype=XSD.date)
    assert "Marsh" in {str(o) for o in g.objects(s, None)}, "labelled for the work"


def test_the_review_shows_the_DI_because_it_goes_on_the_box(env):
    c, _qa, _sot = env

    _guid_, r = _submit(c)

    assert "2026.41" in r.text
    assert "allocated" in r.text


def test_a_digital_work_gets_a_file_provenance_and_its_class(env):
    c, qa_root, _sot = env

    guid, r = _submit(c, "bl")

    (_path, g), = _provenance_of(qa_root, guid)
    s = next(g.subjects(VAD.hasArtwork, None))
    assert (s, RDF.type, VAD.FileProvenance) in g
    assert g.value(s, VAD.dispositionId) == Literal("blender.2026.41")
    assert "does not yet name the" in r.text, "the missing file location is said aloud"


def test_a_resubmit_keeps_the_item_id_and_the_record(env):
    """Going back to fix a typo must not burn a number or leave a second record."""
    c, qa_root, _sot = env
    guid, _r = _submit(c)

    _guid_, r = _submit(c, guid=guid, label="Marsh at Dawn")

    records = _provenance_of(qa_root, guid)
    assert len(records) == 1
    g = records[0][1]
    assert next(g.objects(None, VAD.itemId)) == Literal(41)
    assert "Marsh at Dawn" in {str(o) for o in g.objects(None, None)}
    assert "kept from your earlier submit" in r.text


def test_the_next_work_gets_the_next_id_even_while_the_first_is_a_draft(env):
    c, qa_root, _sot = env
    _submit(c)

    second, _r = _submit(c, label="Heron", image="dusk.jpg")

    g = _provenance_of(qa_root, second)[0][1]
    assert next(g.objects(None, VAD.itemId)) == Literal(42)


def test_approving_distributes_the_work_and_its_provenance_together(env):
    c, _qa, sot = env
    guid, r = _submit(c)
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)

    out = c.post("/rdf/entry/approve", data={"token": token})

    assert out.status_code == 200, out.text[:400]
    assert (sot / LAYOUT.dir("work_ttl") / f"{guid}.ttl").is_file()
    folder = sot / LAYOUT.dir("provenance_ttl")
    assert any("2026.41" in f.read_text() for f in folder.glob("*.ttl"))


def test_no_date_means_no_record_and_the_review_says_so(env):
    """A DI's year cannot be guessed, and it cannot be corrected once on a box."""
    c, qa_root, _sot = env

    guid, r = _submit(c, date="")

    assert _provenance_of(qa_root, guid) == []
    assert "No provenance record was written" in r.text


def test_discarding_the_draft_takes_its_provenance_with_it(env):
    """Left behind, it would ship a provenance citing an artwork that is gone."""
    c, qa_root, _sot = env
    guid, _r = _submit(c)
    assert _provenance_of(qa_root, guid)

    r = c.post("/drafts/discard", data={"guid": guid})

    assert r.status_code == 200, r.text[:400]
    assert _provenance_of(qa_root, guid) == []


def test_a_provenance_for_a_published_work_is_its_own_draft(env):
    """The Lepers' Hearth case: the work went out first, the record comes later."""
    c, qa_root, _sot = env
    prov = qa_root / LAYOUT.dir("provenance_ttl")
    (prov / "late.ttl").write_text(_existing("late", 41, "old"))

    page = c.get("/drafts")

    assert page.status_code == 200
    assert "late" in page.text


# -- the rules on their own ----------------------------------------------------


def test_the_nearest_solution_wins_and_no_match_is_the_blank_class():
    model = Graph().parse(data=MODEL, format="turtle")
    solutions = Graph().parse(data=SOLUTIONS + (
        'work:paint a vad:StorageSolution ; vad:storageClass "paint" ; '
        "vad:hasWorkType vad:PaintingForm .\n"), format="turtle")

    assert storage_class_for({VAD.Watercolor}, solutions, model) == "", (
        "mapped directly to the blank class, ahead of the parent's")
    assert storage_class_for({VAD.BlenderComposition}, solutions, model) == "blender"
    assert storage_class_for({VAD.OilPainting}, solutions, model) == ""
    model.add((VAD.OilPainting, URIRef("http://www.w3.org/2000/01/rdf-schema#subClassOf"),
               VAD.PaintingForm))
    assert storage_class_for({VAD.OilPainting}, solutions, model) == "paint", "by subsumption"


def _gate(tmp_path, *records, content=("old",), unit=None):
    prov = tmp_path / "prov"
    prov.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    for name in content:
        (data_dir / f"{name}.ttl").write_text("")
    for i, text in enumerate(records):
        (prov / f"r{i}.ttl").write_text(text)
    data = Graph().parse(data=unit or records[-1], format="turtle")
    return gates.provenance_gate(data, tmp_path, "prov", content_dirs=["data"])


def test_gate_passes_consistent_records(tmp_path):
    assert _gate(tmp_path, _existing("a", 1), _existing("b", 2, "old2", "2020.2"),
                 content=("old", "old2")).ok


def test_gate_refuses_a_reused_item_id(tmp_path):
    r = _gate(tmp_path, _existing("a", 7), _existing("b", 7, "old2", "2021.7"),
              content=("old", "old2"))
    assert not r.ok and any("item id 7" in m for m in r.messages)


def test_gate_refuses_a_second_incipient_record_for_a_work(tmp_path):
    r = _gate(tmp_path, _existing("a", 1), _existing("b", 2, "old", "2020.2"))
    assert not r.ok and any("already has an incipient" in m for m in r.messages)


def test_gate_refuses_an_item_id_that_disagrees_with_its_DI(tmp_path):
    r = _gate(tmp_path, _existing("a", 3, "old", "2020.4"))
    assert not r.ok and any("not the end of DI" in m for m in r.messages)


def test_gate_refuses_a_dangling_artwork(tmp_path):
    r = _gate(tmp_path, _existing("a", 1, "gone"))
    assert not r.ok and any("not in the store" in m for m in r.messages)


def test_a_transfer_record_needs_no_DI(tmp_path):
    transfer = PROV_PREFIXES + """
work:t a vad:Provenance ; vad:hasArtwork work:old ; vad:hasArtworkOwner work:buyer ;
    schema:startDate "2024-01-01"^^xs:date .
"""
    assert _gate(tmp_path, _existing("a", 1), transfer).ok


# -- the definitive file of a digital work -------------------------------------


def _location_of(qa_root, guid):
    g = _provenance_of(qa_root, guid)[0][1]
    return str(next(g.objects(None, VAD.fileLocation), ""))


def test_a_digital_profile_form_asks_for_the_original_file(env):
    c, _qa, _sot = env

    assert 'name="file_location"' in c.get("/rdf/profile/bl").text
    assert 'name="file_location"' not in c.get("/rdf/profile/wc").text, (
        "a watercolour is a thing in a box, not a file")


def test_a_pasted_windows_path_becomes_a_real_IRI(env):
    c, qa_root, _sot = env
    guid = _guid(c.get("/rdf/profile/bl").text)

    r = c.post("/rdf/profile/bl", data={
        "guid": guid, "type": "BlenderComposition", "label": "Torso",
        "completed_date": "2026-11-16", "image": "sunset.jpg",
        "file_location": r"G:\My Drive\art\3d\torso final.blend"})

    assert r.status_code == 200, r.text[:400]
    assert _location_of(qa_root, guid) == "file:///G:/My%20Drive/art/3d/torso%20final.blend"
    assert "torso%20final.blend" in r.text, "and the review shows it"
    assert "does not yet name" not in r.text


def test_the_location_survives_going_back_to_the_form(env):
    c, qa_root, _sot = env
    guid = _guid(c.get("/rdf/profile/bl").text)
    data = {"guid": guid, "type": "BlenderComposition", "label": "Torso",
            "completed_date": "2026-11-16", "image": "sunset.jpg",
            "file_location": r"G:\art\torso.blend"}
    r = c.post("/rdf/profile/bl", data=data)
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)

    back = c.post("/rdf/entry/edit", data={"token": token})
    assert r"G:\art\torso.blend" in back.text, "what was typed is redisplayed"

    before = [p.name for p, _ in _provenance_of(qa_root, guid)]
    c.post("/rdf/profile/bl", data={**data, "label": "Torso II", "file_location": ""})
    assert [p.name for p, _ in _provenance_of(qa_root, guid)] == before, (
        "the same record, rewritten: Edit form used to trash it and mint another")
    assert _location_of(qa_root, guid) == "file:///G:/art/torso.blend", (
        "a re-submit that leaves it blank keeps the one already recorded")


def test_a_path_that_cannot_be_an_IRI_is_refused_at_the_review(env):
    c, qa_root, _sot = env
    guid = _guid(c.get("/rdf/profile/bl").text)

    r = c.post("/rdf/profile/bl", data={
        "guid": guid, "type": "BlenderComposition", "label": "Torso",
        "completed_date": "2026-11-16", "image": "sunset.jpg",
        "file_location": "torso.blend"})

    assert r.status_code == 200
    assert _provenance_of(qa_root, guid) == []
    assert "not a full path" in r.text


def test_a_location_on_an_object_is_said_to_be_ignored(env):
    c, qa_root, _sot = env
    guid = _guid(c.get("/rdf/profile/wc").text)

    r = c.post("/rdf/profile/wc", data={
        "guid": guid, "type": "Watercolor", "label": "Marsh",
        "completed_date": "2026-11-16", "image": "sunset.jpg",
        "file_location": r"G:\scan.tif"})

    assert _location_of(qa_root, guid) == ""
    assert "was not recorded" in r.text
