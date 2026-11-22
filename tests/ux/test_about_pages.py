"""The About pages: docs/about/*.md read in the dashboard, with the hub's
header, a contents list, and GitHub-style links rewritten (2026-11-19)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.ux.about_pages import DOCS, AboutDocs


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    (root / Layout.default().dir("work_ttl")).mkdir(parents=True)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


def test_the_hub_nav_bar_has_about(client):
    assert '<a class="nav-tab" href="about">About</a>' in client.get("/").text


def test_about_opens_on_the_first_page_with_about_lit(client):
    page = client.get("/about").text
    assert '<h1 id="what-the-dashboard-is">What the dashboard is</h1>' in page
    assert '<a class="nav-tab active" href="/about">About</a>' in page
    assert 'href="/instances">Monitoring</a>' in page  # absolute from any depth


def test_every_listed_page_renders_and_is_in_the_contents(client):
    docs = AboutDocs()
    assert [p.slug for p in docs.pages()][:3] == ["what-it-is", "key-ideas", "tour"]
    for p in docs.pages():
        page = client.get(f"/about/{p.slug}").text
        assert f'class="on" href="/about/{p.slug}"' in page, p.slug


def test_links_between_pages_point_at_the_dashboards_addresses(client):
    page = client.get("/about/what-it-is").text
    assert 'href="/about/key-ideas"' in page and 'href="key-ideas.md"' not in page


def test_parts_still_to_come_are_shown_as_such(client):
    page = client.get("/about").text
    toc = re.search(r'<nav class="toc">(.*?)</nav>', page, re.S).group(1)
    assert "Installing and running" in toc and "to come" in toc


def test_an_unknown_page_is_404(client):
    assert client.get("/about/nope").status_code == 404


def test_every_page_link_in_the_docs_resolves():
    """The same files are the GitHub docs: a link to a missing file is broken
    in both places."""
    for md in DOCS.glob("*.md"):
        for target in re.findall(r"\]\(([\w.-]+\.md)(?:#[\w-]*)?\)", md.read_text()):
            assert (DOCS / target).is_file(), f"{md.name} -> {target}"


def test_the_github_index_lists_every_page():
    readme = (DOCS / "README.md").read_text()
    for p in AboutDocs().pages():
        assert f"({p.file})" in readme, p.file


def test_a_link_to_a_section_lands_on_an_anchor_that_exists(client):
    """GitHub makes heading anchors; the dashboard must make the same ones."""
    for md in DOCS.glob("*.md"):
        for target, frag in re.findall(r"\]\(([\w.-]+\.md)#([\w-]+)\)", md.read_text()):
            slug = next(p.slug for p in AboutDocs().pages() if p.file == target)
            assert f'id="{frag}"' in client.get(f"/about/{slug}").text, f"{md.name} -> {target}#{frag}"
