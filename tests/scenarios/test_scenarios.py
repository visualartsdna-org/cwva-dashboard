"""Smoke episodes: replay the driver-agnostic scenario corpus across all
transport families (files / git_local / gcp via FakeBucket).

FakeBucket is CI regression armor, NOT the phase exit — the gcp_bucket episodes
must also run against a real disposable GCS bucket (generations, metadata-hash
semantics, listing eventual-consistency reproduce least faithfully in a fake).
The harness is transport-agnostic, so those live runs are a short follow-on.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest

from cwva_dashboard import rson
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport, GcpBucketTransport, GitLocalTransport
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.scenarios import Scenario, ScenarioEnv, assert_end_state, replay
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
]

_SCENARIO_DIR = Path(__file__).parent
_SCENARIOS = [
    "entry_promote",
    "entry_promote_rollback",
    "binary_replace_rollback",
    "drift_adoption",
]


# --- in-memory GCS double (CI armor; not a substitute for a real bucket) ---

class _FakeBlob:
    def __init__(self, store, name):
        self._store, self.name = store, name

    def upload_from_filename(self, path):
        with open(path, "rb") as fh:
            self._store[self.name] = fh.read()

    def delete(self):
        if self.name not in self._store:
            raise KeyError(self.name)
        del self._store[self.name]

    def download_as_bytes(self):
        return self._store[self.name]

    @property
    def md5_hash(self):
        return hashlib.md5(self._store[self.name]).hexdigest()


class _FakeBucket:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def blob(self, name):
        return _FakeBlob(self.store, name)

    def list_blobs(self, prefix=None):
        for name in list(self.store):
            if prefix is None or name.startswith(prefix):
                yield _FakeBlob(self.store, name)


def _files(tmp_path):
    return FilesTransport(tmp_path / "sot_files")


def _git_local(tmp_path):
    return GitLocalTransport(tmp_path / "sot_git")


def _gcp(tmp_path):
    return GcpBucketTransport(_FakeBucket())


_TRANSPORTS = {"files": _files, "git_local": _git_local, "gcp_fake": _gcp}


def _load(name: str) -> Scenario:
    return Scenario.from_dict(rson.load(str(_SCENARIO_DIR / f"{name}.rson")))


def _env(tmp_path, transport):
    root = tmp_path / "qa"
    root.mkdir()
    qa = QAGit.init(root)
    ops = FileOps(Sandbox.open(root))
    return ScenarioEnv(fileops=ops, registry=build_default_registry(domain=TEST_DOMAIN), qa=qa, transport=transport)


@pytest.mark.parametrize("scenario_name", _SCENARIOS)
@pytest.mark.parametrize("transport_name", list(_TRANSPORTS))
def test_scenario_replays_to_expected_end_state(tmp_path, scenario_name, transport_name):
    transport = _TRANSPORTS[transport_name](tmp_path)
    env = _env(tmp_path, transport)
    scenario = _load(scenario_name)

    replay(scenario, env)
    assert_end_state(scenario, env)


def test_scenario_files_are_driver_agnostic():
    # Every step is a tool/workflow op with args — no HTTP/UI. This is the
    # property Phase 5's "same scenarios, two drivers" comparison relies on.
    for name in _SCENARIOS:
        for step in _load(name).steps:
            assert isinstance(step.op, str) and isinstance(step.args, dict)
            assert "/" not in step.op and " " not in step.op  # a bare op name
