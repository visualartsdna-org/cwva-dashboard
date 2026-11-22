"""`ai_service` is the only thing that talks to a provider (law 7).

Every test here runs against a recorded double, never the network — which is
the point: the suite must be runnable with no key, on a machine with no
outbound access, and it must assert the STRUCTURE of what comes back rather
than any string a model produced (law 8).
"""

from __future__ import annotations

import json

import pytest

from cwva_dashboard.ai_service import AIService, AIUnavailable, read_api_key
from cwva_dashboard.ai_service.profiles import load_profiles

KEY = "sk-ant-test-not-a-real-key"


def _reply(text="a reply", *, input_tokens=100, output_tokens=20):
    return 200, json.dumps({
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
    }).encode()


def _error(status, message):
    return status, json.dumps({"error": {"message": message}}).encode()


@pytest.fixture
def secrets(tmp_path):
    p = tmp_path / "secrets.rson"
    p.write_text('{"secrets": {"anthropicApiKey": "%s"}}' % KEY)
    return str(p)


@pytest.fixture
def service(secrets, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    sent = []

    def transport(url, headers, payload, timeout):
        sent.append({"url": url, "headers": headers, "payload": payload})
        return _reply()

    svc = AIService(profiles=load_profiles(), secrets_path=secrets)
    svc.transport = transport
    return svc, sent


# -- the credential ----------------------------------------------------------


def test_the_environment_wins_over_the_secrets_file(secrets, monkeypatch):
    """A CI runner has no secrets file, and this machine already carries
    GCP_BUCKET the same way."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-from-env")

    assert read_api_key("anthropic", secrets) == "sk-ant-from-env"


def test_the_secrets_file_is_the_fallback(secrets, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    assert read_api_key("anthropic", secrets) == KEY


def test_NEITHER_says_where_to_put_it(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(AIUnavailable) as exc:
        read_api_key("anthropic", tmp_path / "nothing.rson")

    assert "never in config/" in str(exc.value)


def test_the_key_NEVER_appears_in_what_the_completion_carries(service):
    svc, _sent = service

    out = svc.complete("dts_derive", messages=[{"role": "user", "content": "hi"}])

    assert KEY not in repr(out)
    assert KEY not in json.dumps(out.audit_fields())


def test_the_audit_fields_carry_cost_but_no_CONTENT(service):
    """A prompt can be a whole criticism document and the chain is append-only,
    so nothing goes in that a person would have to redact later."""
    svc, _sent = service

    fields = svc.complete("dts_derive",
                          messages=[{"role": "user", "content": "secret prose"}],
                          system="secret system").audit_fields()

    assert fields["input_tokens"] == 100 and fields["output_tokens"] == 20
    assert "secret" not in json.dumps(fields)
    assert set(fields) == {"task", "model", "ok", "attempts", "input_tokens",
                           "output_tokens", "thinking_tokens", "status_code",
                           "stop_reason", "error"}


# -- the profile decides, the caller does not --------------------------------


def test_the_task_chooses_the_model(service):
    svc, sent = service

    svc.complete("dts_summarize", messages=[{"role": "user", "content": "x"}])

    assert sent[0]["payload"]["model"] == svc.profiles["dts_summarize"].model
    assert sent[0]["payload"]["max_tokens"] == svc.profiles["dts_summarize"].max_tokens


def test_an_unknown_task_is_refused_by_NAME(service):
    svc, _sent = service

    with pytest.raises(KeyError) as exc:
        svc.complete("dts_invent", messages=[])

    assert "ai_profiles.rson" in str(exc.value)


def test_every_DTS_stage_has_a_profile():
    """A missing profile is discovered at the moment of the call otherwise —
    three stages in, after two have already been paid for."""
    profiles = load_profiles()

    for task in ("dts_derive", "dts_tag", "dts_summarize"):
        assert task in profiles, task
        assert profiles[task].model and profiles[task].max_tokens > 0


# -- a refusal is legible ----------------------------------------------------


def test_credits_exhausted_holds_off_and_SAYS_UNTIL_WHEN(service):
    """Retrying into a wall for two minutes, then failing generically, is what
    this replaces."""
    svc, _sent = service
    svc.transport = lambda *a: _error(429, "Your credit balance is too low")

    out = svc.complete("dts_derive", messages=[], sleep=lambda s: None)

    assert not out.ok and "credits exhausted" in out.error
    state = svc.availability()
    assert not state["available"] and state["until"]
    # And the next call does not even try.
    svc.transport = lambda *a: _reply()
    assert "unavailable until" in svc.complete("dts_derive", messages=[]).error


def test_a_BAD_KEY_is_not_a_rate_limit(service):
    svc, _sent = service
    svc.transport = lambda *a: _error(401, "invalid x-api-key")

    out = svc.complete("dts_derive", messages=[], sleep=lambda s: None)

    assert out.status_code == 401
    assert "check the API key" in out.error
    assert out.attempts == 1, "a bad key will not fix itself on a retry"


def test_a_RATE_LIMIT_is_retried_and_then_succeeds(service):
    svc, _sent = service
    calls = {"n": 0}

    def flaky(*a):
        calls["n"] += 1
        return _reply() if calls["n"] > 2 else _error(429, "rate limit exceeded")

    svc.transport = flaky
    out = svc.complete("dts_derive", messages=[], sleep=lambda s: None)

    assert out.ok and out.attempts == 3
    assert svc.availability()["available"], "a rate limit is not a cooldown"


def test_a_SERVER_ERROR_is_retried_then_reported(service):
    svc, _sent = service
    svc.transport = lambda *a: _error(503, "overloaded")

    out = svc.complete("dts_derive", messages=[], sleep=lambda s: None)

    assert not out.ok and out.attempts == 4
    assert "503" in out.error


def test_a_CONNECTION_failure_is_retried_not_raised(service):
    svc, _sent = service

    def dead(*a):
        raise OSError("network is unreachable")

    svc.transport = dead
    out = svc.complete("dts_derive", messages=[], sleep=lambda s: None)

    assert not out.ok and "unreachable" in out.error


# -- what the wire actually accepts ------------------------------------------


def test_TEMPERATURE_is_omitted_unless_a_profile_asks(service):
    """The current Claude models refuse the parameter — HTTP 400,
    "`temperature` is deprecated for this model" — so a harmless-looking
    default of 0.0 failed every call on the first real request."""
    svc, sent = service

    svc.complete("dts_derive", messages=[{"role": "user", "content": "x"}])

    assert "temperature" not in sent[0]["payload"]


def test_a_profile_that_asks_for_one_still_gets_it(service):
    """It stays expressible because an OpenAI-compatible endpoint takes one,
    and CI has to pass against both."""
    from dataclasses import replace

    svc, sent = service
    svc.profiles = {**svc.profiles,
                    "dts_derive": replace(svc.profiles["dts_derive"], temperature=0.2)}

    svc.complete("dts_derive", messages=[{"role": "user", "content": "x"}])

    assert sent[0]["payload"]["temperature"] == 0.2


def test_the_shipped_profiles_set_no_temperature():
    """Guards the config, not just the code: the parameter is refused by the
    models this deployment is configured to use."""
    for profile in load_profiles().values():
        assert profile.temperature is None, profile.task


def test_a_TRUNCATED_reply_says_so(service):
    """"Cut off at the cap" and "malformed" are different problems with
    different remedies, and a parser only ever sees the second."""
    svc, _sent = service
    svc.transport = lambda *a: (200, json.dumps({
        "content": [{"type": "text", "text": '[{"label": "half a con'}],
        "usage": {"input_tokens": 30000, "output_tokens": 8192},
        "stop_reason": "max_tokens"}).encode())

    out = svc.complete("dts_derive", messages=[])

    assert out.ok and out.truncated
    assert out.audit_fields()["stop_reason"] == "max_tokens"


# -- reasoning has a budget, and spending it all is its own failure ----------


def test_the_EFFORT_is_sent_when_a_profile_sets_one(service):
    """A token budget is rejected by these models outright — "use
    `thinking.type.adaptive` and `output_config.effort`"."""
    from dataclasses import replace

    svc, sent = service
    svc.profiles = {**svc.profiles,
                    "dts_derive": replace(svc.profiles["dts_derive"], effort="low")}

    svc.complete("dts_derive", messages=[{"role": "user", "content": "x"}])

    assert sent[0]["payload"]["thinking"] == {"type": "adaptive"}
    assert sent[0]["payload"]["output_config"] == {"effort": "low"}


def test_no_effort_means_no_such_parameter(service):
    svc, sent = service

    svc.complete("dts_summarize", messages=[{"role": "user", "content": "x"}])

    assert "output_config" not in sent[0]["payload"]


def test_ALL_THINKING_is_distinguished_from_a_truncated_answer(service):
    """Both stop at `max_tokens` and they have different remedies: budget the
    reasoning, do not raise the cap. A real derivation spent its entire
    16,384-token budget thinking and returned an empty text block."""
    svc, _sent = service
    svc.transport = lambda *a: (200, json.dumps({
        "content": [{"type": "thinking", "thinking": "..."}],
        "usage": {"input_tokens": 31930, "output_tokens": 16384,
                  "output_tokens_details": {"thinking_tokens": 16384}},
        "stop_reason": "max_tokens"}).encode())

    out = svc.complete("dts_derive", messages=[])

    assert out.truncated and out.all_thinking
    assert out.thinking_tokens == 16384
    assert out.audit_fields()["thinking_tokens"] == 16384


def test_a_truncated_ANSWER_is_not_all_thinking(service):
    svc, _sent = service
    svc.transport = lambda *a: (200, json.dumps({
        "content": [{"type": "text", "text": '[{"label": "half a con'}],
        "usage": {"input_tokens": 100, "output_tokens": 8192},
        "stop_reason": "max_tokens"}).encode())

    out = svc.complete("dts_derive", messages=[])

    assert out.truncated and not out.all_thinking


def test_the_shipped_EXTRACTION_profiles_set_an_effort():
    """Guards the config. The two stages that must return parseable JSON are
    the two that lost a whole output budget to reasoning."""
    profiles = load_profiles()

    for task in ("dts_derive", "dts_tag"):
        assert profiles[task].effort, task
