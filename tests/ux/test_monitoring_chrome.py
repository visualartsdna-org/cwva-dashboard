"""Monitoring is a top-level destination, so it wears the hub's header: the
logo and the nav bar, with Monitoring lit (2026-11-19)."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.ux.hub_chrome import hub_chrome

HUB = Path(__file__).resolve().parents[2] / "html" / "function.html"


def _client(tmp_path):
    root = tmp_path / "qa"
    (root / Layout.default().dir("work_ttl")).mkdir(parents=True)
    return TestClient(create_app(domain=TEST_DOMAIN, sandbox_root=root,
                                 enforce_landlock=False,
                                 audit_path=tmp_path / "audit.jsonl"))


def _nav(html: str) -> list:
    nav = re.search(r'<nav class="header-nav">(.*?)</nav>', html, re.S).group(1)
    return re.findall(r'<(a|button) class="(nav-tab[^"]*)"(?: href="([^"]*)")?[^>]*>([^<]*)<', nav)


def test_monitoring_carries_the_hub_logo_and_every_nav_item(tmp_path):
    with _client(tmp_path) as c:
        page = c.get("/instances").text
        hub = c.get("/").text
    assert 'class="logo" href="/"' in page and "favicon.png" in page
    labels = [n[3] for n in _nav(page)]
    assert labels == [n[3] for n in _nav(hub)]  # the same bar, in the same order
    head = re.search(r'<header class="page-head">.*?</header>', page, re.S).group(0)
    assert "&larr; dashboard" not in head  # the logo is the way home now


def test_monitoring_is_lit_and_the_tabs_link_back_to_the_hub(tmp_path):
    with _client(tmp_path) as c:
        page = c.get("/instances").text
    items = {label: (cls, href) for _tag, cls, href, label in _nav(page)}
    assert items["Monitoring"][0] == "nav-tab active"
    for label, (cls, href) in items.items():
        if label != "Monitoring":
            # a hub tab (/#tools) or a page of its own (/about), never relative
            assert cls == "nav-tab" and href.startswith("/"), label
    assert items["Tools"][1] == "/#tools" and items["About"][1] == "/about"


def test_every_hub_tab_the_bar_names_exists(tmp_path):
    hub = HUB.read_text(encoding="utf-8")
    _links, _css, header = hub_chrome(hub, "Monitoring")
    for target in re.findall(r'href="/#([\w-]+)"', header):
        assert f'id="{target}"' in hub, target


def test_the_hub_opens_the_tab_named_in_the_url():
    hub = HUB.read_text(encoding="utf-8")
    assert "location.hash.slice(1)" in hub


def test_the_version_sits_beside_the_logo_everywhere_the_header_does(tmp_path):
    from cwva_dashboard import __version__

    with _client(tmp_path) as c:
        for path in ("/", "/instances", "/about"):
            page = c.get(path).text
            logo = re.search(r'<(?:div|a) class="logo".*?</(?:div|a)>', page, re.S).group(0)
            assert f'<span class="logo-version" title="dashboard version">v{__version__}</span>' \
                in logo, path
            assert "<!-- VERSION -->" not in page, path


def test_one_version_for_the_build_the_app_and_the_page(tmp_path):
    import tomllib

    from cwva_dashboard import __version__

    pyproject = tomllib.loads((HUB.parents[1] / "pyproject.toml").read_text())
    assert "version" not in pyproject["project"]
    assert pyproject["project"]["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "cwva_dashboard.__version__"}
    with _client(tmp_path) as c:
        assert c.app.version == __version__
