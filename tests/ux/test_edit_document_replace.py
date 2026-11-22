"""An updated document keeps its name (Rick, 2026-11-05).

A record's PDF or markdown is cited by a URL people already hold, so Edit Record
replaces its bytes rather than repointing the record. The promotion side is
asserted too, because "the sidecar changed" is the only thing that carries new
bytes to the SOT when the name does not change.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.inbox import Inbox
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.edit_tools import REPLACE_WITH
from cwva_dashboard.tools.record_tools import documents_base, image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

PDF = "http://visualartsdna.org/thesaurus/pdfDocument"
MD = "http://visualartsdna.org/thesaurus/mdDocument"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
PATH = "content/ttl/data/e1.ttl"
OLD_PDF = b"%PDF old catalog"
OLD_MD = "# old notes"

ENTITY = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix work: <http://visualartsdna.org/work/> .

work:e1 a the:Article ;
    rdfs:label "Sculpture Catalog" ;
    skos:inScheme the:entities ;
    the:pdfDocument <http://visualartsdna.org/documents/SculptureCatalog.pdf> ;
    the:mdDocument <http://visualartsdna.org/documents/Notes.md> .
"""


@pytest.fixture
def env(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    data = qa_root / layout.dir("work_ttl")
    data.mkdir(parents=True)
    (data / "e1.ttl").write_text(ENTITY)
    docs = qa_root / layout.dir("document")
    docs.mkdir(parents=True)
    (docs / "Notes.md").write_text(OLD_MD)
    drop = tmp_path / "drop"
    drop.mkdir()
    sot = tmp_path / "sot"
    sot.mkdir()
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        inbox=Inbox(drop, extensions={"pdf": (".pdf",), "markdown": (".md",)}),
        promotion_driver=PromotionDriver(
            qa, FilesTransport(sot), layout=layout,
            image_base=image_base(TEST_DOMAIN),
            documents_base=documents_base(TEST_DOMAIN),
        ),
    )
    with TestClient(app) as c:
        # The published state: the PDF is a real, sidecar-carrying file that
        # went in through the ordinary channel, and the SOT has it.
        (drop / "SculptureCatalog.pdf").write_bytes(OLD_PDF)
        got = _save(c, **{PDF: REPLACE_WITH + "SculptureCatalog.pdf"})
        assert got.status_code == 200, got.text
        _approve(c)
        (drop / "SculptureCatalog.pdf").unlink()
        yield c, qa, drop, sot, docs


def _approve(c):
    prev = c.post("/api/promotion/preview", json={}).json()
    assert prev["status"] == "previewed", prev
    res = c.post("/api/promotion/approve", json={"token": prev["token"]}).json()
    assert res["status"] == "converged", res
    return res


def _open(c):
    r = c.get("/edit/open", params={"path": PATH})
    assert r.status_code == 200, r.text
    return r.text


def _save(c, **edits):
    return c.post("/edit/save", data={"path": PATH, **edits})


def _options(html, predicate):
    m = re.search(rf'<select id="{re.escape(predicate)}".*?</select>', html, re.S)
    assert m, f"no picker for {predicate}"
    return re.findall(r'<option value="([^"]*)"[^>]*>([^<]*)', m.group(0))


def _status(qa):
    import subprocess

    return subprocess.run(["git", "status", "--short"], cwd=qa.root,
                          capture_output=True, text=True).stdout


def _record(qa):
    return (qa.root / PATH).read_text()


# -- the picker ---------------------------------------------------------------


def test_a_changed_file_with_the_same_name_is_offered_as_a_replacement(env):
    c, _qa, drop, _sot, _docs = env
    (drop / "SculptureCatalog.pdf").write_bytes(b"%PDF new catalog")

    values = [v for v, _ in _options(_open(c), PDF)]

    assert values[0] == "SculptureCatalog.pdf", "unchanged is still the default"
    assert REPLACE_WITH + "SculptureCatalog.pdf" in values


def test_an_identical_file_is_not_offered_or_an_old_copy_could_go_back(env):
    c, _qa, drop, _sot, _docs = env
    (drop / "SculptureCatalog.pdf").write_bytes(OLD_PDF)

    assert [v for v, _ in _options(_open(c), PDF)] == ["SculptureCatalog.pdf"]


def test_a_differently_named_file_says_what_it_will_replace(env):
    c, _qa, drop, _sot, _docs = env
    (drop / "Sculpture Catalog1.pdf").write_bytes(b"%PDF new catalog")

    options = dict(_options(_open(c), PDF))

    assert "replaces SculptureCatalog.pdf" in options["SculptureCatalog1.pdf"]


def test_refresh_offers_exactly_what_the_page_offers(env):
    """The refresh used to return raw names, which is how a name with a space
    reached the save."""
    c, _qa, drop, _sot, _docs = env
    (drop / "Sculpture Catalog.pdf").write_bytes(b"%PDF new catalog")
    (drop / "Other Thing.pdf").write_bytes(b"%PDF other")

    page = [v for v, _ in _options(_open(c), PDF)][1:]
    refreshed = c.get("/api/affordance/file-ref", params={
        "subtree": "content/documents", "kind": "pdf", "edit": 1,
        "current": "SculptureCatalog.pdf",
    }).json()["candidates"]

    assert [x["value"] for x in refreshed] == page
    assert not any(" " in x["value"] for x in refreshed)


def test_an_entry_form_refresh_is_not_affected(env):
    c, _qa, drop, _sot, _docs = env
    (drop / "Dropped Name.pdf").write_bytes(b"%PDF x")

    got = c.get("/api/affordance/file-ref", params={
        "subtree": "content/documents", "kind": "pdf"}).json()["candidates"]

    assert [x["value"] for x in got] == ["Dropped Name.pdf"]


# -- the replacement ----------------------------------------------------------


@pytest.mark.parametrize("dropped", [
    "SculptureCatalog.pdf", "Sculpture Catalog.pdf", "Sculpture Catalog1.pdf",
])
def test_the_picked_file_reaches_the_sot_under_the_existing_name(env, dropped):
    """The whole point, with each spelling the user might have in the folder."""
    c, qa, drop, sot, docs = env
    new = b"%PDF new catalog"
    (drop / dropped).write_bytes(new)
    choice = {v: l for v, l in _options(_open(c), PDF)}
    pick = next(v for v in choice if v != "SculptureCatalog.pdf")

    r = _save(c, **{PDF: pick})

    assert r.status_code == 200, r.text
    assert (docs / "SculptureCatalog.pdf").read_bytes() == new
    assert [p.name for p in docs.glob("*.pdf")] == ["SculptureCatalog.pdf"]
    assert "documents/SculptureCatalog.pdf>" in _record(qa).replace(
        TEST_DOMAIN, "visualartsdna.org")
    assert (drop / dropped).read_bytes() == new, "the drop folder keeps its own"

    _approve(c)
    published = list(sot.rglob("SculptureCatalog.pdf"))
    assert published and published[0].read_bytes() == new
    assert not list(sot.rglob("*Catalog1*"))


def test_the_superseded_version_goes_to_the_attic(env):
    import hashlib

    c, qa, drop, _sot, _docs = env
    (drop / "SculptureCatalog.pdf").write_bytes(b"%PDF new catalog")

    _save(c, **{PDF: REPLACE_WITH + "SculptureCatalog.pdf"})

    attic = qa.root / ".qa/attic" / hashlib.sha256(OLD_PDF).hexdigest()
    assert attic.read_bytes() == OLD_PDF


def test_markdown_follows_the_same_rule(env):
    c, qa, drop, sot, docs = env
    (drop / "Notes.md").write_text("# new notes")
    (drop / "Notes 2.md").write_text("# newer notes")

    r = _save(c, **{MD: REPLACE_WITH + "Notes.md"})
    assert r.status_code == 200, r.text
    assert "# new notes" in (docs / "Notes.md").read_text()

    r = _save(c, **{MD: "Notes2.md"})
    assert r.status_code == 200, r.text
    assert "# newer notes" in (docs / "Notes.md").read_text()
    assert not (docs / "Notes2.md").exists()

    _approve(c)
    assert "# newer notes" in next(sot.rglob("Notes.md")).read_text()


def test_a_replaced_markdown_keeps_its_link_to_the_record(env):
    """Derivation finds a document's entity by this line, and the new version
    came from outside the system, so it does not have one."""
    c, _qa, drop, _sot, docs = env
    (drop / "Notes.md").write_text("# new notes\n\nbody\n")

    _save(c, **{MD: REPLACE_WITH + "Notes.md"})

    assert (docs / "Notes.md").read_text().splitlines()[:2] == [
        "# new notes", "[id=work:e1]"]


def test_a_stamped_markdown_is_not_offered_against_its_own_source(env):
    """The stored copy gained an id line, so comparing bytes would call the
    unchanged source an update for ever."""
    c, _qa, drop, _sot, docs = env
    (drop / "Notes.md").write_text("# new notes\n")
    _save(c, **{MD: REPLACE_WITH + "Notes.md"})
    assert "[id=work:e1]" in (docs / "Notes.md").read_text()

    assert [v for v, _ in _options(_open(c), MD)] == ["Notes.md"]


# -- adding a document the entity does not cite ---------------------------------


def _without_markdown(qa):
    """The record as it stands, minus its markdown."""
    (qa.root / PATH).write_text(ENTITY.replace(
        ';\n    the:mdDocument <http://visualartsdna.org/documents/Notes.md> .', '.'))


def test_an_entity_with_no_markdown_can_be_given_one(env):
    c, qa, drop, sot, docs = env
    _without_markdown(qa)
    (drop / "Fresh Notes.md").write_text("# fresh\n")

    assert "FreshNotes.md" in [v for v, _ in _options(_open(c), MD)]
    r = _save(c, **{MD: "FreshNotes.md"})

    assert r.status_code == 200, r.text
    assert "documents/FreshNotes.md" in _record(qa)
    assert (docs / "FreshNotes.md").read_text().splitlines()[:2] == [
        "# fresh", "[id=work:e1]"]
    _approve(c)
    assert next(sot.rglob("FreshNotes.md")).is_file()


def test_leaving_the_empty_picker_alone_adds_nothing(env):
    c, qa, drop, _sot, docs = env
    _without_markdown(qa)
    (drop / "Fresh Notes.md").write_text("# fresh\n")

    r = _save(c, **{LABEL: "Renamed", MD: ""})

    assert r.status_code == 200, r.text
    assert "mdDocument" not in _record(qa)
    assert not (docs / "FreshNotes.md").exists()


def test_a_new_document_may_not_take_a_name_another_record_cites(env):
    c, qa, drop, _sot, _docs = env
    _without_markdown(qa)
    (qa.root / "content/ttl/data/e2.ttl").write_text(
        ENTITY.replace("work:e1", "work:e2").replace(
            "documents/SculptureCatalog.pdf", "documents/Other.pdf"))
    (drop / "Notes.md").write_text("# someone else's\n")

    r = _save(c, **{MD: "Notes.md"})

    assert r.status_code == 409
    assert "Rename it" in r.text


def test_a_work_is_not_offered_an_empty_document_picker(tmp_path):
    """Scoped to entities, which is what was asked for."""
    from cwva_dashboard.tools.edit_tools import read_instance

    class Ops:
        @staticmethod
        def read_text(_):
            return (
                "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
                "@prefix vad: <http://visualartsdna.org/model/> .\n"
                "@prefix work: <http://visualartsdna.org/work/> .\n"
                'work:w1 a vad:Watercolor ; rdfs:label "A" .\n')

    got = read_instance(Ops, "x.ttl", {MD: {"kind": "markdown", "subtree": "documents"}})

    assert MD not in [f["predicate"] for f in got["fields"]]


def test_a_stale_tab_posting_a_raw_name_is_normalized_not_refused(env):
    c, _qa, drop, _sot, docs = env
    (drop / "Sculpture Catalog1.pdf").write_bytes(b"%PDF new")

    r = _save(c, **{PDF: "Sculpture Catalog1.pdf"})

    assert r.status_code == 200, r.text
    assert (docs / "SculptureCatalog.pdf").read_bytes() == b"%PDF new"
    assert not (docs / "Sculpture Catalog1.pdf").exists()


def test_saving_without_picking_replaces_nothing(env):
    c, _qa, drop, _sot, docs = env
    (drop / "SculptureCatalog.pdf").write_bytes(b"%PDF new")

    _save(c, **{PDF: "SculptureCatalog.pdf", LABEL: "Sculpture Catalog 2"})

    assert (docs / "SculptureCatalog.pdf").read_bytes() == OLD_PDF


def test_a_file_gone_from_the_folder_is_reported_not_silently_kept(env):
    c, _qa, _drop, _sot, docs = env

    r = _save(c, **{PDF: REPLACE_WITH + "SculptureCatalog.pdf"})

    assert "NOT replaced" in r.text
    assert (docs / "SculptureCatalog.pdf").read_bytes() == OLD_PDF


def test_a_refused_save_copies_nothing_in(env):
    """A stray file left by a refusal goes out with the next approval."""
    c, qa, drop, _sot, docs = env
    (drop / "SculptureCatalog.pdf").write_bytes(b"%PDF new")
    # An IRI that cannot be serialized refuses the save: `the:tag` is a
    # reference field, and the PDF field beside it is perfectly good.
    (qa.root / PATH).write_text(ENTITY.replace(
        "skos:inScheme the:entities ;",
        "skos:inScheme the:entities ;\n    the:tag work:e2 ;"))
    r = _save(c, **{PDF: REPLACE_WITH + "SculptureCatalog.pdf",
                    "http://visualartsdna.org/thesaurus/tag": "not an iri"})

    assert r.status_code == 400, r.text
    assert (docs / "SculptureCatalog.pdf").read_bytes() == OLD_PDF
    assert "SculptureCatalog.pdf.ptr" not in _status(qa)


def test_a_document_another_record_cites_is_not_replaced(env):
    c, qa, drop, _sot, docs = env
    (qa.root / "content/ttl/data/e2.ttl").write_text(
        ENTITY.replace("work:e1", "work:e2"))
    (drop / "SculptureCatalog.pdf").write_bytes(b"%PDF new")

    r = _save(c, **{PDF: REPLACE_WITH + "SculptureCatalog.pdf"})

    assert r.status_code == 409
    assert "Replacing it would change" in r.text
    assert (docs / "SculptureCatalog.pdf").read_bytes() == OLD_PDF


def test_discarding_the_review_puts_the_old_version_back(env):
    c, qa, drop, _sot, docs = env
    (drop / "SculptureCatalog.pdf").write_bytes(b"%PDF new")
    (drop / "Notes.md").write_text("# new notes")

    _save(c, **{PDF: REPLACE_WITH + "SculptureCatalog.pdf",
                MD: REPLACE_WITH + "Notes.md"})
    assert (docs / "SculptureCatalog.pdf").read_bytes() == b"%PDF new"

    r = c.post("/wip/discard", data={})
    assert r.status_code == 200, r.text

    assert (docs / "SculptureCatalog.pdf").read_bytes() == OLD_PDF
    assert (docs / "Notes.md").read_text() == OLD_MD
    assert _status(qa) == ""


def test_the_refused_message_for_a_file_does_not_mention_commas():
    from cwva_dashboard.tools.base import ToolError
    from cwva_dashboard.tools.edit_tools import _objects_from

    with pytest.raises(ToolError) as e:
        _objects_from({"kind": "file", "label": "pdfDocument", "base": "http://x/"},
                      "a b.pdf", {})
    assert "comma" not in str(e.value)
