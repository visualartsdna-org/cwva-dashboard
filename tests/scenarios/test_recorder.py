"""Recording a session, and replaying what was recorded.

The only test that proves a recording is worth keeping: drive the app the way
a person does, record it, then replay the result into a FRESH sandbox and
assert it lands in the same place. A recorder whose output does not replay is
a log.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cwva_dashboard import rson
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.driver import PromotionDriver
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.scenarios import Scenario, ScenarioEnv, assert_end_state, replay
from cwva_dashboard.scenarios.recorder import SCENARIO_DIR, Recorder, is_read_only
from cwva_dashboard.tools.fileops_tools import build_default_registry
from cwva_dashboard.tools.record_tools import documents_base, image_base

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

WORK = {
    "guid": "w1", "type": "Watercolor", "label": "Sunrise",
    "description": "A study.", "height": 9, "width": 12, "units": "inch",
    "recorded_date": "2026-07-18", "completed_date": "2026-07-17",
    "has_paper": "the:StrathmoreColdPress", "has_artist_profile": "work:artist",
    "image": "sunrise.jpg",
}


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    qa = QAGit.init(qa_root)
    layout = Layout.default()
    app = create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        promotion_driver=PromotionDriver(
            qa, FilesTransport(tmp_path / "sot"), layout=layout,
            image_base=image_base(TEST_DOMAIN),
            documents_base=documents_base(TEST_DOMAIN)),
    )
    with TestClient(app) as c:
        yield c, qa_root


def _record_a_session(c):
    """A session shaped like a real one: the asset arrives, the record is
    written, the unit is reviewed and approved.

    The assets are written through the dashboard rather than placed in the
    fixture, so they are STEPS — a replay that did not recreate them would
    fail the asset-reference gate, which is the gate doing its job in both
    directions. Stand-in content, as the committed episodes use: the shape of
    the episode is the point, not the bytes.
    """
    c.post("/api/record/start", json={"name": "Round Trip",
                                      "description": "author one work"})
    for path in ("content/images/sunrise.jpg", "content/images/qrc_w1.jpg"):
        c.post("/api/tool/fs.write",
               json={"path": path, "text": "IMG", "make_parents": True})
    c.post("/api/tool/record.new_work", json=WORK)
    pv = c.post("/api/promotion/preview").json()
    assert "token" in pv, f"gates failed: {pv}"
    c.post("/api/promotion/approve", json={"token": pv["token"]})
    return c.post("/api/record/stop").json()


def _written(qa_root, name="roundtrip"):
    return Path(qa_root) / SCENARIO_DIR / f"{name}.rson"


# -- the round trip ----------------------------------------------------------


def test_a_recorded_session_REPLAYS_to_the_same_end_state(client, tmp_path):
    """The whole point. Everything else here is a detail of this."""
    c, qa_root = client
    out = _record_a_session(c)

    scenario = Scenario.from_dict(rson.load(str(Path(qa_root) / out["written"])))
    fresh = tmp_path / "replay"
    fresh.mkdir()
    env = ScenarioEnv(
        fileops=FileOps(Sandbox.open(fresh)),
        registry=build_default_registry(domain=TEST_DOMAIN),
        qa=QAGit.init(fresh),
        transport=FilesTransport(tmp_path / "sot_replay"),
    )

    replay(scenario, env)
    assert_end_state(scenario, env)


def test_the_recording_is_DRIVER_AGNOSTIC(client, qa_root=None):
    """The property Phase 5's "same scenarios, two drivers" rests on: bare op
    names and arguments, no HTTP, no form fields, no UI."""
    c, qa_root = client
    out = _record_a_session(c)
    scenario = Scenario.from_dict(rson.load(str(Path(qa_root) / out["written"])))

    for step in scenario.steps:
        assert isinstance(step.op, str) and isinstance(step.args, dict)
        assert "/" not in step.op and " " not in step.op


def test_it_records_the_PROMOTION_not_only_the_authoring(client):
    """The promotion tail is law 1 machinery and deliberately not a registry
    tool, so it does not pass through the dispatch hook. A session recorded
    without it authors a record and never distributes it."""
    c, qa_root = client
    out = _record_a_session(c)
    scenario = rson.load(str(Path(qa_root) / out["written"]))

    assert [s["op"] for s in scenario["steps"]] == [
        "fs.write", "fs.write", "record.new_work", "workflow.promote"]


def test_the_ARGUMENTS_are_kept_verbatim(client):
    """A recording keeps what the audit log elides — `"definition":
    "<315 chars>"` is right for an audit and useless for a replay."""
    c, qa_root = client
    out = _record_a_session(c)
    scenario = rson.load(str(Path(qa_root) / out["written"]))

    step = next(s for s in scenario["steps"] if s["op"] == "record.new_work")
    assert step["args"]["label"] == "Sunrise"
    assert step["args"]["description"] == "A study."


def test_the_END_STATE_is_captured(client):
    c, qa_root = client
    out = _record_a_session(c)
    scenario = rson.load(str(Path(qa_root) / out["written"]))

    assert scenario["expected"]["qa_clean"] is True
    assert any(p.endswith("w1.ttl") for p in scenario["expected"]["sot"])


# -- what it drops, and why --------------------------------------------------


def test_READS_are_dropped(client):
    """1622 tool calls in a production day, 23 of them authoring. A replay
    does not need the reads: the state they observe is produced by the writes
    around them."""
    c, qa_root = client
    c.post("/api/record/start", json={"name": "reads"})
    c.post("/api/tool/record.list_editable", json={"kind": "work"})
    c.post("/api/tool/fs.list", json={"path": "."})
    out = c.post("/api/record/stop").json()

    assert out["steps"] == 0
    assert out["reads_dropped"] == 2


def test_a_FAILED_call_is_not_recorded(client):
    """It changed nothing, so replaying it would assert a failure the scenario
    format cannot express."""
    c, qa_root = client
    c.post("/api/record/start", json={"name": "failed"})
    c.post("/api/tool/record.new_work", json={"guid": "x"})   # missing fields

    assert c.post("/api/record/stop").json()["steps"] == 0


def test_every_registry_tool_is_CLASSIFIED(client):
    """A new tool must land on one side or the other deliberately. The rule is
    derived from the name, so this is what notices when a name stops carrying
    its verb."""
    names = set(build_default_registry(domain=TEST_DOMAIN).names())
    reads = {n for n in names if is_read_only(n)}

    assert reads, "something must be classified as a read"
    assert len(reads) < len(names), "and something must be kept"
    for n in reads:
        assert not any(n.rsplit(".", 1)[-1].startswith(v)
                       for v in ("new_", "write_", "edit_", "set_")), n


# -- the lifecycle -----------------------------------------------------------


def test_recording_is_OFF_until_asked(client):
    c, _ = client

    assert c.get("/api/record").json() == {"recording": False}


def test_two_recordings_at_once_are_REFUSED(client):
    """Slicing one session out of two overlapping ones is a guess, and the
    point of an explicit start is to remove the guess."""
    c, _ = client
    c.post("/api/record/start", json={"name": "one"})

    r = c.post("/api/record/start", json={"name": "two"})

    assert r.status_code == 409


def test_stopping_when_not_recording_is_REFUSED(client):
    c, _ = client

    assert c.post("/api/record/stop").status_code == 409


def test_it_lands_in_the_SANDBOX_not_the_project(client):
    """The dashboard cannot write to the project tree (law 1), and whether a
    session becomes a committed fixture is a decision a person makes."""
    c, qa_root = client
    out = _record_a_session(c)

    assert out["written"].startswith(".qa/")
    assert (Path(qa_root) / out["written"]).is_file()
    assert "Copy it to tests/scenarios/" in out["note"]


def test_a_recorder_drops_reads_without_an_app():
    """The unit beneath all of the above."""
    rec = Recorder(name="x")
    rec.step("record.new_work", {"a": 1})
    rec.step("workflow.state", {})

    assert [s["op"] for s in rec.steps] == ["record.new_work"]
    assert rec.dropped == 1



# -- saved as it goes (2026-11-24) -------------------------------------------
#
# A whole session held only in memory was erased by a production restart. The
# test that matters below is the restart: a second app on the same sandbox and
# audit log, which is exactly what restarting the dashboard is.


def _journal(tmp_path, qa_root):
    return tmp_path / f"recording-{Path(qa_root).name}.jsonl"


def _app(tmp_path, qa_root):
    layout = Layout.default()
    return create_app(
        domain=TEST_DOMAIN, sandbox_root=qa_root, enforce_landlock=False,
        audit_path=tmp_path / "audit.jsonl",
        promotion_driver=PromotionDriver(
            QAGit(root=qa_root), FilesTransport(tmp_path / "sot"), layout=layout,
            image_base=image_base(TEST_DOMAIN), documents_base=documents_base(TEST_DOMAIN)))


def test_each_step_is_on_disk_before_the_request_returns(client, tmp_path):
    c, qa_root = client
    c.post("/api/record/start", json={"name": "durable"})
    c.post("/api/tool/fs.write", json={"path": "a.txt", "text": "x", "make_parents": True})

    lines = [json.loads(l) for l in _journal(tmp_path, qa_root).read_text().splitlines()]
    assert [l["type"] for l in lines] == ["start", "step"]
    assert lines[1]["op"] == "fs.write" and lines[1]["args"]["text"] == "x"
    assert c.get("/api/record").json()["saved_as_it_goes"] is True


def test_a_restart_resumes_the_recording_with_every_step(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    QAGit.init(qa_root)
    with TestClient(_app(tmp_path, qa_root)) as c:
        c.post("/api/record/start", json={"name": "Long Session"})
        c.post("/api/tool/fs.write", json={"path": "one.txt", "text": "1", "make_parents": True})
        c.get("/api/tool/fs.list")  # a read: dropped, counted
    # ... the dashboard stops and starts again ...
    with TestClient(_app(tmp_path, qa_root)) as c:
        status = c.get("/api/record").json()
        assert status["recording"] and status["name"] == "long_session"
        assert status["ops"] == ["fs.write"] and len(status["resumed"]) == 1
        c.post("/api/tool/fs.write", json={"path": "two.txt", "text": "2", "make_parents": True})
        out = c.post("/api/record/stop").json()

    assert out["steps"] == 2 and len(out["resumed"]) == 1
    scenario = rson.load(str(_written(qa_root, "long_session")))
    assert [s["args"]["path"] for s in scenario["steps"]] == ["one.txt", "two.txt"]
    assert scenario["recorded"]["resumed"], "the restart is noted in the recording"
    assert not _journal(tmp_path, qa_root).exists(), "stop removes the journal"


def test_starting_while_a_resumed_recording_is_open_is_refused(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    QAGit.init(qa_root)
    with TestClient(_app(tmp_path, qa_root)) as c:
        c.post("/api/record/start", json={"name": "first"})
    with TestClient(_app(tmp_path, qa_root)) as c:
        assert c.post("/api/record/start", json={"name": "second"}).status_code == 409


def test_a_line_cut_short_by_a_crash_is_skipped_not_fatal(tmp_path):
    j = tmp_path / "recording-x.jsonl"
    j.write_text('{"type": "start", "name": "s", "started_at": 1}\n'
                 '{"type": "step", "op": "fs.write", "args": {"path": "a"}, "dropped": 3}\n'
                 '{"type": "step", "op": "fs.wr')
    rec = Recorder.resume(j)
    assert rec.name == "s" and [s["args"]["path"] for s in rec.steps] == ["a"]
    assert rec.dropped == 3


def test_no_journal_no_recording(tmp_path):
    assert Recorder.resume(tmp_path / "absent.jsonl") is None
