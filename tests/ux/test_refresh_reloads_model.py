"""A refresh makes the running dashboard current with the ontology.

The dashboard has several currency lifetimes and they are easy to conflate.
Content arrives by sync; field wording is re-read per render; but the `type`
enum is *materialised into the registry*, and the registry the WORKER holds is
what `validate_args` enforces. So a refresh has to move three things together —
the form's options, the parent registry, and the worker's — or the form offers a
class dispatch rejects, which is the offered-set != enforced-set hole again.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import image_base

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

BASE_MODEL = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix vad: <http://visualartsdna.org/model/> .
vad:PaintingForm a owl:Class .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
"""
ADDED = BASE_MODEL + "vad:Gouache a owl:Class ; rdfs:subClassOf vad:PaintingForm .\n"

VOCAB = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
the:%s a vad:WatercolorPaper, skos:Concept ; rdfs:label "%s" .
"""


@pytest.fixture
def env(tmp_path):
    """A dashboard whose ontology arrives the way it really does: from the SOT.

    The fixture seeds the SOT *and* the sandbox, because a refresh is
    `reset_hard` + `clean_untracked` + sync — it discards anything uncommitted,
    so a model hand-placed in the sandbox would simply be wiped. Changing the
    ontology in a test therefore means writing to the SOT and refreshing, which
    is exactly the production path.
    """
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    sot = tmp_path / "sot"

    def publish(model_text: str, vocab_text: str) -> None:
        for root in (sot, qa_root):
            (root / "metacontent" / "model").mkdir(parents=True, exist_ok=True)
            (root / "metacontent" / "vocab").mkdir(parents=True, exist_ok=True)
            (root / "metacontent" / "model" / "m.ttl").write_text(model_text)
            (root / "metacontent" / "vocab" / "v.ttl").write_text(vocab_text)

    publish(BASE_MODEL, VOCAB % ("FirstPaper", "First Paper"))
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "a.jsonl",
        promotion_driver=PromotionDriver(
            qa, FilesTransport(sot), image_base=image_base(TEST_DOMAIN),
            layout=Layout.default(),
        ),
    )
    with TestClient(app) as c:
        yield c, publish


def _types(html: str) -> list[str]:
    m = re.search(r'<select id="type" name="type".*?</select>', html, re.S)
    return re.findall(r'<option value="([^"]*)"', m.group(0)) if m else []


def test_a_new_class_is_absent_until_refresh(env):
    """Establishes the baseline the refresh has to change — and documents that
    without a refresh the running server is deliberately not current."""
    c, publish = env
    assert "Gouache" not in _types(c.get("/rdf/entry").text)

    publish(ADDED, VOCAB % ("FirstPaper", "First Paper"))

    assert "Gouache" not in _types(c.get("/rdf/entry").text), "no refresh, no change"


def test_refresh_brings_a_new_class_into_the_FORM(env):
    c, publish = env
    publish(ADDED, VOCAB % ("FirstPaper", "First Paper"))

    assert c.get("/api/refresh").json() == {"status": "OK"}

    assert "Gouache" in _types(c.get("/rdf/entry").text)


def test_refresh_brings_it_into_DISPATCH_too(env):
    """The half that matters. `validate_args` runs in the worker against the
    registry the worker holds, so a form-only reload would offer a value the
    dispatcher refuses."""
    c, publish = env
    schema = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_work"
    )
    assert "Gouache" not in schema["inputSchema"]["properties"]["type"]["enum"]

    publish(ADDED, VOCAB % ("FirstPaper", "First Paper"))
    c.get("/api/refresh")

    got = c.post(
        "/api/tool/record.check_uniqueness", json={"label": "x", "type": "Gouache"}
    ).json()
    assert got["ok"], got
    schema = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_work"
    )
    assert "Gouache" in schema["inputSchema"]["properties"]["type"]["enum"]


def test_form_and_dispatch_agree_after_a_refresh(env):
    """The invariant, stated directly: what the form offers is what the system
    enforces — before and after a reload."""
    c, publish = env
    publish(ADDED, VOCAB % ("FirstPaper", "First Paper"))
    c.get("/api/refresh")

    offered = [t for t in _types(c.get("/rdf/entry").text) if t]
    enforced = next(
        s for s in c.get("/api/tools").json() if s["name"] == "record.new_work"
    )["inputSchema"]["properties"]["type"]["enum"]

    assert offered == enforced


def test_refresh_reloads_the_vocabulary_too(env):
    """A thesaurus arriving with the sync must reach the pickers, or the paper
    list stays at whatever was on disk when the process started."""
    c, publish = env
    before = c.get("/api/affordance/vocabulary/papers").json()["candidates"]
    assert [x["value"] for x in before] == ["the:FirstPaper"]

    publish(BASE_MODEL, VOCAB % ("SecondPaper", "Second Paper"))
    c.get("/api/refresh")

    after = c.get("/api/affordance/vocabulary/papers").json()["candidates"]
    assert [x["value"] for x in after] == ["the:SecondPaper"]


def test_refresh_reports_what_it_did(env):
    """A refresh that silently half-worked is the failure mode; the response
    says whether the worker actually reloaded."""
    c, _publish = env

    # The signal's own contract: plain success, nothing to parse.
    plain = c.get("/api/refresh")
    assert plain.status_code == 200 and plain.json() == {"status": "OK"}

    # ?detail=1 for a human debugging it — a refresh that silently half-worked
    # is the failure mode, so the evidence stays available.
    body = c.get("/api/refresh?detail=1").json()
    assert body["status"] == "OK"
    assert body["reloaded"]["registry_rebuilt"] is True
    assert body["reloaded"]["worker_reloaded"] is True
    assert not body["reloaded"]["worker_error"]


def test_a_broken_ontology_does_not_kill_the_worker(env):
    """A refresh is an ordinary operation that can meet bad data. The worker
    must report the failure and keep serving, not die and take the session."""
    c, publish = env
    publish("this is not turtle {{{", VOCAB % ("FirstPaper", "First Paper"))

    body = c.get("/api/refresh?detail=1").json()

    assert body["reloaded"]["worker_reloaded"] is True  # rebuild survived
    assert c.get("/api/health").json()["tools"], "worker still answering"


def test_refresh_is_a_GET_and_says_only_OK(env):
    """The signal is a GET returning {"status": "OK"} — that is the convention
    the existing server uses and the one this dashboard will issue to itself."""
    c, _publish = env

    r = c.get("/api/refresh")

    assert r.status_code == 200
    assert r.json() == {"status": "OK"}


def test_POST_still_works_for_callers_that_prefer_it(env):
    """A mutating GET matches the convention but is not the safer verb, so POST
    stays available rather than forcing every caller into GET."""
    c, _publish = env

    assert c.post("/api/refresh").json() == {"status": "OK"}
