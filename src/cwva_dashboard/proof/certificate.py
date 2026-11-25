"""Reading an OriginStamp certificate PDF, with the standard library only.

The disposable half of the proof workflow (the proof workflow notes §5). It exists
because OriginStamp issues API keys by hand after an emailed request, so a CE
user cataloguing their own paintings may simply be declined -- and a feature
that works only for people who can talk a vendor into an account is not a CE
feature. The API adapter, when a key exists, replaces this file and nothing
else.

**Three obvious approaches fail before the right one**, so they are recorded
here to save the next reader the afternoon:

- the proof JSON is NOT in the file as text; searching the raw bytes for
  ``leftSha256`` finds nothing
- nor is it ASCII inside any decompressed stream
- and the page is not an image either, which is the next wrong guess

The text is emitted as **two-byte glyph IDs in hex strings** --
``<0035003700340034002B>`` is ``PROOF`` -- against **subset fonts carrying
ToUnicode CMaps**, and those CMaps are themselves inside compressed object
streams. So: decompress everything, collect every ``beginbfchar`` /
``beginbfrange`` mapping into one table, then decode the content streams
through it. No third-party PDF library is needed, which matters: a CE user
should not have to install one either.
"""

from __future__ import annotations

import json
import re
import unicodedata
import zlib
from dataclasses import dataclass
from datetime import datetime

from .merkle import Step, normalise, reconstruct

__all__ = ["Certificate", "CertificateError", "extract_text", "read_certificate"]

_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
_HEXSTR = re.compile(rb"<([0-9A-Fa-f]+)>")
_BFCHAR = re.compile(rb"beginbfchar(.*?)endbfchar", re.S)
_BFRANGE = re.compile(rb"beginbfrange(.*?)endbfrange", re.S)
_PAIR = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_TRIPLE = re.compile(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>")
_HEX64 = re.compile(r"[0-9a-f]{64}")

#: `Feb 4, 2026, 07:12:03 PM` — a 12-hour clock with NO timezone. The missing
#: zone is the whole reason the original records were twelve hours wrong, and
#: it is why `read_certificate` returns a naive datetime and refuses to guess.
_WHEN = re.compile(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4}), (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)")
_LABELLED = {
    "data": re.compile(r"Data Hash:\s*0x([0-9a-f]{64})"),
    "txn": re.compile(r"Transaction Link:\s*0x([0-9a-f]{64})"),
    "root": re.compile(r"Root Hash:\s*0x([0-9a-f]{64})"),
}
_CHAIN = re.compile(r"([A-Z][A-Za-z]+) Certificate")


class CertificateError(ValueError):
    """The PDF could not be read as an OriginStamp certificate."""


@dataclass(frozen=True)
class Certificate:
    """What a certificate yields. Every hash lowercase, no ``0x``.

    `when` is **naive on purpose**. The certificate prints a local time with no
    offset -- it is rendered in the timezone of whoever generated it -- so the
    zone is not in the document and this module will not invent one. Making it
    absolute is the caller's job, from configuration and from the block time
    (`validate.py`).
    """

    data_hash: str
    root_hash: str
    transaction: str
    blockchain: str
    when: datetime | None
    path: list[Step]
    route: str          # "json" or "search" — which extraction produced the path
    hashes: frozenset   # every 64-hex value seen, for diagnostics


def _tounicode(streams) -> dict:
    """One decoding table from every ToUnicode CMap in the document."""
    cmap: dict[int, str] = {}
    for u in streams:
        for blk in _BFCHAR.findall(u):
            for src, dst in _PAIR.findall(blk):
                try:
                    cmap[int(src, 16)] = bytes.fromhex(dst.decode()).decode("utf-16-be", "replace")
                except ValueError:
                    continue
        for blk in _BFRANGE.findall(u):
            for lo, hi, dst in _TRIPLE.findall(blk):
                lo_i, hi_i, base = int(lo, 16), int(hi, 16), int(dst, 16)
                if hi_i - lo_i > 0xFFFF:      # a malformed range must not hang us
                    continue
                for i in range(hi_i - lo_i + 1):
                    cmap[lo_i + i] = chr(base + i)
    return cmap


def extract_text(pdf: bytes) -> str:
    """All of a certificate's text, in document order."""
    streams = []
    for m in _STREAM.finditer(pdf):
        try:
            streams.append(zlib.decompress(m.group(1)))
        except zlib.error:
            continue
    cmap = _tounicode(streams)
    if not cmap:
        raise CertificateError("no ToUnicode CMap; this is not a text-bearing certificate")
    out = []
    for u in streams:
        if b"<" not in u:
            continue
        for m in _HEXSTR.finditer(u):
            h = m.group(1).decode()
            out.append("".join(cmap.get(int(h[i:i + 4], 16), "")
                               for i in range(0, len(h) - 3, 4)))
    # NFKC, because the certificate sets LIGATURES: "Certificate" arrives as
    # "Certi\ufb01cate" and a plain match for the word fails. Decomposing is
    # safe for everything else here -- hashes are ASCII hex and cannot change.
    return unicodedata.normalize("NFKC", "".join(out))


def _path_from_json(text: str, leaf: str, root: str):
    """Route A: the printed JSON, which nests root -> … -> leaf.

    Each node names BOTH children, so the sibling at every level is whichever
    one is not on our way down.
    """
    # The printed JSON is laid out with spaces -- `{  "sha256"` -- so the
    # opening brace is found by pattern, not by a literal.
    m0 = re.search(r'\{\s*"sha256"', text)
    if not m0:
        return None
    start = m0.start()
    depth = 0
    for i, ch in enumerate(text[start:], start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    else:
        return None
    try:
        node = json.loads(text[start:end])
    except json.JSONDecodeError:
        return None
    if normalise(node.get("sha256", "")) != root:
        return None
    steps = []
    while "left" in node or "right" in node:
        child_key = "left" if "left" in node else "right"
        # the sibling is the OTHER child; the side letter describes the sibling
        side = "R" if child_key == "left" else "L"
        sib = node["rightSha256"] if child_key == "left" else node["leftSha256"]
        steps.append(Step(side, normalise(sib)))
        node = node[child_key]
    if normalise(node.get("sha256", "")) != leaf:
        return None
    steps.reverse()                      # the JSON descends; a path climbs
    return steps


def read_certificate(pdf: bytes) -> Certificate:
    """Parse a certificate. Tries the JSON, falls back to the hash search."""
    text = extract_text(pdf)
    fields = {}
    for key, pat in _LABELLED.items():
        m = pat.search(text)
        if not m:
            raise CertificateError(f"no {key} hash on the certificate")
        fields[key] = m.group(1).lower()
    chain = _CHAIN.search(text)
    w = _WHEN.search(text)
    when = None
    if w:
        mon, day, yr, hh, mm, ss, ap = w.groups()
        hh = int(hh) % 12 + (12 if ap == "PM" else 0)
        when = datetime.strptime(f"{mon} {day} {yr}", "%b %d %Y").replace(
            hour=hh, minute=int(mm), second=int(ss))

    hashes = frozenset(_HEX64.findall(text))
    steps = _path_from_json(text, fields["data"], fields["root"])
    route = "json"
    if steps is None:
        steps = reconstruct(fields["data"], fields["root"], hashes)
        route = "search"
    if steps is None:
        raise CertificateError("no Merkle path recoverable by either route")
    return Certificate(
        data_hash=fields["data"], root_hash=fields["root"], transaction=fields["txn"],
        blockchain=(chain.group(1) if chain else ""), when=when,
        path=steps, route=route, hashes=hashes,
    )
