"""Generate Certificate (#20): title, the record as Property / Value, signature
and date lines, as CertAuthenticity.groovy laid it out."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout

LAYOUT = Layout.default()
G = "fd0a416a-abc2-468d-af76-5d38638e2704"
WORK = f"""@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix schema: <https://schema.org/> .
work:{G} a vad:CreativeWork, vad:Watercolor ; rdfs:label "Lepers' Hearth" ;
    vad:hasWatercolorPaint the:UltramarineLCS, the:UltramarineDD ;
    schema:image <http://visualartsdna.org/images/LepersHearth.jpg> ;
    vad:qrcode <http://visualartsdna.org/images/qrc_{G}.jpg> ;
    schema:height [ a schema:QuantitativeValue ; rdfs:label "15.0 inches" ] ;
    the:tag work:somethingElse ;
    schema:description "Bread & <ovens>" .
"""
VOCAB = """@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix schema: <https://schema.org/> .
the:UltramarineLCS skos:prefLabel "Ultramarine" ; schema:brand the:LCS .
the:UltramarineDD skos:prefLabel "Ultramarine" ; schema:brand the:DD .
the:LCS skos:altLabel "LCS" . the:DD skos:altLabel "DD" .
"""
MODEL = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
vad:Watercolor rdfs:label "Watercolor Painting" .
"""


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    for kind, text in (("work_ttl", WORK), ("vocab_ttl", VOCAB), ("model_ttl", MODEL)):
        d = root / LAYOUT.dir(kind)
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.ttl").write_text(text)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


def _rows(page):
    return dict(re.findall(r'<tr><td class="p">([^<]+)</td><td>(.*?)</td></tr>', page))


def test_the_certificate_reads_like_the_groovy_one_but_in_words(client):
    page = client.get("/certificate", params={"guid": G}).text
    assert "<h1>Certificate of Authenticity</h1>" in page
    assert re.search(rf'<h2><a href="http://visualartsdna.org/work/{G}">Lepers.{{1,8}}Hearth</a></h2>',
                     page)
    rows = _rows(page)
    assert ">Watercolor Painting<" in rows["type"]  # the art form, not CreativeWork
    assert "Ultramarine (DD)" in rows["hasWatercolorPaint"]
    assert "Ultramarine (LCS)" in rows["hasWatercolorPaint"]
    assert rows["height"] == "15.0 inches"  # a dimension by its label, no bnode id
    assert 'width="50"' in rows["image"] and 'width="100"' in rows["qrcode"]
    assert "tag" not in rows  # skipped, as the Groovy did
    assert rows["description"] == "Bread &amp; &lt;ovens&gt;"
    assert "Signed: ____" in page and "Date: ____" in page


def test_anything_ending_in_the_guid_will_do(client):
    page = client.get("/certificate",
                      params={"guid": f"http://visualartsdna.org/work/{G}"}).text
    assert "Watercolor Painting" in page


@pytest.mark.parametrize("guid,why", [("", "GUID"), ("nope", "GUID"),
                                      ("00000000-0000-0000-0000-000000000000", "no work")])
def test_a_bad_or_unknown_guid_says_so(client, guid, why):
    assert why in client.get("/certificate", params={"guid": guid}).text


def test_the_hub_form_submits_here(client):
    hub = client.get("/").text
    assert 'action="/certificate"' in hub and 'name="guid"' in hub
