"""The SPARQL browser over the sandbox (inventory #17).

What it is for: the published server does not load provenance, so this is the
one place a provenance record can be checked against the records it cites. So
the tests ask exactly that kind of question, of a sandbox holding a draft.
"""

from __future__ import annotations

import json
import re
import shutil

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

LAYOUT = Layout.default()

WORK = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:w1 a vad:Watercolor ; rdfs:label "Lepers' Hearth" .
"""

PROVENANCE = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:p1 a vad:Provenance ; vad:hasArtwork work:w1 ; vad:dispositionId "2026.223" .
work:p2 a vad:Provenance ; vad:hasArtwork work:gone ; vad:dispositionId "2026.224" .
"""

DANGLING = """SELECT ?p ?di WHERE {
  ?p a vad:Provenance ; vad:hasArtwork ?w ; vad:dispositionId ?di .
  FILTER NOT EXISTS { ?w rdfs:label ?any }
}"""


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    for kind, text in (("work_ttl", WORK), ("provenance_ttl", PROVENANCE)):
        d = root / LAYOUT.dir(kind)
        d.mkdir(parents=True, exist_ok=True)
        (d / "x.ttl").write_text(text)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


def _cells(html):
    return re.findall(r"<td[^>]*>([^<]*)</td>", html)


def test_the_hub_card_resolves_to_an_empty_browser(client):
    assert 'href="sparql"' in client.get("/").text
    page = client.get("/sparql")
    assert page.status_code == 200
    assert 'name="query"' in page.text and "Execute" in page.text


def test_it_answers_across_records_and_provenance_with_no_prefix_declared(client):
    """The question it exists for: a provenance citing a work that is not there."""
    page = client.get("/sparql", params={"query": DANGLING}).text

    assert _cells(page) == ["work:p2", "2026.224"]
    assert "1 rows" in page


def test_the_page_carries_no_query_set_notes_or_prefix_table(client):
    page = client.get("/sparql").text

    assert "Query Set" not in page and "Notes" not in page and "Prefixes" not in page


@pytest.mark.parametrize("fmt, expect", [
    ("CSV", 'p,di'), ("TSV", "?p\t?di"), ("XML", '<variable name="p"/>'),
])
def test_the_text_formats(client, fmt, expect):
    page = client.get("/sparql", params={"query": DANGLING, "format": fmt}).text

    assert expect in page.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")


def test_json_is_sparql_results_json(client):
    page = client.get("/sparql", params={"query": DANGLING, "format": "JSON"}).text
    text = re.search(r'<textarea readonly[^>]*class="sparql-text"[^>]*>(.*?)</textarea>',
                     page, re.S).group(1)
    import html

    doc = json.loads(html.unescape(text))

    binding = doc["results"]["bindings"][0]
    assert binding["p"] == {"type": "uri", "value": "http://visualartsdna.org/work/p2"}


def test_ask_and_construct(client):
    ask = client.get("/sparql", params={"query": "ASK { ?p vad:dispositionId \"2026.223\" }"})
    assert "ASK result: true" in ask.text
    built = client.get("/sparql", params={
        "query": "CONSTRUCT { ?p vad:dispositionId ?d } WHERE { ?p vad:dispositionId ?d }"})
    assert "2026.223" in built.text and "2 rows" in built.text


@pytest.mark.parametrize("update", [
    'INSERT DATA { work:x a vad:Watercolor }',
    'DELETE WHERE { ?s ?p ?o }',
    'prefix x: <http://x/> DROP ALL',
])
def test_update_is_refused_and_nothing_changes(client, update):
    page = client.get("/sparql", params={"query": update}).text

    assert "UPDATE is disabled" in page
    still = client.get("/sparql", params={"query": "SELECT ?s WHERE { ?s ?p ?o }"}).text
    assert "work:x" not in still


def test_a_syntax_error_is_shown_not_raised(client):
    page = client.get("/sparql", params={"query": "SELECT WHERE {"})

    assert page.status_code == 200
    assert 'class="err"' in page.text


def test_a_word_like_delete_inside_a_literal_is_not_an_update(client):
    page = client.get("/sparql", params={
        "query": 'SELECT ?s WHERE { ?s ?p ?o FILTER(?o = "delete where") }'}).text
    assert "UPDATE is disabled" not in page


def test_an_unlimited_select_is_capped(client):
    from cwva_dashboard.tools.rdf_tools import _with_limit

    assert _with_limit("SELECT ?s WHERE { ?s ?p ?o }").rstrip().endswith("LIMIT 10000")
    assert "10000" not in _with_limit("SELECT ?s WHERE { ?s ?p ?o } LIMIT 5")
    assert _with_limit("PREFIX x: <http://x/>\nSELECT ?s WHERE {?s ?p ?o}").endswith("LIMIT 10000")
