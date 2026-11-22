"""RDF utility tools (Phase 4.5 port of inventory #17 / #30 / #31).

These surface capabilities the legacy UX exposed as cards, now as registry
tools the agent shares:

- ``rdf.sparql``  — read-only SPARQL over sandbox RDF (#17; UPDATE is
  impossible because only ``Graph.query`` is used, never ``update``).
- ``rdf.validate`` — parse + SHACL conformance (#31; the same ``gates`` code
  that runs automatically in promotion, exposed for interactive use).
- ``rdf.diff``    — isomorphic graph diff of two files (#30; never a text diff
  of serialized RDF — CLAUDE.md law).

All files are read through ``FileOps`` (the confinement chokepoint); until the
QA store lands (Phase 7) the caller names the files to load.
"""

from __future__ import annotations

import concurrent.futures
import re
import time

from rdflib import BNode, Graph, Namespace, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS, XSD

from rdflib.compare import graph_diff
from rdflib.plugins.sparql.parser import parseQuery, parseUpdate

from ..promotion.gates import rdf_format, shacl_gate
from ..promotion.layout import Layout
from ..sandbox.quotas import QuotaExceeded
from .base import Tool, ToolError
from .record_tools import SCHEMA, THE, VAD, work_namespace
from .workflow_tools import _content_graph

__all__ = ["RDF_TOOLS", "build_store_query_tool"]


def _load(fileops, paths: list[str]) -> Graph:
    g = Graph()
    for p in paths:
        g.parse(data=fileops.read_text(p), format=rdf_format(p) or "turtle")
    return g


def _sparql(fileops, query, paths):
    result = _load(fileops, paths).query(query)  # query() only — read-only
    kind = str(result.type)
    if kind == "ASK":
        return {"type": "ask", "boolean": bool(result.askAnswer)}
    if kind in ("CONSTRUCT", "DESCRIBE"):
        return {
            "type": "graph",
            "triples": len(result.graph),
            "ttl": result.graph.serialize(format="turtle"),
        }
    vars_ = [str(v) for v in result.vars]
    rows = [
        {str(v): (str(row[v]) if row[v] is not None else None) for v in result.vars}
        for row in result
    ]
    return {"type": "select", "vars": vars_, "rows": rows}


def _validate(fileops, data_paths, shapes_paths):
    data = Graph()
    parse_errors = []
    for p in data_paths:
        try:
            data.parse(data=fileops.read_text(p), format=rdf_format(p) or "turtle")
        except Exception as exc:
            parse_errors.append(f"{p}: {type(exc).__name__}: {exc}")
    if parse_errors:
        return {"ok": False, "stage": "parse", "messages": parse_errors}
    gr = shacl_gate(data, _load(fileops, shapes_paths))
    return {"ok": gr.ok, "stage": "shacl", "summary": gr.summary, "messages": gr.messages}


def _diff(fileops, path_a, path_b):
    a = _load(fileops, [path_a])
    b = _load(fileops, [path_b])
    both, only_a, only_b = graph_diff(a, b)
    return {
        "same": len(both),
        "only_in_a": len(only_a),
        "only_in_b": len(only_b),
        "removed_ttl": only_a.serialize(format="turtle") if len(only_a) else "",
        "added_ttl": only_b.serialize(format="turtle") if len(only_b) else "",
    }


# -- the store browser (inventory #17) -------------------------------------
#
# Copied from cwvaServer-py's `services/sparql_browser.py`, with what a
# single-user localhost dashboard does not need left out: the per-IP rate limit
# and the cached query set. The guards stay: a read-only `query()`, a timeout,
# a row cap, and a refusal that names UPDATE rather than failing to parse it.

_TIMEOUT_S = 10
_ROW_CAP = 10_000


def _is_update(query: str) -> bool:
    """Is this an UPDATE? Decided by the grammar, not by spotting a keyword, which
    the cwvaServer-py copy did and which also catches `"delete where"` in a string.
    `query()` cannot run an update anyway; this is so the answer says why."""
    try:
        parseQuery(query)
        return False
    except Exception:
        pass
    try:
        parseUpdate(query)
        return True
    except Exception:
        return False

#: The prefixes a query may use without declaring, cwvaServer-py's FOR_QUERY.
def _query_prefixes(work_ns: Namespace) -> dict:
    return {
        "dct": Namespace("http://purl.org/dc/terms/"),
        "foaf": Namespace("http://xmlns.com/foaf/0.1/"),
        "ops": Namespace("http://visualartsdna.org/operations/"),
        "owl": OWL, "prov": Namespace("http://www.w3.org/ns/prov#"), "rdf": RDF,
        "rdfs": RDFS, "schema": SCHEMA, "skos": SKOS, "the": THE,
        "tko": Namespace("http://visualartsdna.org/takeout/"), "vad": VAD,
        "work": work_ns, "xs": XSD, "xsd": XSD,
    }


def _with_limit(query: str) -> str:
    """Cap a SELECT that has no LIMIT of its own."""
    body = re.sub(r"(?im)^\s*(PREFIX|BASE)\b[^\n]*\n", "", query)
    if re.match(r"\s*SELECT\b", body, re.I) and not re.search(r"\bLIMIT\b", body, re.I):
        return query.rstrip() + f"\nLIMIT {_ROW_CAP}"
    return query


def _cell(term) -> dict | None:
    if term is None:
        return None
    kind = "uri" if isinstance(term, URIRef) else "bnode" if isinstance(term, BNode) else "literal"
    return {"t": kind, "v": str(term)}


def build_store_query_tool(domain: str, *, layout=None) -> Tool:
    lay = layout or Layout.default()
    # Every RDF folder the placement map names, once each: records and
    # provenance, the model, the vocabulary and the tags.
    dirs = list(dict.fromkeys(lay.dir(k) for k in (
        "work_ttl", "provenance_ttl", "model_ttl", "vocab_ttl", "tags_ttl")))
    prefixes = _query_prefixes(work_namespace(domain))

    def _handler(fileops, query):
        query = str(query).strip()
        if not query:
            raise ToolError("bad_args", "the query is empty")
        if _is_update(query):
            raise ToolError("update_refused", "SPARQL UPDATE is disabled: this is read-only")
        started = time.monotonic()
        g = Graph()
        try:
            for d in dirs:
                g += _content_graph(fileops, d)
        except QuotaExceeded:
            # The store is read a file at a time and cached, so this is the cold
            # first load outrunning the per-minute file quota, not a failure.
            raise ToolError(
                "still_loading",
                "The sandbox is still being read in: more files than the per-minute "
                "file quota allows on a cold start. What was read stays cached, so "
                "run the query again in a minute.") from None
        loaded_ms = int((time.monotonic() - started) * 1000)

        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(g.query, _with_limit(query), initNs=prefixes)
        try:
            result = future.result(timeout=_TIMEOUT_S)
            kind = str(result.type)
            if kind == "SELECT":
                out = {"type": "select", "vars": [str(v) for v in result.vars],
                       "rows": [[_cell(row[v]) for v in result.vars] for row in result]}
            elif kind == "ASK":
                out = {"type": "ask", "boolean": bool(result.askAnswer)}
            else:
                rg = Graph()
                for p, ns in prefixes.items():
                    rg.bind(p, ns)
                for triple in result:
                    rg.add(triple)
                out = {"type": "graph", "triples": len(rg), "ttl": rg.serialize(format="turtle")}
        except concurrent.futures.TimeoutError:
            raise ToolError("timeout", f"the query ran past {_TIMEOUT_S} seconds") from None
        except ToolError:
            raise
        except Exception as exc:  # a SPARQL syntax error, mostly
            raise ToolError("query_error", str(exc)) from None
        finally:
            pool.shutdown(wait=False)
        return {**out, "triples_loaded": len(g), "dirs": dirs, "load_ms": loaded_ms,
                "query_ms": int((time.monotonic() - started) * 1000) - loaded_ms,
                "row_cap": _ROW_CAP}

    return Tool(
        name="rdf.sparql_store",
        description=("Run a read-only SPARQL query over the whole sandbox: records, "
                     "provenance, model, vocabulary and tags, drafts included."),
        input_schema={
            "type": "object",
            "properties": {"query": _str("The SPARQL query text (read-only).")},
            "required": ["query"],
            "additionalProperties": False,
        },
        handler=_handler,
        redact=frozenset({"query"}),
    )


def _str(desc, **extra):
    return {"type": "string", "description": desc, **extra}


def _str_array(desc):
    return {"type": "array", "description": desc, "items": {"type": "string"}}


RDF_TOOLS: list[Tool] = [
    Tool(
        name="rdf.sparql",
        description="Run a read-only SPARQL query (SELECT/ASK/CONSTRUCT) over the named RDF files.",
        input_schema={
            "type": "object",
            "properties": {
                "query": _str("The SPARQL query text (read-only)."),
                "paths": _str_array("Sandbox-relative RDF files to load into the graph."),
            },
            "required": ["query", "paths"],
            "additionalProperties": False,
        },
        handler=_sparql,
        redact=frozenset({"query"}),
    ),
    Tool(
        name="rdf.validate",
        description="Parse the data files and check SHACL conformance against the shape files.",
        input_schema={
            "type": "object",
            "properties": {
                "data_paths": _str_array("Sandbox-relative RDF data files."),
                "shapes_paths": _str_array("Sandbox-relative SHACL shape files."),
            },
            "required": ["data_paths", "shapes_paths"],
            "additionalProperties": False,
        },
        handler=_validate,
    ),
    Tool(
        name="rdf.diff",
        description="Isomorphic graph diff of two RDF files (bnode/reorder-safe).",
        input_schema={
            "type": "object",
            "properties": {
                "path_a": _str("First RDF file (the 'before')."),
                "path_b": _str("Second RDF file (the 'after')."),
            },
            "required": ["path_a", "path_b"],
            "additionalProperties": False,
        },
        handler=_diff,
    ),
]
