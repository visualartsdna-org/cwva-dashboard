"""Syntax checks for a file someone hands the dashboard (inventory #27/#28).

One check for every RDF serialisation rdflib reads, and plain JSON; the hub
picks the parser from the file's extension (Rick, 2026-11-19).

The Groovy "Load TTL File" and "Load JSON File" were never loads: they parsed
the file and said whether it was well formed. Here they are named for what they
do. The text arrives as an argument and nothing is written anywhere, so a file
checked here does not enter the sandbox: content still enters only through the
drop folder (law 12).
"""

from __future__ import annotations

import json
import re

from rdflib import BNode, Dataset, Graph

from .base import Tool, ToolError

__all__ = ["CHECK_TOOLS", "check_syntax", "MAX_CHECK_CHARS", "EXTENSIONS",
           "KIND_NAMES", "RDF_KINDS"]

#: Generous for a hand-checked file; the largest record in the store is ~60 KB
#: and the whole thesaurus ~2 MB.
MAX_CHECK_CHARS = 20_000_000

_REASON = re.compile(r"Bad syntax \((.*?)\) at \^", re.S)


def _context(text: str, line: int, around: int = 2) -> list:
    lines = text.splitlines()
    lo, hi = max(1, line - around), min(len(lines), line + around)
    return [{"n": n, "text": lines[n - 1], "here": n == line} for n in range(lo, hi + 1)]


#: kind -> rdflib parser name, for the RDF serialisations a file may be in.
RDF_KINDS = {"turtle": "turtle", "xml": "xml", "nt": "nt", "n3": "n3",
             "trig": "trig", "nquads": "nquads", "json-ld": "json-ld"}
_DATASETS = {"trig", "nquads"}  # named graphs: parsed into a Dataset
_LINE_BASED = {"nt", "nquads"}  # errors found by re-reading line by line

#: What the hub's one "Syntax Check RDF/JSON" accepts, by extension.
EXTENSIONS = {
    ".ttl": "turtle", ".turtle": "turtle",
    ".rdf": "xml", ".owl": "xml", ".xml": "xml",
    ".nt": "nt", ".n3": "n3", ".trig": "trig", ".nq": "nquads",
    ".jsonld": "json-ld", ".json-ld": "json-ld",
    ".json": "json",
}
KIND_NAMES = {"turtle": "Turtle", "xml": "RDF/XML", "nt": "N-Triples", "n3": "N3",
              "trig": "TriG", "nquads": "N-Quads", "json-ld": "JSON-LD", "json": "JSON"}


def _failure(kind, text, lines, message, line=None, column=None) -> dict:
    if isinstance(line, int):
        line = max(1, min(line, lines))
    return {"ok": False, "kind": kind, "lines": lines, "error": {
        "message": message, "line": line, "column": column,
        "context": _context(text, line) if line else []}}


def _first_bad_line(text: str, parser: str):
    """N-Triples and N-Quads are one statement per line, so the first line that
    will not parse on its own is the error; rdflib only quotes it."""
    for n, ln in enumerate(text.splitlines(), 1):
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        try:
            (Dataset() if parser == "nquads" else Graph()).parse(data=ln + "\n", format=parser)
        except Exception:
            return n
    return None


def check_syntax(text: str, kind: str) -> dict:
    """``{"ok": True, ...counts}`` or ``{"ok": False, "error": {...}}``."""
    if len(text) > MAX_CHECK_CHARS:
        raise ToolError("too_large", f"more than {MAX_CHECK_CHARS:,} characters")
    lines = text.count("\n") + 1
    if kind == "json":
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            return _failure(kind, text, lines, exc.msg, exc.lineno, exc.colno)
        top = type(data).__name__
        size = len(data) if isinstance(data, (dict, list)) else None
        return {"ok": True, "kind": kind, "lines": lines, "top": top, "size": size}
    if kind not in RDF_KINDS:
        raise ToolError("bad_args", f"unknown kind {kind!r}")
    parser = RDF_KINDS[kind]
    g = Dataset() if kind in _DATASETS else Graph()
    try:
        g.parse(data=text, format=parser)
    except json.JSONDecodeError as exc:  # JSON-LD that is not JSON at all
        return _failure(kind, text, lines, exc.msg, exc.lineno, exc.colno)
    except Exception as exc:
        msg = str(exc)
        line = column = None
        if callable(getattr(exc, "getLineNumber", None)):  # RDF/XML (SAX)
            line, column = exc.getLineNumber(), exc.getColumnNumber()
            msg = msg.split(": ", 1)[-1].split(":", 2)[-1].strip() or msg
        elif isinstance(getattr(exc, "lines", None), int):  # Turtle, N3, TriG
            # BadSyntax counts from 0 and can run past the end at end of input
            line = exc.lines + 1
            m = _REASON.search(msg)
            msg = m.group(1) if m else msg.splitlines()[0]
        elif kind in _LINE_BASED:
            line = _first_bad_line(text, parser)
        return _failure(kind, text, lines, msg.splitlines()[0][:300] if msg else
                        type(exc).__name__, line, column)
    triples = sum(1 for _ in g.quads()) if kind in _DATASETS else len(g)
    subjects = {q[0] for q in (g.quads() if kind in _DATASETS else g)
                if not isinstance(q[0], BNode)}
    out = {"ok": True, "kind": kind, "lines": lines, "triples": triples,
           "subjects": len(subjects),
           "prefixes": sorted(p for p, _ in g.namespaces() if p and f"{p}:" in text)}
    if kind in _DATASETS:
        out["graphs"] = sum(1 for c in g.contexts() if len(c))
    return out


def _handler(fileops, text, kind):
    return check_syntax(str(text), kind)


CHECK_TOOLS: list[Tool] = [
    Tool(
        name="check.syntax",
        description=("Check that an RDF (Turtle, RDF/XML, N-Triples, N3, TriG, "
                     "N-Quads, JSON-LD) or JSON text is well formed; report the "
                     "first error with its line. Writes nothing."),
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "The file's contents."},
                "kind": {"type": "string", "enum": [*RDF_KINDS, "json"],
                         "description": "The serialisation: an RDF one, or plain json."},
            },
            "required": ["text", "kind"],
            "additionalProperties": False,
        },
        handler=_handler,
        redact=frozenset({"text"}),
    ),
]
