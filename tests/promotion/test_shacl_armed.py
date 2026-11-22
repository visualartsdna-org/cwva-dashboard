"""The SHACL gate, armed.

It was written, tested and then passed `None` from the only place that runs it,
for the whole of Phase 4 — the same trap the fixtures hit when a driver built
without `image_base` ran neither the asset nor the vocabulary gate and "gates
passed" meant "no gates ran". `create_app` arms it now, and the first test here
is the one that keeps it armed.

What it catches is specific: a profile record that could not build a form. Those
records travel to the SOT and from there to every other copy of the dashboard,
so the moment to refuse one is before it converges.
"""

from __future__ import annotations

import shutil

import pytest
from rdflib import Graph

from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.profiles import shapes_graph

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

PREFIXES = """@prefix vad:  <http://visualartsdna.org/model/> .
@prefix ops:  <http://visualartsdna.org/operations/> .
@prefix work: <http://visualartsdna.org/work/> .
@prefix schema: <https://schema.org/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
"""

GOOD = PREFIXES + """
work:prof-1 a vad:ArtistProfile ;
    vad:artist work:artist-1 ;
    rdfs:label "Watercolor materials profile" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ] ;
    ops:template [
        ops:templateType vad:Watercolor ;
        ops:field [ ops:property rdfs:label ; ops:order 1 ; ops:required true ] ;
    ] .
"""

# A field with no order. The form built from it would list its fields in
# whatever sequence the parser returned.
NO_ORDER = GOOD.replace("ops:order 1 ; ", "")

ORDINARY = PREFIXES + """
work:w1 a vad:Watercolor ; rdfs:label "A Work" .
"""


def _driver(tmp_path, *, armed=True):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    return qa, PromotionDriver(qa, FilesTransport(tmp_path / "sot"),
                               shapes=shapes_graph() if armed else None)


def _write(qa, name, body):
    p = qa.root / "ttl" / "data" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_CREATE_APP_ARMS_IT(tmp_path, monkeypatch):
    """The test that matters. `driver.py` passed `shapes=None` for four phases;
    everything else here would have passed throughout."""
    from cwva_dashboard import config as cfgmod

    shapes = cfgmod.load_shapes(cfgmod.load_config(str(cfgmod.CONFIG_DIR / "base.rson")))

    assert shapes is not None and len(shapes) > 0, (
        "the packaged shapes must load, or create_app arms the gate with nothing"
    )
    # and a gate given no shapes conforms to everything, which is why
    # `load_shapes` returns None rather than an empty graph
    assert cfgmod.load_shapes({"shapes_dir": str(tmp_path)}) is None


def test_an_incoherent_profile_does_not_reach_the_SOT(tmp_path):
    qa, driver = _driver(tmp_path)
    _write(qa, "prof.ttl", NO_ORDER)

    out = driver.preview(workflow="test", description="a broken profile")

    assert out["status"] == "gates_failed"
    assert "shacl" in out["failing"]
    shacl = next(g for g in out["gates"] if g["name"] == "shacl")
    assert any("ops:order" in str(m) for m in shacl["messages"])
    assert not (tmp_path / "sot" / "ttl" / "data" / "prof.ttl").exists()
    assert "token" not in out, "nothing approvable, so nothing to approve"


def test_a_coherent_profile_passes(tmp_path):
    qa, driver = _driver(tmp_path)
    _write(qa, "prof.ttl", GOOD)

    out = driver.preview(workflow="test", description="a good profile")

    assert out["status"] == "previewed", out.get("failing")


def test_ordinary_content_is_not_touched_by_these_shapes(tmp_path):
    """The shapes target `vad:ArtistProfile`. A promotion of watercolours must
    not start failing because a gate was armed."""
    qa, driver = _driver(tmp_path)
    _write(qa, "w1.ttl", ORDINARY)

    out = driver.preview(workflow="test", description="a work")

    assert out["status"] == "previewed"
    assert next(g for g in out["gates"] if g["name"] == "shacl")["ok"]


def test_unarmed_is_VISIBLY_unarmed(tmp_path):
    """No shapes, no gate — and the absence shows in the gate list rather than
    as a gate that passed."""
    qa, driver = _driver(tmp_path, armed=False)
    _write(qa, "prof.ttl", NO_ORDER)

    out = driver.preview(workflow="test", description="a broken profile")

    assert out["status"] == "previewed", "nothing checks it"
    assert not any(g["name"] == "shacl" for g in out["gates"])


def test_the_gate_sees_only_the_UNIT_not_the_whole_store(tmp_path):
    """A broken profile already sitting in QA must not block an unrelated
    promotion — the gate's job is what is converging now."""
    qa, driver = _driver(tmp_path)
    _write(qa, "prof.ttl", NO_ORDER)
    qa.commit("pre-existing, and broken")   # in the tree, not in the unit
    _write(qa, "w1.ttl", ORDINARY)

    out = driver.preview(workflow="test", description="an unrelated work")

    assert out["status"] == "previewed", out.get("failing")
