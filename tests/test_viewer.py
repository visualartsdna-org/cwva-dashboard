"""The cwva-py viewer: cwva-py run over a sandbox, read-only to it.

The confinement test does not need cwva-py: a stand-in `main.py` tries the
writes cwva-py's loader would make (delete the data folder, write a file in
it) and records what happened, inside a really-confined launch.
"""

from __future__ import annotations

import json
import platform
import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.viewer import Viewer, ViewerError, ViewerSettings

LAYOUT = Layout.default()


def _viewer(tmp_path, cwva=None, port=0, **kw) -> Viewer:
    sandbox = tmp_path / "sandbox"
    (sandbox / LAYOUT.dir("work_ttl")).mkdir(parents=True, exist_ok=True)
    settings = ViewerSettings(cwva_py=str(cwva or tmp_path / "cwva"),
                              python=sys.executable, port=port or _free_port(), **kw)
    return Viewer(settings, sandbox_root=sandbox, layout=LAYOUT, domain=TEST_DOMAIN,
                  scratch=tmp_path / "viewer-sandbox")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_generated_config_reaches_no_bucket_and_writes_nothing_in_the_sandbox(tmp_path):
    v = _viewer(tmp_path)
    cfg = v.cwva_config()
    assert cfg["cloud"] is None and cfg["referenceModel"] is None and cfg["agentUrl"] is None
    assert cfg["clobber"] is False
    sandbox = str(tmp_path / "sandbox")
    assert cfg["data"].startswith(sandbox) and cfg["images"].startswith(sandbox)
    # the two things cwva-py WRITES live outside it
    assert not cfg["thumbnails"].startswith(sandbox)
    assert not cfg["dir"].startswith(sandbox)


def test_the_environment_carries_no_bucket_or_credentials(tmp_path, monkeypatch):
    for k in ("GCP_BUCKET", "gcp_bucket", "GOOGLE_APPLICATION_CREDENTIALS",
              "ANTHROPIC_API_KEY", "GCP_TEST_BUCKET"):
        monkeypatch.setenv(k, "secret")
    env = _viewer(tmp_path)._env()
    assert not any(v == "secret" for v in env.values())


def test_a_scratch_folder_inside_the_sandbox_is_refused(tmp_path):
    (tmp_path / "sandbox").mkdir()
    with pytest.raises(ViewerError, match="outside the sandbox"):
        Viewer(ViewerSettings(), sandbox_root=tmp_path / "sandbox", layout=LAYOUT,
               domain=TEST_DOMAIN, scratch=tmp_path / "sandbox" / "viewer")


def test_no_cwva_py_is_a_message_not_a_crash(tmp_path):
    if platform.system() != "Linux":
        pytest.skip("Linux only")
    with pytest.raises(ViewerError, match="no cwva-py"):
        _viewer(tmp_path).start()


def test_a_busy_port_is_refused(tmp_path):
    if platform.system() != "Linux":
        pytest.skip("Linux only")
    cwva = tmp_path / "cwva"
    cwva.mkdir()
    (cwva / "main.py").write_text("")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        v = _viewer(tmp_path, cwva=cwva, port=s.getsockname()[1])
        with pytest.raises(ViewerError, match="already in use"):
            v.start()


STAND_IN = r'''
import json, os, shutil, sys
from pathlib import Path
cfg = json.loads(Path(sys.argv[2]).read_text())
out = {}
def attempt(name, fn):
    try:
        fn(); out[name] = "allowed"
    except OSError as e:
        out[name] = type(e).__name__
data = Path(cfg["data"])
attempt("write_in_sandbox", lambda: (data / "evil.ttl").write_text("x"))
attempt("delete_sandbox_data", lambda: shutil.rmtree(data))
attempt("read_sandbox", lambda: (data / "w1.ttl").read_text())
attempt("write_thumbnail", lambda: (Path(cfg["thumbnails"]) / "t.jpg").write_text("x"))
attempt("read_home_credentials", lambda: (Path(os.environ["HOME"]) / "creds.json").read_text())
out["cwd"] = os.getcwd()
(Path(cfg["dir"]) / "result.json").write_text(json.dumps(out))
'''


@pytest.mark.skipif(platform.system() != "Linux", reason="Landlock is Linux-only")
def test_the_launched_process_cannot_touch_the_sandbox(tmp_path, monkeypatch):
    from cwva_dashboard.sandbox.broker import landlock_abi

    if landlock_abi() < 1:
        pytest.skip("kernel without Landlock")
    home = tmp_path / "home"
    home.mkdir()
    (home / "creds.json").write_text("{}")
    monkeypatch.setenv("HOME", str(home))
    cwva = tmp_path / "cwva"
    cwva.mkdir()
    (cwva / "main.py").write_text(STAND_IN)
    v = _viewer(tmp_path, cwva=cwva)
    (v.sandbox / LAYOUT.dir("work_ttl") / "w1.ttl").write_text("draft")

    v.start()
    for _ in range(100):
        if v.status()["state"] != "loading":
            break
        time.sleep(0.1)
    result = json.loads((v.scratch / "result.json").read_text())

    assert result["write_in_sandbox"] == "PermissionError"
    assert result["delete_sandbox_data"] == "PermissionError"
    assert result["read_sandbox"] == "allowed"
    assert result["write_thumbnail"] == "allowed"
    assert result["read_home_credentials"] == "PermissionError"
    assert (v.sandbox / LAYOUT.dir("work_ttl") / "w1.ttl").read_text() == "draft"
    assert not (v.sandbox / LAYOUT.dir("work_ttl") / "evil.ttl").exists()
    v.stop()


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "qa"
    (root / LAYOUT.dir("work_ttl")).mkdir(parents=True)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl",
                     viewer=ViewerSettings(cwva_py=str(tmp_path / "no-cwva"), port=_free_port()))
    with TestClient(app) as c:
        yield c


def test_unconfigured_the_card_says_so(tmp_path):
    root = tmp_path / "qa"
    (root / LAYOUT.dir("work_ttl")).mkdir(parents=True)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        assert "Not configured" in c.get("/").text
        assert c.post("/api/viewer/start").status_code == 404


def test_starting_without_cwva_py_reports_why_and_is_audited(client, tmp_path):
    r = client.post("/api/viewer/start")
    assert r.status_code == 409 and "no cwva-py" in r.json()["error"]
    log = (tmp_path / "audit.jsonl").read_text()
    assert '"viewer.start"' in log


def test_the_hub_card_and_page_render_stopped(client):
    assert 'href="viewer"' in client.get("/").text
    page = client.get("/viewer").text
    assert "Start" in page and "Read-only" in page
    assert client.get("/api/viewer").json()["state"] == "stopped"


def test_the_viewer_scratch_is_beside_the_sandbox_not_in_it(client, tmp_path):
    v = client.app.state.viewer
    assert v.scratch.parent == tmp_path and v.scratch.name == "viewer-qa"


def test_an_unknown_action_is_refused(client):
    r = client.post("/api/viewer/cestfini")
    assert r.status_code == 404


def test_the_banner_names_the_instance_and_says_it_is_not_published(tmp_path):
    v = _viewer(tmp_path)
    assert v.banner.startswith("DASHBOARD VIEW")
    v = Viewer(v.settings, sandbox_root=v.sandbox, layout=LAYOUT, domain=TEST_DOMAIN,
               scratch=v.scratch, label="PRODUCTION", colour="amber")
    assert v.banner.startswith("PRODUCTION · DASHBOARD VIEW")
    assert "not published" in v.banner


def test_the_app_gives_the_viewer_the_instance_label(tmp_path):
    root = tmp_path / "qa"
    (root / LAYOUT.dir("work_ttl")).mkdir(parents=True)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl", viewer=ViewerSettings())
    # a pinned sandbox carries no config, so no label: the banner still shows
    assert app.state.viewer.banner.startswith("DASHBOARD VIEW")


SERVING_STAND_IN = r'''
import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, Response
from starlette.routing import Route
page = lambda r: HTMLResponse('<!DOCTYPE html><html><body class="x"><p>work</p></body></html>')
ttl = lambda r: Response("<a> <b> <c> .", media_type="text/turtle")
app = Starlette(routes=[Route("/", page), Route("/data", ttl)])
import json, sys
from pathlib import Path
port = json.loads(Path(sys.argv[2]).read_text())["port"]
uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
'''


@pytest.mark.skipif(platform.system() != "Linux", reason="Landlock is Linux-only")
def test_every_html_page_carries_the_banner_and_rdf_does_not(tmp_path):
    import urllib.request

    from cwva_dashboard.sandbox.broker import landlock_abi

    if landlock_abi() < 1:
        pytest.skip("kernel without Landlock")
    cwva = tmp_path / "cwva"
    cwva.mkdir()
    (cwva / "main.py").write_text(SERVING_STAND_IN)
    v = _viewer(tmp_path, cwva=cwva)
    v.start()
    try:
        for _ in range(100):
            try:
                html = urllib.request.urlopen(
                    f"http://127.0.0.1:{v.settings.port}/", timeout=1).read().decode()
                break
            except OSError:
                time.sleep(0.1)
        else:
            pytest.fail("stand-in never answered:\n" + v.log_tail())
        assert html.startswith("<!DOCTYPE html>")
        assert html.count('data-env-banner="1"') == 1
        assert '<body class="x"><div data-env-banner' in html
        assert "DASHBOARD VIEW" in html
        ttl = urllib.request.urlopen(f"http://127.0.0.1:{v.settings.port}/data",
                                     timeout=2).read().decode()
        assert "data-env-banner" not in ttl
    finally:
        v.stop()
