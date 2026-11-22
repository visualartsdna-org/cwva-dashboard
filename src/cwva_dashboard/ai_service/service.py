"""The ONE place the dashboard talks to a model provider (law 7).

Three properties this module exists to guarantee, none of which a caller can
be trusted to remember:

**It runs trusted-side, and it cannot run anywhere else.** The Landlock
worker's filesystem is confined to the sandbox, so glibc's resolver cannot read
`/etc/resolv.conf` and a hostname does not resolve (`EAI_AGAIN`, measured
2026-09-09). A registry tool that called a provider would not fail loudly — it
would *silently return nothing*, which is how updateWorkOnSite's first real run
produced two empty snapshots. So this is a fifth member of the sanctioned
network-effect class (law 11): a deliberate, audited effect in the trusted
orchestrator, whose pure result is handed to a tool that does the writing.

**The credential never enters a log, a record or an audit entry.** It is read
per call from the environment or `~/.secrets.rson`, used, and dropped; it is
not stored on the instance, not passed to a tool, and not included in the
completion this returns. Instance Control's rule, generalised — that is the one
other place the dashboard holds a secret.

**A refusal is legible.** Credits exhausted, a bad key and a rate limit are
three different problems with three different remedies, and a workflow that
reports "call failed" for all of them sends a person to look in the wrong
place. The cooldown is per service instance, so the screen can say *unavailable
until HH:MM* rather than retrying into a wall.

Retry, backoff and the cooldown schedule are ported from `agent_common.py`
rather than reinvented — the shape was right, it was just in the wrong process,
holding its own key and writing its own files.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..rson import loads
from .profiles import TaskProfile, load_profiles

__all__ = ["AIService", "Completion", "AIUnavailable", "read_api_key"]

#: Anthropic's dated API contract. Not a model name — this is the wire format,
#: and it changes on a different clock from the models, so it stays in code.
_ANTHROPIC_VERSION = "2023-06-01"
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_RETRY_DELAYS = (15, 30, 60)          # between attempts 1-2, 2-3, 3-4
_MAX_ATTEMPTS = 4
_CREDITS_COOLDOWN_S = 1800            # 30 minutes: credits do not come back fast
_AUTH_COOLDOWN_S = 300                # 5 minutes: a bad key will not fix itself
_RETRYABLE = frozenset({500, 502, 503, 504, 529})


class AIUnavailable(RuntimeError):
    """The provider cannot be reached, and retrying now will not help."""


@dataclass(frozen=True)
class Completion:
    """What a task asked for, and what it cost. Never the credential."""

    ok: bool
    text: str = ""
    error: str = ""
    model: str = ""
    task: str = ""
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    status_code: int = 0
    #: Tokens spent REASONING rather than answering. Worth recording
    #: separately: it is most of the cost of a hard task, and a run that
    #: returns nothing has usually spent all of it here.
    thinking_tokens: int = 0
    #: Why the model stopped. `"max_tokens"` means the reply was CUT OFF, which
    #: is a different problem from a malformed one and has a different remedy
    #: (raise the cap, or ask for less). A parser that saw only the broken JSON
    #: would report "the reply was not usable" and send a person to look at the
    #: prompt.
    stop_reason: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def truncated(self) -> bool:
        return self.stop_reason == "max_tokens"

    @property
    def all_thinking(self) -> bool:
        """The budget went entirely on reasoning and no answer came back.

        A distinct failure from a truncated answer, with a distinct remedy —
        budget the thinking, do not raise the cap — and indistinguishable from
        it without this, because both stop at `max_tokens`.
        """
        return self.truncated and not self.text.strip() and self.thinking_tokens > 0

    def audit_fields(self) -> dict:
        """What may be written to the audit log: everything but the content.

        The prompt and the reply can carry a whole criticism document, and the
        audit chain is append-only — so it records that a call happened, to
        what, at what cost, and nothing a person would have to redact later.
        """
        return {"task": self.task, "model": self.model, "ok": self.ok,
                "attempts": self.attempts, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "status_code": self.status_code, "stop_reason": self.stop_reason,
                "thinking_tokens": self.thinking_tokens,
                "error": self.error[:200] if self.error else ""}


def read_api_key(provider: str = "anthropic", secrets_path="~/.secrets.rson") -> str:
    """The credential, read fresh and never retained.

    Environment first (`ANTHROPIC_API_KEY`), the secrets file second. The
    environment wins because that is how this machine already carries
    `GCP_BUCKET`, and because a CI runner has no secrets file. Never
    `config/` — config is committed.
    """
    env = f"{provider.upper()}_API_KEY"
    from_env = os.environ.get(env, "").strip()
    if from_env:
        return from_env
    path = Path(str(secrets_path)).expanduser()
    try:
        block = loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise AIUnavailable(
            f"no {env} in the environment and no secrets file at {path}. "
            f"Put the key in one of them; never in config/, which is committed."
        ) from None
    key = str((block.get("secrets") or {}).get(f"{provider}ApiKey") or "").strip()
    if not key:
        raise AIUnavailable(
            f"{path} has no secrets.{provider}ApiKey, and {env} is unset."
        )
    return key


@dataclass
class AIService:
    """Task in, completion out. The only caller of a provider in this codebase.

    ``transport`` exists for the suite: a callable
    ``(url, headers, payload, timeout) -> (status, body_bytes)``. Tests pass a
    recorded double and never touch the network, which is what law 8 needs —
    assert the STRUCTURE of what comes back, never the exact strings.
    """

    profiles: dict[str, TaskProfile] = field(default_factory=dict)
    secrets_path: str = "~/.secrets.rson"
    transport = None
    _unavailable_until: datetime | None = field(default=None, init=False, repr=False)
    _unavailable_why: str = field(default="", init=False, repr=False)

    def __post_init__(self):
        if not self.profiles:
            self.profiles = load_profiles()

    # -- availability -------------------------------------------------------

    def availability(self) -> dict:
        """What the screen shows instead of a generic failure."""
        if self._unavailable_until is None:
            return {"available": True, "until": "", "why": ""}
        if datetime.now(timezone.utc) >= self._unavailable_until:
            self._unavailable_until, self._unavailable_why = None, ""
            return {"available": True, "until": "", "why": ""}
        return {"available": False,
                "until": self._unavailable_until.isoformat(timespec="seconds"),
                "why": self._unavailable_why}

    def _hold_off(self, seconds: int, why: str) -> None:
        self._unavailable_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        self._unavailable_why = why

    # -- the call -----------------------------------------------------------

    def complete(self, task: str, *, messages: list, system: str = "",
                 sleep=time.sleep) -> Completion:
        profile = self.profiles.get(task)
        if profile is None:
            raise KeyError(
                f"no AI profile for task {task!r}; add it to config/ai_profiles.rson"
            )
        state = self.availability()
        if not state["available"]:
            return Completion(ok=False, task=task, model=profile.model,
                              error=f"unavailable until {state['until']} — {state['why']}")
        if profile.provider != "anthropic":
            return Completion(ok=False, task=task, model=profile.model,
                              error=f"no adapter for provider {profile.provider!r}")

        payload = {
            "model": profile.model,
            "max_tokens": profile.max_tokens,
            "messages": messages,
        }
        # Sent only when a profile asks for it: the current Claude models
        # REFUSE the parameter outright (400, "`temperature` is deprecated for
        # this model"), so a default of 0.0 failed every call on the first
        # real request. Kept in the profile because an OpenAI-compatible
        # endpoint still takes one, and CI has to pass against both.
        if profile.temperature is not None:
            payload["temperature"] = profile.temperature
        # Left at the default, the model can spend the whole of `max_tokens`
        # reasoning and return no text at all — measured, on a real derivation.
        # Adaptive thinking plus an effort level is the control these models
        # take; a token budget is rejected outright.
        if profile.effort:
            payload["thinking"] = {"type": "adaptive"}
            payload["output_config"] = {"effort": profile.effort}
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": read_api_key(profile.provider, self.secrets_path),
            "content-type": "application/json",
            "anthropic-version": _ANTHROPIC_VERSION,
        }

        last = ""
        for attempt in range(_MAX_ATTEMPTS):
            if attempt:
                sleep(_RETRY_DELAYS[min(attempt - 1, len(_RETRY_DELAYS) - 1)])
            try:
                status, body = self._send(_ANTHROPIC_URL, headers, payload,
                                          profile.timeout_s)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = f"{type(exc).__name__}: {exc}"
                continue

            if status == 200:
                data = json.loads(body.decode("utf-8"))
                text = "".join(b.get("text", "") for b in data.get("content", [])
                               if b.get("type") == "text")
                usage = data.get("usage") or {}
                return Completion(
                    ok=True, text=text, task=task, model=profile.model,
                    attempts=attempt + 1, status_code=200,
                    stop_reason=str(data.get("stop_reason") or ""),
                    input_tokens=int(usage.get("input_tokens", 0)),
                    output_tokens=int(usage.get("output_tokens", 0)),
                    thinking_tokens=int(
                        (usage.get("output_tokens_details") or {})
                        .get("thinking_tokens", 0)),
                )

            detail = _detail(body)
            if status == 401:
                self._hold_off(_AUTH_COOLDOWN_S, "authentication failed (401)")
                return Completion(ok=False, task=task, model=profile.model,
                                  attempts=attempt + 1, status_code=401,
                                  error="authentication failed — check the API key")
            if status == 429 and _is_credits(detail):
                self._hold_off(_CREDITS_COOLDOWN_S, f"credits/billing: {detail[:80]}")
                return Completion(ok=False, task=task, model=profile.model,
                                  attempts=attempt + 1, status_code=429,
                                  error=f"credits exhausted: {detail[:200]}")
            if status == 429 or status in _RETRYABLE:
                last = f"HTTP {status}: {detail[:200]}"
                continue
            return Completion(ok=False, task=task, model=profile.model,
                              attempts=attempt + 1, status_code=status,
                              error=f"HTTP {status}: {detail[:200]}")

        return Completion(ok=False, task=task, model=profile.model,
                          attempts=_MAX_ATTEMPTS,
                          error=f"{_MAX_ATTEMPTS} attempts failed; last: {last}")

    def _send(self, url, headers, payload, timeout):
        if self.transport is not None:
            return self.transport(url, headers, payload, timeout)
        req = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"),
            headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()


def _detail(body: bytes) -> str:
    try:
        return str(json.loads(body.decode("utf-8")).get("error", {}).get("message", ""))
    except Exception:
        return body.decode("utf-8", errors="replace")[:200]


def _is_credits(detail: str) -> bool:
    """A 429 for money is not a 429 for speed, and only one of them is worth
    waiting out."""
    low = detail.lower()
    return any(word in low for word in ("credit", "billing", "payment", "quota"))
