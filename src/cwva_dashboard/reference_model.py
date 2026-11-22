"""A new collection's ontology and thesaurus, from a reference VisualArtsDNA server.

A collection that starts with no data has no model and no vocabulary, and no
form works without them: the types, the paints, the papers all come from there.
cwva-py solves the same problem the same way (``util/reference.py``): on first
start, if the folders are empty, fetch the model and the vocabulary from a
``referenceModel`` server (Rick, 2026-11-21: "use the referenceModel on first
start").

**A sanctioned network effect** (CLAUDE.md law 11): a read-only GET of two
Turtle documents, trusted-side, run by the import script and never by a
registry tool. The documents are parsed before anything is written, and they
are written into the SANDBOX through FileOps, so they arrive as drafts: the
first distribution puts them into the source of truth, where cwva-py reads
them, exactly as any other change would go.

Only when the folder is empty. A collection that has a model keeps it.
"""

from __future__ import annotations

import urllib.request
from dataclasses import dataclass, field

from rdflib import Graph

__all__ = ["fetch_reference_model", "ReferenceResult", "MODEL_FILE", "VOCAB_FILE"]

#: The same names cwva-py's own bootstrap uses.
MODEL_FILE = "cwva-reference.ttl"
VOCAB_FILE = "vocab-reference.ttl"
_TIMEOUT_S = 60


@dataclass
class ReferenceResult:
    written: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _get(url: str, opener=None) -> str:
    req = urllib.request.Request(url, headers={"Accept": "text/turtle",
                                               "User-Agent": "cwva-dashboard"})
    with (opener or urllib.request.urlopen)(req, timeout=_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8")


def _has_ttl(fileops, directory: str) -> bool:
    try:
        return any(e.is_file and e.name.endswith(".ttl") for e in fileops.list_dir(directory))
    except (FileNotFoundError, NotADirectoryError):
        return False


def fetch_reference_model(base_url: str, fileops, layout, *, opener=None) -> ReferenceResult:
    """Fill an EMPTY model folder and an EMPTY vocabulary folder from
    ``base_url`` (``/schema?format=ttl`` and ``/vocab``, as cwva-py fetches)."""
    base = base_url.rstrip("/")
    res = ReferenceResult()
    for kind, url, name in (("model_ttl", f"{base}/schema?format=ttl", MODEL_FILE),
                            ("vocab_ttl", f"{base}/vocab", VOCAB_FILE)):
        directory = layout.dir(kind).strip("/")
        if _has_ttl(fileops, directory):
            res.skipped.append(directory)
            continue
        try:
            text = _get(url, opener)
            triples = len(Graph().parse(data=text, format="turtle"))
        except Exception as exc:  # network, HTTP or a reply that is not Turtle
            res.errors.append(f"{url}: {type(exc).__name__}: {exc}")
            continue
        if not triples:
            res.errors.append(f"{url}: the reply held no triples")
            continue
        path = f"{directory}/{name}"
        fileops.write_text(path, text, make_parents=True)
        res.written.append({"path": path, "triples": triples, "url": url})
    return res
