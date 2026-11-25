"""The three gates. These never touch a PDF.

The durable half of the workflow is tested with synthetic certificates so it
runs everywhere; the extractor is tested against real ones where they exist
(`test_certificate.py`). That split is the design: an API adapter would replace
the extractor and leave every test here standing.
"""

from datetime import datetime

import pytest

from cwva_dashboard.proof.certificate import Certificate
from cwva_dashboard.proof.merkle import Step, fold
from cwva_dashboard.proof.validate import eastern_offset, validate

LEAF = "fb0b5307d925e290b5a87a68edb0c0102a29b8d3cb98acca98c4318cc66a5812"
SIB = "fad4c150045c6d39fb49962872bfa2445ef2255318203430f53af840d9342774"
PATH = [Step("L", SIB)]
ROOT = fold(LEAF, PATH)
TXN = "eb8b605c2d324e63ff88ea2beca0e434da556787e39d6d5575d9652c199c8d71"


def _cert(**over):
    base = dict(data_hash=LEAF, root_hash=ROOT, transaction=TXN, blockchain="Bitcoin",
                when=datetime(2026, 2, 4, 19, 12, 3), path=PATH, route="json",
                hashes=frozenset())
    return Certificate(**{**base, **over})


def _chain(root):
    return lambda txid: [root]


def test_a_sound_certificate_passes_all_three():
    v = validate(_cert(), LEAF, chain_lookup=_chain(ROOT))
    assert v.ok and len(v.passed) == 3 and not v.failed


def test_gate_1_rejects_a_certificate_for_a_DIFFERENT_record():
    """The defect UnmooredSwing.jpg carries: a proof wearing its sibling's
    values. The join key is the file's own hash, so this cannot pass."""
    v = validate(_cert(), "0x" + "ab" * 32, chain_lookup=_chain(ROOT))
    assert not v.ok and "is not the record's" in v.failed[0]


def test_gate_2_rejects_a_path_that_does_not_reach_the_root():
    v = validate(_cert(path=[Step("L", "00" * 32)]), LEAF, chain_lookup=_chain(ROOT))
    assert not v.ok and any("does not reach" in f for f in v.failed)


def test_gate_3_rejects_a_root_the_transaction_does_not_commit():
    v = validate(_cert(), LEAF, chain_lookup=_chain("cc" * 32))
    assert not v.ok and any("does not commit" in f for f in v.failed)


def test_a_gate_that_did_not_RUN_is_not_a_gate_that_PASSED():
    """`ok` means every gate ran and every gate passed. Otherwise "gates
    passed" comes to mean "no gates ran", which is the trap CLAUDE.md records
    for fixtures -- and which the first draft of `validate` fell into."""
    v = validate(_cert(), LEAF)                      # no chain_lookup
    assert not v.ok
    assert len(v.passed) == 2 and len(v.not_run) == 1
    assert not v.failed, "a skipped gate is not a failed gate either"


def test_no_timestamp_is_a_failure_not_a_blank_field():
    v = validate(_cert(when=None), LEAF, chain_lookup=_chain(ROOT))
    assert not v.ok and any("no timestamp" in f for f in v.failed)


def test_the_zoneless_local_time_is_anchored_and_the_DATE_follows_the_OFFSET():
    """The certificate prints a local time with no zone. `xsd:date` cannot
    carry one either, so the date is read in the same offset -- never UTC,
    which for most of these records is the following day."""
    v = validate(_cert(), LEAF, chain_lookup=_chain(ROOT))
    assert v.fields.timestamp.isoformat() == "2026-02-04T19:12:03-05:00"
    assert v.fields.start_date == "2026-02-04"
    assert v.fields.timestamp.astimezone().utcoffset() is not None


def test_the_utc_date_would_have_been_the_NEXT_DAY():
    """Stated as a test because it is the whole reason for the rule: the
    platform broadcasts just after midnight UTC."""
    import datetime as dt
    v = validate(_cert(when=datetime(2026, 8, 25, 20, 21, 21)), LEAF,
                 chain_lookup=_chain(ROOT))
    assert v.fields.start_date == "2026-08-25"
    assert v.fields.timestamp.astimezone(dt.timezone.utc).date().isoformat() == "2026-08-26"


def test_an_explicit_offset_overrides_the_eastern_default():
    v = validate(_cert(), LEAF, offset_hours=0, chain_lookup=_chain(ROOT))
    assert v.fields.timestamp.isoformat() == "2026-02-04T19:12:03+00:00"


@pytest.mark.parametrize("date,off", [
    ("2026-02-04", -5), ("2026-08-25", -4), ("2026-10-06", -4),
    ("2026-11-02", -5), ("2026-03-07", -5), ("2026-03-08", -4),
    ("2026-10-31", -4), ("2026-11-01", -5),
])
def test_eastern_offset_follows_US_DST(date, off):
    """Three of the original twenty-four carried an offset wrong for their
    date, one of them -21:00, which is not a legal offset at all."""
    from datetime import date as D
    assert eastern_offset(D.fromisoformat(date)) == off


def test_the_written_fields_carry_the_0x_prefix_back():
    """The ontology plan §14 keeps an external system's facts in that system's
    terms, and OriginStamp reports hashes `0x`-prefixed."""
    v = validate(_cert(), LEAF, chain_lookup=_chain(ROOT))
    assert v.fields.data_hash.startswith("0x")
    assert v.fields.root_hash.startswith("0x")
    assert v.fields.transaction.startswith("0x")
    assert not v.fields.merkle_path.startswith("0x"), "the path is packed, not prefixed"
