"""The workflow board page (/workflows), its tick, and its hub card."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout

LAYOUT = Layout.default()
W1 = "http://visualartsdna.org/work/w1"

WORK = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .
work:w1 a vad:CreativeWork, vad:Watercolor ; rdfs:label "Lepers' Hearth" ;
    vad:hasPaper the:Fabriano ; schema:image <http://visualartsdna.org/images/L.jpg> ;
    schema:dateCreated "2026-11-04"^^xs:date .
"""

PROVENANCE = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:p1 a vad:Provenance ; vad:hasArtwork work:w1 ; vad:dispositionId "2026.223" .
"""


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    for kind, name, text in (("work_ttl", "w1.ttl", WORK),
                             ("provenance_ttl", "p1.ttl", PROVENANCE)):
        d = root / LAYOUT.dir(kind)
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(text)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


def _cell(page: str, step_label: str) -> str:
    m = re.search(r'<td class="cell ([^"]*)" title="' + re.escape(step_label) + r'\b', page)
    assert m, step_label
    return m.group(1)


def test_the_hub_card_counts_what_is_in_flight(client):
    hub = client.get("/").text
    card = re.search(r'<a href="workflows"[^>]*>.*?</a>', hub, re.S).group(0)
    assert "1 work in flight" in card
    assert "idle over 7 days" in card  # entered 11-04, nothing since


def test_the_page_shows_the_work_its_di_and_where_it_goes_next(client):
    page = client.get("/workflows").text
    assert "Lepers&#x27; Hearth" in page or "Lepers' Hearth" in page
    assert "2026.223" in page
    assert _cell(page, "Entry").startswith("done")
    assert _cell(page, "Annotate").startswith("ready")
    assert _cell(page, "On site").startswith("blocked")
    assert "next <b>Website, Annotate, Criticism</b>" in page
    # the ready step that has a page of its own links to it
    assert 'href="/annotate"' in page
    # the name opens the record
    assert "/edit/open?path=" in page


def test_ticking_the_website_unblocks_on_site_and_can_be_undone(client):
    assert 'data-step="website"' in client.get("/workflows").text
    r = client.post("/api/workflows/mark",
                    json={"workflow": "A", "step": "website", "work": W1})
    assert r.json()["ok"], r.json()
    page = client.get("/workflows").text
    assert _cell(page, "Website").startswith("done")
    assert _cell(page, "On site").startswith("ready")
    assert ">undo</button>" in page

    client.post("/api/workflows/mark",
                json={"workflow": "A", "step": "website", "work": W1, "done": False})
    assert _cell(client.get("/workflows").text, "Website").startswith("ready")


def test_a_step_the_data_decides_cannot_be_ticked(client):
    r = client.post("/api/workflows/mark",
                    json={"workflow": "A", "step": "annotate", "work": W1}).json()
    assert not r["ok"] and r["error"]["code"] == "not_manual"
    assert _cell(client.get("/workflows").text, "Annotate").startswith("ready")


def test_an_unknown_step_is_refused(client):
    r = client.post("/api/workflows/mark",
                    json={"workflow": "Z", "step": "website", "work": W1}).json()
    assert not r["ok"] and r["error"]["code"] == "bad_args"


def test_the_tabs_filter_to_one_workflow(client):
    page = client.get("/workflows", params={"wf": "B"}).text
    assert "Lepers" not in page and "Nothing in flight" in page


def test_not_needed_dismisses_a_data_step_and_restore_brings_it_back(client):
    page = client.get("/workflows").text
    assert 'data-step="annotate"' in page and ">not needed</button>" in page
    r = client.post("/api/workflows/skip", json={
        "workflow": "A", "step": "annotate", "work": W1,
        "reason": "a study; never annotated"}).json()
    assert r["ok"], r
    page = client.get("/workflows").text
    assert _cell(page, "Annotate").startswith("skipped")
    assert ">restore</button>" in page
    assert "Annotate" not in re.search(r'next <b>([^<]*)</b>', page).group(1)

    client.post("/api/workflows/skip",
                json={"workflow": "A", "step": "annotate", "work": W1, "skip": False})
    assert _cell(client.get("/workflows").text, "Annotate").startswith("ready")


def test_the_dismissal_is_kept_in_the_ledger_with_its_reason(client, tmp_path):
    client.post("/api/workflows/skip", json={
        "workflow": "A", "step": "annotate", "work": W1, "reason": "a study"})
    ledger = (tmp_path / "qa" / ".qa" / "hygiene_ledger.ttl").read_text()
    assert '"board-skip:A:annotate"' in ledger and '"a study"' in ledger
