"""Print Registry (#19): one artist profile's works, artist read from the
data rather than hard-wired as the Groovy did."""

from __future__ import annotations

import re
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout

LAYOUT = Layout.default()
DATA = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
@prefix xs: <http://www.w3.org/2001/XMLSchema#> .
work:artist rdfs:label "A. Painter" ; foaf:name "Ada Painter" .
work:prof a vad:ArtistProfile ; rdfs:label "Watercolor profile" ; vad:artist work:artist .
work:other a vad:ArtistProfile ; rdfs:label "Empty profile" .
work:w1 vad:hasArtistProfile work:prof ; rdfs:label "zebra" ;
    schema:image <http://visualartsdna.org/images/Z.jpg> ;
    vad:qrcode <http://visualartsdna.org/images/qrc_w1.jpg> ;
    schema:dateCreated "2026-11-04"^^xs:date ; schema:description "Stripes & <light>" .
work:w2 vad:hasArtistProfile work:prof ; rdfs:label "Apple" .
"""
PROF = "http://visualartsdna.org/work/prof"


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    d = root / LAYOUT.dir("work_ttl")
    d.mkdir(parents=True)
    (d / "x.ttl").write_text(DATA)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


def test_without_a_profile_it_lists_them_busiest_first(client):
    page = client.get("/report/registry").text
    links = re.findall(r'<li><a href="([^"]+)">([^<]+)</a>', page)
    assert [label for _, label in links] == ["Watercolor profile", "Empty profile"]
    assert "Ada Painter, 2 works" in page
    assert links[0][0] == "/report/registry?profile=" + quote(PROF, safe="")


def test_the_register_by_title_with_artist_from_the_data(client):
    page = client.get("/report/registry", params={"profile": PROF}).text
    assert "Register &mdash; Watercolor profile" in page and "by Ada Painter" in page
    titles = re.findall(r"<tr><td>([^<]*)</td>", page)
    assert titles == ["Apple", "zebra"]  # case-insensitive title order
    assert "<th>Title</th><th>Image</th><th>QR code</th><th>Year</th><th>Description</th>" in page
    assert 'src="http://visualartsdna.org/thumbnails/Z.jpg" width="50"' in page
    assert 'src="http://visualartsdna.org/images/qrc_w1.jpg" width="50"' in page
    assert "<td>2026</td>" in page and "Stripes &amp; &lt;light&gt;" in page
    assert "Rick Spates" not in page


def test_an_unknown_profile_says_so(client):
    page = client.get("/report/registry", params={"profile": "http://x/nope"}).text
    assert "no artist profile" in page


def test_the_tools_tab_links_it(client):
    assert 'href="report/registry"' in client.get("/").text
