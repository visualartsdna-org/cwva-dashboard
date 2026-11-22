"""Instance Control wired from function.html's Monitoring tab.

Status / Refresh / Metrics across the configured servers, fired together and
reported per card. No Stop and no Charts — neither has a route, so they are
absent rather than unimplemented-but-linked.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import threading
import time

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.instances import InstanceTarget
from cwva_dashboard.main import create_app

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

TARGETS = [
    InstanceTarget("visualartsdna.org", "https://visualartsdna.org", "instance-1"),
    InstanceTarget("localhost", "http://localhost", "pc"),
    InstanceTarget("localhost:8081", "http://localhost:8081", "pc"),
]


@pytest.fixture
def secrets(tmp_path):
    p = tmp_path / "secrets.rson"
    p.write_text('{"secrets": {"phrase": "open sesame"}}')
    return str(p)


@pytest.fixture
def client(tmp_path, secrets):
    calls: list[str] = []

    # OVERLAP, not wall clock. The parallel test used to assert "faster than
    # serial would be", with a 0.03s margin between 0.12 and 0.15 — which a
    # loaded machine eats, so a true result failed during an unrelated full-
    # suite run (2026-09-29). Counting how many calls are in flight at once
    # measures the property directly and cannot be lost to scheduling noise.
    live = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def opener(url, timeout):
        calls.append(url)
        with lock:
            live["now"] += 1
            live["peak"] = max(live["peak"], live["now"])
        time.sleep(0.05)
        with lock:
            live["now"] -= 1
        return 200, b'{"status":"OK"}'

    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        instances={"targets": TARGETS, "secrets_path": secrets, "timeout_s": 5},
        instance_opener=opener,
    )
    with TestClient(app) as c:
        yield c, calls, tmp_path, live


def test_the_hub_card_resolves_and_offers_three_actions(client):
    c, _calls, _tmp, _live = client
    hub = c.get("/").text

    assert 'href="instances"' in hub
    page = c.get("/instances")
    assert page.status_code == 200
    for action in ("Status", "Refresh", "Metrics"):
        assert action in page.text


def test_all_three_servers_are_shown_with_the_8081_port(client):
    """Rick: keep the three servers, change localhost:8080 to localhost:8081."""
    c, _calls, _tmp, _live = client
    html = c.get("/instances").text

    assert "https://visualartsdna.org" in html
    assert "http://localhost:8081" in html
    assert ":8080" not in html


def test_STOP_and_CHARTS_are_absent_from_the_page(client):
    c, _calls, _tmp, _live = client
    html = c.get("/instances").text

    assert "Stop" not in html
    assert "Charts" not in html and "statsChart" not in html


def test_stop_has_no_route_at_all(client):
    """Not hidden — unreachable. The server's shutdown command has no code path
    from the dashboard."""
    c, _calls, _tmp, _live = client

    r = c.post("/api/instances/cestfini?target=localhost")

    assert r.status_code == 404
    assert r.json()["actions"] == ["status", "refresh", "metrics"]


def test_a_target_not_in_config_is_refused(client):
    """The minted token authenticates against whatever host it reaches, so a
    caller may name a target but never a URL."""
    c, calls, _tmp, _live = client

    r = c.post("/api/instances/status?target=http://evil.example")

    assert r.status_code == 404
    assert "no configured instance" in r.json()["error"]
    assert calls == [], "and nothing was fetched"


def test_one_target_runs_just_that_server(client):
    c, calls, _tmp, _live = client

    body = c.post("/api/instances/refresh?target=localhost:8081").json()

    assert [r["name"] for r in body["results"]] == ["localhost:8081"]
    assert len(calls) == 1 and calls[0].startswith("http://localhost:8081/cmd?")


def test_no_target_runs_them_ALL_IN_PARALLEL(client):
    """Serially, a refresh of three servers is three full RDF reloads of
    waiting."""
    c, calls, _tmp, live = client

    body = c.post("/api/instances/refresh").json()

    assert [r["name"] for r in body["results"]] == [t.name for t in TARGETS]
    assert len(calls) == 3
    # OVERLAP >= 2 is the property: not serial. Demanding all three at once
    # is stricter than the claim and still loses to scheduling — on a loaded
    # machine one 0.05s call can finish before the third starts, which is
    # parallel execution reporting itself as a failure.
    assert live["peak"] >= 2, "the calls ran one after another"


def test_each_result_stands_alone(client, tmp_path, secrets):
    """Displayed individually, so one unreachable server does not hide the
    others' answers."""
    def selective(url, timeout):
        if "visualartsdna" in url:
            raise OSError("unreachable")
        return 200, b'{"status":"OK"}'

    qa_root = tmp_path / "qa2"
    qa_root.mkdir()
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root,
                     enforce_landlock=False, audit_path=tmp_path / "a2.jsonl",
                     instances={"targets": TARGETS, "secrets_path": secrets, "timeout_s": 5},
                     instance_opener=selective)
    with TestClient(app) as c2:
        results = c2.post("/api/instances/status").json()["results"]

    assert [r["ok"] for r in results] == [False, True, True]
    assert "unreachable" in results[0]["error"]


def test_a_missing_secrets_file_is_one_error_not_three(client, tmp_path):
    """A deployment fault, not three servers being down."""
    qa_root = tmp_path / "qa3"
    qa_root.mkdir()
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root,
                     enforce_landlock=False, audit_path=tmp_path / "a3.jsonl",
                     instances={"targets": TARGETS,
                                "secrets_path": str(tmp_path / "absent.rson"),
                                "timeout_s": 5})
    with TestClient(app) as c3:
        r = c3.post("/api/instances/status")

    assert r.status_code == 503
    assert "secrets" in r.json()["error"]


def test_the_call_is_audited_without_the_token(client):
    """An append-only hash-chained log is exactly the wrong place for a live
    credential."""
    c, _calls, tmp, _live = client
    c.post("/api/instances/status?target=localhost")

    log = (tmp / "audit.jsonl").read_text()
    assert "instance.command" in log
    assert "token" not in log


def test_no_instances_configured_says_so(tmp_path):
    qa_root = tmp_path / "qa4"
    qa_root.mkdir()
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root,
                     enforce_landlock=False, audit_path=tmp_path / "a4.jsonl",
                     instances={"targets": [], "secrets_path": "x", "timeout_s": 5})
    with TestClient(app) as c:
        assert "No instances configured" in c.get("/instances").text
        assert c.post("/api/instances/status").status_code == 404


# ---------------------------------------------------------------------------
# Getting there.
#
# Rick reached Instance Control only by clicking a per-server button on the hub
# — every one of which linked to the bare page, so "Refresh on the PC" meant
# navigating and then hunting for the right card.
# ---------------------------------------------------------------------------

HUB = pathlib.Path(__file__).resolve().parents[2] / "html" / "function.html"


def test_MONITORING_is_this_page():
    """Rick: "The two pages must be resolved into one." The hub's Monitoring tab
    was a second, static copy of Instance Control whose buttons only linked
    here — and it still advertised Stop, Charts and :8080."""
    hub = HUB.read_text()

    assert '<a class="nav-tab" href="instances">Monitoring</a>' in hub
    assert 'data-tab="monitoring"' not in hub
    assert '<div id="monitoring"' not in hub


def test_the_hub_holds_no_second_copy_of_the_cards():
    hub = HUB.read_text()

    assert "instance-card" not in hub and "instance-grid" not in hub
    assert "addInstance" not in hub, "the card factory built for a grid that is gone"
    assert "statsChart" not in hub and "statsReport" not in hub


def test_a_nav_item_that_is_a_link_does_not_break_the_other_tabs():
    """The tab handler switches on data-tab; the Monitoring item no longer has
    one, and `getElementById(undefined)` would throw and take Content, Tools and
    Files with it."""
    hub = HUB.read_text()

    assert "if (!tabId) { return; }" in hub
    for still_a_tab in ("content", "tools", "files"):
        assert f'data-tab="{still_a_tab}"' in hub


def test_the_page_runs_NOTHING_until_a_button_is_clicked(client):
    """It is a landing page now — the hub's Monitoring item goes straight here,
    and a GET that reloaded a server's RDF store would also fire on a browser
    prefetch or a back button."""
    c, calls, _tmp, _live = client

    html = c.get("/instances").text

    assert 'id="srv-localhost-8081"' in html, "each card is anchorable"
    assert calls == [], "nothing was called by arriving"


# -- how old is the refresh ---------------------------------------------------


def _refresh_line(html, slug):
    card = html[html.index(f'id="srv-{slug}"'):]
    return re.search(r'class="instance-refreshed.*?</div>', card, re.S).group(0)


def test_no_refresh_yet_says_so_and_status_does_not_count(client):
    c, _calls, _tmp, _live = client
    c.post("/api/instances/status?target=localhost")

    assert "none recorded" in _refresh_line(c.get("/instances").text, "localhost")


def test_a_refresh_is_timed_per_target_and_survives_a_reload(client):
    c, _calls, _tmp, _live = client

    r = c.post("/api/instances/refresh?target=localhost").json()["results"][0]

    assert r["last_refresh"]["confirmed"] is True
    html = c.get("/instances").text
    assert f'data-at="{r["last_refresh"]["at"]}"' in _refresh_line(html, "localhost")
    assert "none recorded" in _refresh_line(html, "localhost-8081"), "not the others"


def test_status_reports_the_time_of_the_last_refresh(client):
    c, _calls, _tmp, _live = client
    at = c.post("/api/instances/refresh?target=localhost").json()["results"][0]["last_refresh"]

    r = c.post("/api/instances/status?target=localhost").json()["results"][0]

    assert r["last_refresh"] == at


def test_two_dashboards_on_one_machine_share_the_times(client, secrets):
    """QA and production refresh the same servers from separate audit logs."""
    c, _calls, tmp, _live = client
    at = c.post("/api/instances/refresh?target=localhost").json()["results"][0]["last_refresh"]
    root = tmp / "other"
    root.mkdir()
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
        audit_path=tmp / "audit-other.jsonl",
        instances={"targets": TARGETS, "secrets_path": secrets, "timeout_s": 5},
        instance_opener=lambda url, timeout: (200, b"{}"),
    )
    with TestClient(app) as other:
        assert at["at"] in _refresh_line(other.get("/instances").text, "localhost")


def test_a_failed_refresh_keeps_the_older_time(tmp_path):
    from cwva_dashboard.instances import load_refreshes, record_refreshes

    state = tmp_path / "times.json"
    ok = {"action": "refresh", "ok": True, "empty": False, "name": "a"}
    record_refreshes(state, [ok])
    before = load_refreshes(state)

    record_refreshes(state, [{**ok, "ok": False}])

    assert load_refreshes(state) == before


def test_an_empty_answer_is_recorded_as_unconfirmed(tmp_path):
    """The Groovy server answers a completed refresh and a rejected token alike."""
    from cwva_dashboard.instances import load_refreshes, record_refreshes

    state = tmp_path / "times.json"
    record_refreshes(state, [{"action": "refresh", "ok": True, "empty": True, "name": "g"}])

    assert load_refreshes(state)["g"]["confirmed"] is False


def test_a_damaged_times_file_does_not_take_the_page_down(client):
    c, _calls, tmp, _live = client
    (tmp / "instance-refreshes.json").write_text("{not json")

    assert c.get("/instances").status_code == 200
