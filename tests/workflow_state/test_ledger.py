"""Hygiene ledger: idempotent dismissals, kind-keyed lookup, TTL round-trip."""

from __future__ import annotations

from cwva_dashboard.concepts.ledger import HygieneLedger


def test_dismiss_and_lookup():
    lg = HygieneLedger.from_ttl()
    lg.dismiss("works_without_workonsite", "work:w2", "on no site")
    assert lg.is_dismissed("works_without_workonsite", "work:w2")
    assert lg.dismissed("works_without_workonsite") == {"work:w2"}
    assert not lg.is_dismissed("works_without_workonsite", "work:w9")
    assert lg.dismissed("other_kind") == set()


def test_dismiss_is_idempotent():
    lg = HygieneLedger.from_ttl()
    lg.dismiss("k", "x")
    lg.dismiss("k", "x", "changed reason")
    assert lg.dismissed("k") == {"x"}  # one entry, not two


def test_undismiss():
    lg = HygieneLedger.from_ttl()
    lg.dismiss("k", "x")
    assert lg.undismiss("k", "x") is True
    assert lg.dismissed("k") == set()
    assert lg.undismiss("k", "x") is False  # already gone


def test_ttl_roundtrip_survives_reload():
    lg = HygieneLedger.from_ttl()
    lg.dismiss("k", "x", "reason")
    lg.dismiss("k", "y")
    text = lg.to_ttl()

    reloaded = HygieneLedger.from_ttl(text)
    assert reloaded.dismissed("k") == {"x", "y"}
