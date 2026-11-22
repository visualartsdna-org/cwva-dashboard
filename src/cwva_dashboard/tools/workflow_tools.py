"""Workflow-state tools — the panel and the agent's narration, one engine.

``workflow.state`` computes the standing-query results (CE_DESIGN §7.1) against
the QA content in the sandbox and returns the three panel groups + a narration
string. ``workflow.dismiss`` records a dismissal in the hygiene ledger so an
open item stops being reported. Both run in the confined worker: the sources
here are sandbox-derivable (fs counts + SPARQL over content); git/audit sources
join when the orchestrator-tool context lands.

The definitions are supplied at build time (loaded as data in the orchestrator),
so the confined worker never needs to read the project config tree.
"""

from __future__ import annotations

import time

from rdflib import Graph, URIRef

from ..concepts.ledger import LEDGER_PATH, HygieneLedger
from ..promotion.layout import Layout, MIRROR_LAYOUT
from ..workflow_state.board import EMPTY_BOARD, evaluate_board, skip_kind, tick_kind
from ..workflow_state.engine import evaluate
from .base import Tool, ToolError

__all__ = ["build_workflow_tools"]

# Standing-query SPARQL runs over the QA content mirror (§3.6), where records land.
_CONTENT_DIR = MIRROR_LAYOUT["work_ttl"]


# Parsed records, cached per FILE so a poll costs what CHANGED, not what exists.
#
# The panel answers standing queries over the whole record set, so a poll used
# to read every record: 329 fileops calls at 328 records. At the hub's polling
# interval that is more than the entire per-minute quota spent on an *idle*
# dashboard, and it surfaced as `quota_exceeded` on an unrelated Create record
# which merely happened to be operation 601.
#
# The quota is a runaway-agent control, so the fix is to stop normal operation
# costing that much rather than to raise the ceiling. Two levels:
#
#   * one `list_dir` (1 op) yields name/size/mtime for every record;
#   * a record whose (size, mtime_ns) is unchanged is served from its cached
#     parse, so only genuinely changed files are re-read.
#
# An idle poll is therefore 1 op, and a poll after one entry is 2 — proportional
# to the edit rather than the corpus, which is what keeps a burst of entries
# from tripping the quota the way a whole-tree rescan per change would.
# mtime is in the key because a same-length edit (a flag flipping false->true)
# would slip past size alone.
#
# Phase 7's QA store replaces this properly; until then the panel must not
# re-parse 8000 triples on every poll.
# Key: (sandbox root, sandbox-relative path). Value: (size, mtime_ns,
# cached_at_ns, graph).
#
# The root is IN THE KEY because a sandbox-relative path is not unique across
# sandboxes: two FileOps over different roots both call the same records
# "content/ttl/data/x.ttl", and one would be served the other's parse. A single
# running dashboard has one sandbox so this never bit in production, but the
# test suite and the scenario harness both open several — which is how it
# surfaced, as one test seeing another's records.
_FILE_CACHE: dict[tuple[str, str], tuple[int, int, int, Graph]] = {}

# Filesystem timestamps are not infinitely fine-grained, so a write landing in
# the same tick as the cache entry leaves (size, mtime_ns) unchanged and the
# cache would serve stale content forever. Git has the same problem and calls
# such an entry "racily clean": anything whose mtime is not strictly older than
# the moment we cached it is re-read rather than trusted. The window costs a
# re-read of files touched in the last few milliseconds and nothing else.
#
# Found by a test that failed intermittently -- the same-length-edit case,
# which is exactly the scenario the key was widened to cover.
_RACY_WINDOW_NS = 10_000_000  # 10 ms


def _content_graph(fileops, content_dir: str) -> Graph:
    try:
        entries = fileops.list_dir(content_dir)
    except (FileNotFoundError, NotADirectoryError):
        return Graph()

    root = str(getattr(getattr(fileops, "_sb", None), "root", ""))
    g = Graph()
    live: set[tuple[str, str]] = set()
    for e in entries:
        if not (e.is_file and e.name.endswith(".ttl")):
            continue
        path = f"{content_dir}/{e.name}"
        ckey = (root, path)
        live.add(ckey)
        hit = _FILE_CACHE.get(ckey)
        fresh = (
            hit is not None
            and hit[0] == e.size
            and hit[1] == e.mtime_ns
            and e.mtime_ns < hit[2] - _RACY_WINDOW_NS  # not racily clean
        )
        if not fresh:
            fg = Graph()
            fg.parse(data=fileops.read_text(path), format="turtle")
            hit = (e.size, e.mtime_ns, time.time_ns(), fg)
            _FILE_CACHE[ckey] = hit
        for triple in hit[3]:
            g.add(triple)

    _evict_stale(root, content_dir, live)
    return g


def _evict_stale(root: str, content_dir: str, live: set) -> None:
    stale = [
        k
        for k in _FILE_CACHE
        if k[0] == root and k[1].startswith(content_dir + "/") and k not in live
    ]
    for gone in stale:
        del _FILE_CACHE[gone]  # deleted records must not linger in the cache


def file_graphs(fileops, content_dir: str) -> list[tuple[str, Graph]]:
    """``(path, graph)`` per .ttl file, from the SAME cache `_content_graph`
    uses.

    Some questions are per-FILE and a merged graph cannot answer them — "how
    many subjects does this file describe", which is what decides whether a
    record is editable. Without this, the caller re-read all 334 files itself
    and blew the ops quota; that has now happened four times in this project,
    each time because a new reader did its own loop instead of asking the cache.
    """
    try:
        entries = fileops.list_dir(content_dir)
    except (FileNotFoundError, NotADirectoryError):
        return []

    root = str(getattr(getattr(fileops, "_sb", None), "root", ""))
    out: list[tuple[str, Graph]] = []
    live: set[tuple[str, str]] = set()
    for e in entries:
        if not (e.is_file and e.name.endswith(".ttl")):
            continue
        path = f"{content_dir}/{e.name}"
        ckey = (root, path)
        live.add(ckey)
        hit = _FILE_CACHE.get(ckey)
        fresh = (
            hit is not None
            and hit[0] == e.size
            and hit[1] == e.mtime_ns
            and e.mtime_ns < hit[2] - _RACY_WINDOW_NS
        )
        if not fresh:
            fg = Graph()
            try:
                fg.parse(data=fileops.read_text(path), format="turtle")
            except Exception:
                continue
            hit = (e.size, e.mtime_ns, time.time_ns(), fg)
            _FILE_CACHE[ckey] = hit
        out.append((path, hit[3]))
    _evict_stale(root, content_dir, live)
    return out


def _count_fn(fileops):
    def count(directory: str, extensions) -> int:
        try:
            entries = fileops.list_dir(directory)
        except (FileNotFoundError, NotADirectoryError):
            return 0
        exts = tuple(e.lower() for e in extensions) if extensions else None
        return sum(
            1 for e in entries if e.is_file and (exts is None or e.name.lower().endswith(exts))
        )

    return count


def _load_ledger(fileops, ledger_path: str) -> HygieneLedger:
    try:
        text = fileops.read_text(ledger_path)
    except (FileNotFoundError, NotADirectoryError):
        text = ""
    return HygieneLedger.from_ttl(text)


_DI = "http://visualartsdna.org/model/dispositionId"
_HAS_ARTWORK = "http://visualartsdna.org/model/hasArtwork"


def _dispositions(graph) -> dict[str, str]:
    """work IRI -> its disposition identifier, from the provenance records."""
    out = {}
    for rec, art in graph.subject_objects(URIRef(_HAS_ARTWORK)):
        di = graph.value(rec, URIRef(_DI))
        if di is not None:
            out[str(art)] = str(di)
    return out


def build_board_tools(board=None, *, layout=None) -> list[Tool]:
    """The workflow board (``workflow_state/board.py``): ``workflow.board``
    computes it, ``workflow.mark_step`` ticks or unticks a MANUAL step.

    Only a step the definitions declare manual can be ticked. A step with
    evidence in the data is done when the data says so, and letting a tick
    override that would put the board back to being a checklist someone keeps.
    """
    board = board or EMPTY_BOARD
    lay = layout or Layout.default()
    dirs = list(dict.fromkeys(lay.dir(k) for k in ("work_ttl", "entity_ttl")))
    prov_dir = lay.dir("provenance_ttl")

    def _ticks(ledger) -> dict:
        return {tick_kind(w.id, s.id): ledger.dismissals_at(tick_kind(w.id, s.id))
                for w in board.workflows for s in w.steps if s.manual}

    def _skips(ledger) -> dict:
        return {skip_kind(w.id, s.id): ledger.dismissals_at(skip_kind(w.id, s.id))
                for w in board.workflows for s in w.steps}

    def _board(fileops, include_finished=False):
        g = Graph()
        for d in dirs:
            g += _content_graph(fileops, d)
        prov = _content_graph(fileops, prov_dir) if prov_dir not in dirs else g
        ledger = _load_ledger(fileops, LEDGER_PATH)
        return evaluate_board(board, g, ticks=_ticks(ledger), skips=_skips(ledger),
                              include_finished=bool(include_finished),
                              dispositions=_dispositions(prov))

    def _mark(fileops, workflow, step, work, done=True):
        wf = board.workflow(workflow)
        st = wf.step(step) if wf else None
        if st is None:
            raise ToolError("bad_args", f"no step {step!r} in workflow {workflow!r}")
        if not st.manual:
            raise ToolError("not_manual",
                            f"{st.label} is done when the data says so; it cannot be ticked")
        if not str(work).startswith(("http://", "https://")):
            raise ToolError("bad_args", "work must be the work's IRI")
        ledger = _load_ledger(fileops, LEDGER_PATH)
        kind = tick_kind(workflow, step)
        if done:
            ledger.dismiss(kind, str(work), f"{wf.label}: {st.label} done")
        else:
            ledger.undismiss(kind, str(work))
        fileops.write_text(LEDGER_PATH, ledger.to_ttl(), make_parents=True)
        return {"workflow": workflow, "step": step, "work": work, "done": bool(done)}

    def _skip(fileops, workflow, step, work, skip=True, reason=""):
        wf = board.workflow(workflow)
        st = wf.step(step) if wf else None
        if st is None:
            raise ToolError("bad_args", f"no step {step!r} in workflow {workflow!r}")
        if not str(work).startswith(("http://", "https://")):
            raise ToolError("bad_args", "work must be the work's IRI")
        ledger = _load_ledger(fileops, LEDGER_PATH)
        kind = skip_kind(workflow, step)
        if skip:
            ledger.dismiss(kind, str(work), reason or f"{wf.label}: {st.label} not needed")
        else:
            ledger.undismiss(kind, str(work))
        fileops.write_text(LEDGER_PATH, ledger.to_ttl(), make_parents=True)
        return {"workflow": workflow, "step": step, "work": work, "skipped": bool(skip)}

    return [
        Tool(
            name="workflow.skip_step",
            description=("Dismiss a workflow step for one work as not needed (or "
                         "restore it). It stops holding the work in flight; it never "
                         "counts as the step being done. Recorded in the ledger."),
            input_schema={
                "type": "object",
                "properties": {
                    "workflow": {"type": "string", "description": "Workflow id, e.g. A."},
                    "step": {"type": "string", "description": "Step id, e.g. annotate."},
                    "work": {"type": "string", "description": "The work's IRI."},
                    "skip": {"type": "boolean", "default": True,
                             "description": "False restores the step."},
                    "reason": {"type": "string", "default": "",
                               "description": "Why it is not needed."},
                },
                "required": ["workflow", "step", "work"],
                "additionalProperties": False,
            },
            handler=_skip,
            redact=frozenset({"reason"}),
        ),
        Tool(
            name="workflow.board",
            description=("The workflow board: for each work in each workflow, which "
                         "steps are done (with dates), under way, ready or blocked, "
                         "derived from the records."),
            input_schema={
                "type": "object",
                "properties": {
                    "include_finished": {"type": "boolean", "default": False,
                                         "description": "Include works with every step done."},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=_board,
        ),
        Tool(
            name="workflow.mark_step",
            description=("Tick (or untick) a MANUAL workflow step for a work: one "
                         "that leaves no trace in the data, such as updating the "
                         "external website. Recorded, with its date, in the ledger."),
            input_schema={
                "type": "object",
                "properties": {
                    "workflow": {"type": "string", "description": "Workflow id, e.g. A."},
                    "step": {"type": "string", "description": "Step id, e.g. website."},
                    "work": {"type": "string", "description": "The work's IRI."},
                    "done": {"type": "boolean", "default": True,
                             "description": "False removes the tick."},
                },
                "required": ["workflow", "step", "work"],
                "additionalProperties": False,
            },
            handler=_mark,
        ),
    ]


def build_workflow_tools(definitions, *, layout=None) -> list[Tool]:
    """Build the workflow-state tools carrying ``definitions`` (loaded as data
    in the orchestrator and inherited by the worker via fork).

    ``layout`` is the active target's placement map (B1): the standing queries
    must count content where the QA tree actually keeps it."""
    content_dir = (layout or Layout.default()).dir("work_ttl")

    def _state(fileops, content_dir=content_dir, ledger_path=LEDGER_PATH):
        graph = _content_graph(fileops, content_dir)
        ledger = _load_ledger(fileops, ledger_path)
        ws = evaluate(definitions, graph=graph, count_fn=_count_fn(fileops), ledger=ledger)
        return ws.to_dict()

    def _dismiss(fileops, definition_id, item_key, reason="", ledger_path=LEDGER_PATH):
        ledger = _load_ledger(fileops, ledger_path)
        ledger.dismiss(definition_id, item_key, reason)
        fileops.write_text(ledger_path, ledger.to_ttl(), make_parents=True)
        return {"dismissed": item_key, "definition": definition_id}

    return [
        Tool(
            name="workflow.state",
            description="Compute workflow state: pipeline queues + open obligations − dismissals + narration (CE_DESIGN §7.1).",
            input_schema={
                "type": "object",
                "properties": {
                    "content_dir": {
                        "type": "string",
                        "description": "Sandbox-relative QA content dir for SPARQL.",
                        "default": content_dir,
                    },
                    "ledger_path": {
                        "type": "string",
                        "description": "Sandbox-relative hygiene ledger.",
                        "default": LEDGER_PATH,
                    },
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=_state,
        ),
        Tool(
            name="workflow.dismiss",
            description="Dismiss an open item so it stops being reported (records in the hygiene ledger).",
            input_schema={
                "type": "object",
                "properties": {
                    "definition_id": {"type": "string", "description": "Standing-query id."},
                    "item_key": {"type": "string", "description": "The open item's key (its URI)."},
                    "reason": {"type": "string", "description": "Why it is dismissed.", "default": ""},
                    "ledger_path": {
                        "type": "string",
                        "description": "Sandbox-relative hygiene ledger.",
                        "default": LEDGER_PATH,
                    },
                },
                "required": ["definition_id", "item_key"],
                "additionalProperties": False,
            },
            handler=_dismiss,
            redact=frozenset({"reason"}),
        ),
    ]
