"""The bootstrap: an artist, a profile, and the card that appears because of them.

Every other entry form is generated from a profile's `ops:template`, which
cannot help a deployment whose first act is creating the profile. So two forms
are hand-written, and only two.

The profile form is the form builder Rick asked for (`dashboardEntryFormApproach.txt`):
"a simple form builder with a list of the properties available to select from to
populate the template and a means of ordering". A tick and a number per property
— exactly the shape of `ops:field [ops:property … ; ops:order …]`.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.profiles import read_profile, shapes_graph
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

VAD = Namespace("http://visualartsdna.org/model/")
OPS = Namespace("http://visualartsdna.org/operations/")
SCHEMA = Namespace("https://schema.org/")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")

MODEL = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
vad:VisualArtist a owl:Class .
vad:Painter a owl:Class ; rdfs:subClassOf vad:VisualArtist .
vad:DigitalArtist a owl:Class ; rdfs:subClassOf vad:VisualArtist .
vad:VisualArtForm a owl:Class .
vad:PaintingForm a owl:Class ; rdfs:subClassOf vad:VisualArtForm .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .

# The form takes its wording from the model, including where the model is
# talking about something else — see the tests below. The builder's list is
# built from these labels and comments, so the fixture carries the ones the
# real store has.
schema:description  rdfs:label "description"    ; rdfs:comment "A description of a work." .
rdfs:label          rdfs:label "label"          ; rdfs:comment "A version of the resource\'s name." .
schema:dateCreated  rdfs:label "created date"   ; rdfs:comment "The date the work was completed." .
schema:datePublished rdfs:label "published date"; rdfs:comment "The date the work was published." .
schema:image        rdfs:label "image"          ; rdfs:comment "An image URL." .
schema:height       rdfs:label "height"         ; rdfs:comment "The height of the work." .
vad:image3d         rdfs:label "3D image"       ; rdfs:comment "A URI reference to a GLB file." .
# note carries a label and NO comment, which is the "model says nothing" case.
skos:note           rdfs:label "note" .
"""


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    lay = Layout.default()
    (qa_root / lay.dir("work_ttl")).mkdir(parents=True)
    model = qa_root / lay.dir("model_ttl")
    model.mkdir(parents=True)
    (model / "tiny.ttl").write_text(MODEL)
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=lay,
            image_base=image_base(TEST_DOMAIN)),
    )
    with TestClient(app) as c:
        yield c, qa_root, app


def _guid(page: str) -> str:
    return re.search(r'name="guid" value="([^"]+)"', page).group(1)


def _graph(qa_root, guid) -> Graph:
    path = qa_root / Layout.default().dir("work_ttl") / f"{guid}.ttl"
    return Graph().parse(data=path.read_text(), format="turtle")


def _make_artist(c, name="Rick Spates", brand="visualartsdna.org", type_="Painter"):
    page = c.get("/rdf/artist").text
    guid = _guid(page)
    data = {"guid": guid, "type": type_, "name": name,
            "email": "visualartsdna@gmail.com", "homepage": "https://visualartsdna.org"}
    if brand:
        data["brand"] = brand
    r = c.post("/rdf/artist", data=data)
    return guid, r


# ---------------------------------------------------------------------------
# The artist.
# ---------------------------------------------------------------------------

def test_both_bootstrap_cards_are_on_the_hub(client):
    c, _qa, _app = client
    hub = c.get("/").text

    assert 'href="rdf/artist"' in hub and "New artist" in hub
    assert 'href="rdf/artist-profile"' in hub


def test_the_artist_class_comes_from_the_ONTOLOGY(client):
    c, _qa, _app = client

    page = c.get("/rdf/artist").text
    sel = re.search(r'<select id="type" name="type".*?</select>', page, re.S).group(0)

    # The root is offered too: an artist who is neither a painter nor a digital
    # artist is still an artist, and the works forms treat their own root the
    # same way (`allow_abstract_root`).
    assert set(re.findall(r'value="([^"]*)"', sel)) == {
        "Painter", "DigitalArtist", "VisualArtist"}


def test_creating_an_artist_writes_the_record(client):
    c, qa_root, _app = client

    guid, r = _make_artist(c)

    assert r.status_code == 200, r.text[:300]
    g = _graph(qa_root, guid)
    subj = URIRef(f"{TEST_DOMAIN}/work/{guid}")
    assert (subj, RDF.type, VAD.Painter) in g
    # both names, from one field: rdfs:label is what every picker reads,
    # foaf:name is what the vocabulary means by a person's name
    assert str(g.value(subj, RDFS.label)) == "Rick Spates"
    assert str(g.value(subj, FOAF.name)) == "Rick Spates"
    assert str(g.value(subj, VAD.brand)) == "visualartsdna.org"
    assert str(g.value(subj, FOAF.mbox)) == "mailto:visualartsdna@gmail.com"


def test_an_artist_may_decline_to_BRAND(client):
    """Absence is a decision (CE_DESIGN §14.5): no vad:brand, no stamp on their
    published images — and nothing in the record pretending otherwise."""
    c, qa_root, _app = client

    guid, _r = _make_artist(c, name="No Brand", brand="")

    assert (None, VAD.brand, None) not in _graph(qa_root, guid)


def test_a_brand_given_as_a_URL_is_stored_as_the_DOMAIN(client):
    """It is the string drawn on the image, not a link."""
    c, qa_root, _app = client

    guid, _r = _make_artist(c, brand="https://visualartsdna.org/")

    assert str(_graph(qa_root, guid).value(
        URIRef(f"{TEST_DOMAIN}/work/{guid}"), VAD.brand)) == "visualartsdna.org"


# ---------------------------------------------------------------------------
# The profile, and the form builder.
# ---------------------------------------------------------------------------

def test_a_profile_needs_an_ARTIST_FIRST_and_says_so(client):
    """An empty picker looks like a bug; the remedy is one click."""
    c, _qa, _app = client

    r = c.get("/rdf/artist-profile")

    assert r.status_code == 409
    assert "Create an artist" in r.text


def test_the_property_picker_offers_the_PROPERTY_MAP(client):
    """Derived, not listed: a property added to the map becomes available to
    every new profile with no change to this form."""
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text

    assert 'class="tf-pick"' in page
    assert "https://schema.org/height" in page
    # housekeeping is not offered: it is written whatever the template says
    assert 'value="https://schema.org/identifier"' not in page
    assert 'value="http://visualartsdna.org/model/qrcode"' not in page


def test_creating_a_profile_writes_a_TEMPLATE_the_reader_accepts(client):
    """The whole loop in one assertion: the form builder's output is a profile
    that `read_profile` will hand back as a Template."""
    c, qa_root, _app = client
    artist_guid, _ = _make_artist(c)
    artist_uri = f"{TEST_DOMAIN}/work/{artist_guid}"

    page = c.get("/rdf/artist-profile").text
    guid = _guid(page)
    r = c.post("/rdf/artist-profile", data={
        "guid": guid, "label": "Watercolor materials profile",
        "artist": artist_uri, "template_type": "Watercolor", "unit_code": "INH",
        "description": "watercolours on paper",
        "fields": ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type:10,"
                   "http://www.w3.org/2000/01/rdf-schema#label:20,"
                   "https://schema.org/image:30,"
                   "https://schema.org/height:40,"
                   "https://schema.org/width:50"),
    })

    assert r.status_code == 200, r.text[:300]
    g = _graph(qa_root, guid)
    profile = read_profile(g, f"{TEST_DOMAIN}/work/{guid}", shapes=shapes_graph())
    assert profile.label == "Watercolor materials profile"
    assert profile.units == ("INH", "inches")
    assert profile.brand == "", "the artist is in another file; the reader joins them"
    assert [f.order for f in profile.template.ordered()] == [10, 20, 30, 40, 50]


def test_the_order_boxes_become_ops_order(client):
    c, qa_root, _app = client
    artist_guid, _ = _make_artist(c)
    page = c.get("/rdf/artist-profile").text
    guid = _guid(page)

    c.post("/rdf/artist-profile", data={
        "guid": guid, "label": "P", "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "description": "what it covers", "template_type": "Watercolor", "unit_code": "CTM",
        "fields": ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type:2,"
                   "http://www.w3.org/2000/01/rdf-schema#label:1"),
    })

    g = _graph(qa_root, guid)
    tpl = g.value(URIRef(f"{TEST_DOMAIN}/work/{guid}"), OPS.template)
    got = {str(g.value(f, OPS.property)): int(g.value(f, OPS.order))
           for f in g.objects(tpl, OPS.field)}
    assert got["http://www.w3.org/2000/01/rdf-schema#label"] == 1
    assert got["http://www.w3.org/1999/02/22-rdf-syntax-ns#type"] == 2
    # required, explicitly, while "all required for now" stands
    assert all(bool(g.value(f, OPS.required)) for f in g.objects(tpl, OPS.field))


def test_two_fields_at_one_POSITION_are_refused(client):
    """The same rule the reader enforces, enforced where the mistake is made —
    a form that would show them in an arbitrary sequence."""
    c, _qa, _app = client
    artist_guid, _ = _make_artist(c)
    page = c.get("/rdf/artist-profile").text

    r = c.post("/rdf/artist-profile", data={
        "guid": _guid(page), "label": "P",
        "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "description": "what it covers", "template_type": "Watercolor", "unit_code": "INH",
        # both mandatory properties present, so the ORDER clash is what is
        # being tested rather than a missing must-have
        "fields": ("http://www.w3.org/2000/01/rdf-schema#label:1,"
                   "http://www.w3.org/1999/02/22-rdf-syntax-ns#type:1"),
    })

    assert r.status_code == 400
    assert "share the order" in r.text


def test_a_template_with_no_fields_is_refused(client):
    c, _qa, _app = client
    artist_guid, _ = _make_artist(c)
    page = c.get("/rdf/artist-profile").text

    r = c.post("/rdf/artist-profile", data={
        "guid": _guid(page), "label": "P",
        "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "description": "what it covers", "template_type": "Watercolor", "unit_code": "INH", "fields": "",
    })

    assert r.status_code == 400


def test_an_artist_who_is_not_in_the_store_is_refused(client):
    """The picker's set is the schema's enum, so a crafted POST meets the same
    closed set the form offered."""
    c, _qa, _app = client
    _make_artist(c)
    page = c.get("/rdf/artist-profile").text

    r = c.post("/rdf/artist-profile", data={
        "guid": _guid(page), "label": "P",
        "artist": f"{TEST_DOMAIN}/work/somebody-else",
        "description": "what it covers", "template_type": "Watercolor", "unit_code": "INH",
        "fields": "http://www.w3.org/2000/01/rdf-schema#label:1",
    })

    assert r.status_code == 400


def test_THE_WHOLE_BOOTSTRAP_from_an_empty_store(client):
    """Nothing to something: no artist, no profile, no card — then an artist, a
    profile, its card, its form, and a record with the artist's brand on the
    image. This is what a new user's first hour is, and it is the release
    blocker closing."""
    c, qa_root, app = client

    # nothing yet: the hand-written forms stand in, so the Content tab is not
    # empty on day one
    hub = c.get("/").text
    assert "RDF Entry" in hub and "New artist" in hub

    artist_guid, _ = _make_artist(c, name="A Painter", brand="apainter.art")
    assert [a["label"] for a in app.state.artists] == ["A Painter"], (
        "known immediately — not after a refresh"
    )

    page = c.get("/rdf/artist-profile").text
    profile_guid = _guid(page)
    c.post("/rdf/artist-profile", data={
        "guid": profile_guid, "label": "Marsh watercolours",
        "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "description": "what it covers", "template_type": "Watercolor", "unit_code": "INH",
        "fields": ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type:10,"
                   "http://www.w3.org/2000/01/rdf-schema#label:20,"
                   "https://schema.org/height:40,https://schema.org/width:50"),
    })

    hub = c.get("/").text
    assert "Marsh watercolours" in hub
    assert "RDF Entry" not in hub, "the fallback steps aside once a profile exists"

    form = c.get(f"/rdf/profile/{profile_guid}")
    assert form.status_code == 200, "the new card leads somewhere"
    assert [f for f in re.findall(r'<label for="([^"]+)"', form.text)] == [
        "type", "label", "height", "width"]

    work_guid = _guid(form.text)
    r = c.post(f"/rdf/profile/{profile_guid}", data={
        "guid": work_guid, "type": "Watercolor", "label": "Marsh at Dawn",
        "height": "9", "width": "12"})

    assert r.status_code == 200
    g = _graph(qa_root, work_guid)
    subj = URIRef(f"{TEST_DOMAIN}/work/{work_guid}")
    assert (subj, RDF.type, VAD.Watercolor) in g
    assert (subj, VAD.hasArtistProfile,
            URIRef(f"{TEST_DOMAIN}/work/{profile_guid}")) in g
    assert "9.0 inches" in {str(o) for o in g.objects(None, RDFS.label)}


def test_an_EDITED_template_is_not_served_from_the_old_shape(client):
    """The spec is cached per profile; re-reading them drops the cache. A form
    that kept serving the shape a template used to have would be the staleness
    the lazy lookup exists to avoid."""
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    page = c.get("/rdf/artist-profile").text
    profile_guid = _guid(page)
    c.post("/rdf/artist-profile", data={
        "guid": profile_guid, "label": "First", "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "description": "what it covers", "template_type": "Watercolor", "unit_code": "INH",
        "fields": ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type:10,"
                   "http://www.w3.org/2000/01/rdf-schema#label:20"),
    })
    assert "location" not in c.get(f"/rdf/profile/{profile_guid}").text

    # the template gains a field, the way an edit would
    path = qa_root / Layout.default().dir("work_ttl") / f"{profile_guid}.ttl"
    path.write_text(path.read_text().replace(
        "ops:template [",
        "ops:template [ ops:field [ ops:property schema:location ; "
        "ops:order 30 ; ops:required true ] ;", 1))
    from cwva_dashboard.profiles import load_artists_from_dir, load_from_dir
    app.state.profiles, app.state.profiles_broken = load_from_dir(
        qa_root / Layout.default().dir("work_ttl"))
    c.post("/rdf/artist", data={"guid": "reload-trigger", "type": "Painter",
                                "name": "Another"})  # any bootstrap write reloads

    assert "location" in c.get(f"/rdf/profile/{profile_guid}").text


# ---------------------------------------------------------------------------
# What the two forms SAY (Rick, 2026-09-17).
# ---------------------------------------------------------------------------

def test_an_artist_picker_shows_NAMES_not_URIs(client):
    """The enum is what `validate_args` enforces; the labels are how a person
    reads it. Rendering the enum showed the enforced set instead of the offered
    one — the same set, said unhelpfully."""
    c, _qa, _app = client
    _make_artist(c, name="Rick Spates")

    for path, field in (("/rdf/artist", "pseudonym_for"),
                        ("/rdf/artist-profile", "artist")):
        page = c.get(path).text
        sel = re.search(rf'<select id="{field}".*?</select>', page, re.S).group(0)
        assert ">Rick Spates<" in sel, f"{field} still shows URIs"
        assert f"{TEST_DOMAIN}/work/" in sel, "and still submits the URI"


def test_the_builder_says_what_its_NUMBERS_are(client):
    """A column of unexplained numbers is a column of unexplained numbers
    (Rick: "are the number fields the order? Shows values from 10-160?"). The
    caption carries it now — a header row inside the grid rendered as
    "propertyorder" and was removed."""
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text

    caption = re.search(r'<label for="fields">([^<]*)', page).group(1)
    assert "property and order" in caption
    assert "tf-order-h" not in page, "no header row"
    hint = re.search(r'<label for="fields">.*?<div class="hint">([^<]*)</div>',
                     page, re.S).group(1)
    assert "lowest first" in hint
    assert "ten apart" in hint, "and why they are not 1, 2, 3"


def test_the_wording_still_comes_from_the_ONTOLOGY(client):
    """Including where it reads oddly. `schema:description` says "A description
    of a work", which is the wrong subject on a profile form — and the fix is in
    the model, not an override here, because the same comment serves the work
    forms where it is exactly right."""
    c, _qa, _app = client
    _make_artist(c)

    assert "A description of a work." in c.get("/rdf/artist-profile").text
    assert "A description of a work." in c.get("/rdf/entry").text


def test_a_homepage_typed_without_a_SCHEME_is_still_an_absolute_IRI(client):
    """`bj.net` is a relative IRI, and a relative IRI in a published record
    resolves against whatever base the reader uses. This one parsed for the
    gates and threw for the preview, so saving an artist made every promotion
    fail afterwards (Rick, 2026-09-17). People type their own site without the
    scheme, so the scheme is supplied rather than demanded."""
    c, qa_root, _app = client
    page = c.get("/rdf/artist").text
    guid = _guid(page)

    r = c.post("/rdf/artist", data={"guid": guid, "type": "Painter",
                                    "name": "Benny the Jet", "homepage": "bj.net"})

    assert r.status_code == 200, r.text[:300]
    home = _graph(qa_root, guid).value(URIRef(f"{TEST_DOMAIN}/work/{guid}"), FOAF.homepage)
    assert str(home) == "https://bj.net"


def test_a_homepage_that_HAS_a_scheme_is_left_alone(client):
    c, qa_root, _app = client
    page = c.get("/rdf/artist").text
    guid = _guid(page)

    c.post("/rdf/artist", data={"guid": guid, "type": "Painter", "name": "R",
                                "homepage": "http://example.org/studio"})

    assert str(_graph(qa_root, guid).value(
        URIRef(f"{TEST_DOMAIN}/work/{guid}"), FOAF.homepage)) == "http://example.org/studio"


# ---------------------------------------------------------------------------
# The builder's list: what it offers, in what order, and what it will not let
# you drop (Rick, 2026-09-17).
# ---------------------------------------------------------------------------

BROWSER_MINIMUM = [
    "http://www.w3.org/2000/01/rdf-schema#label",
    "https://schema.org/description",
    "https://schema.org/dateCreated",
    "https://schema.org/datePublished",
    "https://schema.org/image",
    "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
]


def test_the_browsers_MINIMUM_is_ticked_and_cannot_be_UNTICKED(client):
    """"These are the minimum properties necessary for the record to be
    correctly displayed in the cwva-py/works browser… that checkbox should be
    readonly." A profile may reorder them and may add to them; it may not make a
    record the browser cannot show."""
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text

    for predicate in BROWSER_MINIMUM:
        row = re.search(rf'<label class="tfield[^"]*">\s*<input type="checkbox" '
                        rf'class="tf-pick" value="{re.escape(predicate)}"[^>]*>', page)
        assert row, predicate
        assert "checked" in row.group(0), f"{predicate} not ticked"
        assert "disabled" in row.group(0), f"{predicate} can be unticked"


def test_everything_else_is_OPTIONAL(client):
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text
    row = re.search(r'<input type="checkbox" class="tf-pick" '
                    r'value="https://schema\.org/height"[^>]*>', page).group(0)

    assert "checked" not in row and "disabled" not in row


def test_the_minimum_comes_FIRST_and_the_rest_alphabetically(client):
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text
    orders = [int(v) for v in re.findall(r'class="tf-order" value="(\d+)"', page)]
    names = re.findall(r'<span class="tf-name">([^,<]+)', page)

    assert orders[:6] == [10, 20, 30, 40, 50, 60]
    assert names[:6] == ["label", "description", "created date", "published date",
                         "image", "type"], (
        "the model's own labels — it calls schema:dateCreated 'created date' "
        "where Rick's note said 'completed date', and the model is the source"
    )
    assert orders[6] == 70, "the rest follow the mandatory block"
    rest = names[6:]
    assert rest == sorted(rest, key=str.lower), "and run alphabetically"


def test_a_property_is_DESCRIBED_not_named_in_RDF(client):
    """"I'm debating whether to include the property CURIs. They may just be
    confusing. The user typically is not RDF literate." The label and definition
    come from the model, which says more and says it in words."""
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text

    assert "label, a version of the resource&#x27;s name" in page or \
           "label, a version of the resource's name" in page
    assert "image, an image URL" in page
    assert "schema:image" not in page, "no CURIEs in the list"


def test_a_property_the_model_says_nothing_about_still_reads(client):
    """`skos:note` has no comment in the model, and `image3d` no underscore-free
    name of its own. Neither may render as a blank row or a field name with an
    underbar in it."""
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text

    shown = re.findall(r'<span class="tf-name">([^<]*)</span>', page)

    assert "note" in shown, "a property with no comment shows its label alone"
    assert not any("_" in s for s in shown), f"an underbar reached the form: {shown}"
    assert any(s.startswith("3D image") for s in shown), (
        "the model's label, not the argument name `image3d`"
    )


def test_an_ACRONYM_keeps_its_capitals(client):
    """The definition is lower-cased to read as a clause after the comma — but a
    word carrying a capital anywhere but the front is a name or an initialism,
    and neither is ours to recase. "URI reference…" must not become "uRI
    reference…" (Rick, 2026-09-17)."""
    from rdflib import Graph
    from cwva_dashboard.tools.bootstrap_tools import offerable_properties

    model = Graph().parse(data="""
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix schema: <https://schema.org/> .
vad:image3d   rdfs:label "3D image" ; rdfs:comment "URI reference to a GLB file." .
schema:height rdfs:label "height"   ; rdfs:comment "The height of the work." .
""", format="turtle")

    shown = {r["name"]: r["label"] for r in offerable_properties(model)}

    assert shown["3D image"] == "3D image, URI reference to a GLB file"
    assert shown["height"] == "height, the height of the work", "ordinary words still open lower-case"


def test_the_builder_does_NOT_claim_ctrl_click_works(client):
    """It is a grid of checkboxes, not a <select multiple>. Rick tried it and
    got one row — the instruction was not merely unnecessary but false."""
    c, _qa, _app = client
    _make_artist(c)

    page = c.get("/rdf/artist-profile").text
    hint = re.search(r'<label for="fields">.*?<div class="hint">([^<]*)</div>',
                     page, re.S).group(1)

    assert "ctrl-click" not in hint


def test_a_profile_must_SAY_WHAT_IT_COVERS(client):
    """A card whose only words are its own label tells the next person nothing
    about which kind of work belongs in it."""
    c, _qa, _app = client
    artist_guid, _ = _make_artist(c)
    page = c.get("/rdf/artist-profile").text

    r = c.post("/rdf/artist-profile", data={
        "guid": _guid(page), "label": "P",
        "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "template_type": "Watercolor", "unit_code": "INH",
        "fields": "http://www.w3.org/2000/01/rdf-schema#label:1",
    })

    assert r.status_code == 400
    assert "description" in r.text


def test_the_builders_rows_are_NOT_lower_cased_by_the_stylesheet(client):
    """A field's caption is house style — lower-cased on purpose. The builder's
    rows are <label> elements too, but what they carry is the MODEL's words, and
    the house style turned an initialism into a word and a dimension into a
    letter: "3d image, a uri reference to a glb file" (Rick, 2026-09-17).

    Asserted against the stylesheet because CSS is where the damage was done —
    the HTML had "3D image" and "GLB" in it all along, which is exactly why
    reading the markup could not find this.
    """
    c, _qa, _app = client
    _make_artist(c)
    page = c.get("/rdf/artist-profile").text

    assert ".tfield, .tfield .tf-name{text-transform:none" in page, (
        "the builder's rows must opt out of the lower-casing"
    )
    # and the markup carries the model's casing, as it did before
    assert "3D image" in page


def test_a_template_with_no_TYPE_is_refused_even_by_a_crafted_post(client):
    """The ticks are locked, so the form cannot produce this — but a POST can,
    and a profile that reads fine and then fails every record it drives is the
    worst of the three places this could break. `graph_from_template` catches it
    at record time, which is as far as possible from the mistake."""
    c, _qa, _app = client
    artist_guid, _ = _make_artist(c)
    page = c.get("/rdf/artist-profile").text

    r = c.post("/rdf/artist-profile", data={
        "guid": _guid(page), "label": "P", "description": "d",
        "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "template_type": "Watercolor", "unit_code": "INH",
        "fields": "http://www.w3.org/2000/01/rdf-schema#label:10",
    })

    assert r.status_code == 400
    assert "must include type" in r.text


# -- Edit artist (Rick, 2026-09-19) -------------------------------------------
# The artist record, not the works. Its counterpart on the profile is a harder
# question and is settled the other way: the artist there is read-only, because
# changing it re-attributes every work ever made under that profile
# (CE_DESIGN §14.10).


def _artist_with_extras(qa_root, guid="art-1"):
    """An artist as the STORE really holds one: `schema:creator` and
    `schema:identifier` that the form never asks about, and a second type."""
    path = qa_root / Layout.default().dir("work_ttl") / f"{guid}.ttl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix foaf: <http://xmlns.com/foaf/0.1/> .\n"
        "@prefix schema: <https://schema.org/> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        f'work:{guid} a vad:Painter, schema:Person ;\n'
        '    rdfs:label "Rick Spates" ; foaf:name "Rick Spates" ;\n'
        '    foaf:mbox <mailto:old@example.com> ;\n'
        '    vad:brand "visualartsdna.org" ;\n'
        '    schema:creator "the groovy server" ;\n'
        f'    schema:identifier "{guid}" .\n'
    )
    return path


def test_the_form_OPENS_ON_the_record(client):
    c, qa_root, app = client
    _artist_with_extras(qa_root)

    html = c.get("/rdf/artist/edit?guid=art-1").text

    assert "Rick Spates" in html
    assert 'value="old@example.com"' in html, "shown as typed, not as mailto:"
    assert 'value="visualartsdna.org"' in html
    assert 'id="recordPick"' in html, "and the chooser rides above it"


def test_saving_PRESERVES_what_the_form_does_not_own(client):
    """The personas in Rick's store carry `schema:creator` and
    `schema:identifier`. An editor that rebuilt the record from its own fields
    would delete them — the same silent loss the profile editor has to avoid
    with `ops:dependsOn`."""
    c, qa_root, app = client
    path = _artist_with_extras(qa_root)

    c.post("/rdf/artist/edit", data={
        "guid": "art-1", "type": "Painter",
        "email": "new@example.com", "brand": "art.visualartsdna.org",
    })

    g = Graph().parse(data=path.read_text(), format="turtle")
    subj = URIRef(f"{TEST_DOMAIN}/work/art-1")
    assert (subj, URIRef("https://schema.org/creator"),
            Literal("the groovy server")) in g
    assert (subj, URIRef("https://schema.org/identifier"), Literal("art-1")) in g
    assert URIRef("https://schema.org/Person") in set(g.objects(subj, RDF.type)), (
        "a type the form does not offer is not a type the form may remove"
    )
    assert str(g.value(subj, VAD.brand)) == "art.visualartsdna.org"
    assert str(g.value(subj, FOAF.mbox)) == "mailto:new@example.com"


def test_an_EMPTIED_field_is_removed(client):
    """Absence is a decision: an artist who declares no brand gets no stamp."""
    c, qa_root, app = client
    path = _artist_with_extras(qa_root)

    c.post("/rdf/artist/edit", data={
        "guid": "art-1", "type": "Painter", "brand": "",
    })

    g = Graph().parse(data=path.read_text(), format="turtle")
    assert g.value(URIRef(f"{TEST_DOMAIN}/work/art-1"), VAD.brand) is None


def test_editing_something_that_is_NOT_AN_ARTIST_is_refused(client):
    c, qa_root, app = client
    _artist_with_extras(qa_root)  # so the page is not the "no artists yet" one
    path = qa_root / Layout.default().dir("work_ttl") / "w9.ttl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        'work:w9 a vad:Watercolor ; rdfs:label "A painting" .\n'
    )

    r = c.get("/rdf/artist/edit?guid=w9")

    assert r.status_code == 404
    assert "not an artist record" in r.text


def test_the_edit_form_ENDS_AT_THE_REVIEW_like_every_writer(client):
    c, qa_root, app = client
    _artist_with_extras(qa_root)

    r = c.post("/rdf/artist/edit", data={"guid": "art-1", "type": "Painter"})

    assert "Distribute Data — review" in r.text


def test_the_hub_offers_it(client):
    c, _qa, _app = client

    assert 'href="rdf/artist/edit"' in c.get("/").text


def test_a_THESAURUS_CONCEPT_is_not_offered_as_an_artist(client):
    """"John Singer Sargent Watercolors" and "Winslow Homer" are `skos:Concept`s
    in a scheme that also carry `vad:Artist`, and both appeared in the artist
    pickers as if they were personas of this deployment (CE_DESIGN §14.10).
    They are subjects a work is ABOUT, not people it belongs to."""
    c, qa_root, app = client
    _artist_with_extras(qa_root)
    (qa_root / Layout.default().dir("work_ttl") / "concept.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix the: <http://visualartsdna.org/thesaurus/> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        'the:winslowHomer a skos:Concept, vad:Artist ; rdfs:label "Winslow Homer" ;\n'
        "    skos:inScheme the:ArtistScheme .\n"
    )

    html = c.get("/rdf/artist/edit").text

    assert "Rick Spates" in html
    assert "Winslow Homer" not in html


def test_the_NAME_cannot_be_changed_by_the_capability(client):
    """Rick, 2026-09-19: read-only "for the same reason the link from artist
    profile to artist cannot be changed". In the SCHEMA, not merely on the form:
    a field the page renders read-only can still be posted by a stale tab, and
    the tool is where a constraint lives."""
    c, qa_root, app = client
    _artist_with_extras(qa_root)

    r = c.post("/rdf/artist/edit", data={
        "guid": "art-1", "type": "Painter", "name": "Someone Else"})

    assert r.status_code == 400
    path = qa_root / Layout.default().dir("work_ttl") / "art-1.ttl"
    assert "Rick Spates" in path.read_text()


def test_the_name_is_SHOWN_with_the_reason_it_is_fixed(client):
    """A field that vanishes reads as a field the system forgot."""
    c, qa_root, app = client
    _artist_with_extras(qa_root)

    html = c.get("/rdf/artist/edit?guid=art-1").text

    assert "Read-only. The name identifies the persona" in html
    assert 'name="name"' not in html, "no input to post"
    assert "discard the draft" in html, "and what to do about a typo"


def test_an_ordinary_edit_LEAVES_THE_NAME_ALONE(client):
    c, qa_root, app = client
    path = _artist_with_extras(qa_root)

    c.post("/rdf/artist/edit", data={"guid": "art-1", "type": "DigitalArtist"})

    g = Graph().parse(data=path.read_text(), format="turtle")
    subj = URIRef(f"{TEST_DOMAIN}/work/art-1")
    assert str(g.value(subj, RDFS.label)) == "Rick Spates"
    assert str(g.value(subj, FOAF.name)) == "Rick Spates"
    assert VAD.DigitalArtist in set(g.objects(subj, RDF.type))
    assert VAD.Painter not in set(g.objects(subj, RDF.type))


# -- Edit artist profile (Rick, 2026-09-19) -----------------------------------
# The template is EDITED, not regenerated: `ops:dependsOn` is a statement the
# builder cannot express (§14.8b), and a rebuild from the grid would delete
# every one of them with no way to put them back.

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
IMAGE3D = "http://visualartsdna.org/model/image3d"
BACKGROUND = "http://visualartsdna.org/model/background"


def _profile_with_dependency(c, qa_root, artist_guid):
    """A profile as Rick's Blender one really is: a hand-authored mutual
    dependency between image3d and background, which no form can write."""
    page = c.get("/rdf/artist-profile").text
    guid = _guid(page)
    c.post("/rdf/artist-profile", data={
        "guid": guid, "label": "Blender application profile",
        "artist": f"{TEST_DOMAIN}/work/{artist_guid}",
        "description": "3D compositions", "template_type": "Watercolor",
        "unit_code": "INH",
        "fields": f"{RDF_TYPE}:10,{LABEL}:20,{IMAGE3D}:30,{BACKGROUND}:40",
    })
    path = qa_root / Layout.default().dir("work_ttl") / f"{guid}.ttl"
    # By hand, because the builder has no way to say it. Through rdflib rather
    # than by patching the text: the writer emits prefixed names, so a string
    # replace looking for a full IRI matches nothing and the test would pass for
    # having tested nothing.
    OPS = Namespace("http://visualartsdna.org/operations/")
    g = Graph().parse(data=path.read_text(), format="turtle")
    node = next(n for n in g.objects(None, OPS.field)
                if str(g.value(n, OPS.property)) == IMAGE3D)
    g.add((node, OPS.dependsOn, URIRef(BACKGROUND)))
    path.write_text(g.serialize(format="turtle"))
    return guid, path


def test_the_profile_form_OPENS_ON_the_profile(client):
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    guid, _path = _profile_with_dependency(c, qa_root, artist_guid)

    html = c.get(f"/rdf/artist-profile/edit?guid={guid}").text

    assert 'value="Blender application profile"' in html
    assert "3D compositions" in html
    assert 'id="recordPick"' in html
    # The grid opens on the template's own ticks and orders.
    assert re.search(rf'value="{re.escape(IMAGE3D)}"[^>]*checked', html)
    assert 'value="30"' in html


def test_the_ARTIST_is_shown_and_cannot_be_changed(client):
    """Changing it re-attributes every work ever made under the profile, and
    those works' images already carry the old artist's brand."""
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    guid, _path = _profile_with_dependency(c, qa_root, artist_guid)

    html = c.get(f"/rdf/artist-profile/edit?guid={guid}").text

    assert "Read-only. Every work ever made under this profile" in html
    assert 'name="artist"' not in html, "no input to post"


def test_a_posted_ARTIST_is_refused_by_the_capability(client):
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    guid, path = _profile_with_dependency(c, qa_root, artist_guid)

    r = c.post("/rdf/artist-profile/edit", data={
        "guid": guid, "label": "Blender application profile",
        "artist": f"{TEST_DOMAIN}/work/someone-else",
        "description": "3D compositions", "template_type": "Watercolor",
        "unit_code": "INH",
        "fields": f"{RDF_TYPE}:10,{LABEL}:20",
    })

    assert r.status_code == 400
    # Parsed, not grepped: the writer emits prefixed names, so a substring
    # search for a full IRI passes or fails for the wrong reason.
    g = Graph().parse(data=path.read_text(), format="turtle")
    assert set(g.objects(None, VAD.artist)) == {
        URIRef(f"{TEST_DOMAIN}/work/{artist_guid}")}


def test_editing_an_order_KEEPS_the_dependency(client):
    """The statement the builder cannot express survives the edit, because the
    existing field node is reused rather than rebuilt."""
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    guid, path = _profile_with_dependency(c, qa_root, artist_guid)

    c.post("/rdf/artist-profile/edit", data={
        "guid": guid, "label": "Blender application profile",
        "artist_unused": "", "description": "3D compositions",
        "template_type": "Watercolor", "unit_code": "INH",
        "fields": f"{RDF_TYPE}:10,{LABEL}:20,{IMAGE3D}:50,{BACKGROUND}:40",
    })

    g = Graph().parse(data=path.read_text(), format="turtle")
    OPS = Namespace("http://visualartsdna.org/operations/")
    deps = list(g.objects(None, OPS.dependsOn))
    assert deps == [URIRef(BACKGROUND)], "the hand-written dependency is still there"
    orders = {str(g.value(n, OPS.property)): int(g.value(n, OPS.order))
              for n in g.objects(None, OPS.field)}
    assert orders[IMAGE3D] == 50, "and the order it was edited to"


def test_removing_the_TARGET_of_a_dependency_is_refused(client):
    """`read_profile` refuses a profile whose dependency can never be satisfied,
    so writing one would kill the card. Refused here, where it can be
    explained."""
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    guid, path = _profile_with_dependency(c, qa_root, artist_guid)

    r = c.post("/rdf/artist-profile/edit", data={
        "guid": guid, "label": "Blender application profile",
        "description": "3D compositions", "template_type": "Watercolor",
        "unit_code": "INH",
        "fields": f"{RDF_TYPE}:10,{LABEL}:20,{IMAGE3D}:30",
    })

    assert r.status_code == 400
    assert "strand a dependency" in r.text
    g = Graph().parse(data=path.read_text(), format="turtle")
    OPS = Namespace("http://visualartsdna.org/operations/")
    props = {str(g.value(n, OPS.property)) for n in g.objects(None, OPS.field)}
    assert BACKGROUND in props, "and nothing was written"


def test_a_REMOVED_field_goes_and_a_NEW_one_arrives(client):
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    guid, path = _profile_with_dependency(c, qa_root, artist_guid)
    location = "https://schema.org/location"

    c.post("/rdf/artist-profile/edit", data={
        "guid": guid, "label": "Blender application profile",
        "description": "3D compositions", "template_type": "Watercolor",
        "unit_code": "INH",
        "fields": f"{RDF_TYPE}:10,{LABEL}:20,{location}:60",
    })

    g = Graph().parse(data=path.read_text(), format="turtle")
    OPS = Namespace("http://visualartsdna.org/operations/")
    props = {str(g.value(n, OPS.property)) for n in g.objects(None, OPS.field)}
    assert props == {RDF_TYPE, LABEL, location}
    assert not list(g.objects(None, OPS.dependsOn)), "its node went with it"


def test_the_edited_template_DRIVES_THE_FORM(client):
    """The registry is rebuilt from the profile, so the record form changes the
    same way it does when a template is created."""
    c, qa_root, app = client
    artist_guid, _ = _make_artist(c)
    guid, _path = _profile_with_dependency(c, qa_root, artist_guid)
    assert "location" not in c.get(f"/rdf/profile/{guid}").text

    c.post("/rdf/artist-profile/edit", data={
        "guid": guid, "label": "Blender application profile",
        "description": "3D compositions", "template_type": "Watercolor",
        "unit_code": "INH",
        "fields": f"{RDF_TYPE}:10,{LABEL}:20,https://schema.org/location:60",
    })

    assert "location" in c.get(f"/rdf/profile/{guid}").text


def test_the_hub_offers_the_profile_editor(client):
    c, _qa, _app = client

    assert 'href="rdf/artist-profile/edit"' in c.get("/").text
