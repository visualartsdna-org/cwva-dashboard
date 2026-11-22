"""A0 over HTTP: the promotion tail is drivable by a human, and the review stop
survives the trip through the web layer.

These routes are deliberately **not** registry tools — promotion is the single
gated exit and stays in the trusted orchestrator (law 1) — so they are tested
against the app directly rather than through the dispatch contract.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

TTL = "@prefix ex: <http://example.org/> .\nex:a ex:b ex:c .\n"


@pytest.fixture
def app_env(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    sot = FilesTransport(tmp_path / "sot")
    driver = PromotionDriver(qa, sot)
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root,
        enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        promotion_driver=driver,
    )
    with TestClient(app) as client:
        yield client, qa, sot


def _stage(qa, rel="content/ttl/data/w1.ttl", body=TTL):
    p = qa.root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_preview_returns_a_token_and_converges_nothing(app_env):
    client, qa, sot = app_env
    _stage(qa)

    r = client.post("/api/promotion/preview", json={"workflow": "entry"})

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "previewed" and body["token"]
    assert list(sot.target.rglob("*.ttl")) == []


def test_approve_is_the_only_path_that_converges(app_env):
    client, qa, sot = app_env
    _stage(qa)
    token = client.post("/api/promotion/preview", json={}).json()["token"]

    r = client.post("/api/promotion/approve", json={"token": token})

    assert r.status_code == 200
    assert r.json()["status"] == "converged"
    assert (sot.target / "content/ttl/data/w1.ttl").exists()


def test_reject_leaves_sot_untouched(app_env):
    client, qa, sot = app_env
    _stage(qa)
    token = client.post("/api/promotion/preview", json={}).json()["token"]

    r = client.post("/api/promotion/reject", json={"token": token})

    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert list(sot.target.rglob("*.ttl")) == []
    assert client.get("/api/promotion/pending").json()["pending"] == []


def test_stale_approval_is_refused_with_409(app_env):
    """The reviewed change is no longer what is on disk, so approving it is a
    conflict — not a success, and certainly not a convergence."""
    client, qa, sot = app_env
    _stage(qa)
    token = client.post("/api/promotion/preview", json={}).json()["token"]
    _stage(qa, "content/ttl/data/w2.ttl")  # tree moves under the approval

    r = client.post("/api/promotion/approve", json={"token": token})

    assert r.status_code == 409
    assert r.json()["status"] == "stale"
    assert list(sot.target.rglob("*.ttl")) == []


def test_unknown_token_is_a_conflict_not_a_crash(app_env):
    client, _, _ = app_env
    r = client.post("/api/promotion/approve", json={"token": "nope"})
    assert r.status_code == 409


def test_token_is_required(app_env):
    client, _, _ = app_env
    assert client.post("/api/promotion/approve", json={}).status_code == 400


def test_refresh_is_drivable(app_env):
    """The other half of every workflow tail: state must flow across a refresh
    between dependency-ordered steps."""
    client, qa, sot = app_env
    _stage(qa)
    token = client.post("/api/promotion/preview", json={}).json()["token"]
    client.post("/api/promotion/approve", json={"token": token})

    r = client.get("/api/refresh")

    assert r.status_code == 200
    assert r.json() == {"status": "OK"}
    assert (qa.root / "content/ttl/data/w1.ttl").exists()


def test_routes_503_when_no_target_is_configured(tmp_path):
    """A dashboard with nothing synced still starts and is useful; the promotion
    routes just say so rather than half-working."""
    qa_root = tmp_path / "qa2"
    qa_root.mkdir()
    app = create_app(
        domain=TEST_DOMAIN,
        sandbox_root=qa_root, enforce_landlock=False, audit_path=tmp_path / "a.jsonl"
    )
    with TestClient(app) as client:
        assert client.post("/api/promotion/preview", json={}).status_code == 503
        assert client.get("/api/refresh").status_code == 503


# -- discard work in progress ------------------------------------------------


def _stage_two(qa):
    _stage(qa, "content/ttl/data/w1.ttl")
    _stage(qa, "content/ttl/data/w2.ttl")


def test_discard_page_lists_what_would_be_thrown_away(app_env):
    """A bare 'are you sure?' is worse than nothing here — the pile is usually
    bigger than the user remembers."""
    client, qa, _ = app_env
    _stage_two(qa)

    r = client.get("/wip/discard")

    assert r.status_code == 200
    assert "This will be thrown away" in r.text
    assert "content/ttl/data/w1.ttl" in r.text
    assert "content/ttl/data/w2.ttl" in r.text
    assert "cannot be undone" in r.text


def test_the_confirm_page_does_not_discard(app_env):
    """GET shows, POST acts — a page view must never be destructive."""
    client, qa, _ = app_env
    _stage_two(qa)

    client.get("/wip/discard")

    assert (qa.root / "content/ttl/data/w1.ttl").exists()


def test_posting_discards_and_reports(app_env):
    client, qa, sot = app_env
    _stage_two(qa)

    r = client.post("/wip/discard")

    assert r.status_code == 200 and "Discarded" in r.text
    assert not (qa.root / "content/ttl/data/w1.ttl").exists()
    assert not (qa.root / "content/ttl/data/w2.ttl").exists()


def test_discard_leaves_distributed_work_alone(app_env):
    """Committed and converged records are rollback's business, not discard's."""
    client, qa, sot = app_env
    _stage(qa, "content/ttl/data/kept.ttl")
    token = client.post("/api/promotion/preview", json={}).json()["token"]
    client.post("/api/promotion/approve", json={"token": token})

    _stage(qa, "content/ttl/data/scratch.ttl")
    client.post("/wip/discard")

    assert (sot.target / "content/ttl/data/kept.ttl").exists()
    assert (qa.root / "content/ttl/data/kept.ttl").exists()
    assert not (qa.root / "content/ttl/data/scratch.ttl").exists()


def test_clean_tree_says_nothing_to_discard(app_env):
    client, _, _ = app_env
    r = client.get("/wip/discard")
    assert "Nothing to discard" in r.text


def test_api_wip_reports_the_uncommitted_change(app_env):
    client, qa, _ = app_env
    _stage_two(qa)

    body = client.get("/api/wip").json()

    assert body["clean"] is False and body["counts"]["adds"] == 2


def test_review_page_offers_edit_form_not_reject():
    """Reject only abandoned the promotion and left the record in QA for the
    next one to sweep up. The useful action after reviewing your own entry is
    "let me fix that", so the review page offers Edit form and, separately, the
    way to clear everything uncommitted."""
    from cwva_dashboard.ux.forms import render_review_page

    html = render_review_page(preview={"status": "previewed", "token": "t", "gates": []})

    assert "/rdf/entry/edit" in html
    assert "Edit form" in html
    assert ">Reject<" not in html
    assert "/wip/discard" in html


# -- Preview Staged (Immediate Actions) ---------------------------------------
# The review stop reached from the STAGED TREE rather than from a form. Rick,
# 2026-09-17: "go ahead and wire the card Preview Staged … we need it
# eventually." The case it answers is work nothing is holding open — a session
# abandoned before approve, or (Phase 5) an agent that wrote while nobody was
# looking. Until it existed, the only way to distribute that was to write
# something else and approve THAT, which promotes the whole tree as a side
# effect: the right outcome reached by a route nobody could explain.


def test_preview_staged_shows_the_review_stop_for_work_no_form_is_holding(app_env):
    client, qa, sot = app_env
    _stage(qa)

    r = client.get("/staged/preview")

    assert r.status_code == 200
    assert "Change preview" in r.text and "Approve &amp; distribute" in r.text


def test_preview_staged_CONVERGES_NOTHING(app_env):
    """It is a GET, and a GET that published would be a mutating link on a page
    a browser may prefetch."""
    client, qa, sot = app_env
    _stage(qa)

    client.get("/staged/preview")

    assert not (sot.target / "content/ttl/data/w1.ttl").exists()


def test_the_token_from_it_approves_through_the_ORDINARY_exit(app_env):
    """No second gated exit: the button on that page posts the same token to
    the same approve route every form uses (law 1)."""
    client, qa, sot = app_env
    _stage(qa)

    page = client.get("/staged/preview").text
    token = page.split('name="token" value="', 1)[1].split('"', 1)[0]
    r = client.post("/rdf/entry/approve", data={"token": token})

    assert r.status_code == 200
    assert (sot.target / "content/ttl/data/w1.ttl").exists()


def test_an_EMPTY_tree_says_so_instead_of_offering_a_button(app_env):
    """The usual state of a store is that everything in it has been
    distributed, so this is the ordinary answer here, not an edge case."""
    client, _qa, _sot = app_env

    r = client.get("/staged/preview")

    assert "Nothing is staged" in r.text
    assert "Approve &amp; distribute" not in r.text


def test_it_offers_the_DASHBOARD_back_not_a_form_it_never_came_from(app_env):
    client, qa, _sot = app_env
    _stage(qa)

    r = client.get("/staged/preview")

    assert "Edit form" not in r.text
