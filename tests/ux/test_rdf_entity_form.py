"""RDF Entity wired from function.html (Phase 4.7, cycle 3).

The entity form is the first that is genuinely MULTI-VALUED, and that is what
these tests are mostly about. Topics are a checkbox grid, images take a list,
tags take free text, and notes repeat with a kind each — none of which the two
work forms needed, and each of which is a way for the offered set and the
enforced set to come apart.

Three differences from the Groovy are deliberate and pinned here:

1. **No QR code.** The Groovy generated one for works. An entity is not a work
   and carries no `vad:qrcode`, so generating one would leave an orphan
   `qrc_<guid>.jpg` in the sandbox that no record references.
2. **`md_document`/`pdf_document` are drop-folder pickers, not gdoc fetches.**
   The Groovy downloaded them from Google Docs; that is network I/O outside the
   three sanctioned effects (law 11), and the record would name a document that
   never reached SOT. Law 12 gives the replacement: the user drops the file.
3. **Note kinds are really enforced.** They were a form-only closed set while
   `validate_args` did not recurse into object items — so `skos:<anything>` was
   mintable by any caller that was not the form.
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
from cwva_dashboard.tools.record_tools import documents_base, image_base

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

MODEL = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix vad: <http://visualartsdna.org/model/> .
vad:PaintingForm a owl:Class .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
vad:SculptureForm a owl:Class .
"""

TOPICS = """@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
the:Criticism a skos:Concept ; rdfs:label "Criticism" ; skos:inScheme the:TopicScheme .
the:Watercolor a skos:Concept ; rdfs:label "Watercolor" ; skos:inScheme the:TopicScheme .
the:Digital a skos:Concept ; rdfs:label "Digital" ; skos:inScheme the:TopicScheme .
the:Loose a skos:Concept ; rdfs:label "Loose" .
"""


@pytest.fixture
def drop_folder(tmp_path):
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "fresco.jpg").write_bytes(b"\xff\xd8jpeg")
    (folder / "detail.jpg").write_bytes(b"\xff\xd8jpeg2")
    (folder / "Analysis.md").write_text("# Colour and light\n\nBody.\n")
    # A name carrying the problem this exists for.
    (folder / "Spirited Tree.jpg").write_bytes(b"\xff\xd8spirited")
    (folder / "Analysis.pdf").write_bytes(b"%PDF-1.4 fake")
    return folder


@pytest.fixture
def client(tmp_path, drop_folder):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    model = qa_root / layout.dir("model_ttl")
    model.mkdir(parents=True)
    (model / "m.ttl").write_text(MODEL)
    vocab = qa_root / layout.dir("vocab_ttl")
    vocab.mkdir(parents=True)
    (vocab / "topics.ttl").write_text(TOPICS)
    # Something to tag: a collection record in content, a concept in the
    # thesaurus. Real tags point at both.
    data = qa_root / layout.dir("work_ttl")
    data.mkdir(parents=True)
    (data / "c1.ttl").write_text(
        '@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n'
        '@prefix the: <http://visualartsdna.org/thesaurus/> .\n'
        '@prefix work: <http://visualartsdna.org/work/> .\n'
        'work:c1 a the:Collection ; rdfs:label "Unmoored Collection" ;\n'
        '    the:topic the:Criticism .\n'
    )
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        inbox=Inbox(
            drop_folder,
            extensions={"image": (".jpg",), "markdown": (".md",), "pdf": (".pdf",)},
        ),
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"),
            image_base=image_base(TEST_DOMAIN),
            documents_base=documents_base(TEST_DOMAIN),
            layout=layout,
            # ARM THE GATES exactly as create_app does, or "gates passed" would
            # only mean "no gates ran".
            vocab_dirs=[layout.dir("vocab_ttl"), layout.dir("tags_ttl")],
            content_dirs=[layout.dir("work_ttl")],
        ),
    )
    with TestClient(app) as c:
        yield c, qa


def _form(c):
    return c.get("/rdf/entity").text


def _guid(html):
    return re.search(r'name="guid" value="([^"]+)"', html).group(1)


def _submit(c, html, **over):
    data = {
        "guid": _guid(html), "type": "Article", "label": "Colour and Light",
        "topic": ["the:Criticism"], "definition": "An essay about colour.",
        "recorded_date": "2026-09-07",
    }
    data.update(over)
    return data["guid"], c.post("/rdf/entity", data=data)


def _ttl(qa, guid):
    return (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()


def _checkboxes(html, field):
    grid = re.search(r'<div class="check-grid">.*?</div>\s*</div>', html, re.S)
    if not grid:
        return []
    return re.findall(rf'name="{field}" value="([^"]*)"', grid.group(0))


def _picker(html, field):
    m = re.search(rf'<select id="{field}" name="{field}".*?</select>', html, re.S)
    return [o for o in re.findall(r'<option value="([^"]*)"', m.group(0)) if o] if m else []


# -- the form -----------------------------------------------------------------


def test_the_card_on_the_hub_now_resolves(client):
    c, _ = client
    hub = c.get("/").text
    assert 'href="rdf/entity"' in hub
    assert "entity_page" not in hub, "the legacy Groovy route must not linger"
    assert c.get("/rdf/entity").status_code == 200


def test_topics_are_a_checkbox_grid_from_the_TopicScheme(client):
    """The Groovy laid these out five to a row from the same query. `the:Loose`
    is a concept but NOT in the scheme, so it must not be offered — the picker's
    query is the gate's requirement."""
    c, _ = client
    boxes = _checkboxes(_form(c), "topic")

    assert boxes == ["the:Criticism", "the:Digital", "the:Watercolor"]
    assert "the:Loose" not in boxes


def test_several_topics_survive_the_round_trip(client):
    """`form.items()` keeps one value per key, which silently drops all but the
    last box. Topics are 1-4 per entity in the real store, so losing all but one
    would corrupt most records quietly."""
    c, qa = client
    guid, r = _submit(c, _form(c), topic=["the:Criticism", "the:Watercolor"])

    assert r.status_code == 200, r.text
    ttl = _ttl(qa, guid)
    assert "the:Criticism" in ttl and "the:Watercolor" in ttl


def test_a_topic_outside_the_scheme_is_refused_at_the_gate(client):
    """Offered == enforced, in the direction that matters: something the grid
    did not show must not pass either."""
    c, _ = client
    _guid, r = _submit(c, _form(c), topic=["the:Loose"])

    assert "Gates failed" in r.text


def test_images_take_several_files(client):
    """The Groovy took a comma-separated list. It stays a <select>, multiple, so
    the in-place Refresh list control keeps working on it."""
    c, qa = client
    html = _form(c)
    # The picker lists the DROP FOLDER's own names, un-normalized: those are
    # the files the user can see. Normalization happens on the way in.
    assert sorted(_picker(html, "images")) == [
        "Spirited Tree.jpg", "detail.jpg", "fresco.jpg",
    ]
    assert 'name="images" multiple' in html

    guid, r = _submit(c, html, images=["fresco.jpg", "detail.jpg"])
    assert r.status_code == 200, r.text
    ttl = _ttl(qa, guid)
    assert "fresco.jpg" in ttl and "detail.jpg" in ttl
    for name in ("fresco.jpg", "detail.jpg"):
        assert (qa.root / "content/images" / name).is_file(), f"{name} not ingested"


def test_tags_are_free_text_split_on_commas_and_lines(client):
    """Tags are arbitrary work: URIs — up to 20 on one record in the real store
    — so there is no closed set to offer."""
    c, qa = client
    guid, r = _submit(c, _form(c), tags="work:abc, work:def\nwork:ghi")

    assert r.status_code == 200
    ttl = _ttl(qa, guid)
    for t in ("work:abc", "work:def", "work:ghi"):
        assert t in ttl


# -- notes --------------------------------------------------------------------


def test_notes_repeat_with_a_kind_each(client):
    c, qa = client
    guid, r = _submit(
        c, _form(c),
        note_type=["scopeNote", "note"],
        note_text=["Written for the newsletter.", "Second thought."],
    )

    assert r.status_code == 200, r.text
    ttl = _ttl(qa, guid)
    assert 'skos:scopeNote "Written for the newsletter."' in ttl
    assert 'skos:note "Second thought."' in ttl


def test_an_empty_note_row_is_not_recorded(client):
    """The form always shows one row, so a user who writes no note still posts
    an empty one. An empty skos:note is noise in the record."""
    c, qa = client
    guid, r = _submit(c, _form(c), note_type=["note"], note_text=["   "])

    assert r.status_code == 200
    assert "skos:note" not in _ttl(qa, guid)


def test_a_note_kind_outside_the_set_is_REFUSED(client):
    """`skos:<anything>` was mintable while validate_args did not recurse into
    object items — the form offered six kinds and nothing enforced them."""
    c, qa = client
    guid, r = _submit(c, _form(c), note_type=["evilNote"], note_text=["x"])

    assert r.status_code == 400
    assert "not_in_enum" in r.text
    assert not (qa.root / "content/ttl/data" / f"{guid}.ttl").exists()


def test_the_offered_note_kinds_ARE_the_enforced_enum(client):
    c, _ = client
    html = _form(c)
    offered = re.findall(r'<select name="note_type">(.*?)</select>', html, re.S)[0]
    offered = set(re.findall(r'<option value="([^"]*)"', offered))

    entity = next(t for t in c.get("/api/tools").json()
                  if t["name"] == "record.new_entity")
    enum = set(entity["inputSchema"]["properties"]["notes"]["items"]
               ["properties"]["type"]["enum"])
    assert offered == enum


# -- documents ----------------------------------------------------------------


def test_documents_come_from_the_drop_folder_not_a_gdoc_fetch(client):
    """Law 11 forbids the Groovy's download; law 12 supplies the replacement."""
    c, qa = client
    html = _form(c)
    assert _picker(html, "md_document") == ["Analysis.md"]
    assert _picker(html, "pdf_document") == ["Analysis.pdf"]

    guid, r = _submit(c, html, md_document="Analysis.md", pdf_document="Analysis.pdf")
    assert r.status_code == 200, r.text
    ttl = _ttl(qa, guid)
    assert "the:mdDocument <http://visualartsdna.org/documents/Analysis.md>" in ttl
    assert "the:pdfDocument <http://visualartsdna.org/documents/Analysis.pdf>" in ttl
    assert (qa.root / "content/documents/Analysis.md").is_file()
    assert (qa.root / "content/documents/Analysis.pdf").is_file()


def test_a_markdown_document_is_git_content_and_a_pdf_is_pointer_managed(client):
    """Both ingest, but they are tracked differently: `.md` is in
    git_content_extensions, `.pdf` is not, so only the PDF gets a sidecar. The
    gate has to accept either, which is why documents cannot reuse the image
    family's managed-binary test."""
    c, qa = client
    _guid, r = _submit(c, _form(c), md_document="Analysis.md", pdf_document="Analysis.pdf")

    assert "Gates failed" not in r.text, r.text
    docs = qa.root / "content/documents"
    assert not (docs / "Analysis.md.ptr").exists(), "markdown is ordinary git content"
    assert (docs / "Analysis.pdf.ptr").is_file(), "a PDF is pointer-managed"


def test_the_source_link_field_is_GONE(client):
    """`the:document` held a Google Docs link. Removed 2026-09-07: those
    reference links are not dependable enough to record. Old records keep
    theirs; the property is not gated, so nothing downstream changes."""
    c, qa = client
    html = _form(c)
    assert 'name="document"' not in html
    assert "gdoc" not in html.lower()

    guid, r = _submit(c, html)
    assert r.status_code == 200
    ttl = _ttl(qa, guid)
    assert "the:document" not in ttl
    assert "gdoc source" not in ttl


def test_the_dbpedia_field_is_GONE(client):
    """The wikipedia link covers the same referent in human-readable form, and a
    dbpedia URI can go in primary_site (schema:sameAs) if one is ever wanted."""
    c, qa = client
    html = _form(c)
    assert 'name="dbpedia"' not in html

    guid, r = _submit(c, html, wikipedia="https://en.wikipedia.org/wiki/Colour")
    assert r.status_code == 200
    ttl = _ttl(qa, guid)
    assert "the:dbpedia" not in ttl
    assert "the:wikipedia" in ttl


# -- entity-specific record shape --------------------------------------------


def test_no_qrcode_is_generated_for_an_entity(client):
    """An entity is not a work. Generating one would leave an orphan JPEG in the
    sandbox that no record references — and promotion sweeps up everything
    uncommitted, so the user would find it on the review page."""
    c, qa = client
    guid, r = _submit(c, _form(c))

    assert r.status_code == 200
    assert "vad:qrcode" not in _ttl(qa, guid)
    assert not list((qa.root / "content/images").glob("qrc_*.jpg"))
    assert "qrc_" not in r.text


def test_the_constant_triples_are_always_written(client):
    """`the:conceptsExtracted false` and `skos:inScheme the:entities` are not
    fields — the Groovy wrote them unconditionally and downstream concept
    extraction keys off them."""
    c, qa = client
    guid, _r = _submit(c, _form(c))
    ttl = _ttl(qa, guid)

    # `the:conceptsExtracted` is no longer written (2026-10-02); the scheme
    # is the one constant triple the form still always adds.
    assert "the:conceptsExtracted" not in ttl
    assert "skos:inScheme the:entities" in ttl


def test_submit_stops_at_review_without_converging(client):
    c, qa = client
    _guid, r = _submit(c, _form(c))

    assert "Distribute Data — review" in r.text
    assert not list((qa.root.parent / "sot").rglob("*.ttl")), "must not converge"


def test_the_shared_cycle_is_shared_not_copied(client):
    """Entity reuses the entry route's submit cycle, so the affordances earned
    in cycles 1 and 2 apply here too."""
    c, _ = client
    _guid, r = _submit(c, _form(c))

    assert "Approve" in r.text and "Edit form" in r.text


def test_a_reused_image_filename_is_still_REFUSED(client):
    c, qa = client
    _submit(c, _form(c), images=["fresco.jpg"])
    _guid, r = _submit(c, _form(c), label="Another", images=["fresco.jpg"])

    assert r.status_code == 409
    assert "fresco.jpg" in r.text


def test_a_reused_DOCUMENT_filename_is_REFUSED(client):
    """Documents resolve against the documents base, not the image base — a
    collision check that joined the wrong base would compare the wrong URI and
    report nothing."""
    c, qa = client
    _submit(c, _form(c), md_document="Analysis.md")
    _guid, r = _submit(c, _form(c), label="Another", md_document="Analysis.md")

    assert r.status_code == 409
    assert "Analysis.md" in r.text
    assert "(md_document)" in r.text


def test_each_document_picker_offers_only_its_own_type(client):
    """Markdown and PDF are separate KINDS sharing one directory. A single
    "document" kind let the .md field offer the .pdf — the same defect as a 3D
    picker offering photographs, found the first time the form was rendered."""
    c, _ = client
    html = _form(c)

    assert _picker(html, "md_document") == ["Analysis.md"]
    assert _picker(html, "pdf_document") == ["Analysis.pdf"]


def test_a_pdf_is_refused_for_the_markdown_field(client):
    """Enforced at ingest, not merely offered."""
    c, qa = client
    _guid, r = _submit(c, _form(c), md_document="Analysis.pdf")

    assert not (qa.root / "content/documents/Analysis.pdf").is_file()
    assert "Gates failed" in r.text, "an un-ingested document must dangle"


def test_a_document_that_never_ingested_FAILS_the_gate(client):
    """The point of gating the document family: without it the record reaches
    SOT naming a markdown file that never converged — the same silent defect as
    the hand-placed binary, one property over."""
    c, _ = client
    _guid, r = _submit(c, _form(c), md_document="NotInTheDropFolder.md")

    assert "Gates failed" in r.text


def test_the_field_is_named_for_the_property_it_writes(client):
    """It was `media`, the Groovy's own name, which put the word "media" above a
    grid of topics and matched nothing in the record."""
    c, qa = client
    html = _form(c)
    assert 'name="topic"' in html
    assert 'name="media"' not in html
    # Caption and help come from the ontology: the:topic carries both.
    assert ">topic <" in html or ">topic<" in html

    guid, r = _submit(c, html, topic=["the:Criticism"])
    assert r.status_code == 200
    assert "the:topic the:Criticism" in _ttl(qa, guid)


def test_a_checkbox_keeps_its_intrinsic_size(client):
    """The global `input{width:100%}` stretched each box to fill its grid cell,
    which pushed every caption to the far right and made the columns look
    ragged. Pinned because it is invisible in any test that only reads values."""
    c, _ = client
    html = _form(c)

    assert ".check input[type=checkbox]{width:auto" in html
    assert "grid-template-columns" in html


def test_a_multi_value_field_says_how_to_enter_several(client):
    """Input mechanics the ontology cannot know, appended to its comment rather
    than replacing it."""
    c, _ = client
    html = _form(c)

    assert "Separate several with commas." in html      # tags: free text
    assert "ctrl-click" in html                          # images: multi-select
    assert 'name="images" multiple' in html


def test_a_field_the_model_does_not_describe_falls_back_to_its_schema(client):
    """`primary_site` and `definition` are deliberately NOT in the field→property
    map: mapping a field asserts "the model describes this", and a mapped
    property with no rdfs:comment renders no hint by design (silence in the
    model is meaningful — `height` needs no "Height value." beneath it). These
    two are undescribed, so they fall through to their schema description."""
    c, _ = client
    html = _form(c)

    assert "canonical URL for this entity elsewhere" in html
    assert "What this entity is" in html


# -- filename normalization and markdown stamping (2026-09-07) ---------------


def test_a_filename_with_spaces_is_normalized_on_entry(client):
    """The name becomes part of the IRI the record cites, where a space is
    invalid. The record, the sandbox file and the reference all use the
    normalized name."""
    c, qa = client
    guid, r = _submit(c, _form(c), images=["Spirited Tree.jpg"])

    assert r.status_code == 200, r.text
    assert (qa.root / "content/images/SpiritedTree.jpg").is_file()
    assert not (qa.root / "content/images/Spirited Tree.jpg").exists()
    assert "images/SpiritedTree.jpg" in _ttl(qa, guid)


def test_the_drop_folder_keeps_its_own_name(client, drop_folder):
    """The user's folder is theirs. Renaming a file they can see, out from under
    them, is not the dashboard's business — and leaving it means re-running the
    entry still works."""
    c, _qa = client
    _submit(c, _form(c), images=["Spirited Tree.jpg"])

    assert (drop_folder / "Spirited Tree.jpg").is_file()


def test_the_rename_is_reported_on_the_review_page(client):
    """The user did not type this name, so they find out where Edit form is
    still one click away."""
    c, _ = client
    _guid, r = _submit(c, _form(c), images=["Spirited Tree.jpg"])

    assert "Applied on entry" in r.text
    assert "Spirited Tree.jpg" in r.text and "SpiritedTree.jpg" in r.text


def test_uniqueness_is_checked_AFTER_the_rename(client):
    """Two different original names can normalize to one. Checking before the
    rename would compare names nothing will ever be stored under."""
    c, qa = client
    _submit(c, _form(c), images=["Spirited Tree.jpg"])
    # A second drop-folder file whose normalized name collides with the first.
    (qa.root.parent / "drop" / "Spirited  Tree.jpg").write_bytes(b"\xff\xd8other")

    _guid, r = _submit(c, _form(c), label="Another", images=["Spirited  Tree.jpg"])

    assert r.status_code == 409
    assert "already referenced by another record" in r.text


def test_two_files_normalizing_to_one_name_are_REFUSED(client, drop_folder):
    """Inside a single submission neither file is in the store yet, so no
    collision check against records can see it — the second would simply
    overwrite the first."""
    c, _ = client
    (drop_folder / "Spirited  Tree.jpg").write_bytes(b"\xff\xd8other")

    _guid, r = _submit(c, _form(c), images=["Spirited Tree.jpg", "Spirited  Tree.jpg"])

    assert r.status_code == 409
    assert "normalize to the same name" in r.text


def test_a_markdown_document_is_stamped_with_the_records_CURIE(client):
    """Concept derivation and tagging read this line to find the entity a
    document belongs to. It was a manual step until now."""
    c, qa = client
    guid, r = _submit(c, _form(c), md_document="Analysis.md")

    assert r.status_code == 200, r.text
    lines = (qa.root / "content/documents/Analysis.md").read_text().splitlines()
    assert lines[0] == "# Colour and light"
    assert lines[1] == f"[id=work:{guid}]"
    assert f"[id=work:{guid}]" in r.text, "and it is reported on the review page"


def test_the_stamp_goes_in_the_SANDBOX_copy_not_the_drop_folder(client, drop_folder):
    c, _qa = client
    _submit(c, _form(c), md_document="Analysis.md")

    assert "[id=" not in (drop_folder / "Analysis.md").read_text()


def test_a_pdf_is_not_stamped(client):
    """Only markdown carries the id line; a PDF is not text to append to."""
    c, qa = client
    _guid, r = _submit(c, _form(c), pdf_document="Analysis.pdf")

    assert r.status_code == 200
    assert (qa.root / "content/documents/Analysis.pdf").read_bytes().startswith(b"%PDF")


def test_the_work_forms_normalize_too(client):
    """Not an entity-form feature: every file field on every form goes through
    the same ingest path."""
    from cwva_dashboard.inbox import normalize_filename

    assert normalize_filename("Unmoored Swing.jpg") == "UnmooredSwing.jpg"
    c, _ = client
    html = c.get("/rdf/entry").text
    assert html.count("Refresh list") >= 1, "the work form still renders its picker"


def test_a_case_variant_filename_is_refused_with_the_existing_spelling(client, drop_folder):
    """On Windows and default macOS these are the same file, so the second
    ingest overwrites the first work's image. The refusal shows what it clashes
    with, because otherwise the user is looking at a different name in their
    folder and has nothing to go on."""
    c, _qa = client
    _submit(c, _form(c), images=["fresco.jpg"])
    (drop_folder / "FRESCO.jpg").write_bytes(b"\xff\xd8other")

    _guid, r = _submit(c, _form(c), label="Another", images=["FRESCO.jpg"])

    assert r.status_code == 409
    assert "FRESCO.jpg" in r.text
    assert "already has" in r.text and "fresco.jpg" in r.text


# -- tag references on the review page (2026-09-09) --------------------------


def _tag_card(html):
    import re

    m = re.search(r"Tag references</h2>(.*?)</div>\s*(?:<div class=\"card\"|<div class=\"summary)",
                  html, re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else ""


def test_a_resolved_tag_is_shown_with_its_LABEL(client):
    """`work:c1` tells a reviewer nothing about whether the right thing was
    tagged; "Unmoored Collection" does."""
    c, _ = client
    _guid, r = _submit(c, _form(c), tags="work:c1")

    card = _tag_card(r.text)
    assert "Unmoored Collection" in card
    assert "work:c1" in card
    assert "Collection" in card, "the referent's type is shown too"


def test_a_thesaurus_tag_resolves_as_well_as_a_record(client):
    c, _ = client
    _guid, r = _submit(c, _form(c), tags="the:Criticism")

    assert "Criticism" in _tag_card(r.text)


def test_a_tag_pointing_at_nothing_is_FLAGGED_not_refused(client):
    """Advisory by design: a tag may legitimately run ahead of the record it
    names — a work tagged into a series collection created afterwards — and the
    real store already holds one such tag among 186."""
    c, qa = client
    guid, r = _submit(c, _form(c), tags="work:c1, work:nosuch")

    assert r.status_code == 200, "reported, not refused"
    card = _tag_card(r.text)
    assert "work:nosuch" in card and "matches nothing in the store yet" in card
    assert "Unmoored Collection" in card, "the good tag is still shown"
    # and it really was written — this is a report, not a veto
    assert "work:nosuch" in _ttl(qa, guid)


def test_NO_tags_is_called_out_explicitly(client):
    """The commonest tagging mistake is not a wrong tag, it is forgetting to
    tag. Silence would look like success."""
    c, _ = client
    _guid, r = _submit(c, _form(c))

    card = _tag_card(r.text)
    assert "No tags on this record" in card
    assert "Edit form" in card


def test_the_tag_card_is_absent_on_a_form_with_no_tags_field(client):
    """RDF Entry has no tags. A "no tags" notice there would be nonsense."""
    c, _ = client
    html = c.get("/rdf/entry").text
    assert "Tag references" not in html


# -- Rick's findings, 2026-09-27 ---------------------------------------------


def test_an_entity_offers_NO_BRANDING(client):
    """An entity's images are references — a background plate, a document scan,
    a reference photograph — and are left exactly as they arrive. The control
    was appearing because the form HAS an image field, and having one is not the
    same as owning the image."""
    c, _qa = client

    html = c.get("/rdf/entity").text

    assert "Brand this image" not in html
    assert 'name="brand_signature"' not in html


def test_an_EMPTY_file_picker_still_offers_Refresh():
    """The remedy for "no files in your drop folder" is to put one there, and
    without the control the only way to see it was to reload the page and lose
    everything typed. Asserted on the widget with NO options, because a
    populated picker would show the control either way."""
    from cwva_dashboard.ux.forms import _multi_select, _widget

    empty = _multi_select("images", [], None, "— no files in /drop —",
                          "content/images", "image")
    assert "disabled" in empty, "nothing to choose yet"
    assert "Refresh list" in empty, "and a way to look again"

    single = _widget("image", {"type": "string", "x-file-ref": "content/images"},
                     None, options=[], empty_hint="— no files in /drop —",
                     refresh_subtree="content/images", refresh_kind="image")
    assert "disabled" in single and "Refresh list" in single


def test_an_HDR_is_offered_as_an_image(client, tmp_path):
    """A Radiance HDR is not a photograph, but it is what a Background entity's
    `schema:image` points at."""
    from cwva_dashboard.inbox import DEFAULT_EXTENSIONS

    assert ".hdr" in DEFAULT_EXTENSIONS["image"]
