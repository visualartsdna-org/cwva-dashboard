"""Movable cards on the hub's Content Management section, and the cards
removed from Immediate Actions (2026-11-19)."""

from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.hub_layout import LayoutError, load_layout, save_order
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    (root / Layout.default().dir("work_ttl")).mkdir(parents=True)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


def _saved(page: str) -> list:
    return json.loads(re.search(r"var saved = (\[.*?\]);", page).group(1))


def test_the_content_section_is_movable_and_starts_unarranged(client):
    hub = client.get("/").text
    assert 'class="card-grid" data-section="content"' in hub
    assert "card-handle" in hub
    assert _saved(hub) == []


def test_an_order_is_kept_and_served_back(client, tmp_path):
    r = client.post("/api/hub/layout",
                    json={"section": "content", "order": ["workflows", "edit", "edit"]})
    assert r.json() == {"section": "content", "order": ["workflows", "edit"]}
    assert _saved(client.get("/").text) == ["workflows", "edit"]
    # beside the audit log, outside the sandbox
    assert json.loads((tmp_path / "hub-layout.json").read_text()) == {
        "content": ["workflows", "edit"]}


def test_an_empty_order_resets(client):
    client.post("/api/hub/layout", json={"section": "content", "order": ["edit"]})
    client.post("/api/hub/layout", json={"section": "content", "order": []})
    assert _saved(client.get("/").text) == []


@pytest.mark.parametrize("body", [
    {"section": "files", "order": []},
    {"section": "content", "order": "edit"},
    {"section": "content", "order": [3]},
    {"section": "content", "order": ["x" * 400]},
    [],
])
def test_a_bad_order_is_refused(client, body):
    assert client.post("/api/hub/layout", json=body).status_code == 400


def test_a_broken_layout_file_never_breaks_the_hub(tmp_path):
    p = tmp_path / "hub-layout.json"
    p.write_text("{not json")
    assert load_layout(p) == {}
    assert save_order(p, "content", ["edit"]) == ["edit"]
    with pytest.raises(LayoutError):
        save_order(p, "nope", [])


def test_a_saved_key_cannot_close_the_script(client):
    client.post("/api/hub/layout",
                json={"section": "content", "order": ["</script><b>x"]})
    hub = client.get("/").text
    assert "</script><b>x" not in hub


def test_the_concept_derivation_cards_and_notes_are_gone(client):
    hub = client.get("/").text
    for gone in ("Markdown Concept Derivation and Tagging Workflow",
                 "Derive Concepts from Documents", "Tag Markdowns",
                 "Annotate Document Instances", "Summarize Documents",
                 "conceptQueue/processed/tagged"):
        assert gone not in hub, gone
    # Concept Promote and Distribute Metadata followed them (later, 2026-11-19)
    assert "Concept Promote" not in hub and "Distribute Metadata" not in hub
