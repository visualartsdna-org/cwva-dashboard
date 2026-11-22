"""updateWorkOnSite wired from function.html (Phase 4.7, cycle 4).

The only workflow that reaches OUTSIDE the sandbox — read-only HTTP to
config-listed sites, one of the three sanctioned network effects (law 11). It
therefore gets a confirm-first page like promotion: GET shows what is
configured, POST performs the reads. An effect the user never saw is an effect
they cannot judge.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

SITE = "https://test.art"
G1 = "321ad3da-4069-4f8d-8514-4094f0aa1862"
GONE = "0e5bef85-8839-41ca-b6c5-a855c7eb1ffe"

HOME = f"""<html><body>
<a href="https://www.visualartsdna.org/work/{G1}">Catalog entry</a>
<a href="https://visualartsdna.org/work/{GONE}">Catalog entry</a>
</body></html>"""


class FakeFetcher:
    """The network effect stays injectable: no test ever leaves the machine."""

    def __init__(self, pages):
        self.pages = pages
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        try:
            return self.pages[url].encode()
        except KeyError:
            raise OSError(f"404 {url}")


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    data = qa_root / layout.dir("work_ttl")
    data.mkdir(parents=True)
    (data / "works.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        f'work:{G1} rdfs:label "Spirited Tree" .\n'
    )
    fetcher = FakeFetcher({SITE: HOME})
    # The fetcher is injected into the ROUTE, because the site read is a
    # trusted-orchestrator effect: the confined worker cannot resolve a
    # hostname, so it never fetches anything.
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl", sites=[SITE], site_fetcher=fetcher,
        promotion_driver=PromotionDriver(qa, FilesTransport(tmp_path / "sot"), layout=layout),
    )
    with TestClient(app) as c:
        yield c, qa, fetcher


def test_the_card_on_the_hub_now_resolves(client):
    c, _qa, _f = client
    hub = c.get("/").text

    assert 'href="site/update"' in hub
    assert c.get("/site/update").status_code == 200


def test_the_page_asks_before_it_reaches_out(client):
    """A GET must not perform the network effect.

    Asserted on the OBSERVABLE result — no snapshot staged — rather than on the
    fetcher's call log: the tool runs in the forked worker, so a counter it
    increments lives in the child process and the parent would read an empty
    list whether or not anything was fetched. That is also how the fake fetcher
    reaches the worker at all: it is inherited across the fork.
    """
    c, qa, _f = client
    html = c.get("/site/update").text

    assert SITE in html and "Read the sites" in html
    assert not (qa.root / "content/ttl/data/workonsite_test_art.ttl").exists()


def test_running_it_reports_what_the_site_DECLARES(client):
    c, qa, _f = client
    html = c.post("/site/update").text

    assert "Spirited Tree" in html and G1 in html
    assert (qa.root / "content/ttl/data/workonsite_test_art.ttl").is_file()


def test_a_work_the_store_lacks_is_shown_separately(client):
    c, _qa, _f = client
    html = c.post("/site/update").text

    assert GONE in html
    assert "does not have them" in html


def test_the_snapshot_is_staged_in_QA_and_not_converged(client):
    c, qa, _f = client
    c.post("/site/update")

    staged = qa.root / "content/ttl/data/workonsite_test_art.ttl"
    assert staged.is_file()
    assert "vad:workOnSite" in staged.read_text()
    assert not list((qa.root.parent / "sot").rglob("*.ttl")), "must not converge"


def test_a_site_that_declares_nothing_says_so(tmp_path):
    """Silence from a site is an answer, and the page has to say which answer it
    is — an empty list looks identical to a broken run otherwise."""
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
                     audit_path=tmp_path / "a.jsonl", sites=[SITE],
                     site_fetcher=FakeFetcher({SITE: "<html><body>nothing</body></html>"}),
                     promotion_driver=PromotionDriver(qa, FilesTransport(tmp_path / "sot"),
                                                      layout=layout))
    with TestClient(app) as c:
        html = c.post("/site/update").text

    assert "names no works" in html


def test_no_sites_configured_is_stated_not_silent(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
                     audit_path=tmp_path / "a.jsonl", sites=[],
                     promotion_driver=PromotionDriver(qa, FilesTransport(tmp_path / "sot")))
    with TestClient(app) as c:
        assert "No sites configured" in c.get("/site/update").text
        assert c.post("/site/update").status_code == 400


def test_the_confined_worker_never_fetches(client):
    """The site read is TRUSTED-ORCHESTRATOR work, and not by preference: the
    Landlock-confined worker cannot resolve a hostname at all — glibc's resolver
    needs /etc/resolv.conf and the NSS libraries, which confinement denies.
    Measured 2026-09-09: an IP-literal fetch from the worker succeeds, a
    named-host fetch fails with EAI_AGAIN, and the first real run produced two
    empty snapshots with no explanation.

    So the tool stages what it is TOLD was observed. Calling it with no
    observations must therefore write empty snapshots rather than quietly going
    to the network itself.
    """
    c, qa, f = client
    before = list(f.asked)

    out = c.post("/api/tool/workflow.update_work_on_site", json={}).json()

    assert out["ok"], out
    assert f.asked == before, "dispatching the tool must not fetch"
    assert all(r["declared"] == [] for r in out["result"]["runs"])


def test_a_page_that_cannot_be_read_says_so(tmp_path):
    """A run that finds nothing and says nothing is indistinguishable from a
    site that publishes nothing — which is exactly what the first real run
    looked like."""
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
                     audit_path=tmp_path / "a.jsonl", sites=[SITE],
                     site_fetcher=FakeFetcher({}),  # every fetch fails
                     promotion_driver=PromotionDriver(qa, FilesTransport(tmp_path / "sot")))
    with TestClient(app) as c:
        html = c.post("/site/update").text

    assert "could not be read" in html
    assert "OSError" in html or "404" in html


def test_a_malformed_catalog_link_is_shown(tmp_path):
    """Real, from the first narrowed run: `…/work/%09<guid>` — a tab pasted into
    the URL. It will not resolve for a visitor either, so it is reported for
    fixing at the site rather than tolerated by the pattern."""
    BROKEN = "e776711b-7b0a-4835-88bc-16c2cfa0179b"
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    page = f'<html><body><a href="https://visualartsdna.org/work/%09{BROKEN}">Catalog entry</a></body></html>'
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
                     audit_path=tmp_path / "a.jsonl", sites=[SITE],
                     site_fetcher=FakeFetcher({SITE: page}),
                     promotion_driver=PromotionDriver(qa, FilesTransport(tmp_path / "sot")))
    with TestClient(app) as c:
        html = c.post("/site/update").text

    assert BROKEN in html
    assert "almost name a work" in html
    assert "names no works" in html, "and it is not counted as a declaration"


def test_an_empty_result_names_the_base_it_looked_for(tmp_path):
    """The only defence against a misconfigured `domain` (CE_DESIGN §13.4a).

    The dashboard and cwvaServer-py declare the domain in separate configs and
    neither can check the other — they need not be on the same machine, and in
    Rick's deployment they are not: content management on a workstation,
    production on GCP. So a wrong `domain` cannot be detected; it can only be
    made legible. Without this line, a wrong domain and a site that publishes
    nothing produce identical output.
    """
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    page = '<html><body><a href="https://someoneelse.org/work/x">nothing of ours</a></body></html>'
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
                     audit_path=tmp_path / "a.jsonl", sites=[SITE],
                     site_fetcher=FakeFetcher({SITE: page}),
                     promotion_driver=PromotionDriver(qa, FilesTransport(tmp_path / "sot")))
    with TestClient(app) as c:
        html = c.post("/site/update").text

    assert "names no works" in html
    assert "http://visualartsdna.org/work/" in html
    assert "domain" in html, "and it points at the setting to check"


def test_the_page_describes_the_rule_it_actually_APPLIES(client):
    """Prose outlived the rule once already: the page still advertised the
    3D-viewer link and the bare CURIE a day after both were dropped, so it was
    telling the user to expect matches that could not happen.

    The base is now rendered from the same namespace the matcher is built from,
    and the dropped forms must not reappear in the copy.
    """
    c, _qa, _f = client
    html = c.get("/site/update").text

    assert "http://visualartsdna.org/work/&lt;guid&gt;" in html
    assert "3D-viewer" not in html
    assert "written as text" not in html
