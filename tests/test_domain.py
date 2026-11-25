"""The shared `domain` table, agreed with cwva-py (November 2026)."""

from __future__ import annotations

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, RDFS
from rdflib import Literal

from cwva_dashboard import config as cfgmod
from cwva_dashboard.main import create_app
from cwva_dashboard.tools.record_tools import _expand, work_namespace
from cwva_dashboard.ux.affordance import resolve_referent


@pytest.mark.parametrize("raw, value", [
    ("http://janedoe-art.com", "http://janedoe-art.com"),
    ("https://janedoe-art.com", "https://janedoe-art.com"),
    ("http://localhost:8080", "http://localhost:8080"),
    ("http://janedoe-art.com/", "http://janedoe-art.com"),
    (" http://janedoe-art.com ", "http://janedoe-art.com"),
    ("http://visualartsdna.org", "http://visualartsdna.org"),
    ("http://www.visualartsdna.org", "http://www.visualartsdna.org"),
])
def test_accepted(raw, value):
    assert cfgmod.domain({"domain": raw}) == value


@pytest.mark.parametrize("raw", [
    "", "   ", "janedoe-art.com", "http://janedoe-art.com/art",
    "http://janedoe-art.com/?x", "http://janedoe-art.com#x",
    "http://JaneDoe-art.com", "http://http://janedoe-art.com",
    "http://user@janedoe-art.com", "http://janedoe-art.com:80",
    "https://janedoe-art.com:443", "http://janedoe-art.com.",
    "ftp://janedoe-art.com", "http://", "http://jane doe.com",
    "http://janedoe-art.com:99999", "http://janedoe-art.com\nx",
    "https://visualartsdna.org", "https://visualartsdna.org/",
])
def test_refused_and_the_message_names_the_setting(raw):
    with pytest.raises(ValueError, match="domain"):
        cfgmod.domain({"domain": raw})


def test_the_app_refuses_one_passed_to_it(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    with pytest.raises(ValueError, match="janedoe-art.com"):
        create_app(domain="janedoe-art.com", sandbox_root=root,
                   enforce_landlock=False, audit_path=tmp_path / "a.jsonl")


VAD = "http://visualartsdna.org/model/"
THE = "http://visualartsdna.org/thesaurus/"


@pytest.mark.parametrize("base", ["http://janedoe-art.com", "http://visualartsdna.org"])
def test_a_pickers_value_names_the_record_it_shows(base):
    """`work:` was always shortened from visualartsdna.org and expanded to the
    configured domain, so picking a shared background cited a record nobody has."""
    work_ns = work_namespace("http://janedoe-art.com")
    bg = URIRef(f"{base}/work/bg1")
    g = Graph()
    g.add((bg, RDF.type, URIRef(THE + "Image")))
    g.add((bg, URIRef(THE + "topic"), URIRef(THE + "Background")))
    g.add((bg, RDFS.label, Literal("Sky")))
    [c] = resolve_referent(g, "backgrounds", str(work_ns))
    assert _expand(c["value"], {"work": work_ns}) == bg
    assert (c["value"] == "work:bg1") == (base == "http://janedoe-art.com")
