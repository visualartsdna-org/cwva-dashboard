"""The Storage Report: the works in one storage class, by DispId, with a
50-px thumbnail (Rick, 2026-11-19)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.tools.report_tools import parse_di, storage_rows

LAYOUT = Layout.default()
P = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
"""
WORKS = P + """
work:w1 rdfs:label "Lepers' Hearth" ; schema:image <http://visualartsdna.org/images/LepersHearth.jpg> .
work:w2 rdfs:label "Cup Vase" ; schema:image <http://visualartsdna.org/images/CupVase.jpg> .
work:w3 rdfs:label "Torso" ; schema:image <http://visualartsdna.org/images/Torso.jpg> .
work:w4 rdfs:label "Old <b> one" .
"""
PROVS = P + """
work:p1 vad:hasArtwork work:w1 ; vad:dispositionId "2026.223" .
work:p2 vad:hasArtwork work:w2 ; vad:dispositionId "1980.32" .
work:p3 vad:hasArtwork work:w3 ; vad:dispositionId "blender.2026.225" .
work:p4 vad:hasArtwork work:w4 ; vad:dispositionId "2026.9" .
"""


def _graph():
    g = Graph()
    g.parse(data=WORKS, format="turtle")
    g.parse(data=PROVS, format="turtle")
    return g


def test_the_di_grammar():
    assert parse_di("2026.159") == ("", 2026, 159)
    assert parse_di("blender.2026.157") == ("blender", 2026, 157)
    assert parse_di("wall.1982.292") == ("wall", 1982, 292)
    assert parse_di("26.1") is None and parse_di("x.y.z") is None


def test_default_storage_in_di_order_numerically():
    rows = storage_rows(_graph())
    assert [r["di"] for r in rows] == ["1980.32", "2026.9", "2026.223"]
    assert rows[2]["title"] == "Lepers' Hearth"
    assert rows[2]["thumbnail"] == "http://visualartsdna.org/thumbnails/LepersHearth.jpg"
    assert rows[1]["image"] == ""  # no image: still listed, by its DI


def test_another_class_on_request():
    assert [r["di"] for r in storage_rows(_graph(), "blender")] == ["blender.2026.225"]


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    for kind, text in (("work_ttl", WORKS), ("provenance_ttl", PROVS)):
        d = root / LAYOUT.dir(kind)
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.ttl").write_text(text)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


def test_the_page_has_the_three_columns_and_50px_thumbnails(client):
    page = client.get("/report/storage").text
    assert "<th>DispId</th><th>Title</th><th>Image</th>" in page
    dis = re.findall(r'<td class="di">([^<]+)</td>', page)
    assert dis == ["1980.32", "2026.9", "2026.223"]
    assert page.count('width="50"') == 2
    assert "Old &lt;b&gt; one" in page  # escaped
    assert "3 works" in page


def test_the_page_takes_a_class_and_refuses_a_malformed_one(client):
    assert "blender.2026.225" in client.get("/report/storage?storage_class=blender").text
    assert "not a storage class" in client.get(
        "/report/storage?storage_class=../x").text


def test_the_tools_tab_links_it(client):
    assert 'href="report/storage"' in client.get("/").text
