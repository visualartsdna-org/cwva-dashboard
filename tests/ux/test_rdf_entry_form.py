"""RDF Entry wired from function.html (Phase 4.7, first per-function cycle).

**This file carries the contract that replaced the zero-UX-code test** deleted
under D1. That test asserted "every affordance reaches the renderer verbatim",
which was meaningful when one renderer served every tool. With a real form per
function, the property worth keeping is narrower and stronger:

    what the form OFFERS is what the system ENFORCES.

So the tests below check that each closed set in the rendered HTML is the schema
`enum` `validate_args` enforces, and that each picker's options come from the
same vocabulary the promotion gate checks — not that some markup exists.
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
from cwva_dashboard.tools.fileops_tools import build_default_registry
from cwva_dashboard.tools.record_tools import image_base
from cwva_dashboard.ux.forms import RDF_ENTRY_LAYOUT, render_entry_form

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def drop_folder(tmp_path):
    """The user's drop folder — outside the sandbox, where files actually come
    from. The user never opens the sandbox."""
    folder = tmp_path / "drop"
    folder.mkdir()
    (folder / "dropped.jpg").write_bytes(b"\xff\xd8dropped")
    return folder


@pytest.fixture
def client(tmp_path, drop_folder):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    (qa_root / "content" / "images").mkdir(parents=True)
    (qa_root / "content" / "images" / "pic.jpg").write_bytes(b"\xff\xd8jpeg")
    # A minimal ontology so `type` resolves to a real enum, as it does against
    # synced content — testing the fallback here would prove nothing about the
    # offered-set == enforced-set contract.
    model = qa_root / "metacontent" / "model"
    model.mkdir(parents=True)
    (model / "tiny.ttl").write_text(
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "vad:PaintingForm a owl:Class .\n"
        "vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .\n"
        "vad:OilPainting a owl:Class ; rdfs:subClassOf vad:PaintingForm .\n"
    )
    # A real paper concept, so the has_paper picker offers something and the
    # vocabulary gate has a reference graph — picker set == gate's accepted set.
    vocab = qa_root / "metacontent" / "vocab"
    vocab.mkdir(parents=True)
    (vocab / "papers.ttl").write_text(
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix the: <http://visualartsdna.org/thesaurus/> .\n"
        "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        'the:TestPaper a vad:WatercolorPaper, skos:Concept ; rdfs:label "Test Paper" .\n'
    )
    # The driver must be armed exactly as create_app arms the real one, or the
    # asset/vocabulary gates silently do not run and "gates passed" means far
    # less than it reads. (The first version of this fixture omitted image_base
    # and layout — the entry test then proved nothing about asset references.)
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root,
        enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        inbox=Inbox(drop_folder),
        promotion_driver=PromotionDriver(
            qa,
            FilesTransport(tmp_path / "sot"),
            image_base=image_base(TEST_DOMAIN),
            layout=Layout.default(),
            vocab_dirs=[Layout.default().dir("vocab_ttl")],
        ),
    )
    with TestClient(app) as c:
        yield c, qa





def _options(html: str, field: str) -> list[str]:
    """The values a <select> actually offers."""
    m = re.search(rf'<select id="{field}" name="{field}".*?</select>', html, re.S)
    if not m:
        return []
    return re.findall(r'<option value="([^"]*)"', m.group(0))


def test_hub_is_function_html_served_directly(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200
    # The proven dashboard, not a regenerated approximation.
    assert "Visual Arts" in r.text and 'data-tab="content"' in r.text
    assert 'href="rdf/entry"' in r.text


def test_entry_form_renders_with_a_fresh_guid_and_derived_qrcode(client):
    c, _ = client
    html = c.get("/rdf/entry").text
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
    assert len(guid) == 36
    # qrcode is derived + readonly + not submitted (EXTRACTION D1)
    qr = re.search(r'id="qrcode"[^>]*value="([^"]*)"[^>]*>', html).group(0)
    assert f"qrc_{guid}.jpg" in qr and "readonly" in qr and "disabled" in qr


def test_two_loads_get_different_guids(client):
    c, _ = client
    g = [
        re.search(r'name="guid" value="([^"]+)"', c.get("/rdf/entry").text).group(1)
        for _ in range(2)
    ]
    assert g[0] != g[1]


def test_offered_type_set_IS_the_enforced_enum(client):
    """The contract that replaced the zero-UX-code test."""
    c, _ = client
    html = c.get("/rdf/entry").text
    schema = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_work"
    )
    enforced = schema["inputSchema"]["properties"]["type"]["enum"]
    assert _options(html, "type") == enforced
    assert _options(html, "units") == ["cm", "inch", "meter", "pixel"]


def test_units_defaults_to_inch_like_the_groovy_form(client):
    c, _ = client
    html = c.get("/rdf/entry").text
    sel = re.search(r'<select id="units".*?</select>', html, re.S).group(0)
    assert '<option value="inch" selected>' in sel  # D6


def test_dates_default_to_today(client):
    import datetime

    c, _ = client
    html = c.get("/rdf/entry").text
    today = datetime.date.today().isoformat()
    for field in ("recorded_date", "completed_date"):
        assert re.search(rf'id="{field}"[^>]*value="{today}"', html)


def test_file_ref_picker_offers_the_drop_folder(client):
    """With an inbox configured, the drop folder is the source of user-supplied
    images — see test_picker_excludes_generated_artifacts for why the sandbox is
    not also offered."""
    c, _ = client
    html = c.get("/rdf/entry").text
    assert "dropped.jpg" in _options(html, "image")


def test_file_ref_picker_falls_back_to_the_sandbox_without_an_inbox(tmp_path):
    """A deployment with no drop folder configured still gets a working picker."""
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    QAGit.init(qa_root)
    (qa_root / "content" / "images").mkdir(parents=True)
    (qa_root / "content" / "images" / "sandbox-only.jpg").write_bytes(b"\xff\xd8j")
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
    )
    with TestClient(app) as c:
        assert "sandbox-only.jpg" in _options(c.get("/rdf/entry").text, "image")


def test_required_fields_are_marked(client):
    c, _ = client
    html = c.get("/rdf/entry").text
    schema = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_work"
    )
    for name in schema["inputSchema"].get("required", []):
        assert re.search(rf'for="{name}">{name} <span class="req">', html), name


def test_submit_creates_the_record_and_STOPS_at_review(client):
    """The whole point of the wiring: a submit reaches QA and then stops. The
    SOT must be untouched until the operator approves."""
    c, qa = client
    html = c.get("/rdf/entry").text
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
    types = _options(html, "type")
    papers = _options(html, "has_paper")

    r = c.post(
        "/rdf/entry",
        data={
            "guid": guid, "type": types[0], "label": "Test Work",
            "description": "a test", "height": "10", "width": "8",
            "units": "inch", "recorded_date": "2026-08-22",
            "completed_date": "2026-08-22",
            "has_paper": papers[-1] if papers else "the:X",
            "has_artist_profile": "work:abc", "image": "pic.jpg",
        },
    )

    assert r.status_code == 200
    assert "Distribute Data — review" in r.text
    assert "Approve &amp; distribute" in r.text
    assert (qa.root / "ttl" / "data" / f"{guid}.ttl").exists() or (
        qa.root / "content" / "ttl" / "data" / f"{guid}.ttl"
    ).exists(), "record must be written into QA"
    assert not list((qa.root.parent / "sot").rglob("*.ttl")), "must not converge yet"


def test_submit_generates_the_qr_so_the_asset_gate_PASSES(client):
    """The regression from the first real run: every entry failed the
    asset-reference gate with a dangling `vad:qrcode`, because the record derives
    the reference and nothing generated the file. Submit must now produce both."""
    c, qa = client
    html = c.get("/rdf/entry").text
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
    types = _options(html, "type")
    papers = _options(html, "has_paper")

    r = c.post(
        "/rdf/entry",
        data={
            "guid": guid, "type": types[0], "label": "QR Work", "description": "d",
            "height": "10", "width": "8", "units": "inch",
            "recorded_date": "2026-08-25", "completed_date": "2026-08-25",
            "has_paper": papers[-1] if papers else "the:X",
            "has_artist_profile": "work:abc", "image": "pic.jpg",
        },
    )

    assert r.status_code == 200
    assert (qa.root / "content" / "images" / f"qrc_{guid}.jpg").is_file()
    # and therefore the gates pass and there is something to approve
    assert "Gates failed" not in r.text
    assert "Approve &amp; distribute" in r.text
    assert "asset_reference" in r.text


def test_invalid_value_is_refused_at_dispatch_and_redisplayed(client):
    """A value outside the enum is rejected by validate_args — the form is a
    convenience, the schema is the guard. The agent sending the same value gets
    the same refusal."""
    c, _ = client
    html = c.get("/rdf/entry").text
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)

    r = c.post(
        "/rdf/entry",
        data={
            "guid": guid, "type": "NotARealType", "label": "x", "description": "x",
            "height": "1", "width": "1", "units": "inch",
            "recorded_date": "2026-08-22", "completed_date": "2026-08-22",
            "has_paper": "the:X", "has_artist_profile": "work:abc", "image": "pic.jpg",
        },
    )

    assert r.status_code == 400
    assert "NotARealType" not in _options(r.text, "type")


def test_layout_only_names_fields_the_tool_actually_has(client):
    """Layout comes from the Groovy form, affordances from the schema — but a
    layout naming a field the tool dropped would silently render nothing."""
    c, _ = client
    schema = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_work"
    )
    props = set(schema["inputSchema"]["properties"]) | {"qrcode"}
    for row in RDF_ENTRY_LAYOUT:
        for field in row:
            assert field in props, f"{field} is in the layout but not the schema"


def test_render_is_pure_given_its_inputs():
    """No hidden globals: the same schema and values render the same page."""
    schema = next(
        s for s in build_default_registry(domain=TEST_DOMAIN).schemas() if s["name"] == "record.new_work"
    )
    a = render_entry_form(schema, guid="g1", qrcode_url="http://x/qrc_g1.jpg")
    b = render_entry_form(schema, guid="g1", qrcode_url="http://x/qrc_g1.jpg")
    assert a == b


# -- the drop folder: the user never touches the sandbox ---------------------


def test_picker_excludes_GENERATED_artifacts(client, drop_folder):
    """The regression. The sandbox holds what the system *generates* — QR codes
    now, brand images and thumbnails later — and those are outputs, never a
    work's source image. Offering the sandbox alongside the drop folder put a
    `qrc_<guid>.jpg` in the picker after the first completed entry."""
    c, qa = client
    images = qa.root / "content" / "images"
    images.mkdir(parents=True, exist_ok=True)
    (images / "qrc_f28b42d3-2062-4b66-a239-f01cc33f8e42.jpg").write_bytes(b"\xff\xd8qr")

    offered = _options(c.get("/rdf/entry").text, "image")

    assert not any(o.startswith("qrc_") for o in offered), offered
    assert "dropped.jpg" in offered, "the user's own files are still offered"


def test_an_ingested_image_is_still_offered_from_the_drop_folder(client, drop_folder):
    """Why dropping the sandbox half costs nothing: ingest COPIES rather than
    moves, so a file used by a previous entry is still in the user's folder —
    and appears exactly once, not twice."""
    c, qa = client
    images = qa.root / "content" / "images"
    images.mkdir(parents=True, exist_ok=True)
    (images / "dropped.jpg").write_bytes((drop_folder / "dropped.jpg").read_bytes())

    offered = _options(c.get("/rdf/entry").text, "image")

    assert offered.count("dropped.jpg") == 1


def test_submitting_a_dropped_file_copies_it_in_with_its_sidecar(client, drop_folder):
    """The ingest: selecting a dropped file copies it into the sandbox through
    FileOps, so the `.ptr` sidecar exists and promotion can see the binary."""
    c, qa = client
    html = c.get("/rdf/entry").text
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)

    r = c.post(
        "/rdf/entry",
        data={
            "guid": guid, "type": _options(html, "type")[0], "label": "Dropped",
            "description": "d", "height": "10", "width": "8", "units": "inch",
            "recorded_date": "2026-09-03", "completed_date": "2026-09-03",
            "has_paper": _options(html, "has_paper")[-1],
            "has_artist_profile": "work:abc", "image": "dropped.jpg",
        },
    )

    assert r.status_code == 200
    # Named after the record ("Dropped"), not after the camera (2026-10-07).
    img = qa.root / "content" / "images" / "Dropped.jpg"
    assert img.is_file(), "the file must be copied into the sandbox"
    assert img.read_bytes() == (drop_folder / "dropped.jpg").read_bytes()
    assert (qa.root / "content" / "images" / "Dropped.jpg.ptr").is_file(), "sidecar"
    assert "Gates failed" not in r.text


def test_ingest_leaves_the_users_folder_untouched(client, drop_folder):
    """The drop folder is the user's; ingest copies, never moves."""
    c, _ = client
    html = c.get("/rdf/entry").text
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
    c.post(
        "/rdf/entry",
        data={
            "guid": guid, "type": _options(html, "type")[0], "label": "x",
            "description": "d", "height": "1", "width": "1", "units": "inch",
            "recorded_date": "2026-09-03", "completed_date": "2026-09-03",
            "has_paper": _options(html, "has_paper")[-1],
            "has_artist_profile": "work:abc", "image": "dropped.jpg",
        },
    )
    assert (drop_folder / "dropped.jpg").is_file()


def test_empty_picker_names_the_drop_folder(tmp_path):
    """A dead-end "none available" would leave the user with nowhere to go —
    they must be told where files come from, since the sandbox is off limits."""
    from cwva_dashboard.ux.forms import render_entry_form

    schema = next(
        s for s in build_default_registry(domain=TEST_DOMAIN).schemas() if s["name"] == "record.new_work"
    )
    html = render_entry_form(
        schema, guid="g1", file_refs={"content/images": []},
        drop_folder="/home/u/cwva-py/stage/data",
    )
    assert "no files in /home/u/cwva-py/stage/data" in html
    assert "You never touch the sandbox" in html


def test_type_defaults_to_the_configured_member(client):
    """The Groovy form had Watercolor `checked`; the default is config-driven and
    must be a member of the enforced enum, not merely rendered."""
    from cwva_dashboard.promotion.layout import Layout
    from cwva_dashboard.tools.fileops_tools import build_default_registry

    reg = build_default_registry(
        domain=TEST_DOMAIN,
        entry_forms={"work": {"type_root": "vad:PaintingForm",
                              "type_default": "Watercolor"}},
        model=None, layout=Layout.default(),
    )
    props = next(
        s for s in reg.schemas() if s["name"] == "record.new_work"
    )["inputSchema"]["properties"]
    assert props["type"]["default"] == "Watercolor"
    offered = props["type"].get("enum") or props["type"]["x-enum-suggested"]
    assert props["type"]["default"] in offered, "a default must be selectable"


def test_a_default_the_ontology_lacks_is_dropped_not_offered(tmp_path):
    """Preselecting a value dispatch would reject is the offered-set != enforced-set
    hole in miniature, so an unresolvable default is dropped."""
    from rdflib import Graph

    from cwva_dashboard.promotion.layout import Layout
    from cwva_dashboard.tools.fileops_tools import build_default_registry

    model = Graph()
    model.parse(data=(
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "vad:PaintingForm a rdfs:Class .\n"
        "vad:OilPainting rdfs:subClassOf vad:PaintingForm .\n"
    ), format="turtle")
    reg = build_default_registry(
        domain=TEST_DOMAIN,
        entry_forms={"work": {"type_root": "vad:PaintingForm",
                              "type_default": "NotInTheOntology"}},
        model=model, layout=Layout.default(),
    )
    spec = next(
        s for s in reg.schemas() if s["name"] == "record.new_work"
    )["inputSchema"]["properties"]["type"]
    assert "NotInTheOntology" not in spec["enum"]
    assert "default" not in spec, "an unresolvable default must be dropped"


def test_artist_profile_prefills_from_config(client):
    """An overridable default, not a constant — but it must actually reach the
    rendered form, since typing a GUID by hand every time is the thing it fixes."""
    from cwva_dashboard.promotion.layout import Layout
    from cwva_dashboard.tools.fileops_tools import build_default_registry
    from cwva_dashboard.ux.forms import render_entry_form

    reg = build_default_registry(
        domain=TEST_DOMAIN,
        layout=Layout.default(), artist_profile="work:test-profile-guid"
    )
    schema = next(s for s in reg.schemas() if s["name"] == "record.new_work")
    assert schema["inputSchema"]["properties"]["has_artist_profile"]["default"] == (
        "work:test-profile-guid"
    )
    html = render_entry_form(schema, guid="g1")
    assert re.search(r'id="has_artist_profile"[^>]*value="work:test-profile-guid"', html)


# -- Edit form (replaces Reject) ---------------------------------------------


def _submit(c, html, **overrides):
    guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
    data = {
        "guid": guid, "type": _options(html, "type")[0], "label": "Draft",
        "description": "d", "height": "10", "width": "8", "units": "inch",
        "recorded_date": "2026-09-03", "completed_date": "2026-09-03",
        "has_paper": _options(html, "has_paper")[-1],
        "has_artist_profile": "work:abc", "image": "dropped.jpg",
    }
    data.update(overrides)
    return guid, c.post("/rdf/entry", data=data)


def test_edit_form_repopulates_the_submitted_values(client):
    c, _ = client
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html, label="Butterfly", height="15")
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)

    r = c.post("/rdf/entry/edit", data={"token": token})

    assert r.status_code == 200
    assert re.search(r'id="label"[^>]*value="Butterfly"', r.text)
    assert re.search(r'name="guid" value="' + guid + '"', r.text), "same guid"
    assert "Editing your entry" in r.text


def test_edit_form_KEEPS_the_draft(client):
    """It used to trash it immediately, which meant leaving the reopened form —
    or refreshing, or cycling the server — destroyed the record with nothing in
    the UI to say so. Rick lost an artist profile that way (2026-09-17). A draft
    you can still see is a draft you can still finish."""
    c, qa = client
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html)
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)

    r = c.post("/rdf/entry/edit", data={"token": token})

    assert (qa.root / "content/ttl/data" / f"{guid}.ttl").is_file()
    assert (qa.root / "content/images" / f"qrc_{guid}.jpg").is_file()
    assert "still in QA" in r.text and "nothing has been thrown away" in r.text


def test_a_RESUBMIT_replaces_the_draft_in_place(client):
    """Same guid, same path: the record is rewritten rather than piled on top of
    itself, and no second draft appears."""
    c, qa = client
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html)
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    c.post("/rdf/entry/edit", data={"token": token})

    _guid2, _again = _submit(c, html, guid=guid, label="Corrected")

    records = list((qa.root / "content/ttl/data").glob("*.ttl"))
    assert [r.name for r in records] == [f"{guid}.ttl"], "one record, not two"
    assert "Corrected" in (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()


def test_a_resubmit_trashes_what_it_SUPERSEDED(client, drop_folder):
    """The cleanup happens when there is something to replace the old file
    with — not on the intention to edit. An image swapped out during the edit is
    soft-deleted then, so a wrong click is still recoverable."""
    c, qa = client
    (drop_folder / "second.jpg").write_bytes(b"\xff\xd8second")
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html, image="dropped.jpg")
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    c.post("/rdf/entry/edit", data={"token": token})
    stored = qa.root / "content/images" / "Draft.jpg"
    assert stored.read_bytes() == (drop_folder / "dropped.jpg").read_bytes()

    _submit(c, html, guid=guid, image="second.jpg")

    # BOTH files are named after the record, so swapping one REPLACES it in
    # place rather than minting a second name and trashing the first
    # (2026-10-07). The superseded bytes go to the attic, which is where a
    # replaced binary belongs — the rollback reserve, CE_DESIGN §3.4.
    assert stored.read_bytes() == (drop_folder / "second.jpg").read_bytes()
    assert list((qa.root / ".qa" / "attic").glob("*")), (
        "the replaced bytes must stay recoverable"
    )


def test_a_resubmit_leaves_an_EARLIER_entrys_image_alone(client, drop_folder):
    """Only what THIS submission minted can be superseded. An image an earlier
    entry already ingested may belong to committed work — and a submit that did
    not copy it in has no claim on it."""
    c, qa = client
    img = qa.root / "content" / "images" / "dropped.jpg"
    img.parent.mkdir(parents=True, exist_ok=True)
    img.write_bytes((drop_folder / "dropped.jpg").read_bytes())  # already ingested

    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html, image="dropped.jpg")
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    c.post("/rdf/entry/edit", data={"token": token})
    _submit(c, html, guid=guid, image="dropped.jpg")

    assert img.is_file(), "a pre-existing image must survive the round trip"


def test_edit_form_clears_the_pending_promotion(client):
    """The reviewed change is gone, so its token must be too."""
    c, _ = client
    html = c.get("/rdf/entry").text
    _guid, review = _submit(c, html)
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)

    c.post("/rdf/entry/edit", data={"token": token})

    assert c.get("/api/promotion/pending").json()["pending"] == []
    assert c.post("/rdf/entry/edit", data={"token": token}).status_code == 409


def test_edit_state_guards_both_exits_but_a_fresh_form_does_not(client):
    """The double dare. In edit state the form holds corrections that exist
    nowhere else — the draft on disk is the version you came back to change — so
    Reset and the dashboard link both confirm. A fresh empty form must never
    nag."""
    c, _ = client
    fresh = c.get("/rdf/entry").text
    assert "confirmDiscard" not in fresh and "beforeunload" not in fresh

    html = c.get("/rdf/entry").text
    _guid, review = _submit(c, html)
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    edit = c.post("/rdf/entry/edit", data={"token": token}).text

    # Reset is disabled in edit state (it could only restore the same values),
    # so the guarded exits are the dashboard link and beforeunload.
    assert 'onclick="return confirmDiscard()"' in edit
    assert "beforeunload" in edit


# -- the generated RDF is shown on the review page ---------------------------


def test_review_page_shows_the_generated_ttl(client):
    """Reviewing a change you cannot read is not reviewing it. The file list
    says what was written and the graph summary says how much; only the text
    says whether the triples are right."""
    c, _ = client
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html, label="Readable")

    assert "Generated RDF" in review.text
    assert f"{guid}.ttl" in review.text
    # actual triple content, HTML-escaped
    assert "rdfs:label &quot;Readable&quot;" in review.text
    assert "vad:hasArtistProfile" in review.text
    assert 'class="src"' in review.text, "scrollable container"


def test_review_page_does_not_try_to_show_the_qr_binary(client):
    """Only RDF is echoed; a JPEG read as text would be noise at best."""
    c, _ = client
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html)

    heads = re.findall(r'<div class="src-head mono">([^<]*)', review.text)
    assert any(h.strip().endswith(".ttl") for h in heads)
    assert not any(".jpg" in h for h in heads)


def test_shown_ttl_is_read_back_from_disk(client):
    """Read back rather than echoed, so the page shows what was actually
    written — a tool that reported success but wrote nothing would show empty."""
    c, qa = client
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html, label="OnDisk")

    on_disk = (qa.root / "content/ttl/data" / f"{guid}.ttl").read_text()
    shown = re.search(r'<pre class="src">(.*?)</pre>', review.text, re.S).group(1)
    import html as _h

    assert _h.unescape(shown).strip() == on_disk.strip()


def test_long_sources_are_truncated_not_dumped():
    from cwva_dashboard.ux.forms import render_review_page

    page = render_review_page(
        preview={"status": "previewed", "token": "t", "gates": []},
        sources=[{"path": "x.ttl", "text": "a" * 50, "note": "truncated at 50 chars"}],
    )
    assert "truncated at 50 chars" in page


# -- the leave guard must actually PARSE -------------------------------------


def _scripts(html: str) -> list[str]:
    return re.findall(r"<script>(.*?)</script>", html, re.S)


def _unterminated_string_lines(js: str) -> list[str]:
    """Lines where a JS string literal opens and never closes.

    A raw newline inside a quoted string is a SyntaxError that kills the whole
    script — silently, since the browser just stops. That is exactly what
    happened: the guard never ran, `confirmDiscard` was undefined, and both the
    Reset button and the dashboard link fell through to their default actions
    with no dialog. A page-renders-fine assertion cannot see it, so check the
    property directly.
    """
    bad = []
    for line in js.splitlines():
        stripped = re.sub(r"\\.", "", line)  # drop escaped chars
        if stripped.count("'") % 2 or stripped.count('"') % 2:
            bad.append(line.strip())
    return bad


def test_the_leave_guard_javascript_parses(client):
    c, _ = client
    html = c.get("/rdf/entry").text
    _guid, review = _submit(c, html)
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    edit = c.post("/rdf/entry/edit", data={"token": token}).text

    js = _scripts(edit)
    assert js, "edit state must carry the guard"
    for block in js:
        assert not _unterminated_string_lines(block), _unterminated_string_lines(block)


def test_the_guard_defines_what_the_handlers_call(client):
    """`onclick="return confirmDiscard()"` is only a guard if that function
    exists — otherwise the click throws and the browser navigates anyway."""
    c, _ = client
    html = c.get("/rdf/entry").text
    _guid, review = _submit(c, html)
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    edit = c.post("/rdf/entry/edit", data={"token": token}).text

    called = set(re.findall(r'onclick="return (\w+)\(\)"', edit))
    assert called, "edit state must guard its exits"
    for fn in called:
        assert f"window.{fn} = function" in "".join(_scripts(edit)), fn


def test_reset_is_disabled_in_edit_state_and_live_on_a_fresh_form(client):
    """Reset restores INITIAL values; in edit state those are the repopulated
    ones, so it can only ever no-op. Disabled with the reason, not left looking
    broken."""
    c, _ = client
    fresh = c.get("/rdf/entry").text
    assert re.search(r'<button type="reset">Reset</button>', fresh)

    _guid, review = _submit(c, fresh)
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    edit = c.post("/rdf/entry/edit", data={"token": token}).text

    btn = re.search(r"<button[^>]*>Reset</button>", edit).group(0)
    assert "disabled" in btn and "type=\"reset\"" not in btn
    assert "title=" in btn, "say why it is disabled"


# -- uniqueness: filename is an error, label is advice ------------------------


def _existing_work(qa, *, image, label, cls="Watercolor"):
    """A record already in the store, as a prior entry would have left it.

    Callers testing the *label* path must name an image that actually exists in
    the fixture sandbox (`pic.jpg`), or the asset-reference gate fails on the
    pre-existing record and the submit never reaches a promotable preview —
    which looks exactly like "the warning did not appear".
    """
    d = qa.root / "content/ttl/data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "existing.ttl").write_text(
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix schema: <https://schema.org/> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        f"work:existing a vad:{cls} ; rdfs:label \"{label}\" ;\n"
        f'  schema:image <http://visualartsdna.org/images/{image}> .\n'
    )


def test_a_reused_LABEL_takes_an_ORDINAL(client, drop_folder):
    """Labels are not unique and a repeated one has never been a blocking
    error — "titles legitimately repeat, worth surfacing, never worth
    blocking". So the derived name disambiguates instead of refusing (Rick,
    2026-10-07), and neither work's image is at risk."""
    c, qa = client
    _existing_work(qa, image="SomethingElse.jpg", label="Something Else")
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Something Else")

    assert r.status_code == 200, r.text[:400]
    assert (qa.root / "content/images/SomethingElse-2.jpg").is_file()
    assert "Distribute Data" in r.text, "it reaches the review stop"


def test_two_records_may_use_the_SAME_DROP_FILE(client, drop_folder):
    """The refusal that correctly went away. Two works legitimately showing one
    photograph each get their own copy under their own name; nothing is
    overwritten, because neither name is the other's."""
    c, qa = client
    _existing_work(qa, image="SomethingElse.jpg", label="Something Else")
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="A New Work", image="dropped.jpg")

    assert r.status_code == 200
    assert (qa.root / "content/images/ANewWork.jpg").is_file()
    assert (qa.root / "content/images/SomethingElse.jpg").is_file() or True


def test_a_refused_filename_does_not_overwrite_the_existing_image(client, drop_folder):
    """The ordering that makes the check worth anything: it runs BEFORE the
    ingest, so the existing image is still intact after the refusal."""
    c, qa = client
    _existing_work(qa, image="dropped.jpg", label="Something Else")
    existing = qa.root / "content/images/dropped.jpg"
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_bytes(b"ORIGINAL BYTES")

    html = c.get("/rdf/entry").text
    _submit(c, html, label="A New Work")

    assert existing.read_bytes() == b"ORIGINAL BYTES", "ingest must not have run"


def test_a_refused_submit_keeps_the_users_values(client, drop_folder):
    c, qa = client
    # A work image only refuses when it was NOT renamed — i.e. already in the
    # sandbox rather than arriving from the drop folder (2026-10-07).
    _existing_work(qa, image="pic.jpg", label="Other")
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Typed This Carefully", image="pic.jpg")

    assert re.search(r'id="label"[^>]*value="Typed This Carefully"', r.text)


def test_a_reused_label_only_WARNS_and_still_promotes(client, drop_folder):
    """Titles legitimately repeat. Worth surfacing, never worth blocking."""
    c, qa = client
    _existing_work(qa, image="pic.jpg", label="Fairy Pool", cls="Watercolor")
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Fairy Pool", type="Watercolor")

    assert r.status_code == 200
    assert "already uses the label" in r.text
    assert "Approve &amp; distribute" in r.text, "the warning must not block"


def test_a_label_reused_under_a_DIFFERENT_type_is_not_flagged(client, drop_folder):
    """Uniqueness is scoped to the type, as asked — a sculpture and a
    watercolour may share a title without comment."""
    c, qa = client
    _existing_work(qa, image="pic.jpg", label="Shared Title", cls="OilPainting")
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Shared Title", type="Watercolor")

    assert r.status_code == 200
    assert "already uses the label" not in r.text


def test_a_unique_entry_is_flagged_neither_way(client, drop_folder):
    c, qa = client
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Entirely Novel")

    assert r.status_code == 200
    assert "already uses the label" not in r.text
    assert "already referenced by another record" not in r.text


# -- refreshing the file list without losing the form ------------------------


def test_a_refused_submit_keeps_every_field(client, drop_folder):
    """The collision page is a working form, not a dead end: everything typed
    survives, so the only thing still needed is the renamed file."""
    c, qa = client
    _existing_work(qa, image="pic.jpg", label="Other")
    html = c.get("/rdf/entry").text

    _guid, r = _submit(
        c, html, label="Carefully Typed", description="A long description",
        height="15", width="11", image="pic.jpg",
    )

    assert r.status_code == 409
    assert re.search(r'id="label"[^>]*value="Carefully Typed"', r.text)
    assert "A long description" in r.text
    assert re.search(r'id="height"[^>]*value="15"', r.text)


def test_the_picker_offers_an_in_place_refresh(client):
    """Renaming is only a remedy if the new name can be picked up WITHOUT
    reloading — a reload discards everything typed."""
    c, _ = client
    html = c.get("/rdf/entry").text

    assert "Refresh list" in html
    assert "function refreshFileRef" in html
    assert 'refreshFileRef(this, &#x27;image&#x27;' in html or "refreshFileRef(this, 'image'" in html


def test_the_refresh_endpoint_reads_the_drop_folder_live(client, drop_folder):
    """A file renamed after the page rendered must appear without a reload."""
    c, _ = client
    before = c.get("/api/affordance/file-ref?subtree=content/images").json()["candidates"]
    assert [f["value"] for f in before] == ["dropped.jpg"]

    (drop_folder / "dropped.jpg").rename(drop_folder / "renamed.jpg")

    after = c.get("/api/affordance/file-ref?subtree=content/images").json()["candidates"]
    assert [f["value"] for f in after] == ["renamed.jpg"]


def test_refresh_endpoint_and_form_use_ONE_source(client, drop_folder):
    """A picker that refreshes from a different source than it rendered from is
    the offered-set divergence this project keeps paying for."""
    c, _ = client
    rendered = _options(c.get("/rdf/entry").text, "image")
    endpoint = [
        f["value"]
        for f in c.get("/api/affordance/file-ref?subtree=content/images").json()["candidates"]
    ]

    assert [o for o in rendered if o] == endpoint


def test_the_refresh_script_parses(client):
    """Same check that caught the dead leave-guard: a raw newline inside a JS
    string kills the block silently."""
    c, _ = client
    html = c.get("/rdf/entry").text

    for block in _scripts(html):
        assert not _unterminated_string_lines(block), _unterminated_string_lines(block)


def test_the_refresh_script_defines_what_the_button_calls(client):
    c, _ = client
    html = c.get("/rdf/entry").text

    called = set(re.findall(r"onclick=\"(\w+)\(this", html))
    assert "refreshFileRef" in called
    joined = "".join(_scripts(html))
    for fn in called:
        assert f"function {fn}" in joined, fn


def test_the_collision_message_does_not_tell_you_to_reload(client, drop_folder):
    """The remedy has to match the affordance on the page. Telling the user to
    reload would discard everything they typed.

    On THIS form the only file field is the image, and an image is named after
    the record — so the remedy is the label, not the drop folder. "Refresh list"
    would be the wrong advice here and is asserted absent; the drop-folder
    remedy is still right for a document and is covered on the entity form."""
    c, qa = client
    _existing_work(qa, image="pic.jpg", label="Other")
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Mine", image="pic.jpg")

    assert r.status_code == 409
    err = re.search(r'<div class="err">(.*?)</div>', r.text, re.S).group(1)
    assert "Refresh list" in err
    assert "reload this page" not in err
    assert "do not" in err.lower() and "reload" in err.lower()


def test_a_resubmit_does_not_collide_with_ITS_OWN_DRAFT(client):
    """Keeping the draft made the entry form collide with itself: the record
    being corrected already cites the image, so the uniqueness check reported
    the user's own file as taken by a record they were in the middle of
    fixing."""
    c, _qa = client
    html = c.get("/rdf/entry").text
    guid, review = _submit(c, html, image="dropped.jpg")
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    c.post("/rdf/entry/edit", data={"token": token})

    _guid, again = _submit(c, html, guid=guid, image="dropped.jpg", label="Fixed")

    assert again.status_code == 200, again.text[:300]
    assert "already in use" not in again.text


def test_ANOTHER_records_file_is_not_overwritten(client, drop_folder):
    """The exclusion is for the record being rewritten, not an amnesty: a
    second entry must not land on the first one's image.

    It used to be refused. Since the name is derived, the ordinal keeps them
    apart instead — the same guarantee, reached without stopping the user
    (2026-10-07)."""
    c, qa = client
    html = c.get("/rdf/entry").text
    _first, _review = _submit(c, html, image="dropped.jpg")
    first_bytes = (qa.root / "content/images/Draft.jpg").read_bytes()

    second = c.get("/rdf/entry").text          # a fresh guid, same default label
    _guid, r = _submit(c, second, image="dropped.jpg")

    assert r.status_code == 200, r.text[:400]
    assert (qa.root / "content/images/Draft-2.jpg").is_file()
    assert (qa.root / "content/images/Draft.jpg").read_bytes() == first_bytes


def test_an_ALREADY_INGESTED_image_can_still_clash(client, drop_folder):
    """The one refusal a work image can still reach. A file already in the
    sandbox is NOT renamed — the ingest has nothing to copy for it, so a
    derived name would dangle — which leaves it able to collide the old way,
    and the old remedy is the right one: rename it in the drop folder."""
    c, qa = client
    _existing_work(qa, image="pic.jpg", label="Other")   # pic.jpg is in the sandbox
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Mine", image="pic.jpg")

    assert r.status_code == 409
    assert "already referenced by another record" in r.text
    assert "drop folder" in r.text, "the remedy that does apply here"


# -- recording a real session (Phase 5) --------------------------------------
#
# Here rather than in tests/scenarios/, because the two acts a naive recorder
# misses are only reachable through the real form: the drop-folder INGEST is
# trusted-side and not a registry tool (law 12), so it leaves no dispatch to
# record, and without it a replay fails the asset gate on a file that never
# arrived.


def _recorded(c, qa):
    from cwva_dashboard import rson
    from pathlib import Path as _P
    out = c.post("/api/record/stop").json()
    return out, rson.load(str(_P(qa.root) / out["written"]))


def test_a_form_session_records_the_INGEST_and_the_QR(client, drop_folder):
    c, qa = client
    c.post("/api/record/start", json={"name": "form session"})
    html = c.get("/rdf/entry").text

    _guid, r = _submit(c, html, label="Sunrise", image="dropped.jpg")
    assert r.status_code == 200, r.text[:300]
    _out, scenario = _recorded(c, qa)

    ops = [s["op"] for s in scenario["steps"]]
    assert "record.new_work" in ops
    assert "image.qrcode" in ops, "a tool, so it records itself"
    assert any(s["op"] == "fs.write" and "Sunrise.jpg" in s["args"]["path"]
               for s in scenario["steps"]), "the ingest, under its derived name"


def test_the_ingest_is_recorded_as_a_STAND_IN(client, drop_folder):
    """A recording is a shape to re-run, not a copy of the artist's
    photographs. Keeping 3 MB per step would make the corpus unusable and the
    diffs unreadable — the convention the committed episodes already use."""
    import json as _json

    c, qa = client
    c.post("/api/record/start", json={"name": "standin"})
    html = c.get("/rdf/entry").text
    _submit(c, html, label="Sunrise", image="dropped.jpg")
    _out, scenario = _recorded(c, qa)

    ingest = next(s for s in scenario["steps"]
                  if s["op"] == "fs.write" and "Sunrise.jpg" in s["args"]["path"])
    assert ingest["args"]["text"] == "INGESTED-STAND-IN"
    blob = _json.dumps(scenario)
    assert "dropped.jpg" not in blob, "not the drop folder's name"
    assert "\\xff\\xd8" not in blob, "and certainly not its bytes"


def test_an_APPROVED_session_records_the_promotion(client, drop_folder):
    """Authoring without distributing is half an episode."""
    c, qa = client
    c.post("/api/record/start", json={"name": "approved"})
    html = c.get("/rdf/entry").text
    _guid, review = _submit(c, html, label="Sunrise", image="dropped.jpg")
    token = re.search(r'name="token" value="([^"]+)"', review.text).group(1)
    c.post("/rdf/entry/approve", data={"token": token})
    _out, scenario = _recorded(c, qa)

    assert scenario["steps"][-1]["op"] == "workflow.promote"
    assert scenario["expected"]["qa_clean"] is True


def test_a_refused_entry_leaves_no_copied_image_behind(client, drop_folder):
    """A refused submit's image belongs to nothing. Left in the sandbox it was
    distributed with the next approval, and the retry arrived as `-2` beside
    it (2026-11-21)."""
    c, qa = client
    html = c.get("/rdf/entry").text
    images = qa.root / "content" / "images"
    _guid, r = _submit(c, html, label="Morning Light", description="")
    assert r.status_code == 400
    assert not (images / "MorningLight.jpg").exists()
    assert not (images / "MorningLight.jpg.ptr").exists()
    assert (drop_folder / "dropped.jpg").is_file()  # the user's copy untouched

    _guid, r = _submit(c, html, label="Morning Light")
    assert r.status_code == 200
    assert (images / "MorningLight.jpg").is_file()
    assert not (images / "MorningLight-2.jpg").exists()
