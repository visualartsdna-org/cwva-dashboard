"""Profile-driven entry: a card per artist profile, and the form behind it.

Rick's design (`dashboardEntryFormApproach.txt`, CE_DESIGN §14): "The names RDF
Entry and RDF Digital go away, replaced by the labels from the respective artist
profiles. These become the selectable cards for Content Management."

The form behind a card is generated from that profile's `ops:template` — fields,
their order, what is required — and the record it writes is generated from the
same template. So this is the release blocker closing: the dashboard stops being
tailored to one artist's watercolours.
"""

from __future__ import annotations

import re
import shutil
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from rdflib import Graph, Namespace, URIRef

from conftest import TEST_DOMAIN
from cwva_dashboard.inbox import Inbox
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

VAD = Namespace("http://visualartsdna.org/model/")
SCHEMA = Namespace("https://schema.org/")
RDFS_NS = Namespace("http://www.w3.org/2000/01/rdf-schema#")

PROFILE_TTL = """@prefix vad:    <http://visualartsdna.org/model/> .
@prefix ops:    <http://visualartsdna.org/operations/> .
@prefix work:   <http://visualartsdna.org/work/> .
@prefix schema: <https://schema.org/> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

work:artist-1 a vad:Painter ; rdfs:label "A Painter" ; vad:brand "example.art" .

work:prof-1 a vad:ArtistProfile ;
    vad:artist work:artist-1 ;
    rdfs:label "Watercolor materials profile" ;
    schema:description "watercolours on paper" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ] ;
    ops:template [
        ops:templateType vad:Watercolor ;
        ops:field [ ops:property vad:hasArtistProfile ; ops:order 1 ; ops:required true ] ;
        ops:field [ ops:property rdf:type             ; ops:order 2 ; ops:required true ] ;
        ops:field [ ops:property rdfs:label           ; ops:order 3 ; ops:required true ] ;
        ops:field [ ops:property schema:image         ; ops:order 4 ; ops:required true ] ;
        ops:field [ ops:property schema:height        ; ops:order 5 ; ops:required true ] ;
        ops:field [ ops:property schema:width         ; ops:order 6 ; ops:required true ] ;
        ops:field [ ops:property schema:identifier    ; ops:order 7 ; ops:required true ] ;
        ops:field [ ops:property vad:qrcode           ; ops:order 8 ; ops:required true ] ;
    ] .

work:prof-broken a vad:ArtistProfile ;
    vad:artist work:artist-1 ;
    rdfs:label "Half-written profile" ;
    ops:template [ ops:templateType vad:Watercolor ] .
"""

MODEL = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
vad:PaintingForm a owl:Class .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:OilPainting a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:BlenderComposition a owl:Class ; rdfs:subClassOf vad:SculptureForm .
"""


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    lay = Layout.default()
    data = qa_root / lay.dir("work_ttl")
    data.mkdir(parents=True)
    (data / "profiles.ttl").write_text(PROFILE_TTL)
    model = qa_root / lay.dir("model_ttl")
    model.mkdir(parents=True)
    (model / "tiny.ttl").write_text(MODEL)
    (qa_root / lay.dir("image")).mkdir(parents=True)

    drop = tmp_path / "drop"
    drop.mkdir()
    # A REAL JPEG. Four fake bytes make branding refuse the file, correctly, and
    # then the test is measuring the fixture rather than the feature.
    buf = BytesIO()
    Image.new("RGB", (600, 400), (40, 80, 120)).save(buf, format="JPEG")
    (drop / "sunset.jpg").write_bytes(buf.getvalue())

    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl", inbox=Inbox(drop),
        sites=["https://legacy.example"],
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=lay,
            image_base=image_base(TEST_DOMAIN),
        ),
    )
    with TestClient(app) as c:
        yield c, qa_root


def _card_guids(html: str) -> dict:
    return {label: guid for guid, label in re.findall(
        r'href="rdf/profile/([\w-]+)" class="card[^"]*"><div class="card-title">([^<]+)</div>',
        html)}


def test_the_hub_offers_a_card_PER_PROFILE(client):
    c, _qa = client

    cards = _card_guids(c.get("/").text)

    assert "Watercolor materials profile" in cards
    assert cards["Watercolor materials profile"] == "prof-1"


def test_the_old_names_are_GONE_from_the_hub(client):
    """Rick: "The names RDF Entry and RDF Digital go away." The routes survive —
    nothing is broken by removing a card — but the hub speaks in the artist's
    own words now."""
    c, _qa = client
    hub = c.get("/").text

    assert "RDF Entry" not in hub and "RDF Digital" not in hub
    assert c.get("/rdf/entry").status_code == 200, "still reachable, just not offered"


def test_a_profile_that_cannot_build_a_form_says_so_ON_A_CARD(client):
    """Not omitted. A card that never appears is indistinguishable from a
    profile nobody wrote, and the person who can fix it is looking at it."""
    c, _qa = client
    hub = c.get("/").text

    assert "Half-written profile" in hub
    assert "cannot build a form" in hub
    assert 'href="rdf/profile/prof-broken"' not in hub, "and it does not lead anywhere"


def test_opening_the_broken_one_directly_explains_itself(client):
    c, _qa = client

    r = c.get("/rdf/profile/prof-broken")

    assert r.status_code == 404
    assert "Half-written profile" in r.text and "no ops:field" in r.text


def test_the_form_follows_the_TEMPLATES_ORDER(client):
    c, _qa = client

    page = c.get("/rdf/profile/prof-1").text
    fields = [f for f in re.findall(r'<label for="([^"]+)"', page)
              if f not in ("brand_signature",)]

    assert fields == ["type", "label", "image", "height", "width"]
    assert "units" not in fields, "the profile's measurement system supplies it"
    assert "qrcode" not in fields and "guid" not in fields, (
        "derived, never typed — and neither is shown, where showing one and not "
        "the other made the form look arbitrary"
    )
    assert "has_artist_profile" not in fields, (
        "the page is titled with the profile's label; a field repeating it asks "
        "a question already answered on screen"
    )


def test_the_type_picker_offers_the_PARENTS_subclasses(client):
    """A watercolour profile can still record the mixed-media piece the work
    turned into — but not a Blender composition."""
    c, _qa = client

    page = c.get("/rdf/profile/prof-1").text
    sel = re.search(r'<select id="type" name="type".*?</select>', page, re.S).group(0)
    offered = re.findall(r'value="([^"]*)"', sel)

    assert "Watercolor" in offered and "OilPainting" in offered
    assert "BlenderComposition" not in offered


def test_the_artist_profile_is_SUPPLIED_not_asked_and_not_posted(client):
    """Housekeeping (Rick, 2026-09-16): every record carries it, no form shows
    it, and it is written server-side rather than round-tripped as a hidden
    input — a field the browser posts back is a field the browser can change,
    and this is the record's provenance."""
    c, qa_root = client

    page = c.get("/rdf/profile/prof-1").text
    assert "has_artist_profile" not in page

    guid = re.search(r'name="guid" value="([^"]+)"', page).group(1)
    c.post("/rdf/profile/prof-1", data={
        "guid": guid, "type": "Watercolor", "label": "Supplied",
        "image": "sunset.jpg", "height": "12", "width": "9",
    })

    g = Graph().parse(
        data=(qa_root / Layout.default().dir("work_ttl") / f"{guid}.ttl").read_text(),
        format="turtle")
    subj = URIRef(f"{TEST_DOMAIN}/work/{guid}")
    assert (subj, VAD.hasArtistProfile, URIRef(f"{TEST_DOMAIN}/work/prof-1")) in g


def test_posting_a_housekeeping_field_is_REFUSED(client):
    """Not ignored — refused. The schema does not declare it, and
    `additionalProperties: false` is what makes "supplied server-side" mean
    something against a crafted POST rather than only against the form."""
    c, _qa = client
    page = c.get("/rdf/profile/prof-1").text
    guid = re.search(r'name="guid" value="([^"]+)"', page).group(1)

    r = c.post("/rdf/profile/prof-1", data={
        "guid": guid, "type": "Watercolor", "label": "Crafted",
        "image": "sunset.jpg", "height": "12", "width": "9",
        "has_artist_profile": f"{TEST_DOMAIN}/work/somebody-else",
    })

    assert r.status_code == 400
    assert "has_artist_profile" in r.text


def test_submitting_writes_the_record_AND_STOPS_at_review(client):
    c, qa_root = client
    page = c.get("/rdf/profile/prof-1").text
    guid = re.search(r'name="guid" value="([^"]+)"', page).group(1)

    r = c.post("/rdf/profile/prof-1", data={
        "guid": guid, "type": "Watercolor", "label": "A Watercolour",
        "image": "sunset.jpg", "height": "12", "width": "9",
    })

    assert r.status_code == 200, r.text[:400]
    assert "review" in r.text.lower()
    written = qa_root / Layout.default().dir("work_ttl") / f"{guid}.ttl"
    assert written.exists()

    g = Graph().parse(data=written.read_text(), format="turtle")
    subj = URIRef(f"{TEST_DOMAIN}/work/{guid}")
    assert (subj, None, VAD.Watercolor) in g or (subj, None, None) in g
    # The unit came from the PROFILE, not from a field on the form. "12.0" and
    # not "12" because the route coerces numeric fields to float, which is what
    # every dashboard-created record already carries — Groovy-era records say
    # "15 inches", dashboard ones say "15.0 inches". Matching the existing
    # behaviour is the point; changing it is a separate decision.
    labels = {str(o) for _s, _p, o in g.triples((None, RDFS_NS.label, None))}
    assert "12.0 inches" in labels
    # and the derived properties are there though nobody typed them
    assert (subj, VAD.qrcode, None) in g
    assert (subj, SCHEMA.identifier, None) in g


def test_a_required_field_left_empty_is_REFUSED(client):
    """The template said required, so the schema says required, so
    `validate_args` refuses — one rule, not three."""
    c, _qa = client
    page = c.get("/rdf/profile/prof-1").text
    guid = re.search(r'name="guid" value="([^"]+)"', page).group(1)

    r = c.post("/rdf/profile/prof-1", data={
        "guid": guid, "type": "Watercolor", "label": "", "image": "sunset.jpg",
        "height": "12", "width": "9",
    })

    assert r.status_code == 400, "refused, and the form comes back to be fixed"
    assert "label" in r.text and ("required" in r.text.lower() or "missing" in r.text.lower())


def test_the_registered_TOOL_is_what_the_form_offers(client):
    """Offered == enforced, per profile: the tool's schema IS the form's."""
    c, _qa = client

    tools = c.get("/api/tools").json()
    tool = next(t for t in tools if t["name"] == "record.new.prof-1")
    page = c.get("/rdf/profile/prof-1").text

    for name in tool["inputSchema"]["properties"]:
        if name in ("dest_dir",):
            continue
        assert f'name="{name}"' in page, f"{name} is enforced but not offered"


# ---------------------------------------------------------------------------
# Branding comes from the ARTIST, so the form does not ask (CE_DESIGN §14.5).
# ---------------------------------------------------------------------------

def test_a_profile_form_does_NOT_ask_about_branding(client):
    """Rick: "We decided to let the artist vad:brand drive the branding
    process." The profile names the artist, the artist declares a brand or does
    not — asking offers a choice about someone whose answer is already
    recorded."""
    c, _qa = client

    page = c.get("/rdf/profile/prof-1").text

    assert "brand_signature" not in page
    assert "Brand this image" not in page


def test_an_arriving_image_is_branded_with_the_ARTISTS_brand(client):
    c, qa_root = client
    page = c.get("/rdf/profile/prof-1").text
    guid = re.search(r'name="guid" value="([^"]+)"', page).group(1)

    r = c.post("/rdf/profile/prof-1", data={
        "guid": guid, "type": "Watercolor", "label": "Branded",
        "image": "sunset.jpg", "height": "12", "width": "9",
    })

    assert "example.art" in r.text, "the artist's vad:brand, never typed here"
    assert "branded" in r.text


def test_the_legacy_forms_KEEP_the_picker(client):
    """They do not know whose work it is until the profile field is answered, so
    there is nobody to ask on their behalf."""
    c, _qa = client

    assert "brand_signature" in c.get("/rdf/entry").text


def test_a_measurement_field_NAMES_THE_UNIT_it_wants(client):
    """The artist stopped typing the unit when the profile started supplying it,
    so the field has to say which one — otherwise the form expects a number in a
    unit it never names (Rick, 2026-09-16)."""
    c, _qa = client

    page = c.get("/rdf/profile/prof-1").text
    hint = re.search(r'<label for="height">.*?<div class="hint">([^<]*)</div>',
                     page, re.S).group(1)

    assert "inches" in hint


def test_the_unit_is_APPENDED_to_what_the_model_says(client):
    """`schema:height` is the height of a thing whatever the unit; the profile's
    measurement system is what makes it inches here. Same rule as the date
    format — the model's words are not replaced."""
    from cwva_dashboard.tools.property_map import Template, TemplateField, schema_from_template
    from rdflib.namespace import RDF, RDFS

    tpl = Template(type_default=str(VAD.Watercolor), fields=(
        TemplateField(str(RDF.type), 1), TemplateField(str(RDFS.label), 2),
        TemplateField(str(SCHEMA.identifier), 3), TemplateField(str(VAD.qrcode), 4),
        TemplateField(str(SCHEMA.height), 5)))

    inches = schema_from_template(tpl, images_dir="i", unit_name="inches")
    bare = schema_from_template(tpl, images_dir="i")

    assert inches["properties"]["height"]["x-unit"] == "inches"
    assert "in inches" in inches["properties"]["height"]["description"], (
        "the tool's own description too — an agent authoring a record sees only "
        "the schema"
    )
    assert "x-unit" not in bare["properties"]["height"], "no profile, no claim"


def test_the_discard_page_leads_back_to_the_CARDS(client):
    """It used to link straight to RDF Entry — a form the hub no longer offers,
    reachable only from there (Rick, 2026-09-17). A record starts from a profile
    card now, so the exit is the dashboard, which is right in either shape: a
    deployment with no profiles still shows the hand-written cards there."""
    c, _qa = client

    # the exit is on the RESULT page — the confirm page only asks
    page = c.post("/wip/discard").text

    assert "Start a new RDF Entry" not in page
    assert 'href="/rdf/entry"' not in page
    assert "Start another record" in page


# ---------------------------------------------------------------------------
# A card is a claim that a profile exists (Rick, 2026-09-17: "I'm concerned
# about the missing profile card to get me to the form to enter a record").
# ---------------------------------------------------------------------------

def test_a_card_does_not_OUTLIVE_its_profile(client):
    """The card list came from app state, which only learned about deletions
    when a bootstrap record was written. So a profile trashed at the review stop
    left its card standing — and clicking it minted records pointing at a
    profile that was no longer there."""
    c, qa_root = client
    assert "Watercolor materials profile" in c.get("/").text

    # the Edit-form path: the record is trashed, and nothing tells app state
    (qa_root / Layout.default().dir("work_ttl") / "profiles.ttl").unlink()

    hub = c.get("/").text

    assert "Watercolor materials profile" not in hub
    assert c.get("/rdf/profile/prof-1").status_code == 404, (
        "and the URL does not resolve from a cached spec either"
    )


def test_a_profile_that_APPEARS_gets_a_card_without_a_restart(client, tmp_path):
    """The other direction: a profile synced down from the SOT, or written while
    the dashboard is running, is offered as soon as it is there."""
    c, qa_root = client
    data = qa_root / Layout.default().dir("work_ttl")

    (data / "second.ttl").write_text(
        PROFILE_TTL.replace("work:prof-1", "work:prof-9")
                   .replace('"Watercolor materials profile"', '"A later profile"')
                   .split("work:prof-broken")[0]
    )

    assert "A later profile" in c.get("/").text
    assert c.get("/rdf/profile/prof-9").status_code == 200


def test_an_UNDISTRIBUTED_profile_says_so_on_its_card(client):
    """It works like any other, and it is also the one a refresh or a discard
    takes away. Saying it on the card beats finding out when the card is gone."""
    c, _qa = client

    hub = c.get("/").text

    assert "draft &mdash; not distributed yet" in hub, (
        "the fixture's profile is uncommitted in QA"
    )


def test_a_DISTRIBUTED_profile_carries_no_such_warning(client):
    c, qa_root = client
    from cwva_dashboard.promotion.qa_git import QAGit

    QAGit(root=qa_root).commit("distribute the profile")

    assert "not distributed yet" not in c.get("/").text


def test_a_profile_driven_record_gets_its_QR(client, tmp_path):
    """`vad:qrcode` is housekeeping — always written, never listed by a built
    template — so asking the template whether to generate one answered False on
    every profile the builder made, and the record cited a QR nobody generated.
    Rick's first work through a new profile failed the asset gate on exactly
    that (2026-09-17)."""
    c, qa_root = client
    page = c.get("/rdf/profile/prof-1").text
    guid = re.search(r'name="guid" value="([^"]+)"', page).group(1)

    r = c.post("/rdf/profile/prof-1", data={
        "guid": guid, "type": "Watercolor", "label": "With a QR",
        "image": "sunset.jpg", "height": "12", "width": "9"})

    assert r.status_code == 200
    qr = qa_root / Layout.default().dir("image") / f"qrc_{guid}.jpg"
    assert qr.is_file(), "the record cites it, so it must exist"
    assert "gates failed" not in r.text.lower()


def test_a_FAILED_GATE_offers_a_way_back(client):
    """The page said "Go back to change it" and gave nothing to click: a unit
    that never previewed has no token, and the Edit-form button is built from
    one."""
    c, qa_root = client
    page = c.get("/rdf/profile/prof-1").text
    guid = re.search(r'name="guid" value="([^"]+)"', page).group(1)
    # an image that is not there: the asset gate refuses it
    r = c.post("/rdf/profile/prof-1", data={
        "guid": guid, "type": "Watercolor", "label": "Missing image",
        "image": "not-in-the-store.jpg", "height": "1", "width": "1"})

    assert "Gates failed" in r.text
    assert f"/rdf/resume/{guid}" in r.text, "and a link to get back to the form"

    back = c.get(f"/rdf/resume/{guid}")
    assert back.status_code == 200
    assert 'value="Missing image"' in back.text, "repopulated with what was typed"
    assert "still in QA" in back.text


def test_resuming_something_that_is_not_in_progress_says_so(client):
    c, _qa = client

    r = c.get("/rdf/resume/nothing-like-this")

    assert r.status_code == 404
    assert "Edit Record" in r.text, "and points at the tool that can still fix it"


def _content_tab(html: str) -> str:
    """The Content tab alone — the hub is one document with four of them."""
    return html.split('<div id="tools"', 1)[0].split('id="content"', 1)[1]


def test_the_content_cards_are_IN_THE_STATED_ORDER(client):
    """Rick's order (2026-09-17), and the reason it is a test: the profile cards
    and the bootstrap pair are substituted into the page at two different marks,
    so an edit to either side can silently reshuffle the tab."""
    c, _qa = client

    tab = _content_tab(c.get("/").text)
    titles = re.findall(r'<div class="card-title">([^<]+)</div>', tab)
    profiles = [t for t in titles if "profile" in t and t.startswith("Watercolor")]

    assert profiles, "the profile cards lead"
    assert titles.index(profiles[0]) == 0
    assert [t for t in titles if t in {
        "Edit Record", "Update workOnSite", "Annotate Work", "Entity", "Proof",
        "New artist profile", "New artist",
    }] == ["Edit Record", "Update workOnSite", "Annotate Work", "Entity",
           "Proof", "New artist profile", "New artist"]


def test_SPARQL_and_the_graph_editor_left_the_CONTENT_tab(client):
    """They are maintenance, not authoring. Moved rather than dropped — a
    function that disappears from the hub is indistinguishable from one that
    was never written."""
    c, _qa = client

    html = c.get("/").text
    tab = _content_tab(html)
    tools = html.split('<div id="tools"', 1)[1].split('<div id="files"', 1)[0]

    assert "SPARQL" not in tab
    assert "SPARQL" in tools
    # parked 2026-11-19 (html/parked.html), so on neither tab
    assert "RDF Graph Editor" not in tab and "RDF Graph Editor" not in tools


def test_the_RETIRED_cards_are_gone(client):
    """Interpretation was never used; Distribute Data is what the review stop
    already does on every write (law 4), and Discard Work in Progress is offered
    at that same stop, where you are when you want it."""
    c, _qa = client

    # Card TITLES, not the whole tab: the markdown-workflow notes printed below
    # the cards still narrate the legacy Groovy sequence, and rewriting those is
    # the job of wiring that workflow, not of reordering this one.
    titles = re.findall(r'<div class="card-title">([^<]+)</div>',
                        _content_tab(c.get("/").text))

    assert "Interpretation" not in titles
    assert "Distribute Data" not in titles
    assert "Discard Work in Progress" not in titles
    # Retired 2026-11-19 with Concept Promote: both were links to routes that
    # never existed. Model and vocabulary changes leave like any other staged
    # file, through Preview Staged — how the operations ontology reached
    # production.
    assert "Distribute Metadata" not in titles
    assert "Concept Promote" not in titles
    assert "Preview Staged" in titles


# -- a converged profile is a different form (Rick, 2026-09-27) ---------------
# Creating one through the bootstrap form rebuilds the registry on submit, so
# this never shows in ordinary use. A profile that arrives by SYNC or by SCRIPT
# was written by nobody the app can hear: the card appears (the hub reads
# profiles from disk) while the registry has no tool behind it.

ARRIVED = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ops:  <http://visualartsdna.org/operations/> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix vad:  <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:arrived-artist a vad:Painter ; rdfs:label "Arrived By Script" .

work:arrived-prof a vad:ArtistProfile ;
    rdfs:label "Arrived by script" ;
    vad:artist work:arrived-artist ;
    schema:description "A profile nobody typed into this app" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ] ;
    ops:template [ ops:templateType vad:Watercolor ;
        ops:field [ ops:property rdf:type ; ops:order 10 ; ops:required true ] ,
                  [ ops:property rdfs:label ; ops:order 20 ; ops:required true ] ] .
"""


def _approve_everything(c):
    r = c.get("/staged/preview")
    token = r.text.split('name="token" value="', 1)[1].split('"', 1)[0]
    return c.post("/rdf/entry/approve", data={"token": token})


def test_a_profile_that_ARRIVES_BY_SCRIPT_gets_a_working_form(client):
    """The card comes from disk and would appear either way; what the reload
    buys is the tool behind it."""
    c, qa_root = client
    path = qa_root / Layout.default().dir("work_ttl") / "arrived.ttl"
    path.write_text(ARRIVED)

    assert "record.new.arrived-prof" not in c.get("/api/tools").text
    _approve_everything(c)

    assert "record.new.arrived-prof" in c.get("/api/tools").text
    page = c.get("/rdf/profile/arrived-prof")
    assert page.status_code == 200
    assert "Arrived by script" in page.text


def test_a_PROFILE_record_DOES_rebuild_the_registry(client):
    """The positive counterpart to the test below, and it was missing.

    `_bootstrap_in` decides this with an EQUALITY against the type's local
    name, and nothing asserted that the equality was the right string. The
    failure is silent in the worst way: the promotion succeeds, the card is
    there because it is read from disk, and only the TOOL behind it is stale —
    a profile form serving the shape it had before.

    Found while preparing the `vad:ArtistInMedia` rename (`ARTIST_IN_MEDIA.md`),
    which would have changed that string; the rename was postponed and this gap
    was not contingent on it. Verified by mutation: changing the comparison to
    a name nothing declares fails this test and no other.
    """
    from cwva_dashboard.promotion.qa_git import QAGit

    c, qa_root = client
    qa = QAGit(root=qa_root)
    qa.stage_all()
    qa.commit("fixture baseline")
    (qa_root / Layout.default().dir("work_ttl") / "newprof.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        'work:newprof a vad:ArtistProfile ; rdfs:label "A new practice" .\n'
    )
    calls = []
    real = c.app.state.dash.reload
    c.app.state.dash.reload = lambda: (calls.append(1), real())[1]
    try:
        _approve_everything(c)
    finally:
        c.app.state.dash.reload = real

    assert calls, "a profile arrived and the registry was not rebuilt"


def test_an_ORDINARY_record_does_not_rebuild_the_registry(client):
    """A registry rebuild re-parses the model; doing it on every work creation
    would be a cost paid for nothing."""
    from cwva_dashboard.promotion.qa_git import QAGit

    c, qa_root = client
    # Commit the fixture's own profiles first: a promotion carries the WHOLE
    # staged tree, so without this the manifest would contain them and the
    # reload would be correct rather than spurious.
    qa = QAGit(root=qa_root)
    qa.stage_all()
    qa.commit("fixture baseline")
    (qa_root / Layout.default().dir("work_ttl") / "plain.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        'work:plain a vad:Watercolor ; rdfs:label "Just a painting" .\n'
    )
    calls = []
    real = c.app.state.dash.reload
    c.app.state.dash.reload = lambda: (calls.append(1), real())[1]
    try:
        _approve_everything(c)
    finally:
        c.app.state.dash.reload = real

    assert calls == [], "no bootstrap record was touched"
