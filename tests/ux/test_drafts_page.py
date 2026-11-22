"""Drafts, on the hub and on a page of their own.

Rick, 2026-09-18: "we need to treat drafts as first-class citizens. They need to
have their own card for review and management, and there needs to be a visible
drafts status on the Content page … some way to stay on top of them."

Before this, the way you found out you had three drafts was that all three
converged together with whatever you approved next.
"""

from __future__ import annotations

import re
import shutil

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.tools.record_tools import image_base

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

GUID = "a6671c83-4ebc-4c2d-84f2-8671d2c8e597"
OTHER = "b7782d94-5fcd-4e3d-9583-9782e3d9a608"

REC = """@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix vad: <http://visualartsdna.org/model/> .
@prefix work: <http://visualartsdna.org/work/> .
work:{guid} a vad:Watercolor ; rdfs:label "{label}" .
"""


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    lay = Layout.default()
    (qa_root / lay.dir("work_ttl")).mkdir(parents=True)
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=lay,
            image_base=image_base(TEST_DOMAIN),
        ),
    )
    with TestClient(app) as c:
        yield c, qa


def _draft(qa, guid=GUID, label="Spirited Tree"):
    p = qa.root / Layout.default().dir("work_ttl") / f"{guid}.ttl"
    p.write_text(REC.format(guid=guid, label=label))
    return p


def test_the_hub_card_SHOWS_THE_COUNT(client):
    c, qa = client
    assert "Nothing undistributed" in c.get("/").text

    _draft(qa)
    _draft(qa, OTHER, "Another")

    hub = c.get("/").text
    assert "Drafts &mdash; 2" in hub
    assert 'href="drafts"' in hub


def test_the_page_lists_them_BY_NAME(client):
    c, qa = client
    _draft(qa)

    html = c.get("/drafts").text

    assert "Spirited Tree" in html
    assert "Watercolor" in html
    assert "new" in html


def test_a_draft_links_back_to_ITS_EDITOR(client):
    c, qa = client
    _draft(qa)

    html = c.get("/drafts").text

    assert f'href="/edit/open?path=content/ttl/data/{GUID}.ttl"' in html


def test_DISCARD_SELECTED_removes_one_and_leaves_the_rest(client):
    c, qa = client
    _draft(qa, GUID, "Throw me")
    _draft(qa, OTHER, "Keep me")

    r = c.post("/drafts/discard", data={"guid": GUID})

    assert "Discarded: Throw me" in r.text
    assert "Keep me" in r.text
    assert not (qa.root / Layout.default().dir("work_ttl") / f"{GUID}.ttl").exists()


def test_DISCARD_ALL_empties_the_page(client):
    """"After review of a number of drafts a user may say, discard them all." """
    c, qa = client
    _draft(qa, GUID, "One")
    _draft(qa, OTHER, "Two")

    r = c.post("/drafts/discard", data={"all": "1"})

    assert "No drafts" in r.text
    assert c.get("/").text.count("Nothing undistributed") == 1


def test_an_EMPTY_page_says_so_rather_than_showing_a_list(client):
    c, _qa = client

    assert "No drafts" in c.get("/drafts").text


def test_the_page_distinguishes_the_TWO_DISCARDS(client):
    """One undoes the session, the other undoes the draft. A page that offered
    both under one word would be asking the user to guess."""
    c, qa = client
    _draft(qa)

    html = c.get("/drafts").text

    assert "last distributed version" in html
    assert "Discard changes" in html and "only the session" in html


def test_REVIEWING_a_draft_shows_its_triples(client):
    """The list answers "what have I got"; this answers "what does it SAY",
    which is the question you have to answer before discarding something."""
    c, qa = client
    _draft(qa)

    html = c.get(f"/drafts/view?guid={GUID}").text

    assert "Spirited Tree" in html
    assert "rdfs:label" in html, "the record as written"
    assert "New record" in html and "none of it distributed yet" in html


def test_REVIEWING_a_modified_draft_shows_the_DIFF(client):
    c, qa = client
    _draft(qa, GUID, "As distributed")
    qa.stage_all(); qa.commit("distributed")
    _draft(qa, GUID, "Renamed since")

    html = c.get(f"/drafts/view?guid={GUID}").text

    assert "Change since it was last distributed" in html
    assert "1 added, 1 removed" in html
    assert "Renamed since" in html and "As distributed" in html
    assert "Compared as GRAPHS" in html


def test_the_draft_page_can_DISCARD_that_one(client):
    c, qa = client
    _draft(qa, GUID, "Throw me")
    _draft(qa, OTHER, "Keep me")

    r = c.post("/drafts/discard", data={"guid": GUID})

    assert "Discarded: Throw me" in r.text and "Keep me" in r.text


def test_a_draft_that_is_GONE_says_so_rather_than_500ing(client):
    c, _qa = client

    r = c.get("/drafts/view?guid=nope")

    assert r.status_code == 404 and "No such draft" in r.text


def test_the_list_links_to_the_review(client):
    c, qa = client
    _draft(qa)

    assert f'href="/drafts/view?guid={GUID}"' in c.get("/drafts").text


# -- Refresh: confirm before a deletion (Rick, 2026-09-26) --------------------
# `/api/refresh` had no card and no confirmation, which was tolerable while a
# refresh was rare. With a second instance and the legacy dashboard publishing
# to the same SOT it is routine — and it is the single action that silently
# destroys drafts.


def test_the_hub_offers_REFRESH(client):
    c, _qa = client

    assert 'href="refresh"' in c.get("/").text


def test_the_refresh_page_SHOWS_WHAT_WOULD_BE_LOST(client):
    c, qa = client
    _draft(qa, GUID, "About to vanish")

    html = c.get("/refresh").text

    assert "About to vanish" in html
    assert "will delete work that has not been distributed" in html
    assert 'action="/refresh"' in html


def test_it_says_so_when_NOTHING_would_be_lost(client):
    c, _qa = client

    html = c.get("/refresh").text

    assert "Nothing is staged" in html


def test_the_page_names_the_INSTANCE(client):
    """Two dashboards, and this is the destructive button on both."""
    c, _qa = client
    c.app.state.environment = {"label": "PRODUCTION", "colour": "amber"}

    assert "PRODUCTION" in c.get("/refresh").text


def test_REFRESHING_discards_the_draft_and_reports(client):
    c, qa = client
    path = _draft(qa)

    r = c.post("/refresh")

    assert r.status_code == 200 and "Refreshed" in r.text
    assert not path.exists()


# -- the batch workflow (Rick, 2026-09-27) ------------------------------------
# Make four related records, each stopping short of approval, review them
# together for connectedness, approve once. A promotion unit is everything
# uncommitted in the QA tree, so approving once at the end is the normal case
# rather than a workaround — but it needed a way to say "keep this and carry
# on", and a way to see that the records point at each other.


def test_the_review_offers_LEAVE_IT_STAGED(client):
    c, qa = client
    _draft(qa)

    r = c.get("/staged/preview")

    assert 'action="/episode/stage"' in r.text
    assert "Leave it staged" in r.text


def test_LEAVING_BY_A_LINK_never_destroys(client):
    """The first version discarded on OK, which made "go to the dashboard and
    make the next record" the one gesture that threw a record away."""
    c, qa = client
    _draft(qa)

    html = c.get("/staged/preview").text

    assert "stays as a draft" in html
    assert "Discard it and leave?" not in html


def test_STAGING_keeps_the_record_and_clears_the_session(client):
    c, qa = client
    path = _draft(qa)
    c.app.state.promotion_driver.begin_episode("rdf_entity", "/rdf/entity")

    r = c.post("/episode/stage", follow_redirects=False)

    assert r.status_code == 303 and r.headers["location"] == "/drafts"
    assert path.exists(), "the record is kept"
    assert c.app.state.promotion_driver.open_episode() == {}, "the session is over"
    assert c.app.state.promotion_driver.pending() == [], "and so is the token"


def test_the_draft_page_names_WHAT_IT_POINTS_AT(client):
    """`vad:background work:a1b2c3…` cannot answer "is this connected the way I
    meant"; matching four records by GUID across four pages is work the
    dashboard should do."""
    c, qa = client
    _draft(qa, GUID, "Pillars background")
    lay = Layout.default()
    (qa.root / lay.dir("work_ttl") / f"{OTHER}.ttl").write_text(
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix vad: <http://visualartsdna.org/model/> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        f'work:{OTHER} a vad:BlenderComposition ; rdfs:label "The composition" ;\n'
        f"    vad:background work:{GUID} .\n"
    )

    comp = c.get(f"/drafts/view?guid={OTHER}").text
    assert "Points at" in comp
    assert "Pillars background" in comp, "by name, not by GUID"
    assert f'href="/drafts/view?guid={GUID}"' in comp

    back = c.get(f"/drafts/view?guid={GUID}").text
    assert "The composition" in back, "and the other direction"


def test_a_record_that_STANDS_ALONE_says_so(client):
    c, qa = client
    _draft(qa)

    html = c.get(f"/drafts/view?guid={GUID}").text

    assert "this record stands alone" in html
    assert "Nothing else staged refers to it" in html
