"""CE runs one environment from one config (2026-11-21): config resolution,
the no-config message, and the hub without the developer extras."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard import config as cfgmod
from cwva_dashboard.main import create_app


def test_resolution_order(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("CWVA_DASHBOARD_CONFIG", raising=False)
    with pytest.raises(cfgmod.NoConfig, match="examples/folder.rson"):
        cfgmod.resolve_config_path()
    (tmp_path / "dashboard.rson").write_text("{}")
    assert cfgmod.resolve_config_path().endswith("dashboard.rson")  # the developer's
    (tmp_path / "config.rson").write_text("{}")
    assert cfgmod.resolve_config_path().endswith("config.rson")  # a CE user's wins
    monkeypatch.setenv("CWVA_DASHBOARD_CONFIG", "/x/prod.rson")
    assert cfgmod.resolve_config_path() == "/x/prod.rson"
    assert cfgmod.resolve_config_path("/y/explicit.rson") == "/y/explicit.rson"


def test_no_config_is_a_message_not_a_traceback(tmp_path, monkeypatch):
    monkeypatch.setattr(cfgmod, "CONFIG_DIR", tmp_path)
    monkeypatch.delenv("CWVA_DASHBOARD_CONFIG", raising=False)
    with pytest.raises(cfgmod.NoConfig) as exc:
        cfgmod.load_config()
    assert "cp " in str(exc.value) and "config.rson" in str(exc.value)


def _app(tmp_path, developer: bool):
    cfg = tmp_path / "config.rson"
    cfg.write_text(json.dumps({
        "extends": str(cfgmod.CONFIG_DIR / "base.rson"),
        "domain": TEST_DOMAIN, "developer": developer,
        "sandbox": {"stage_root": str(tmp_path / "sandbox")},
    }))
    return create_app(config_path=str(cfg), enforce_landlock=False,
                      audit_path=tmp_path / "audit.jsonl")


def test_a_ce_hub_has_no_developer_extras(tmp_path):
    with TestClient(_app(tmp_path, developer=False)) as c:
        hub = c.get("/").text
        assert "QA Backup" not in hub and "<!-- DEVELOPER -->" not in hub
        assert "Preview Staged" in hub and "Refresh" in hub  # these a CE user needs
        assert c.get("/backup").status_code == 200  # the route stays


def test_a_developer_hub_keeps_them(tmp_path):
    with TestClient(_app(tmp_path, developer=True)) as c:
        assert "QA Backup" in c.get("/").text


def test_the_shipped_base_is_ce():
    assert cfgmod.developer(cfgmod.load_config(str(cfgmod.CONFIG_DIR / "base.rson"))) is False
    assert "environment" not in cfgmod.load_config(
        str(cfgmod.CONFIG_DIR / "examples" / "folder.rson"))  # one environment: no banner
