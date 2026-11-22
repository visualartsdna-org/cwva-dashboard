"""Instance control — Status / Refresh / Metrics against the configured servers.

The dashboard drives the cwva servers it is paired with. The call shape is
**ported from** `~/cwva-py/main/tools/cwva_cmd.py` rather than imported from it:
that script lives in the server's tree, and the dashboard may not be co-resident
with a server at all (Rick runs content management on a workstation and
production on GCP). `cwva_core` is not even importable from this venv. So the
logic is reproduced here and the script stays the reference for what the wire
protocol is.

**This is a network effect and it lives in the trusted orchestrator** (law 11),
never in the tool vocabulary — not by preference but by construction: the
Landlock-confined worker cannot read `/etc/resolv.conf`, so a hostname does not
resolve there and a registered tool would silently return nothing. Same split as
updateWorkOnSite and the ffprobe probe.

Law 11 previously named three sanctioned members. Instance **Refresh** is the
first of them (post-promotion refresh, inventory #25) reaching a server other
than this one; **Status** and **Metrics** are read-only additions of the same
kind as the site scrape (#9) — see CLAUDE.md, where the class is now recorded as
four.

Two security properties, both enforced here rather than in the page:

- **The action set is an allowlist.** `cestfini` — the server command that dumps
  metrics *and shuts the server down* — is not expressible through this module.
  Stop is not implemented, so there is no code path to reach it, which is a
  stronger guarantee than a button nobody rendered.
- **Targets come from config, never from the request.** The token minted here is
  a valid credential for any host it is sent to. If a caller could name the URL,
  this would be an SSRF proxy that helpfully attaches the deployer's auth token
  to it. `resolve_target` matches a *name* against the configured list and the
  URL never crosses the wire from the browser.

The token is short-lived by design (the server allows ±30 s) so it is minted per
call, never cached and never logged.
"""

from __future__ import annotations

import email.utils
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "ACTIONS", "InstanceTarget", "InstanceError",
    "java_hashcode", "make_token", "call", "call_all", "resolve_target",
    "WSL_HOST_ALIASES", "wsl_host_ip", "resolve_base",
]

# The only commands this module can express. `cestfini` (dump metrics and shut
# down) is deliberately absent: Rick asked for Stop to be removed and for no
# call to be implemented for it, and an allowlist is how that becomes true of
# the code rather than of the UI.
ACTIONS = ("status", "refresh", "metrics")

_DEFAULT_SECRETS = "~/.secrets.rson"
_DEFAULT_TIMEOUT = 300


class InstanceError(Exception):
    """A call that could not be attempted — bad action, unknown target, no
    secret. Distinct from a call that was made and failed, which is reported in
    the result rather than raised, so one unreachable server does not abort the
    others."""


# The two server GENERATIONS do not answer at the same places, and both are in
# service: cwvaServer-py (FastAPI) and the original Groovy server on Jetty, which
# still runs on Rick's PC. `refresh` and `metrics` agree; STATUS does not.
#
#   python : GET /status/os?token=…       — /cmd accepts only refresh|cestfini
#   groovy : GET /cmd?token=…&cmd=stats   — has no /status/os at all
#
# Declared per target rather than sniffed: a wrong guess here reads as a healthy
# server (the Groovy answers an unknown route with an empty 200), and the
# deployer knows which server they are running.
API_FLAVOURS = ("py", "groovy")


@dataclass(frozen=True)
class InstanceTarget:
    name: str
    url: str
    tag: str = ""
    api: str = "py"

    def __post_init__(self):
        if self.api not in API_FLAVOURS:
            raise InstanceError(
                f"instance {self.name!r} has api={self.api!r}; "
                f"expected one of {list(API_FLAVOURS)}"
            )

    @property
    def base(self) -> str:
        return self.url.rstrip("/")


def java_hashcode(s: str) -> int:
    """Java's `String.hashCode()`, which the server's token scheme is built on.

    Reproduced exactly — including the wrap to a signed 32-bit value — because
    the token is `milliseconds * hashcode` and the server recovers the
    milliseconds by dividing. Any difference here yields a token that decodes to
    the wrong moment and is refused.
    """
    h = 0
    for ch in s:
        h = (31 * h + ord(ch)) & 0xFFFFFFFF
    if h >= 0x80000000:
        h -= 0x100000000
    return h


def _rson(path: Path) -> dict:
    raw = path.read_text()
    return json.loads("\n".join(re.sub(r"\s*#.*$", "", ln) for ln in raw.splitlines()))


def make_token(secrets_path: str = _DEFAULT_SECRETS) -> str:
    """A fresh token for right now.

    Read per call rather than cached: the server's window is ±30 s, so a cached
    token would expire mid-session, and re-reading means rotating the phrase
    takes effect without restarting the dashboard.
    """
    path = Path(str(secrets_path)).expanduser()
    try:
        phrase = _rson(path)["secrets"]["phrase"]
    except FileNotFoundError:
        raise InstanceError(
            f"no secrets file at {path}. Instance control needs the shared "
            "phrase the servers authenticate with — point `instances."
            "secrets_path` at one, or create it as "
            '{"secrets": {"phrase": "…"}}.'
        ) from None
    except (KeyError, ValueError) as exc:
        raise InstanceError(f"{path} has no secrets.phrase ({exc})") from None

    hc = java_hashcode(phrase)
    if hc == 0:
        raise InstanceError("the configured phrase hashes to 0; the server rejects it")
    return str(int(time.time() * 1000) * hc)


def _url_for(base: str, action: str, token: str, api: str = "py") -> str:
    if action == "status":
        if api == "groovy":
            return f"{base}/cmd?token={token}&cmd=stats"
        return f"{base}/status/os?token={token}"
    if action == "refresh":
        # The one command both generations spell the same way.
        return f"{base}/cmd?token={token}&cmd=refresh"
    if action == "metrics":
        # The server does NOT currently validate a token on /metrics (it is
        # marked "internal" there). The token is sent anyway so this keeps
        # working if that changes — but do not read its presence as proof the
        # endpoint is protected. It is not.
        return f"{base}/metrics?token={token}"
    raise InstanceError(f"unknown action {action!r}; expected one of {list(ACTIONS)}")


# A dashboard inside WSL2 and a server on the Windows box are on DIFFERENT
# hosts, and `localhost` inside the VM is the VM. Rick's card 2 is the server on
# the PC at port 80; addressed as `http://localhost` from here it reached nothing
# at all — connection refused with no entry in that server's log, because no
# connection ever left the VM.
#
# The Windows host is the VM's default gateway under WSL's NAT networking, and
# that address CHANGES when WSL restarts, so it must not be frozen into config.
# A target URL therefore names the host symbolically and it is resolved per call.
WSL_HOST_ALIASES = ("wsl-host", "host.wsl.internal")


def _gateway_from_route(route_table: str) -> str:
    """The default gateway out of `/proc/net/route` — as a string, so it can be
    tested without a kernel."""
    for line in route_table.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 2 and parts[1] == "00000000":
            packed = int(parts[2], 16)
            return ".".join(str((packed >> (8 * i)) & 0xFF) for i in range(4))
    return ""


def wsl_host_ip(proc_root: str = "/proc") -> str:
    """The Windows host as seen from inside WSL2."""
    root = Path(proc_root)
    try:
        kernel = (root / "version").read_text().lower()
    except OSError:
        kernel = ""
    if "microsoft" not in kernel:
        raise InstanceError(
            "this target is addressed as the WSL host, but this machine is not "
            "running under WSL. Give the server's real address in "
            "`instances.targets`."
        )
    try:
        gateway = _gateway_from_route((root / "net" / "route").read_text())
    except OSError as exc:
        raise InstanceError(f"cannot read the routing table to find the WSL host ({exc})") from None
    if not gateway:
        raise InstanceError("no default route, so the WSL host cannot be located")
    return gateway


def resolve_base(base: str) -> str:
    """The base URL actually dialled.

    Identity for every ordinary target; only a symbolic host is substituted.
    Kept separate from `_url_for` so a target that cannot be located fails as
    ITS OWN result rather than taking the parallel batch down with it.
    """
    for alias in WSL_HOST_ALIASES:
        for prefix in ("http://", "https://"):
            if base == f"{prefix}{alias}" or base.startswith(f"{prefix}{alias}/") \
                    or base.startswith(f"{prefix}{alias}:"):
                return base.replace(alias, wsl_host_ip(), 1)
    return base


def resolve_target(name: str, targets) -> InstanceTarget:
    """The configured target called ``name``, or raise.

    The request names a target; it never supplies a URL. Anything else makes
    this an SSRF proxy with the deployer's credential attached.
    """
    for t in targets:
        if t.name == name:
            return t
    raise InstanceError(f"no configured instance named {name!r}")


def call(target: InstanceTarget, action: str, *, secrets_path: str = _DEFAULT_SECRETS,
         timeout: int = _DEFAULT_TIMEOUT, opener=None) -> dict:
    """Run one action against one server and describe what happened.

    A failure is REPORTED, not raised: an unreachable server is a fact about
    that server, and raising would take the other results down with it.
    """
    if action not in ACTIONS:
        raise InstanceError(f"unknown action {action!r}; expected one of {list(ACTIONS)}")

    result = {
        "name": target.name, "tag": target.tag, "url": target.base,
        "api": target.api, "action": action, "ok": False, "status": None,
        "elapsed_ms": 0, "data": None, "error": "", "warning": "", "skew_s": None,
        "empty": False,
    }
    started = time.monotonic()
    try:
        base = resolve_base(target.base)
    except InstanceError as exc:
        # One target being unlocatable is a fact about that target, like being
        # unreachable. The other cards still get their answers.
        result["error"] = str(exc)
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
        return result
    result["url"] = base
    try:
        url = _url_for(base, action, make_token(secrets_path), target.api)
        fetch = opener or _fetch
        # Openers in tests answer with (status, body); the real one adds the
        # server's Date. Both are accepted rather than forcing every double to
        # care about a header it has no opinion about.
        answer = fetch(url, timeout)
        status, body = answer[0], answer[1]
        served_at = answer[2] if len(answer) > 2 else None
        asked = answer[3] if len(answer) > 3 else time.time()
        heard = answer[4] if len(answer) > 4 else asked
        result["status"] = status
        result["skew_s"] = _measure_skew(served_at, asked, heard)
        try:
            result["data"] = json.loads(body)
        except ValueError:
            # /cmd answers with plain text on some paths; show it rather than
            # calling a successful call a failure because it was not JSON.
            result["data"] = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
        result["ok"] = 200 <= (status or 0) < 300
        if not result["ok"]:
            result["error"] = f"HTTP {status}"
        if result["skew_s"] is not None and abs(result["skew_s"]) >= _SKEW_WARN_S:
            result["warning"] = _skew_note(target.name, result["skew_s"])
        if result["ok"] and not body:
            # The Groovy server returns an EMPTY 200 both for a route it does
            # not have and for a token it rejected (`if (valid) {…}` with no
            # else). Silence is therefore not success, and saying "ok" with a
            # blank pane would be the dashboard inventing a healthy server.
            result["empty"] = True
            result["data"] = (
                "empty response. A cwva server answers this way for a route it "
                "does not have AND for a token it rejected — check the server "
                "console for 'Invalid token'."
            )
    except InstanceError:
        raise
    except urllib.error.HTTPError as exc:
        result["status"] = exc.code
        result["error"] = (
            "unauthorized — the dashboard's phrase does not match this server's"
            if exc.code == 401 else f"HTTP {exc.code} {exc.reason}"
        )
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
    return result


# ---------------------------------------------------------------------------
# When each server was last refreshed.
#
# No server can be asked: /status/os reports OS health, and the Groovy stats do
# not carry it. So the dashboard keeps what it did. One small file beside the
# audit logs, because QA and production dashboards refresh the SAME servers and
# each has its own log; a target's age must not depend on which one you opened.
# Scanning those logs would also mean reading 35 MB to draw a page.
# ---------------------------------------------------------------------------

_refresh_lock = threading.Lock()


def load_refreshes(path) -> dict:
    """target name -> {at, confirmed}. A missing or damaged file means nothing
    is recorded: this is a display aid, and must not take the page down."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record_refreshes(path, results: list[dict], *, now=None) -> None:
    """Stamp each SUCCESSFUL refresh in ``results``; a failed one reloaded
    nothing, so the older time is still the true one.

    `confirmed` is false for an empty 200, which is how the Groovy server answers
    a completed refresh AND a rejected token. The time is kept and flagged,
    because dropping it would leave that server with no age at all.
    """
    done = [r for r in results if r["action"] == "refresh" and r["ok"]]
    if not done:
        return
    at = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    with _refresh_lock:
        state = load_refreshes(path)
        for r in done:
            state[r["name"]] = {"at": at, "confirmed": not r["empty"]}
        tmp = Path(f"{path}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
        os.replace(tmp, path)


def _fetch(url: str, timeout: int):
    """(status, body, the server's Date, when we asked, when we heard).

    The last two bracket the reading: our clock is read BEFORE the request and
    again the moment the headers land — never after the body, which on a refresh
    takes forty seconds and would be charged to the clock.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "cwva-dashboard/0.1"})
    asked = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (config-listed hosts)
        heard = time.time()
        return resp.status, resp.read(), resp.headers.get("Date"), asked, heard


# The token IS a timestamp: the server divides it back out and requires the
# result to be within ±30 s of its own clock. So a server whose clock has
# drifted rejects a perfectly good credential, and does so INTERMITTENTLY as the
# skew crosses the boundary — which is what Rick saw from the PC, whose Windows
# clock was 29 s behind. Every HTTP response carries the server's clock in its
# `Date` header, so the diagnosis costs nothing and beats "empty response".
TOLERANCE_S = 30
_SKEW_WARN_S = 20


def _measure_skew(date_header: str | None, asked: float, heard: float) -> float | None:
    """How far the server's clock is BEHIND ours *at least*, or None for no claim.

    The server stamped `Date` at some unobservable moment between our sending
    the request and our receiving the headers, so what we know is an INTERVAL,
    not a number. Report only what the whole interval agrees on: if it straddles
    zero the reading is indistinguishable from round-trip time and the honest
    answer is silence.

    This is not pedantry. The first version measured after reading the body and
    announced a 40s drift on a refresh that takes 40s — on a machine whose clock
    had just been fixed. A diagnostic that cries wolf is worse than none, since
    the next real skew reads as another false alarm.
    """
    if not date_header:
        return None
    try:
        served = email.utils.parsedate_to_datetime(date_header).timestamp()
    except (TypeError, ValueError):
        return None
    # `Date` has one-second resolution; spend it in the server's favour.
    behind_by_at_least = asked - served - 1.0
    ahead_by_at_least = heard - served + 1.0
    if behind_by_at_least > 0:
        return behind_by_at_least
    if ahead_by_at_least < 0:
        return ahead_by_at_least
    return None


def _skew_note(name: str, skew: float) -> str:
    direction = "behind" if skew > 0 else "ahead of"
    verdict = ("past that window, so this server rejects the token — as an "
               "empty 200 on the Groovy server, 401 on the Python one"
               if abs(skew) > TOLERANCE_S else
               "inside the window but near its edge, so calls will fail "
               "intermittently as it drifts")
    return (f"CLOCK SKEW: {name}'s clock is at least {abs(skew):.0f}s {direction} this "
            f"machine. The token IS a timestamp, accepted within "
            f"\u00b1{TOLERANCE_S}s: {verdict}. Resync the clock on that machine "
            f"(Windows: w32tm /resync, as administrator).")


def call_all(targets, action: str, *, secrets_path: str = _DEFAULT_SECRETS,
             timeout: int = _DEFAULT_TIMEOUT, opener=None) -> list[dict]:
    """Every target at once.

    In parallel because serially is the thing Rick asked to stop doing: a
    refresh reloads a server's whole RDF store, so three servers in sequence is
    three full reloads of waiting. Threads rather than async because the call is
    a blocking `urlopen` and there are three of them, not three hundred.

    Results come back in TARGET ORDER regardless of who answered first, so a
    page can put each one in its own card without guessing.
    """
    targets = list(targets)
    if not targets:
        return []
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = [
            pool.submit(call, t, action, secrets_path=secrets_path,
                        timeout=timeout, opener=opener)
            for t in targets
        ]
        return [f.result() for f in futures]
