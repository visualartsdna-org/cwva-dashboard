"""Reports and converted documents carry no instance banner: they are
documents to print or read, not pages of the dashboard (2026-11-19)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import HTMLResponse
from starlette.routing import Route

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.ux.banner import NO_BANNER, EnvironmentBanner


def _app():
    page = lambda r: HTMLResponse("<!doctype html><body><p>page</p></body>")
    doc = lambda r: HTMLResponse("<!doctype html><body><p>doc</p></body>",
                                 headers={NO_BANNER: "1"})
    app = Starlette(routes=[Route("/page", page), Route("/doc", doc)])
    app.add_middleware(EnvironmentBanner, label="PRODUCTION", colour="amber")
    return app


def test_a_page_has_the_banner_and_a_document_does_not():
    c = TestClient(_app())
    assert 'data-env-banner="1"' in c.get("/page").text
    r = c.get("/doc")
    assert "data-env-banner" not in r.text
    assert NO_BANNER.lower() not in {k.lower() for k in r.headers}  # removed on the way out


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    (root / Layout.default().dir("work_ttl")).mkdir(parents=True)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("path", ["/report/storage", "/report/registry",
                                  "/certificate?guid=fd0a416a-abc2-468d-af76-5d38638e2704"])
def test_every_report_is_marked_a_document(client, path):
    assert client.get(path).headers.get(NO_BANNER.lower()) == "1"


def test_ordinary_pages_are_not(client):
    assert NO_BANNER.lower() not in client.get("/workflows").headers
