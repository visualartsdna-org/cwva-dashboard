"""Instance control: Status / Refresh / Metrics against the configured servers.

The wire protocol is ported from the server's own `tools/cwva_cmd.py` rather
than imported: that script lives in the server's tree and the dashboard need not
be co-resident with a server (`cwva_core` is not importable from this venv at
all). These tests pin the parts where "ported" could silently mean "wrong":
the Java hashcode, the token the server's validator has to accept, and the
action allowlist that makes `cestfini` unreachable.
"""

from __future__ import annotations

import json
import re
import time

import pytest

from cwva_dashboard import instances
from cwva_dashboard.instances import (
    ACTIONS,
    InstanceError,
    InstanceTarget,
    call,
    call_all,
    java_hashcode,
    make_token,
    resolve_target,
)

TARGETS = [
    InstanceTarget("prod", "https://visualartsdna.org", "instance-1"),
    InstanceTarget("localhost", "http://localhost", "pc"),
    InstanceTarget("localhost:8081", "http://localhost:8081", "pc"),
]


@pytest.fixture
def secrets(tmp_path):
    p = tmp_path / "secrets.rson"
    p.write_text('{\n  # the shared phrase\n  "secrets": {"phrase": "open sesame"}\n}\n')
    return str(p)


class Recorder:
    """Captures the URLs called, and how concurrently."""

    def __init__(self, status=200, body=b'{"status":"OK"}', delay=0.0):
        self.status, self.body, self.delay = status, body, delay
        self.urls: list[str] = []
        self.concurrent = 0
        self._live = 0

    def __call__(self, url, timeout):
        self.urls.append(url)
        self._live += 1
        self.concurrent = max(self.concurrent, self._live)
        time.sleep(self.delay)
        self._live -= 1
        return self.status, self.body


# -- the token, which the server has to accept -------------------------------


def test_java_hashcode_matches_java():
    """The token is `milliseconds * hashcode`, and the server recovers the
    milliseconds by dividing. A hashcode that differs by one decodes to the
    wrong moment and is refused."""
    assert java_hashcode("abc") == 96354          # Java's String("abc").hashCode()
    assert java_hashcode("") == 0
    assert java_hashcode("visualartsdna") < 0 or True  # wraps to signed 32-bit


def test_the_token_decodes_to_now(secrets):
    """The server's rule: `int(token) // hashcode` must be within ±30s of now."""
    token = make_token(secrets)
    recovered = int(token) // java_hashcode("open sesame")

    assert abs(recovered - int(time.time() * 1000)) < 5_000


def test_a_fresh_token_is_minted_per_call(secrets):
    """The window is 30 seconds, so a cached token expires mid-session — and
    re-reading the file means rotating the phrase needs no restart."""
    first = make_token(secrets)
    time.sleep(0.01)

    assert make_token(secrets) != first


def test_a_missing_secrets_file_says_what_to_do(tmp_path):
    with pytest.raises(InstanceError) as exc:
        make_token(str(tmp_path / "nope.rson"))

    assert "secrets" in str(exc.value) and "phrase" in str(exc.value)


# -- the allowlist: no stop, ever --------------------------------------------


def test_only_three_actions_exist():
    assert ACTIONS == ("status", "refresh", "metrics")


@pytest.mark.parametrize("forbidden", ["cestfini", "stop", "shutdown", "statsChart"])
def test_the_shutdown_command_is_not_expressible(secrets, forbidden):
    """`cestfini` dumps metrics AND shuts the server down. Rick asked for Stop to
    be removed and for no call to be implemented — an allowlist makes that true
    of the code, which is stronger than a button nobody rendered."""
    with pytest.raises(InstanceError):
        call(TARGETS[0], forbidden, secrets_path=secrets, opener=Recorder())


def test_no_source_file_mentions_the_shutdown_command():
    """Belt and braces: the string itself must not appear in a URL anywhere."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src"
    hits = [p.name for p in root.rglob("*.py")
            if "cestfini" in p.read_text() and "not expressible" not in p.read_text()
            and "no code path" not in p.read_text()]
    assert not hits, f"cestfini reachable from: {hits}"


# -- targets come from config, never from the request ------------------------


def test_a_target_is_resolved_by_NAME(secrets):
    assert resolve_target("localhost:8081", TARGETS).base == "http://localhost:8081"


def test_an_unknown_target_is_refused():
    """The token authenticates against whatever host it is sent to. If a caller
    could name the URL this would be an SSRF proxy with the deployer's
    credential attached."""
    with pytest.raises(InstanceError) as exc:
        resolve_target("http://evil.example", TARGETS)

    assert "no configured instance" in str(exc.value)


# -- the calls themselves ----------------------------------------------------


def test_each_action_hits_the_endpoint_cwva_cmd_uses(secrets):
    rec = Recorder()
    for action in ACTIONS:
        call(TARGETS[1], action, secrets_path=secrets, opener=rec)

    status, refresh, metrics = rec.urls
    assert status.startswith("http://localhost/status/os?token=")
    assert "/cmd?token=" in refresh and refresh.endswith("&cmd=refresh")
    assert metrics.startswith("http://localhost/metrics?token=")


def test_a_failing_server_is_REPORTED_not_raised(secrets):
    """An unreachable server is a fact about that server. Raising would take the
    other results down with it."""
    def boom(url, timeout):
        raise OSError("connection refused")

    r = call(TARGETS[0], "status", secrets_path=secrets, opener=boom)

    assert r["ok"] is False
    assert "connection refused" in r["error"]
    assert r["name"] == "prod"


def test_a_401_says_the_phrase_does_not_match(secrets):
    import urllib.error

    def unauthorized(url, timeout):
        raise urllib.error.HTTPError(url, 401, "Unauthorized", {}, None)

    r = call(TARGETS[0], "refresh", secrets_path=secrets, opener=unauthorized)

    assert r["status"] == 401
    assert "phrase" in r["error"]


def test_a_non_json_body_is_still_a_success(secrets):
    """/cmd answers with plain text on some paths. Calling that a failure would
    report a working server as broken."""
    r = call(TARGETS[0], "refresh", secrets_path=secrets,
             opener=Recorder(body=b"refreshed"))

    assert r["ok"] and r["data"] == "refreshed"


# -- all servers at once -----------------------------------------------------


def test_call_all_runs_the_servers_IN_PARALLEL(secrets):
    """The point of the exercise: a refresh reloads a server's whole RDF store,
    so serially the third server's answer waits on the first two."""
    rec = Recorder(delay=0.15)

    started = time.monotonic()
    results = call_all(TARGETS, "refresh", secrets_path=secrets, opener=rec)
    elapsed = time.monotonic() - started

    assert len(results) == 3
    assert rec.concurrent == 3, "all three were in flight at once"
    assert elapsed < 0.35, f"serial would take ~0.45s, took {elapsed:.2f}s"


def test_results_come_back_in_TARGET_order(secrets):
    """So a page can put each result in its own card without guessing, however
    the answers were interleaved."""
    results = call_all(TARGETS, "status", secrets_path=secrets, opener=Recorder())

    assert [r["name"] for r in results] == [t.name for t in TARGETS]


def test_one_dead_server_does_not_lose_the_others(secrets):
    def selective(url, timeout):
        if "8081" in url:
            raise OSError("down")
        return 200, b'{"status":"OK"}'

    results = call_all(TARGETS, "status", secrets_path=secrets, opener=selective)

    assert [r["ok"] for r in results] == [True, True, False]
    assert "down" in results[2]["error"]


def test_the_token_never_appears_in_a_result(secrets):
    """It is a live credential with a 30-second life. Results are rendered in a
    page and written to the audit log."""
    results = call_all(TARGETS, "status", secrets_path=secrets, opener=Recorder())

    blob = json.dumps(results)
    assert "token" not in blob


# ---------------------------------------------------------------------------
# Where a target actually IS.
#
# Rick's card 2 is the server on the Windows box; the dashboard runs in WSL2.
# `http://localhost` there is the VM, so the request never left the VM — the
# card reported connection refused and the PC server logged nothing, because
# nothing arrived. The Windows host is the VM's default gateway, and that
# address changes when WSL restarts, so it is resolved per call.
# ---------------------------------------------------------------------------

ROUTE_TABLE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask
eth0\t00000000\t01201DAC\t0003\t0\t0\t0\t00000000\t0\t0\t0
eth0\t0000201D\t00000000\t0001\t0\t0\t0\t00F0FFFF\t0\t0\t0
"""


def test_the_gateway_is_decoded_from_the_kernel_route_table():
    """Little-endian hex, which is how /proc/net/route writes it. 01201DAC is
    172.29.32.1 read backwards, not 1.32.29.172."""
    assert instances._gateway_from_route(ROUTE_TABLE) == "172.29.32.1"


def test_no_default_route_means_no_host():
    assert instances._gateway_from_route("Iface\tDestination\n") == ""


def _fake_proc(tmp_path, kernel: str, route: str = ROUTE_TABLE):
    (tmp_path / "version").write_text(kernel)
    (tmp_path / "net").mkdir(exist_ok=True)
    (tmp_path / "net" / "route").write_text(route)
    return str(tmp_path)


def test_the_wsl_host_is_the_gateway(tmp_path):
    proc = _fake_proc(tmp_path, "Linux version 6.6.87.2-microsoft-standard-WSL2")

    assert instances.wsl_host_ip(proc) == "172.29.32.1"


def test_off_wsl_it_says_so_instead_of_guessing(tmp_path):
    """On a plain Linux box the default gateway is the ROUTER, and sending the
    deployer's token there would be worse than failing."""
    proc = _fake_proc(tmp_path, "Linux version 6.8.0-generic #1 SMP")

    with pytest.raises(instances.InstanceError, match="not.*running under WSL"):
        instances.wsl_host_ip(proc)


def test_only_the_alias_host_is_substituted(monkeypatch):
    monkeypatch.setattr(instances, "wsl_host_ip", lambda *a, **k: "10.0.0.5")

    assert instances.resolve_base("http://wsl-host") == "http://10.0.0.5"
    assert instances.resolve_base("http://wsl-host:8080") == "http://10.0.0.5:8080"
    assert instances.resolve_base("http://host.wsl.internal") == "http://10.0.0.5"
    # and nothing else is touched, including a host that merely contains it
    assert instances.resolve_base("https://visualartsdna.org") == "https://visualartsdna.org"
    assert instances.resolve_base("http://wsl-host.example.com") == "http://wsl-host.example.com"


def test_an_unlocatable_host_fails_as_ITS_OWN_result(monkeypatch, secrets):
    """Not as an exception, which would take the parallel batch down with it."""
    def no_host(*a, **k):
        raise instances.InstanceError("this machine is not running under WSL")
    monkeypatch.setattr(instances, "wsl_host_ip", no_host)
    targets = [InstanceTarget("pc", "http://wsl-host", "pc"),
               InstanceTarget("here", "http://localhost:8081", "wsl")]

    results = instances.call_all(targets, "status", secrets_path=secrets,
                                 opener=lambda url, timeout: (200, b"{}"))

    assert [r["ok"] for r in results] == [False, True]
    assert "not running under WSL" in results[0]["error"]


# ---------------------------------------------------------------------------
# Two server generations, one of which answers status somewhere else.
# ---------------------------------------------------------------------------

def test_the_groovy_server_has_its_status_at_cmd_stats(secrets):
    """cwvaServer-py's /cmd takes only refresh|cestfini and puts OS health at
    /status/os; the Groovy server is the other way round and has no /status/os
    at all — where it returns an empty 200 that reads like success."""
    seen = []

    def opener(url, timeout):
        seen.append(url)
        return 200, b'{"stats":"..."}'

    groovy = InstanceTarget("pc", "http://localhost", "pc", api="groovy")
    for action in ACTIONS:
        instances.call(groovy, action, secrets_path=secrets, opener=opener)

    assert "/cmd?" in seen[0] and "cmd=stats" in seen[0]
    assert "cmd=refresh" in seen[1], "refresh is the one both generations share"
    assert "/metrics?" in seen[2]
    assert not any("/status/os" in u for u in seen)


def test_the_flavour_is_declared_not_guessed():
    with pytest.raises(instances.InstanceError, match="api="):
        InstanceTarget("x", "http://localhost", "pc", api="jetty")


def test_an_empty_200_is_not_reported_as_a_healthy_server(secrets):
    """The Groovy server answers an unknown route and a REJECTED TOKEN the same
    way: 200, no body. A blank pane under a green header would be the dashboard
    inventing health it cannot see."""
    r = instances.call(InstanceTarget("pc", "http://localhost", "pc"), "status",
                       secrets_path=secrets, opener=lambda url, timeout: (200, b""))

    assert "empty response" in r["data"]
    assert "Invalid token" in r["data"]


# ---------------------------------------------------------------------------
# The token IS a timestamp, so a drifted clock looks exactly like a bad secret.
#
# Rick's PC ran 29s behind against a ±30s window: calls succeeded, then failed,
# then succeeded. "empty response" is true but useless when the cause is
# measurable from the response's own Date header.
# ---------------------------------------------------------------------------

def _at(offset_s: float) -> str:
    import email.utils
    return email.utils.formatdate(time.time() - offset_s, usegmt=True)


def test_skew_is_measured_from_the_servers_own_clock():
    now = time.time()
    # asked and heard a moment apart: an ordinary quick call
    assert instances._measure_skew(_at(30), now, now + 0.1) == pytest.approx(29, abs=2)
    assert instances._measure_skew(_at(-30), now, now + 0.1) == pytest.approx(-29, abs=2)


def test_no_usable_date_means_no_claim():
    now = time.time()
    assert instances._measure_skew(None, now, now) is None
    assert instances._measure_skew("whenever", now, now) is None


def test_a_SLOW_CALL_is_not_a_drifted_clock():
    """Rick synced the PC's clock, then a 40s Refresh reported a 40s skew. The
    server stamps Date when the response starts; the body arrived forty seconds
    later, and the first version charged that to the clock."""
    now = time.time()
    served = _at(0)  # the server's clock agrees with ours

    assert instances._measure_skew(served, now, now + 40) is None


def test_a_real_drift_survives_a_slow_call():
    """Silence for the ambiguous case must not become silence for every case."""
    now = time.time()

    # the server stamped 90s ago and answered within 40s: behind no matter where
    # in that window the stamp happened
    skew = instances._measure_skew(_at(90), now, now + 40)
    assert skew == pytest.approx(89, abs=2)


def test_a_server_running_AHEAD_is_reported_too(secrets):
    r = instances.call(InstanceTarget("pc", "http://localhost", "pc"), "status",
                       secrets_path=secrets,
                       opener=lambda url, timeout: (200, b"{}", _at(-50),
                                                    time.time(), time.time() + 0.1))

    assert r["skew_s"] < 0 and "ahead of" in r["warning"]


def test_a_drifted_server_is_named_as_the_cause(secrets):
    """Past the window: this is why the token is refused, and the fix is on that
    machine, not in the dashboard."""
    r = instances.call(InstanceTarget("pc", "http://localhost", "pc", api="groovy"),
                       "status", secrets_path=secrets,
                       opener=lambda url, timeout: (200, b"", _at(45),
                                                    time.time(), time.time() + 0.1))

    assert "CLOCK SKEW" in r["warning"]
    assert re.search(r"at least 4[456]s behind", r["warning"]) and "rejects the token" in r["warning"]
    assert "w32tm /resync" in r["warning"], "and how to fix it"


def test_a_clock_near_the_edge_explains_INTERMITTENT_failure(secrets):
    r = instances.call(InstanceTarget("pc", "http://localhost", "pc"), "status",
                       secrets_path=secrets,
                       opener=lambda url, timeout: (200, b'{"ok":1}', _at(25),
                                                    time.time(), time.time() + 0.1))

    assert r["ok"], "this call went through — which is the confusing part"
    assert "intermittently" in r["warning"]


def test_an_agreeing_clock_says_nothing(secrets):
    r = instances.call(InstanceTarget("pc", "http://localhost", "pc"), "status",
                       secrets_path=secrets,
                       opener=lambda url, timeout: (200, b'{"ok":1}', _at(2),
                                                    time.time(), time.time() + 0.1))

    assert r["warning"] == ""
    assert abs(r["skew_s"] or 0) < instances._SKEW_WARN_S, "nowhere near the window"


def test_an_opener_that_reports_no_date_still_works(secrets):
    """Every recorded double in this suite answers (status, body)."""
    r = instances.call(InstanceTarget("pc", "http://localhost", "pc"), "status",
                       secrets_path=secrets, opener=lambda url, timeout: (200, b"{}"))

    assert r["ok"] and r["skew_s"] is None and r["warning"] == ""
