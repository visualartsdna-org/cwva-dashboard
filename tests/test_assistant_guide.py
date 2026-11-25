"""The assistant guide is the About pages plus a preface, assembled; it must
never drift from them (2026-11-22)."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.ux.about_pages import AboutDocs

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "START_HERE.md"


def _anchor(title):
    return re.sub(r"\s", "-", re.sub(r"[^\w\s-]", "", title.strip().lower()))


def test_the_committed_guide_is_up_to_date():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_assistant_guide.py"),
                        "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_it_holds_every_about_page_in_order():
    text = GUIDE.read_text()
    titles = [p.title for p in AboutDocs().pages()]
    positions = [text.find(f"## {t}") for t in titles]
    assert all(p > 0 for p in positions), titles
    assert positions == sorted(positions)


def test_every_link_inside_it_lands_on_a_heading():
    text = GUIDE.read_text()
    headings = {_anchor(h) for h in re.findall(r"^#{1,6} (.+)$", text, re.M)}
    for target in re.findall(r"\]\(#([\w-]+)\)", text):
        assert target in headings, target
    assert not re.search(r"\]\([\w./-]+\.md", text), "a link to another file survived"


def test_the_preface_names_the_decisions_and_the_ground_rules():
    text = GUIDE.read_text()
    for must in ("Their domain", "Never place files in the sandbox",
                 "Never change `domain`", "Never weaken or bypass a failed check"):
        assert must in text, must


def test_the_dashboard_serves_it_and_links_to_it(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        r = c.get("/about/assistant-guide.md")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
        assert r.text == GUIDE.read_text()
        assert 'href="/about/assistant-guide.md"' in c.get("/about/what-it-is").text


def test_claude_md_points_a_helper_at_it():
    assert "START_HERE.md" in (ROOT / "CLAUDE.md").read_text().split("## What this project is")[0]
