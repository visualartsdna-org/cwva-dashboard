"""The three gates that decide whether a certificate may complete a proof.

The durable half (`PROOF_WORKFLOW.md` §6). A scraped certificate and an API
response are both untrusted input; what makes either acceptable is that a wrong
one cannot pass. **A parser that cannot silently lie is a sound foundation for
an evidentiary record; one that can is not.**

    1. the extracted leaf equals the incipient record's `vad:dataHash`
    2. the path recomputes to the extracted root
    3. the root appears in the named transaction, on-chain

Gate 3 is the only one needing the network, so it arrives as a callable rather
than being performed here: law 11 puts the fetch trusted-side and hands the
pure result to the code that writes, the way the ffprobe duration probe is
split. **A gate that was not run is reported as not run, never as passed** --
the trap CLAUDE.md records for fixtures, where "gates passed" came to mean "no
gates ran".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .certificate import Certificate
from .merkle import normalise, pack, verify

__all__ = ["ProofFields", "Validation", "validate", "eastern_offset"]


def eastern_offset(d) -> int:
    """US Eastern's UTC offset for a date: −4 under DST, −5 otherwise.

    Here because the certificate prints a LOCAL time with no zone (it is
    rendered in the timezone of whoever generated it) and the zone has to come
    from somewhere. This is a default for a US-Eastern artist, not a law: it
    belongs in configuration the moment a second timezone exists, and the
    caller may pass any offset it likes.
    """
    y = d.year
    mar = datetime(y, 3, 1).date()
    start = mar + timedelta(days=(6 - mar.weekday()) % 7 + 7)   # 2nd Sunday
    nov = datetime(y, 11, 1).date()
    end = nov + timedelta(days=(6 - nov.weekday()) % 7)          # 1st Sunday
    return -4 if start <= d < end else -5


@dataclass(frozen=True)
class ProofFields:
    """What a validated certificate contributes to an incipient record."""

    data_hash: str
    root_hash: str
    transaction: str
    blockchain: str
    timestamp: datetime          # absolute: the local reading, with its offset
    start_date: str              # the date part IN THAT OFFSET, never UTC
    merkle_path: str             # the packed literal


@dataclass
class Validation:
    ok: bool = False
    fields: ProofFields | None = None
    passed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    not_run: list[str] = field(default_factory=list)

    def summary(self) -> str:
        bits = [f"{len(self.passed)} passed"]
        if self.failed:
            bits.append(f"{len(self.failed)} FAILED")
        if self.not_run:
            bits.append(f"{len(self.not_run)} not run")
        return ", ".join(bits)


def validate(cert: Certificate, expected_data_hash: str, *,
             offset_hours=None, chain_lookup=None) -> Validation:
    """Run the gates over ``cert`` against the incipient record's hash.

    ``chain_lookup(txid) -> iterable of hex strings`` returns whatever the
    transaction commits to; omit it and gate 3 is recorded as not run.
    ``offset_hours`` overrides the US-Eastern default used to anchor the
    certificate's zoneless local time.
    """
    v = Validation()

    # 1 — binds the document to the record. Catches a certificate attached to
    #     the wrong proof, which is the defect UnmooredSwing.jpg carries.
    if normalise(cert.data_hash) == normalise(expected_data_hash):
        v.passed.append("leaf matches the record's dataHash")
    else:
        v.failed.append(
            f"leaf {cert.data_hash[:16]}… is not the record's "
            f"{normalise(expected_data_hash)[:16]}…")

    # 2 — binds the path to the root. A wrong sibling cannot produce the right
    #     parent, so this catches every extraction and transcription error.
    if cert.path and verify(cert.data_hash, cert.path, cert.root_hash):
        v.passed.append(f"path of {len(cert.path)} levels reaches the root")
    else:
        v.failed.append("path does not reach the declared root")

    # 3 — binds the root to the blockchain. The only networked step.
    if chain_lookup is None:
        v.not_run.append("root not checked on-chain (no lookup supplied)")
    else:
        committed = {normalise(h) for h in (chain_lookup(cert.transaction) or ())}
        if normalise(cert.root_hash) in committed:
            v.passed.append("root is committed by the transaction")
        else:
            v.failed.append(
                f"transaction {cert.transaction[:16]}… does not commit "
                f"{cert.root_hash[:16]}…")

    if v.failed or cert.when is None:
        if cert.when is None:
            v.failed.append("no timestamp on the certificate")
        v.ok = False
        return v

    # The certificate's time is LOCAL and zoneless. Anchor it, and take the
    # date in that same offset -- `xsd:date` cannot carry a zone, so a UTC
    # reading would silently assert a convention nothing states, and for most
    # of these records the UTC date is the following day.
    off = eastern_offset(cert.when.date()) if offset_hours is None else offset_hours
    when = cert.when.replace(tzinfo=timezone(timedelta(hours=off)))
    v.fields = ProofFields(
        data_hash="0x" + normalise(cert.data_hash),
        root_hash="0x" + normalise(cert.root_hash),
        transaction="0x" + normalise(cert.transaction),
        blockchain=cert.blockchain,
        timestamp=when,
        start_date=when.date().isoformat(),
        merkle_path=pack(cert.path),
    )
    # `ok` means FULLY validated: every gate ran and every gate passed. A
    # skipped gate 3 leaves ok False with the reason in `not_run`, because
    # "gates passed" must never come to mean "no gates ran" -- the trap
    # CLAUDE.md records for fixtures, and one I wrote the warning for and then
    # fell into on the first draft of this function.
    v.ok = not v.failed and not v.not_run
    return v
