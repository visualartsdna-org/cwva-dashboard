"""Edit Record wired from function.html.

File-based, not instance-based: a subject's triples are spread across files, so
"edit this instance" has no single target. What a user can coherently edit is
one file — and because the editor renders the WHOLE file, writing it back whole
cannot drop what it never showed. A form with a fixed field list would have to
merge, and on a real watercolour it owns a minority of the predicates.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF, RDFS

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import documents_base, image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

WORK = URIRef("http://visualartsdna.org/work/w1")

RECORD = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .

work:w1 a vad:Watercolor ;
    rdfs:label "Adelaide Sketch" ;
    schema:location "Woodstock, GA" ;
    schema:image <http://visualartsdna.org/images/a.jpg> ;
    schema:height [ a schema:QuantitativeValue ;
        rdfs:label "12 inches" ; schema:unitCode "INH" ; schema:value "12"^^xs:float ] ;
    the:document [ ] .
"""

# An ENTITY: single subject, no art-form type, `skos:inScheme the:entities`.
# Shaped after the Pillars background image in production — the record that had
# to be opened by hand-typed URL because the picker was works-only.
ENTITY = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:e1 a the:Image ;
    rdfs:label "Pillars" ;
    the:topic the:Background ;
    skos:definition "Inside a structure with classical columns" ;
    skos:inScheme the:entities ;
    the:tag work:e2 ;
    schema:image <http://visualartsdna.org/images/pillars_2k.hdr> .
"""

AGGREGATE = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix work: <http://visualartsdna.org/work/> .
work:a rdfs:label "One" .
work:b rdfs:label "Two" .
"""


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    model = qa_root / layout.dir("model_ttl")
    model.mkdir(parents=True)
    # What the record picker offers is the downward closure of `vad:ArtForm`,
    # so the fixture has to say which classes are art forms — with no model,
    # nothing is offered and every test here would fail for that reason.
    (model / "tiny.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "vad:ArtForm a owl:Class .\n"
        # The class carries a label, as the real ontology does — it is what the
        # type field shows instead of a CURIE.
        'vad:Watercolor a owl:Class ; rdfs:subClassOf vad:ArtForm ;\n'
        '    rdfs:label "Watercolor Painting" .\n'
        # An annotation property: an owl:ObjectProperty WITH a range, which is
        # what TCAP matches a concept's type against and what marks a field as
        # an annotation rather than an ordinary reference.
        "vad:WatercolorPaint a owl:Class .\n"
        "vad:hasWatercolorPaint a owl:ObjectProperty ;\n"
        "    rdfs:range vad:WatercolorPaint .\n"
    )
    data = qa_root / layout.dir("work_ttl")
    data.mkdir(parents=True)
    (data / "w1.ttl").write_text(RECORD)
    (data / "e1.ttl").write_text(ENTITY)
    (data / "workonsite_x.ttl").write_text(AGGREGATE)
    images = qa_root / layout.dir("image")
    images.mkdir(parents=True)
    (images / "a.jpg").write_bytes(b"\xff\xd8jpeg")
    (images / "pillars_2k.hdr").write_bytes(b"#?RADIANCE")
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=layout,
            image_base=image_base(TEST_DOMAIN),
            documents_base=documents_base(TEST_DOMAIN),
        ),
    )
    with TestClient(app) as c:
        yield c, qa


def _graph(qa):
    return Graph().parse(
        data=(qa.root / "content/ttl/data/w1.ttl").read_text(), format="turtle")


def _open(c, path="content/ttl/data/w1.ttl"):
    return c.get(f"/edit/open?path={path}").text


def _save(c, **edits):
    html = _open(c)
    values = dict(re.findall(r'<input type="[^"]*" id="([^"]+)" name="[^"]+" value="([^"]*)"', html))
    values.update(edits)
    values["path"] = "content/ttl/data/w1.ttl"
    return c.post("/edit/save", data=values)


def test_the_card_on_the_hub_resolves(client):
    c, _ = client
    assert 'href="edit"' in c.get("/").text
    assert c.get("/edit").status_code == 200


ENTITY_PATH = "content/ttl/data/e1.ttl"


# -- Works | Entities: two groups, named, never merged ------------------------


def test_the_default_group_is_works(client):
    c, _ = client
    picker = c.get("/edit").text

    assert "Adelaide Sketch" in picker
    assert "Pillars" not in picker


def test_the_entity_group_lists_entities(client):
    """The Pillars background image, which used to be reachable only by typing
    `/edit/open?path=…` (Rick, 2026-09-27)."""
    c, _ = client
    picker = c.get("/edit?kind=entity").text

    assert "Pillars" in picker
    assert "Adelaide Sketch" not in picker


def test_the_toggle_offers_exactly_what_the_TOOL_ENFORCES(client):
    """The offered set is the enforced set. The tabs' `kind` values must be the
    enum `validate_args` accepts, or a tab is a 422 with a friendly name."""
    c, _ = client
    offered = set(re.findall(r'href="/edit\?kind=([a-z]+)"', c.get("/edit").text))
    schemas = c.get("/api/tools").json()
    spec = next(t for t in schemas if t["name"] == "record.list_editable")
    enforced = set(spec["inputSchema"]["properties"]["kind"]["enum"])

    assert offered == enforced


def test_an_unknown_group_shows_works_rather_than_an_error(client):
    """A query string anyone can type. A mistyped `?kind=` should show a list,
    not a refusal."""
    c, _ = client
    r = c.get("/edit?kind=sculptures")

    assert r.status_code == 200
    assert "Adelaide Sketch" in r.text


def test_opening_an_entity_keeps_you_in_the_entity_group(client):
    """Open from the entities list and the list above the fields is still
    entities — otherwise choosing the next record snaps back to works."""
    c, _ = client
    html = c.get(f"/edit/open?path={ENTITY_PATH}&kind=entity").text

    assert 'name="kind" value="entity"' in html
    assert "Pillars" in html
    assert "Adelaide Sketch" not in html


def test_an_entity_renders_every_predicate_in_its_file(client):
    """The reason the editor needed no changing: it shows what is in the file,
    including the three fields no entry form owns."""
    c, _ = client
    html = c.get(f"/edit/open?path={ENTITY_PATH}&kind=entity").text

    for field in ("label", "topic", "definition", "inScheme", "image"):
        assert f">{field}</label>" in html, field


def test_an_entity_saves_through_the_ordinary_review_stop(client):
    c, qa = client
    html = c.get(f"/edit/open?path={ENTITY_PATH}&kind=entity").text
    values = dict(re.findall(
        r'<input type="[^"]*" id="([^"]+)" name="[^"]+" value="([^"]*)"', html))
    values["http://www.w3.org/2000/01/rdf-schema#label"] = "Pillars 4k"
    values["path"] = ENTITY_PATH
    values["kind"] = "entity"

    r = c.post("/edit/save", data=values)

    assert r.status_code == 200
    assert "Distribute Data — review" in r.text
    saved = Graph().parse(data=(qa.root / ENTITY_PATH).read_text(), format="turtle")
    subject = URIRef("http://visualartsdna.org/work/e1")
    assert saved.value(subject, RDFS.label) == Literal("Pillars 4k")
    # The group survives the save: the way back is into the list you came from.
    assert "kind=entity" in r.text


# -- a reference field takes a LIST (Rick, 2026-09-28) ------------------------


def _save_entity(c, **edits):
    html = c.get(f"/edit/open?path={ENTITY_PATH}&kind=entity").text
    values = dict(re.findall(
        r'<input type="[^"]*" id="([^"]+)" name="[^"]+" value="([^"]*)"', html))
    values.update(edits)
    values["path"] = ENTITY_PATH
    values["kind"] = "entity"
    return c.post("/edit/save", data=values)


TAG = "http://visualartsdna.org/thesaurus/tag"


def _tags(qa):
    g = Graph().parse(data=(qa.root / ENTITY_PATH).read_text(), format="turtle")
    return sorted(str(o) for o in
                  g.objects(URIRef("http://visualartsdna.org/work/e1"), URIRef(TAG)))


def test_a_list_of_CURIEs_becomes_several_references(client):
    """The Prestress Images collection: nine background CURIEs typed into
    `the:tag`, which went in as ONE IRI with eight commas and converged to the
    real SOT that way."""
    c, qa = client

    r = _save_entity(c, **{TAG: "work:e2,work:e3,work:e4"})

    assert r.status_code == 200
    assert _tags(qa) == ["http://visualartsdna.org/work/e2",
                         "http://visualartsdna.org/work/e3",
                         "http://visualartsdna.org/work/e4"]


def test_spaces_after_the_commas_do_not_raise(client):
    """This form of the list reached the user as a raw serializer exception."""
    c, qa = client

    r = _save_entity(c, **{TAG: "work:e2, work:e3"})

    assert r.status_code == 200
    assert len(_tags(qa)) == 2


def test_a_value_that_is_not_an_IRI_comes_back_as_a_FORM_ERROR(client):
    """Not a 500, and not a record written that cannot be re-serialized."""
    c, qa = client

    r = _save_entity(c, **{TAG: "work:e2 and work:e3"})

    assert r.status_code == 400
    assert "invalid_iri" in r.text
    assert _tags(qa) == ["http://visualartsdna.org/work/e2"]


# -- the drop folder can be re-read in place (Rick, 2026-09-27) --------------


def test_the_file_picker_carries_a_REFRESH_control(client):
    """The remedy for "nothing in your drop folder" is to put a file there, and
    without this the only way to see it was to reload the page and lose
    everything typed. The entry form got this control; the editor did not."""
    c, _ = client
    html = c.get(f"/edit/open?path={ENTITY_PATH}&kind=entity").text

    assert "Refresh list" in html
    assert "function refreshFileRef" in html


def test_the_refresh_puts_the_RECORDS_OWN_FILE_back(client):
    """A refresh that replaced the current value with an empty "- choose -"
    would make the next save clear the reference."""
    c, _ = client
    html = c.get(f"/edit/open?path={ENTITY_PATH}&kind=entity").text

    assert 'data-unchanged="pillars_2k.hdr"' in html
    assert "data-unchanged" in html[html.index("function refreshFileRef"):]


def test_only_single_subject_files_are_offered(client):
    """The aggregates and system output describe many records at once, so there
    is no single instance to edit. Derived from the file, not a maintained
    list."""
    c, _ = client
    picker = c.get("/edit").text

    assert "w1.ttl" in picker
    assert "workonsite_x.ttl" not in picker


def test_opening_an_aggregate_directly_is_refused(client):
    """Not merely absent from the picker — the capability itself refuses."""
    c, _ = client
    html = c.get("/edit/open?path=content/ttl/data/workonsite_x.ttl").text

    assert "2 subjects" in html


def test_every_predicate_in_the_file_is_rendered(client):
    """What makes overwriting safe. A fixed field list would drop what it did
    not know about."""
    c, _ = client
    html = _open(c)

    for field in ("label", "location", "image", "height", "type"):
        assert f">{field}</label>" in html, field


def test_a_saved_edit_lands_at_the_review_stop(client):
    c, qa = client
    r = _save(c, **{"http://www.w3.org/2000/01/rdf-schema#label": "Adelaide Sketch II"})

    assert r.status_code == 200
    assert "Distribute Data — review" in r.text
    assert _graph(qa).value(WORK, RDFS.label) == Literal("Adelaide Sketch II")
    assert not list((qa.root.parent / "sot").rglob("*.ttl")), "must not converge"


def test_a_comma_bearing_value_survives_a_save(client):
    """`"Woodstock, GA"` split into two literals on 194 of 326 real records
    before arity was taken from the data rather than from counting commas."""
    c, qa = client
    _save(c)

    assert list(_graph(qa).objects(WORK, URIRef("https://schema.org/location"))) == [
        Literal("Woodstock, GA")
    ]


def test_a_dimension_is_edited_through_its_label(client):
    c, qa = client
    _save(c, **{"https://schema.org/height": "15.5 inches"})

    g = _graph(qa)
    bn = g.value(WORK, URIRef("https://schema.org/height"))
    assert g.value(bn, RDFS.label) == Literal("15.5 inches")
    assert str(g.value(bn, URIRef("https://schema.org/value"))) == "15.5"


def test_clearing_a_field_is_reported_on_the_review(client):
    """Removing a statement is not the same as leaving a field blank by
    accident, and the review is the last place to notice."""
    c, _ = client
    r = _save(c, **{"https://schema.org/location": ""})

    assert "Cleared" in r.text and "location" in r.text


def test_sensitive_fields_carry_their_warning(client):
    c, _ = client
    html = _open(c)

    assert "does NOT delete the image" in html


def test_the_review_offers_a_way_back_to_the_record(client):
    c, _ = client
    r = _save(c, **{"http://www.w3.org/2000/01/rdf-schema#label": "Changed"})

    assert "Back to the record" in r.text
    assert "/edit/open?path=" in r.text


def test_an_empty_blank_node_is_dropped_on_save(client):
    c, qa = client
    _save(c)

    assert _graph(qa).value(
        WORK, URIRef("http://visualartsdna.org/thesaurus/document")) is None


# -- file fields: the drop folder, and only the drop folder -------------------


@pytest.fixture
def with_drop(tmp_path):
    """The record cites a.jpg; the drop folder holds a replacement and a file
    for another kind. The store also holds another record's image."""
    from cwva_dashboard.inbox import Inbox

    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    data = qa_root / layout.dir("work_ttl")
    data.mkdir(parents=True)
    # An existing mdDocument, so the markdown field has somewhere to appear: the
    # editor renders the predicates the file HAS. It cannot add one that is
    # absent — changing and clearing are its vocabulary, not creating.
    (data / "w1.ttl").write_text(
        RECORD.replace(
            "the:document [ ] .",
            "the:document [ ] ;\n    the:mdDocument "
            "<http://visualartsdna.org/documents/old.md> .",
        )
    )
    images = qa_root / layout.dir("image")
    images.mkdir(parents=True)
    for n in ("a.jpg", "belongs_to_w2.jpg"):
        (images / n).write_bytes(b"\xff\xd8" + n.encode())
    docs = qa_root / layout.dir("document")
    docs.mkdir(parents=True)
    (docs / "old.md").write_text("# old")   # or the asset gate flags it, rightly
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "IMG_1235.jpg").write_bytes(b"\xff\xd8new")
    (drop / "Notes For It.md").write_text("# notes")
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        inbox=Inbox(drop, extensions={"image": (".jpg",), "markdown": (".md",)}),
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=layout,
            image_base=image_base(TEST_DOMAIN),
            documents_base=documents_base(TEST_DOMAIN),
        ),
    )
    with TestClient(app) as c:
        yield c, qa, drop


def _image_options(html):
    m = re.search(r'<select id="https://schema.org/image".*?</select>', html, re.S)
    return re.findall(r'<option value="([^"]*)"', m.group(0)) if m else []


def test_a_file_field_offers_the_drop_folder_not_the_store(with_drop):
    """Everything in the store got there by being associated with a record.
    Offering it invites pointing two records at one file — which passes every
    gate, because the file genuinely exists."""
    c, _qa, _drop = with_drop
    opts = _image_options(_open(c))

    assert "IMG_1235.jpg" in opts, "the drop folder is offered"
    assert "belongs_to_w2.jpg" not in opts, "another record's image is not"


def test_the_current_value_stays_selectable(with_drop):
    """Otherwise opening a record and saving would silently change or clear its
    image."""
    c, _qa, _drop = with_drop
    html = _open(c)

    assert re.search(r'<option value="a\.jpg" selected>', html)


def test_choosing_a_drop_folder_file_INGESTS_it_on_save(with_drop):
    """The editor's one side effect beyond rewriting a TTL — and what turns
    "wrong image picked at entry" from a dead end into a fix.

    A ONE-FOR-ONE replacement on a work lands under the name it replaces
    (Rick, 2026-10-07), so the bytes change and nothing else does."""
    c, qa, _drop = with_drop
    before = (qa.root / "content/images/a.jpg").read_bytes()

    r = _save(c, **{"https://schema.org/image": "IMG_1235.jpg"})

    assert r.status_code == 200
    stored = qa.root / "content/images/a.jpg"
    assert stored.is_file() and stored.read_bytes() != before, "replaced in place"
    assert (qa.root / "content/images/a.jpg.ptr").is_file(), "with its sidecar"
    assert not (qa.root / "content/images/IMG_1235.jpg").exists(), (
        "the drop folder's name is not what it is stored under"
    )
    assert "Gates failed" not in r.text, "and the asset gate now resolves"
    assert "Copied in from the drop folder" in r.text, "and the review says so"


def test_a_one_for_one_replacement_does_NOT_change_the_RDF(with_drop):
    """"No RDF update, just the replacement file overwriting the binary."" The
    record goes on citing the same IRI, so nothing downstream has to notice
    that the picture changed — and no orphan is left behind, which repointing
    to a new name always produced."""
    c, qa, _drop = with_drop

    _save(c, **{"https://schema.org/image": "IMG_1235.jpg"})

    ttl = (qa.root / "content/ttl/data/w1.ttl").read_text()
    assert "images/a.jpg" in ttl
    assert "IMG_1235" not in ttl


def test_the_REPLACED_bytes_stay_recoverable(with_drop):
    """Overwriting through FileOps attics the previous binary — the rollback
    reserve (CE_DESIGN §3.4). Nothing hard-deletes what was published."""
    c, qa, _drop = with_drop

    _save(c, **{"https://schema.org/image": "IMG_1235.jpg"})

    assert list((qa.root / ".qa" / "attic").glob("*")), "the old image is kept"


def test_the_old_image_is_left_alone(with_drop):
    """Nothing vanishes. Since 2026-10-07 a one-for-one replacement lands on
    the same name rather than repointing to a new one, so there is no orphan
    to find either — the previous bytes are in the attic instead."""
    c, qa, _drop = with_drop
    _save(c, **{"https://schema.org/image": "IMG_1235.jpg"})

    assert (qa.root / "content/images/a.jpg").is_file()


def test_saving_without_touching_the_file_field_ingests_nothing(with_drop):
    """Opening and saving a record must not re-copy everything it mentions."""
    c, qa, _drop = with_drop
    _save(c)

    assert not (qa.root / "content/images/IMG_1235.jpg").exists()


def test_a_drop_name_is_shown_as_it_will_BE(with_drop):
    """`Notes For It.md` becomes `NotesForIt.md` on ingest, and that is what the
    record will cite — so that is what the picker shows, with the original in
    tow so the file is recognisable."""
    c, _qa, _drop = with_drop
    html = _open(c)

    assert "NotesForIt.md" in html
    assert "dropped as Notes For It.md" in html


def test_a_drop_file_that_NORMALISES_onto_another_record_is_refused(with_drop):
    """The edge case restricting the picker to the drop folder did NOT close.

    `Spirited Tree.jpg` in the drop folder becomes `SpiritedTree.jpg` — which
    may already be another record's image. `copy_into` overwrites when the bytes
    differ, so a save silently replaced a published work's picture and every gate
    passed, because the file genuinely existed. The collision check now runs in
    the editor as it does in the entry forms, and BEFORE the ingest.
    """
    c, qa, drop = with_drop
    images = qa.root / "content/images"
    (images / "SpiritedTree.jpg").write_bytes(b"\xff\xd8belongs-to-another")
    (qa.root / "content/ttl/data/w2.ttl").write_text(
        RECORD.replace("work:w1", "work:w2").replace(
            "images/a.jpg", "images/SpiritedTree.jpg")
    )
    (drop / "Spirited Tree.jpg").write_bytes(b"\xff\xd8different-bytes")

    r = _save(c, **{"https://schema.org/image": "SpiritedTree.jpg"})

    # It used to be a 409. Since a one-for-one replacement lands on the name it
    # REPLACES, an edit can no longer write to any name but its own — so the
    # hazard is gone rather than guarded, which is the better outcome of the
    # two (2026-10-07). The check itself still stands for the cases that are
    # not one-for-one: documents, entity images, multi-slot fields.
    assert r.status_code == 200, r.text[:300]
    assert (images / "SpiritedTree.jpg").read_bytes() == b"\xff\xd8belongs-to-another", (
        "the other record's file must be untouched"
    )
    assert (images / "a.jpg").read_bytes() == b"\xff\xd8different-bytes", (
        "the bytes landed on this record's own name"
    )
    assert "images/a.jpg" in (qa.root / "content/ttl/data/w1.ttl").read_text()


def test_a_record_may_re_save_its_OWN_file(with_drop):
    """Without excluding the subject under edit, a record's own image collides
    with itself and every save is refused."""
    c, _qa, _drop = with_drop

    assert _save(c, **{"https://schema.org/image": "a.jpg"}).status_code == 200


QR_RECORD = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:w3 a vad:Watercolor ;
    rdfs:label "Missing its QR" ;
    schema:identifier "w3" ;
    vad:qrcode <http://visualartsdna.org/images/qrc_w3.jpg> .
"""


def test_saving_GENERATES_A_MISSING_QR(client):
    """A record citing `vad:qrcode` whose JPEG was never generated fails the
    asset gate, and until now the only way out was to enter the work again —
    which Rick tried, and which collided with the filenames the first attempt
    already claimed (2026-09-17). The edit that rewrites the record makes the
    file it promises, as entry does on submit.
    """
    c, qa = client
    (qa.root / "content/ttl/data/w3.ttl").write_text(QR_RECORD)
    qr = qa.root / Layout.default().dir("image") / "qrc_w3.jpg"
    assert not qr.exists()

    path = "content/ttl/data/w3.ttl"
    html = _open(c, path)
    values = dict(re.findall(
        r'<input type="[^"]*" id="([^"]+)" name="[^"]+" value="([^"]*)"', html))
    values["path"] = path
    r = c.post("/edit/save", data=values)

    assert r.status_code == 200
    assert qr.exists() and qr.stat().st_size > 0


def test_saving_does_NOT_regenerate_a_QR_that_is_already_there(client):
    """`image.qrcode` leaves an existing file alone, so an edit cannot quietly
    replace the picture a printed card already points at."""
    c, qa = client
    (qa.root / "content/ttl/data/w3.ttl").write_text(QR_RECORD)
    qr = qa.root / Layout.default().dir("image") / "qrc_w3.jpg"
    qr.write_bytes(b"\xff\xd8already here")

    path = "content/ttl/data/w3.ttl"
    html = _open(c, path)
    values = dict(re.findall(
        r'<input type="[^"]*" id="([^"]+)" name="[^"]+" value="([^"]*)"', html))
    values["path"] = path
    c.post("/edit/save", data=values)

    assert qr.read_bytes() == b"\xff\xd8already here"


# -- The record picker (Rick, 2026-09-18) -------------------------------------
# One widget shared with Annotate Work, ordered by date with title a radio away,
# and it rides at the TOP OF THE FORM rather than on a page you leave behind.


def _picked(html):
    m = re.search(r'<option value="([^"]+)"[^>]*\sselected', html)
    return m.group(1) if m else ""


def test_the_picker_is_ON_the_edit_form_with_this_record_selected(client):
    c, _ = client

    html = _open(c)

    assert 'id="recordPick"' in html
    assert _picked(html) == "content/ttl/data/w1.ttl"
    # Above the fields, not below them: it is how you change your mind about
    # which record you are editing.
    assert html.index('id="recordPick"') < html.index('action="/edit/save"')


def test_the_FILTER_BOX_is_gone(client):
    """Filtering answered "where is the one I am thinking of". The answer is now
    "at the top", so the box is noise on both pages."""
    c, _ = client

    assert "recordFilter" not in _open(c)
    assert "recordFilter" not in c.get("/edit").text


def test_the_NEWEST_record_is_first_and_title_order_is_a_radio_away(client):
    """Ordered by `schema:datePublished` — a date the user gave and can see on
    the option — not by when the sandbox last wrote the file."""
    c, qa = client
    data = qa.root / Layout.default().dir("work_ttl")
    (data / "zz.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix schema: <https://schema.org/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        'work:z a <http://visualartsdna.org/model/Watercolor> ; rdfs:label "Zebra" ;\n'
        '    schema:datePublished "2026-09-17" .\n'
    )

    html = c.get("/edit").text
    order = re.findall(r'<option value="([^"]+)"', html)

    assert order[0] == "content/ttl/data/zz.ttl", "newest first, though Z sorts last"
    assert "2026-09-17" in html
    assert 'name="workOrder" value="d"' in html and 'name="workOrder" value="t"' in html


def test_only_ART_FORMS_are_offered(client):
    """An artist, an artist profile and an entity are all single-subject records
    and none of them is a work. Editing those needs forms that understand them —
    a design session, not a filter (Rick, 2026-09-18)."""
    c, qa = client
    data = qa.root / Layout.default().dir("work_ttl")
    (data / "artist.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        'work:a1 a vad:Painter ; rdfs:label "A Painter" .\n'
    )

    html = c.get("/edit").text

    assert "Adelaide Sketch" in html
    assert "A Painter" not in html


def test_choosing_from_it_OPENS_that_record(client):
    """The select is its own GET form, because the edit form below it is a POST
    and forms cannot nest."""
    c, _ = client

    html = c.get("/edit").text
    assert 'action="/edit/open"' in html and 'name="path"' in html

    r = c.get("/edit/open", params={"path": "content/ttl/data/w1.ttl"})
    assert r.status_code == 200 and "Adelaide Sketch" in r.text


# -- Unsaved edits are not thrown away silently (Rick, 2026-09-18) -------------
# "If I modify a value then choose a different work and hit Open any edits I had
# made to the previous work are immediately gone." The picker that made changing
# records convenient made losing edits convenient with it.
#
# These are STRUCTURAL: the guard is client-side, and TestClient runs no
# JavaScript. They assert it is present, wired to the right form, and absent
# where there is nothing to lose — not that the browser dialog appears.


def test_the_edit_form_carries_the_UNSAVED_EDITS_guard(client):
    c, _ = client

    html = _open(c)

    assert 'id="editForm"' in html
    assert "unsaved edits" in html
    assert "beforeunload" in html, "the backstop for tab close and browser back"


def test_the_picker_ASKS_THE_FORM_before_opening_another_record(client):
    """The select navigates on change, and a programmatic submit fires no submit
    event — so the picker calls the guard itself rather than relying on one."""
    c, _ = client

    html = _open(c)

    assert "__editGuard" in html
    assert 'id="pickForm"' in html
    assert "onchange" not in html, "an inline submit() could not be guarded"


def test_the_PICKER_PAGE_has_no_guard_because_nothing_is_open(client):
    """No record, no edits, no challenge. The picker still navigates."""
    c, _ = client

    html = c.get("/edit").text

    assert "unsaved edits" not in html
    assert 'id="pickForm"' in html and "__editGuard" in html


# -- References read as names, not handles (Rick, 2026-09-18) ------------------
# "A CURIE is displayed for artist profile, background and type … meaningless to
# the user." All three name something the store already has a label for.

REFERRING = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:w4 a vad:Watercolor ;
    rdfs:label "Refers to things" ;
    vad:hasArtistProfile work:prof-1 ;
    vad:background work:bg-1 .
"""

REFERENTS = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:prof-1 a vad:ArtistProfile ; rdfs:label "Watercolor materials profile" .
work:bg-1 a the:Image ; the:topic the:Background ; rdfs:label "Studio Wall" .
work:bg-2 a the:Image ; the:topic the:Background ; rdfs:label "Open Sky" .
"""


@pytest.fixture
def referring(client):
    c, qa = client
    data = qa.root / Layout.default().dir("work_ttl")
    (data / "w4.ttl").write_text(REFERRING)
    (data / "referents.ttl").write_text(REFERENTS)
    return c, qa, c.get("/edit/open?path=content/ttl/data/w4.ttl").text


def test_the_TYPE_shows_the_class_label_readonly(referring):
    _c, _qa, html = referring

    assert "Watercolor Painting" in html, "the model's rdfs:label, not vad:Watercolor"
    assert "vad:Watercolor" not in html


def test_the_ARTIST_PROFILE_shows_its_label_and_cannot_be_changed(referring):
    """It is baked into the record: it chose the form, the fields and their
    order, and it is how the work reaches its artist's branding."""
    _c, _qa, html = referring

    assert "Watercolor materials profile" in html
    assert "work:prof-1" not in html
    assert 'name="http://visualartsdna.org/model/hasArtistProfile"' not in html, (
        "read-only means no input, not a disabled one"
    )


def test_the_BACKGROUND_is_a_SELECT_of_backgrounds_by_name(referring):
    """A background is a record in the store, so the closed set is the same one
    the entry form offers and the gate checks."""
    _c, _qa, html = referring
    field = html[html.index('id="http://visualartsdna.org/model/background"'):]
    field = field[:field.index("</select>")]

    assert field.startswith('id="http://visualartsdna.org/model/background"')
    assert "Studio Wall" in field and "Open Sky" in field
    assert "work:bg-1" in field, "the value still round-trips as a CURIE"


def test_saving_KEEPS_the_references_it_only_renamed_on_screen(referring):
    """The label is a display, not a value: a save that changed what the record
    points at because the form showed a name would be the worst kind of bug."""
    c, qa, html = referring
    values = dict(re.findall(
        r'<input type="[^"]*" id="([^"]+)" name="[^"]+" value="([^"]*)"', html))
    for sel in re.finditer(r'<select id="([^"]+)"[^>]*>(.*?)</select>', html, re.S):
        cur = re.search(r'<option value="([^"]*)" selected', sel.group(2))
        if cur:
            values[sel.group(1)] = cur.group(1)
    values["path"] = "content/ttl/data/w4.ttl"
    c.post("/edit/save", data=values)

    data = qa.root / Layout.default().dir("work_ttl")
    g = Graph().parse(data=(data / "w4.ttl").read_text(), format="turtle")
    subj = URIRef("http://visualartsdna.org/work/w4")
    assert (subj, URIRef("http://visualartsdna.org/model/hasArtistProfile"),
            URIRef("http://visualartsdna.org/work/prof-1")) in g
    assert (subj, URIRef("http://visualartsdna.org/model/background"),
            URIRef("http://visualartsdna.org/work/bg-1")) in g
    assert (subj, RDF.type, URIRef("http://visualartsdna.org/model/Watercolor")) in g



ANNOTATED = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .

work:w5 a vad:Watercolor ;
    rdfs:label "Has concepts" ;
    vad:hasWatercolorPaint the:IndigoSCC ;
    the:tag work:w1 .
"""

CONCEPTS = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
the:IndigoSCC a skos:Concept , vad:WatercolorPaint ; rdfs:label "Indigo (SCC)" .
"""


@pytest.fixture
def annotated(client):
    c, qa = client
    lay = Layout.default()
    (qa.root / lay.dir("work_ttl") / "w5.ttl").write_text(ANNOTATED)
    vocab = qa.root / lay.dir("vocab_ttl")
    vocab.mkdir(parents=True, exist_ok=True)
    (vocab / "paints.ttl").write_text(CONCEPTS)
    return c, c.get("/edit/open?path=content/ttl/data/w5.ttl").text


def test_ANNOTATIONS_read_as_concept_names(annotated):
    _c, html = annotated

    assert "Indigo (SCC)" in html
    assert "the:IndigoSCC" not in html


def test_ANNOTATIONS_are_readonly_and_point_at_Annotate_Work(annotated):
    """The property a concept lands on is navigated from the ontology, so this
    field is an answer — editing an answer by hand is how a record comes to
    disagree with the model it was derived from."""
    _c, html = annotated

    assert "Annotations are edited in Annotate Work" in html
    assert 'href="/annotate?work=work:w5"' in html
    assert 'name="http://visualartsdna.org/model/hasWatercolorPaint"' not in html


def test_a_TAG_is_still_editable(annotated):
    """`the:tag` is deliberately range-less in the thesaurus, so it is not an
    annotation — it is the user's own text and stays theirs."""
    _c, html = annotated

    assert 'name="http://visualartsdna.org/thesaurus/tag"' in html


# -- Leaving without saving (Rick, 2026-09-18) --------------------------------


def test_DISCARDING_an_edit_puts_the_record_back(client):
    """Approve & distribute is the save; the review is still the form. Before
    this, submitting wrote the record and walking away kept the write — which
    Rick found by seeing an annotation he had reversed on screen still present
    in the file."""
    c, qa = client
    before = (qa.root / "content/ttl/data/w1.ttl").read_text()

    _save(c, **{"http://www.w3.org/2000/01/rdf-schema#label": "Renamed"})
    assert "Renamed" in (qa.root / "content/ttl/data/w1.ttl").read_text()

    r = c.post("/episode/abandon")

    assert r.status_code == 200 and "Discarded" in r.text
    assert (qa.root / "content/ttl/data/w1.ttl").read_text() == before


def test_the_review_page_OFFERS_the_discard(client):
    c, _qa = client

    r = _save(c, **{"http://www.w3.org/2000/01/rdf-schema#label": "Renamed"})

    assert 'action="/episode/abandon"' in r.text
    assert "Discard changes" in r.text


def test_going_back_to_the_form_KEEPS_the_work(client):
    """One piece of work, one restore point: submit, read the review, go back,
    submit again. Only leaving discards."""
    c, qa = client

    _save(c, **{"http://www.w3.org/2000/01/rdf-schema#label": "First try"})
    html = c.get("/edit/open?path=content/ttl/data/w1.ttl").text

    assert "First try" in html, "the draft is still there to build on"


def test_APPROVING_then_discarding_undoes_NOTHING(client):
    """Once it is in the SOT, putting it back is rollback — a different
    operation with a different blast radius (law 6)."""
    c, qa = client

    r = _save(c, **{"http://www.w3.org/2000/01/rdf-schema#label": "Kept"})
    token = r.text.split('name="token" value="', 1)[1].split('"', 1)[0]
    c.post("/rdf/entry/approve", data={"token": token})

    c.post("/episode/abandon")

    assert "Kept" in (qa.root / "content/ttl/data/w1.ttl").read_text()


def test_the_FORM_offers_the_discard_too_not_only_the_review(client):
    """The button used to live on the review page alone, so pressing "Edit form"
    and then thinking better of the whole thing meant submitting again just to
    reach a way of throwing it away."""
    c, _qa = client

    _save(c, **{"http://www.w3.org/2000/01/rdf-schema#label": "Renamed"})
    html = c.get("/edit/open?path=content/ttl/data/w1.ttl").text

    assert 'action="/episode/abandon"' in html
    assert "Unsaved work on" in html


def test_a_form_with_NO_OPEN_SESSION_offers_nothing_to_discard(client):
    c, _qa = client

    html = c.get("/edit/open?path=content/ttl/data/w1.ttl").text

    assert 'action="/episode/abandon"' not in html
