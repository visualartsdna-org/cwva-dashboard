"""The gcp_bucket obligations that a fake cannot discharge (Phase 4.5 exit).

`tests/scenarios` replays the smoke episodes against an in-memory FakeBucket:
that is CI regression armor, not proof. GCS-specific behavior — object
generations, the `md5_hash` base64 encoding, listing consistency, delete of a
missing object, prefix scoping — is exactly what a hand-written double
reproduces least faithfully. This module runs the same episodes, plus a
transport-level smoke (open since the Phase 3 review), against a **real
disposable bucket**.

Opt in with the bucket name in the environment; the suite is skipped otherwise,
so CI and offline runs are unaffected:

    export GCP_TEST_BUCKET=<disposable-bucket>
    pytest tests/live_gcs -q

Credentials come from ADC (`gcloud auth application-default login`) or a service
account key in `GOOGLE_APPLICATION_CREDENTIALS` — never from anything checked in.
Every test is scoped to a unique random prefix under `_ROOT_PREFIX` and deletes
that prefix afterwards, so concurrent runs cannot collide and nothing outside
the prefix is ever touched.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest

from cwva_dashboard.promotion.transports import GcpBucketTransport
from cwva_dashboard.promotion.unit import ChangeManifest
from cwva_dashboard.scenarios import replay, assert_end_state


def _load_sibling(name: str):
    """Import a test module from a sibling directory. `tests/` is deliberately
    not a package (pytest imports each module top-level), so the sibling is
    loaded by path rather than restructuring the tree for one import."""
    path = Path(__file__).resolve().parents[1] / "scenarios" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Reuse the episode corpus and env builder — the point is that these are the
# *same* scenarios as the fake-bucket run, not a parallel live-only corpus.
_scenarios_mod = _load_sibling("test_scenarios")
_SCENARIOS = _scenarios_mod._SCENARIOS
_env = _scenarios_mod._env
_load = _scenarios_mod._load

pytestmark = [pytest.mark.live_gcs, pytest.mark.e2e]

_BUCKET_ENV = "GCP_TEST_BUCKET"
_ROOT_PREFIX = "cwva-dashboard-tests"


def _require_bucket() -> str:
    name = os.environ.get(_BUCKET_ENV)
    if not name:
        pytest.skip(f"{_BUCKET_ENV} not set — live GCS suite is opt-in")
    return name


@pytest.fixture(scope="session")
def gcs_client():
    _require_bucket()
    storage = pytest.importorskip("google.cloud.storage", reason="install the 'gcp' extra")
    import google.auth

    credentials, project = google.auth.default()
    # No hardcoded accounts or projects: take the project from the environment,
    # else whatever the ambient credentials resolve to.
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or project
    project = project or getattr(credentials, "quota_project_id", None)
    if not project:
        pytest.skip("no GCP project resolvable from the environment or credentials")
    return storage.Client(project=project, credentials=credentials)


@pytest.fixture
def live_transport(gcs_client):
    """A transport scoped to a unique prefix, torn down after the test."""
    bucket_name = _require_bucket()
    bucket = gcs_client.bucket(bucket_name)
    if not bucket.exists():
        pytest.skip(f"bucket {bucket_name!r} does not exist or is not readable")

    prefix = f"{_ROOT_PREFIX}/{uuid.uuid4().hex}"
    try:
        yield GcpBucketTransport(bucket, prefix=prefix)
    finally:
        # Delete only under our own prefix. A failed delete must not mask a
        # test failure, but a leak is worth seeing, so it is reported.
        for blob in gcs_client.list_blobs(bucket_name, prefix=prefix + "/"):
            try:
                blob.delete()
            except Exception as exc:  # pragma: no cover - cleanup diagnostics
                print(f"live_gcs cleanup: could not delete {blob.name}: {exc}")


# -- transport smoke (the Phase 3 open item) --------------------------------


def test_live_bucket_converge_snapshot_and_delete(tmp_path, live_transport):
    """Converge adds, read them back, then converge a delete — against real GCS."""
    content = tmp_path / "content"
    (content / "content/documents").mkdir(parents=True)
    (content / "content/documents/note.md").write_text("live note")
    (content / "content/documents/second.md").write_text("second")

    empty_stamp = live_transport.current_stamp()

    live_transport.converge(
        content, ChangeManifest(adds=["content/documents/note.md", "content/documents/second.md"])
    )
    snap = live_transport.snapshot()
    assert set(snap) == {"content/documents/note.md", "content/documents/second.md"}
    assert live_transport.fetch("content/documents/note.md") == b"live note"

    # The stamp must move when SOT changes — this is what drift detection rides on.
    after_add = live_transport.current_stamp()
    assert after_add != empty_stamp

    # Real md5_hash is base64, not hex as in the fake; sync only requires that
    # it be a stable, comparable fingerprint per unchanged object.
    assert live_transport.snapshot() == snap

    live_transport.converge(content, ChangeManifest(deletes=["content/documents/second.md"]))
    assert set(live_transport.snapshot()) == {"content/documents/note.md"}
    assert live_transport.current_stamp() not in (empty_stamp, after_add)


def test_live_bucket_delete_missing_is_idempotent(tmp_path, live_transport):
    """Convergence is idempotent: deleting an object GCS does not have is fine."""
    live_transport.converge(tmp_path, ChangeManifest(deletes=["content/documents/absent.md"]))
    assert live_transport.snapshot() == {}


def test_live_bucket_prefix_scopes_the_view(tmp_path, gcs_client, live_transport):
    """A transport must only ever see and touch its own prefix."""
    (tmp_path / "content").mkdir()
    (tmp_path / "content/a.md").write_text("mine")
    live_transport.converge(tmp_path, ChangeManifest(adds=["content/a.md"]))

    other = GcpBucketTransport(
        gcs_client.bucket(_require_bucket()), prefix=f"{_ROOT_PREFIX}/{uuid.uuid4().hex}"
    )
    assert other.snapshot() == {}
    assert set(live_transport.snapshot()) == {"content/a.md"}


# -- the smoke episodes, replayed live --------------------------------------


@pytest.mark.parametrize("scenario_name", _SCENARIOS)
def test_scenario_replays_against_live_bucket(tmp_path, live_transport, scenario_name):
    env = _env(tmp_path, live_transport)
    scenario = _load(scenario_name)

    replay(scenario, env)
    assert_end_state(scenario, env)
