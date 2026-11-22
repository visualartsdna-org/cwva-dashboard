"""Affordance resolution: the trusted-side backend for the dynamic pickers.

The renderer reads the schema and fetches x-file-ref / x-vocabulary candidates
from uniform endpoints (no per-field knowledge). These test that backend. Static
affordances (enum/format/x-enum-suggested) need no backend — their candidates are
in the schema — and are covered by the tool tests.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph, Namespace
from rdflib.namespace import RDF, RDFS, SKOS

from cwva_dashboard.main import create_app
from cwva_dashboard.ux.affordance import resolve_vocabulary

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(not hasattr(os, "fork"), reason="worker requires os.fork (POSIX)")

VAD = Namespace("http://visualartsdna.org/model/")
THE = Namespace("http://visualartsdna.org/thesaurus/")


@pytest.fixture
def client(tmp_path):
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=str(tmp_path / "stage"),
        enforce_landlock=False,
        audit_path=str(tmp_path / "audit.jsonl"),
    )
    with TestClient(app) as c:
        yield c


# -- x-file-ref via the confined fs.list -------------------------------------


def test_file_ref_lists_staged_files(client):
    client.post("/api/tool/fs.write", json={"path": "content/images/b.jpg", "text": "x", "make_parents": True})
    client.post("/api/tool/fs.write", json={"path": "content/images/a.jpg", "text": "y"})
    r = client.get("/api/affordance/file-ref", params={"subtree": "content/images"})
    cands = r.json()["candidates"]
    assert [c["value"] for c in cands] == ["a.jpg", "b.jpg"]  # sorted


def test_file_ref_hides_pointer_sidecars(client):
    # a managed binary write creates an a.png.ptr sidecar; it must not be offered
    client.post("/api/tool/fs.write", json={"path": "content/images/a.png", "text": "PNG", "make_parents": True})
    cands = client.get("/api/affordance/file-ref", params={"subtree": "content/images"}).json()["candidates"]
    names = [c["value"] for c in cands]
    assert "a.png" in names and "a.png.ptr" not in names


def test_file_ref_empty_for_absent_subtree(client):
    assert client.get("/api/affordance/file-ref", params={"subtree": "content/nope"}).json()["candidates"] == []


def test_file_ref_cannot_escape_the_sandbox(client):
    # goes through fs.list, so containment holds — a traversal yields no candidates
    assert client.get("/api/affordance/file-ref", params={"subtree": "../../etc"}).json()["candidates"] == []


# -- x-vocabulary (resolver unit + endpoint) ---------------------------------


def _vocab_graph():
    g = Graph()
    for ln, lab in [("StrathmoreColdPress", "Strathmore Cold Press"), ("FabrianoHot", "Fabriano Hot")]:
        g.add((THE[ln], RDF.type, VAD.WatercolorPaper))
        g.add((THE[ln], RDFS.label, lab and __import__("rdflib").Literal(lab)))
    # a concept in the topic scheme, and one NOT in it
    g.add((THE.Watercolor, RDF.type, SKOS.Concept))
    g.add((THE.Watercolor, SKOS.inScheme, THE.TopicScheme))
    g.add((THE.Loose, RDF.type, SKOS.Concept))
    return g


def test_resolve_papers_returns_value_label_pairs():
    cands = resolve_vocabulary(_vocab_graph(), "papers")
    assert {c["value"] for c in cands} == {"the:StrathmoreColdPress", "the:FabrianoHot"}
    assert any(c["label"] == "Strathmore Cold Press" for c in cands)


def test_resolve_topics_requires_scheme_membership():
    cands = resolve_vocabulary(_vocab_graph(), "topics")
    vals = {c["value"] for c in cands}
    assert "the:Watercolor" in vals and "the:Loose" not in vals  # Loose isn't in the scheme


def test_resolve_unknown_name_is_empty():
    assert resolve_vocabulary(_vocab_graph(), "nonesuch") == []


def test_resolve_none_graph_is_empty():
    assert resolve_vocabulary(None, "papers") == []


def test_vocabulary_endpoint_is_empty_pre_sync(client):
    # no vocabulary synced into the fresh sandbox → empty (renderer falls back)
    assert client.get("/api/affordance/vocabulary/papers").json()["candidates"] == []
