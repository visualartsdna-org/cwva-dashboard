"""Branding on the way in — inventory #7 (Brand Image) reached from both writers.

Rick: "we don't need brand image anymore because edit record does everything
needed. It takes a new file, associates it with the record and brands it on the
way in." Two of those three were true — the image he tested with arrived already
branded by the legacy Groovy server, and the dashboard's copy was byte-identical
to it. These tests are the third.

It is wired into the INGEST PATH rather than a page of its own, so RDF Entry
gets it too. Branding only in Edit Record would mean a new work's image arrives
unbranded and you create the record, then edit it just to brand — which is Brand
Image again, wearing a different hat.
"""

from __future__ import annotations

import re
import shutil
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import TEST_DOMAIN
from cwva_dashboard.inbox import Inbox
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

SITES = ["https://test.art", "https://other.art"]


def _photo(colour=(30, 90, 140), w=1200, h=900) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


@pytest.fixture
def drop_folder(tmp_path):
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "fresh.jpg").write_bytes(_photo())
    (folder / "second.jpg").write_bytes(_photo(colour=(200, 200, 40)))
    return folder


def _app(tmp_path, drop_folder, *, sites=SITES):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    (qa_root / "content" / "images").mkdir(parents=True)
    (qa_root / "content" / "images" / "pic.jpg").write_bytes(_photo(colour=(9, 9, 9)))
    (qa_root / "content" / "images" / "pic2.jpg").write_bytes(_photo(colour=(8, 8, 8)))
    model = qa_root / "metacontent" / "model"
    model.mkdir(parents=True)
    (model / "tiny.ttl").write_text(
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "vad:PaintingForm a owl:Class .\n"
        "vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .\n"
    )
    vocab = qa_root / "metacontent" / "vocab"
    vocab.mkdir(parents=True)
    (vocab / "papers.ttl").write_text(
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix the: <http://visualartsdna.org/thesaurus/> .\n"
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        'the:TestPaper a vad:WatercolorPaper, skos:Concept ; rdfs:label "Test Paper" .\n'
    )
    return create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl", inbox=Inbox(drop_folder), sites=sites,
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"),
            image_base=image_base(TEST_DOMAIN), layout=Layout.default(),
            vocab_dirs=[Layout.default().dir("vocab_ttl")],
        ),
    ), qa_root


@pytest.fixture
def client(tmp_path, drop_folder):
    app, qa_root = _app(tmp_path, drop_folder)
    with TestClient(app) as c:
        yield c, qa_root, drop_folder


def _options(html: str, field: str) -> list[str]:
    m = re.search(rf'<select id="{field}" name="{field}".*?</select>', html, re.S)
    return re.findall(r'<option value="([^"]*)"', m.group(0)) if m else []


def _entry(c, **over):
    html = c.get("/rdf/entry").text
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
    data = {
        "guid": guid, "type": _options(html, "type")[0], "label": "Branded Work",
        "description": "d", "height": "10", "width": "8", "units": "inch",
        "recorded_date": "2026-09-14", "completed_date": "2026-09-14",
        "has_paper": (_options(html, "has_paper") or ["the:X"])[-1],
        "has_artist_profile": "work:abc", "image": "fresh.jpg",
    }
    data.update(over)
    return c.post("/rdf/entry", data=data), guid


def _ink_count(path, ground):
    img = Image.open(path).convert("RGB")
    w, h = img.size
    return sum(1 for x in range(int(w * 0.85), w) for y in range(int(h * 0.93), h)
               if abs(img.getpixel((x, y))[0] - ground) > 25)


# ---------------------------------------------------------------------------
# What the form offers is what the deployment configured.
# ---------------------------------------------------------------------------

def test_the_form_offers_the_signatures_from_config(client):
    c, _qa, _drop = client

    offered = _options(c.get("/rdf/entry").text, "brand_signature")

    assert offered == ["", "test.art", "other.art"], "blank first — see below"


def test_the_default_is_NOT_TO_BRAND(client):
    """Branding is destructive and not idempotent, and Rick's images already
    arrive branded from the legacy server — a default of on would double-stamp
    his existing workflow on day one."""
    c, _qa, _drop = client

    html = c.get("/rdf/entry").text

    assert re.search(r'<option value=""[^>]*>&mdash; leave as they are', html)
    assert 'value="test.art" selected' not in html


def test_a_deployment_with_no_sites_is_offered_nothing(tmp_path, drop_folder):
    app, _ = _app(tmp_path, drop_folder, sites=[])
    with TestClient(app) as c:
        assert "brand_signature" not in c.get("/rdf/entry").text


# ---------------------------------------------------------------------------
# RDF Entry.
# ---------------------------------------------------------------------------

def test_entry_brands_the_image_it_ingested(client):
    c, qa_root, drop = client

    r, _guid = _entry(c, brand_signature="test.art")

    assert r.status_code == 200
    landed = qa_root / "content" / "images" / "BrandedWork.jpg"
    assert landed.read_bytes() != (drop / "fresh.jpg").read_bytes()
    assert _ink_count(landed, 140) > 50, "a signature was drawn in the corner"
    assert "branded" in r.text and "test.art" in r.text


def test_the_drop_folder_FILE_IS_NEVER_TOUCHED(client):
    """The user's folder is theirs (law 12) — the stamp lands on the sandbox
    copy, so re-running the entry still starts from a clean original."""
    c, _qa, drop = client
    before = (drop / "fresh.jpg").read_bytes()

    _entry(c, brand_signature="test.art")

    assert (drop / "fresh.jpg").read_bytes() == before


def test_without_a_signature_the_bytes_ARRIVE_UNCHANGED(client):
    """Which is exactly what Rick observed on 2026-09-14: the ingested file was
    byte-identical to the one he dropped, because his arrived pre-branded."""
    c, qa_root, drop = client

    _entry(c)

    landed = qa_root / "content" / "images" / "BrandedWork.jpg"
    assert landed.read_bytes() == (drop / "fresh.jpg").read_bytes()


def test_an_image_ALREADY_IN_THE_STORE_is_left_alone(client):
    """Only files this submit copied in are branded. Anything already in the
    store belongs to a record that was published with whatever it carries."""
    c, qa_root, _drop = client
    stored = qa_root / "content" / "images" / "pic.jpg"
    before = stored.read_bytes()

    _entry(c, image="pic.jpg", brand_signature="test.art")

    assert stored.read_bytes() == before


def test_the_signature_is_not_offered_to_the_record_tool(client):
    """`brand_signature` is an instruction about the file, not a predicate. The
    record tool refuses what it does not declare, so a leak fails the submit."""
    c, _qa, _drop = client

    r, _guid = _entry(c, brand_signature="test.art")

    assert r.status_code == 200
    assert "additionalProperties" not in r.text and "unexpected" not in r.text.lower()


def test_a_signature_this_deployment_never_configured_is_refused(client):
    """The form's enum and the tool's enum are one list; posting past the form
    reaches the same closed set."""
    c, qa_root, drop = client

    r, _guid = _entry(c, brand_signature="evil.example")

    landed = qa_root / "content" / "images" / "BrandedWork.jpg"
    assert landed.read_bytes() == (drop / "fresh.jpg").read_bytes(), "not branded"
    assert "NOT branded" in r.text, "and the review says so rather than staying quiet"


# ---------------------------------------------------------------------------
# Edit Record — the path Rick actually drove.
# ---------------------------------------------------------------------------

# The record names a profile, the profile names an artist, the artist declares
# the brand — which is the whole chain Edit Record follows instead of asking.
RECORD = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ops:  <http://visualartsdna.org/operations/> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:w1 a vad:Watercolor ;
    rdfs:label "Adelaide Sketch" ;
    vad:hasArtistProfile work:prof-1 ;
    schema:image <http://test.example/images/pic.jpg> .
"""

# A SEPARATE file: Edit Record only opens a file with one named subject, which
# is what makes rewriting it whole safe.
PROFILE_AND_ARTIST = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ops:  <http://visualartsdna.org/operations/> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:artist-1 a vad:Painter ; rdfs:label "A Painter" ; vad:brand "example.art" .

work:prof-1 a vad:ArtistProfile ;
    vad:artist work:artist-1 ;
    rdfs:label "A profile" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ] ;
    ops:template [
        ops:templateType vad:Watercolor ;
        ops:field [ ops:property rdf:type   ; ops:order 1 ; ops:required true ] ;
        ops:field [ ops:property rdfs:label ; ops:order 2 ; ops:required true ] ;
    ] .
"""


@pytest.fixture
def edit_client(tmp_path, drop_folder):
    app, qa_root = _app(tmp_path, drop_folder)
    data = qa_root / Layout.default().dir("work_ttl")
    data.mkdir(parents=True, exist_ok=True)
    (data / "w1.ttl").write_text(
        RECORD.replace("http://test.example/images/", image_base(TEST_DOMAIN))
    )
    (data / "profile.ttl").write_text(PROFILE_AND_ARTIST)
    # The legacy shape: a record that names no profile, so there is no artist to
    # ask about branding.
    # Its OWN image. Sharing one with w1 made a one-for-one replacement on
    # either of them an overwrite of the other's file — correctly refused since
    # 2026-10-07, and an accident of the fixture rather than the case under
    # test here.
    (data / "w2.ttl").write_text(
        RECORD.replace("http://test.example/images/", image_base(TEST_DOMAIN))
              .replace("work:w1", "work:w2")
              .replace("    vad:hasArtistProfile work:prof-1 ;\n", "")
              .replace("images/pic.jpg", "images/pic2.jpg")
    )
    with TestClient(app) as c:
        yield c, qa_root, drop_folder


def _edit_save(c, path="content/ttl/data/w1.ttl", **edits):
    html = c.get(f"/edit/open?path={path}").text
    values = dict(re.findall(
        r'<input type="[^"]*" id="([^"]+)" name="[^"]+" value="([^"]*)"', html))
    # the image field is a <select>; carry its current value forward
    for sel in re.finditer(r'<select id="([^"]+)" name="[^"]+".*?</select>', html, re.S):
        cur = re.search(r'<option value="([^"]*)" selected', sel.group(0))
        if cur:
            values[sel.group(1)] = cur.group(1)
    values.update(edits)
    values["path"] = path
    return c.post("/edit/save", data=values)


def test_the_edit_form_asks_NO_branding_question(edit_client):
    """Rick: "I already made my decision on branding when I created the artist."
    The record names a profile, the profile names an artist, the artist declares
    a brand or does not — so there is nothing to ask."""
    c, _qa, _drop = edit_client

    html = c.get("/edit/open?path=content/ttl/data/w1.ttl").text

    assert "brand_signature" not in html
    assert "Brand this image" not in html


def test_editing_in_a_NEW_IMAGE_brands_it(edit_client):
    """"It takes a new file, associates it with the record and brands it on the
    way in" — now true of the dashboard, not of the file's history. The
    signature is the ARTIST's, reached through the record's profile."""
    c, qa_root, drop = edit_client

    r = _edit_save(c, **{"https://schema.org/image": "fresh.jpg"})

    assert r.status_code == 200
    # Edit Record keeps the drop folder's name. Naming after the record is an
    # ENTRY-SUBMIT rule (2026-10-07) and deliberately one call site, so a file
    # picked here lands as it was dropped.
    landed = qa_root / "content" / "images" / "pic.jpg"
    assert landed.exists() and landed.read_bytes() != (drop / "fresh.jpg").read_bytes()
    assert _ink_count(landed, 140) > 50
    assert "branded" in r.text


def test_saving_WITHOUT_changing_the_image_does_not_restamp(edit_client):
    """The hazard branding-on-ingest has to answer: a record saved twice must
    not carry two signatures. Only a file this save copied in is branded, and an
    unchanged field copies nothing."""
    c, qa_root, _drop = edit_client
    _edit_save(c, **{"https://schema.org/image": "fresh.jpg",
                     "brand_signature": "test.art"})
    once = (qa_root / "content" / "images" / "pic.jpg").read_bytes()

    r = _edit_save(c, **{"https://schema.org/image": "fresh.jpg",
                         "brand_signature": "test.art",
                         "http://www.w3.org/2000/01/rdf-schema#label": "Renamed"})

    assert r.status_code == 200
    assert (qa_root / "content" / "images" / "pic.jpg").read_bytes() == once


# ---------------------------------------------------------------------------
# The affordance, not the mechanism.
#
# Rick changed a record's image to an unbranded drop-folder file, reached the
# review, and found it unbranded — the control was correct and offered both
# signatures, but it sat at the foot of the form below every predicate, and the
# review said nothing about the image that had just arrived.
# ---------------------------------------------------------------------------

def test_the_control_sits_UNDER_THE_IMAGE_FIELD_on_entry(client):
    c, _qa, _drop = client

    html = c.get("/rdf/entry").text
    image_at = html.index('name="image"')
    brand_at = html.index('name="brand_signature"')
    next_field = html.find('<div class="row">', brand_at)

    assert image_at < brand_at, "after the image field"
    # and not parked at the end: some other row still follows it
    assert next_field != -1, "the form continues below it"


def test_an_UNBRANDED_arrival_is_reported_at_the_review(client):
    """The failure that cost Rick a round trip was silence: the image came in
    unstamped and the review had nothing to say about it."""
    c, _qa, _drop = client

    r, _guid = _entry(c)  # no signature chosen

    assert "not branded" in r.text
    assert "fresh.jpg" in r.text


def test_an_unbranded_arrival_is_reported_on_EDIT_too(edit_client):
    """A record with no profile to ask — one made before profiles existed — has
    no artist and therefore no brand. That is a legitimate outcome, not an
    error, so the review reports it rather than failing the save."""
    c, _qa, _drop = edit_client

    r = _edit_save(c, path="content/ttl/data/w2.ttl",
                   **{"https://schema.org/image": "fresh.jpg"})

    assert "not branded" in r.text and "pic2.jpg" in r.text


def test_an_image_that_did_not_arrive_is_not_mentioned(client):
    """Only files this save copied in. A record pointing at something already in
    the store has nothing to report either way."""
    c, _qa, _drop = client

    r, _guid = _entry(c, image="pic.jpg")

    assert "not branded" not in r.text
