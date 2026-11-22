"""Getting to the drop folder: copy the path, or open it.

A browser cannot open a folder — navigation from an http page to a `file://`
URL is blocked, silently, everywhere. So the dashboard offers two things: a
server-side launch of the desktop's file manager, and the path itself, which is
the one that always works.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.inbox import Inbox, open_folder
from cwva_dashboard.main import create_app

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


@pytest.fixture
def launched(monkeypatch):
    """Record what would have been opened WITHOUT opening it.

    The first version of these tests called the real opener, which on this
    machine launched Windows Explorer — a test suite that opens windows on the
    developer's desktop is a test suite nobody runs twice. The failure paths
    below still use the real thing, because they launch nothing by definition.
    """
    from cwva_dashboard import inbox as inbox_mod

    calls = []

    def fake(path):
        calls.append(str(path))
        return {"ok": True, "path": str(path), "opener": "pretend-manager"}

    monkeypatch.setattr(inbox_mod, "open_folder", fake)
    return calls


@pytest.fixture
def client(tmp_path):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    drop = tmp_path / "drop"
    drop.mkdir()
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root,
                     enforce_landlock=False, audit_path=tmp_path / "audit.jsonl",
                     inbox=Inbox(drop))
    with TestClient(app) as c:
        yield c, drop, tmp_path


def test_the_form_offers_BOTH_ways(client):
    c, drop, _tmp = client

    page = c.get("/rdf/entry").text

    assert str(drop) in page
    assert 'id="dropCopy"' in page and "Copy path" in page
    assert 'id="dropOpen"' in page and "Open folder" in page


def test_opening_is_a_POST(client):
    """A GET is something a prefetch, a back button or a link preview can fire,
    and this starts a process."""
    c, _drop, _tmp = client

    assert c.get("/api/inbox/open").status_code == 405


def test_the_folder_is_the_CONFIGURED_one_never_the_request(client, launched):
    """A caller who could name a directory could name any directory, and "open
    this in a file manager" is a fine way to find out what is on a disk."""
    c, drop, tmp = client
    secret = tmp / "somewhere-else"
    secret.mkdir()

    r = c.post("/api/inbox/open", json={"path": str(secret)})

    assert r.json()["path"] == str(drop), "the request's path was ignored"
    assert launched == [str(drop)], "and the opener was handed the configured one"
    assert str(secret) not in launched


def test_the_answer_always_carries_the_PATH(client, launched):
    """Whether it launched or not. On a headless host or a dashboard reached
    from another machine, naming the folder is the whole answer."""
    c, drop, _tmp = client

    body = c.post("/api/inbox/open").json()

    assert body["path"] == str(drop)
    assert "opener" in body


def test_it_is_audited(client, launched):
    c, _drop, tmp = client

    c.post("/api/inbox/open")

    assert "inbox.open" in (tmp / "audit.jsonl").read_text()


def test_no_drop_folder_configured_says_so(tmp_path, launched):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    app = create_app(domain=TEST_DOMAIN, sandbox_root=qa_root,
                     enforce_landlock=False, audit_path=tmp_path / "a.jsonl")
    with TestClient(app) as c:
        r = c.post("/api/inbox/open")

    assert r.status_code == 404
    assert "no drop folder" in r.json()["error"]


# ---------------------------------------------------------------------------
# The opener itself.
# ---------------------------------------------------------------------------

def test_a_folder_that_is_not_there_is_reported_not_raised(tmp_path):
    """This runs on a request; an exception would be a 500 for a convenience."""
    result = open_folder(tmp_path / "absent")

    assert result["ok"] is False
    assert "not a folder" in result["error"]
    assert result["path"].endswith("absent"), "and still names what it looked for"


def test_a_file_is_not_a_folder(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")

    assert open_folder(f)["ok"] is False


def test_the_WSL_path_is_translated_for_EXPLORER(tmp_path):
    """Windows Explorer cannot read /home/you/…; `wslpath -w` turns it into
    the \\\\wsl.localhost\\… form it can. Skipped where there is no WSL to ask."""
    from cwva_dashboard.inbox import _native_path, _platform

    if _platform() != "wsl" or shutil.which("wslpath") is None:
        pytest.skip("not running under WSL")

    native = _native_path(tmp_path, "wsl")

    assert "/" not in native, f"a Windows path has no forward slashes: {native}"
    assert native.startswith("\\\\") or native[1:3] == ":\\", native
