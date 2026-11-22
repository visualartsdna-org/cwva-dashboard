"""The workflow board — where each work is in its workflow, DERIVED from data.

"There are too many steps to remember" (TODO). The answer here is not a
checklist someone keeps: every step that leaves a trace in the store is
computed from that trace, the same way the standing queries compute obligations
(CE_DESIGN §7.1). A step that leaves NO trace — updating the external website
is the one in workflows A and B — is ticked by hand, and the tick is recorded
in the hygiene ledger with its date, so it is still data rather than memory.

Definitions are data (``config/workflows.rson``): a workflow names a members
query (which works are in it) and an ordered list of steps; a step names the
steps it depends on and a SPARQL file that lists every work for which the step
is DONE. Adding a workflow or a step is a config change, no code.

A cell is one of:

* ``done``    — the step's evidence query matched, it was ticked, or a later
                step that depends on it is done (``implied``: the evidence for
                "criticism generated" IS the criticism entity, so the entity
                existing completes it);
* ``started`` — the optional ``started_file`` matched (DTS part-way);
* ``ready``   — every dependency is done, nothing has happened yet;
* ``blocked`` — some dependency is not done.

Dates are whatever the data carries — a record's ``schema:dateCreated``, a DTS
stamp's ``ops:at``, a proof's ``vad:timestamp`` — and are absent where the data
has none (an annotation writes no date). Pace is the age of the row's most
recent known completion, which is what puts a stalled work at the top.

A step can also be dismissed for one work — "not needed": a watercolor that
will never be annotated, say. That is ``skipped``: recorded in the ledger with
its date, it satisfies whatever depends on it and lets the work finish, but it
is never evidence that the step was DONE, so it implies nothing about earlier
steps — and if the data later shows the step done, the data wins.

Pure: the caller supplies the graph, the ticks, the skips and the clock.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

__all__ = ["StepDef", "WorkflowDef", "BoardConfig", "load_workflows", "skip_kind",
           "evaluate_board", "tick_kind", "EMPTY_BOARD"]

DONE, STARTED, READY, BLOCKED, SKIPPED = "done", "started", "ready", "blocked", "skipped"
#: States that let a dependent step go ahead and count towards finishing.
SATISFIED = (DONE, SKIPPED)


def skip_kind(workflow: str, step: str) -> str:
    """The ledger kind a "not needed" dismissal is recorded under."""
    return f"board-skip:{workflow}:{step}"


def tick_kind(workflow: str, step: str) -> str:
    """The ledger kind a manual tick is recorded under."""
    return f"board:{workflow}:{step}"


@dataclass(frozen=True)
class StepDef:
    id: str
    label: str
    description: str = ""
    depends_on: tuple = ()
    query: str | None = None          # ?work [?at] [?record]: the step is DONE
    started_query: str | None = None  # ?work [?at] [?record] [?note]: under way
    manual: bool = False              # no trace in the data: ticked by hand
    action: str = ""                  # a dashboard link that does the step

    @classmethod
    def from_dict(cls, d: dict) -> "StepDef":
        return cls(
            id=d["id"], label=d.get("label", d["id"]),
            description=d.get("description", ""),
            depends_on=tuple(d.get("depends_on", ())),
            query=d.get("query"), started_query=d.get("started_query"),
            manual=bool(d.get("manual", False)), action=d.get("action", ""),
        )


@dataclass(frozen=True)
class WorkflowDef:
    id: str
    label: str
    members_query: str                # ?work ?label [?created]
    steps: tuple = ()
    description: str = ""

    def step(self, step_id: str) -> StepDef | None:
        return next((s for s in self.steps if s.id == step_id), None)


@dataclass(frozen=True)
class BoardConfig:
    workflows: tuple = ()
    #: Works created before this are not tracked. Most of the store predates
    #: the later steps (61 of 180 watercolors were ever annotated), so without
    #: a horizon every legacy work would sit "in flight" for ever and bury the
    #: ones actually moving.
    track_since: str = ""
    #: A work whose last movement is older than this is flagged as stalled.
    stall_days: int = 7

    def workflow(self, wf_id: str) -> WorkflowDef | None:
        return next((w for w in self.workflows if w.id == wf_id), None)


EMPTY_BOARD = BoardConfig()


def _read(base: str, rel: str | None) -> str | None:
    if not rel:
        return None
    with open(os.path.join(base, rel), "r", encoding="utf-8") as fh:
        return fh.read()


def load_workflows(path) -> BoardConfig:
    """Load ``workflows.rson``. SPARQL lives in ``.sparql`` files beside it
    (RSON strips ``#``), read HERE in the orchestrator so the confined worker
    never touches the config tree. Absent file -> an empty board."""
    from .. import rson

    if not os.path.exists(path):
        return EMPTY_BOARD
    raw = rson.load(path) or {}
    base = os.path.dirname(path)
    wfs = []
    for w in raw.get("workflows", []):
        steps = []
        for s in w.get("steps", []):
            d = dict(s)
            d["query"] = _read(base, d.pop("query_file", None)) or d.get("query")
            d["started_query"] = (_read(base, d.pop("started_file", None))
                                  or d.get("started_query"))
            steps.append(StepDef.from_dict(d))
        ids = {s.id for s in steps}
        for s in steps:
            missing = set(s.depends_on) - ids
            if missing:
                raise ValueError(f"workflow {w['id']} step {s.id} depends on "
                                 f"unknown step(s) {sorted(missing)}")
            if s.manual and s.query:
                raise ValueError(f"workflow {w['id']} step {s.id} is manual AND "
                                 "has an evidence query: pick one")
        wfs.append(WorkflowDef(
            id=w["id"], label=w.get("label", w["id"]),
            description=w.get("description", ""),
            members_query=_read(base, w.get("members_file")) or w.get("members_query", ""),
            steps=tuple(steps)))
    return BoardConfig(workflows=tuple(wfs), track_since=str(raw.get("track_since", "")),
                       stall_days=int(raw.get("stall_days", 7)))


# -- evaluation ---------------------------------------------------------------

def _when(value) -> datetime | None:
    """A literal's value as an aware datetime; a bare date is midnight UTC."""
    if value is None:
        return None
    v = getattr(value, "toPython", lambda: value)()
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _var(row, name):
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


def _hits(graph, query: str | None) -> dict[str, dict]:
    """work IRI -> {at: newest datetime, records: set, note}."""
    out: dict[str, dict] = {}
    if not query:
        return out
    for row in graph.query(query):
        work = _var(row, "work")
        if work is None:
            continue
        h = out.setdefault(str(work), {"at": None, "records": set(), "note": None})
        at = _when(_var(row, "at"))
        if at and (h["at"] is None or at > h["at"]):
            h["at"] = at
            note = _var(row, "note")
            if note is not None:
                h["note"] = str(note)
        elif h["note"] is None and _var(row, "note") is not None:
            h["note"] = str(_var(row, "note"))
        rec = _var(row, "record")
        if rec is not None:
            h["records"].add(str(rec))
    return out


def _closure(step: StepDef, wf: WorkflowDef) -> set[str]:
    """Every step ``step`` depends on, transitively."""
    seen: set[str] = set()
    todo = list(step.depends_on)
    while todo:
        sid = todo.pop()
        if sid in seen:
            continue
        seen.add(sid)
        dep = wf.step(sid)
        if dep:
            todo.extend(dep.depends_on)
    return seen


def _age_days(since: datetime | None, now: datetime) -> float | None:
    return None if since is None else round((now - since).total_seconds() / 86400, 1)


def evaluate_board(config: BoardConfig, graph, *, ticks=None, skips=None, now=None,
                   include_finished: bool = False, dispositions=None) -> dict:
    """The board as plain data.

    ``ticks``: ``{ledger kind: {work IRI: iso timestamp}}`` — the manual
    steps' record. ``dispositions``: ``{work IRI: DI}``, shown under the name.
    """
    now = now or datetime.now(timezone.utc)
    ticks = ticks or {}
    skips = skips or {}
    dispositions = dispositions or {}
    horizon = _when(config.track_since) if config.track_since else None
    out = []
    for wf in config.workflows:
        members: dict[str, dict] = {}
        for row in graph.query(wf.members_query):
            work = str(_var(row, "work"))
            created = _when(_var(row, "created"))
            if horizon and created and created < horizon:
                continue
            m = members.setdefault(work, {"label": None, "created": created})
            label = _var(row, "label")
            if label is not None and m["label"] is None:
                m["label"] = str(label)
        done_hits = {s.id: _hits(graph, s.query) for s in wf.steps}
        started_hits = {s.id: _hits(graph, s.started_query) for s in wf.steps}
        closures = {s.id: _closure(s, wf) for s in wf.steps}

        rows = []
        for work, m in members.items():
            cells: dict[str, dict] = {}
            for s in wf.steps:
                hit = done_hits[s.id].get(work)
                tick = ticks.get(tick_kind(wf.id, s.id), {}).get(work)
                if hit is not None:
                    cells[s.id] = {"state": DONE, "source": "data", "at": hit["at"],
                                   "records": sorted(hit["records"]), "note": hit["note"]}
                elif s.manual and tick:
                    cells[s.id] = {"state": DONE, "source": "manual", "at": _when(tick),
                                   "records": [], "note": None}
                elif work in skips.get(skip_kind(wf.id, s.id), {}):
                    cells[s.id] = {"state": SKIPPED, "source": "dismissed",
                                   "at": _when(skips[skip_kind(wf.id, s.id)][work]),
                                   "records": [], "note": None}
                else:
                    cells[s.id] = None
            # A done step completes everything it depends on: the criticism
            # entity existing IS the evidence the criticism was generated.
            for s in wf.steps:
                if cells[s.id] is not None and cells[s.id]["state"] == DONE:
                    for dep in closures[s.id]:
                        if cells[dep] is None:
                            cells[dep] = {"state": DONE, "source": "implied", "at": None,
                                          "records": [], "note": None}
            for s in wf.steps:
                if cells[s.id] is not None:
                    continue
                deps_done = all(cells[d] is not None and cells[d]["state"] in SATISFIED
                                for d in s.depends_on)
                st = started_hits[s.id].get(work)
                if st is not None:
                    cells[s.id] = {"state": STARTED, "source": "data", "at": st["at"],
                                   "records": sorted(st["records"]), "note": st["note"]}
                elif deps_done:
                    dep_ats = [cells[d]["at"] for d in s.depends_on if cells[d]["at"]]
                    cells[s.id] = {"state": READY, "source": None,
                                   "at": max(dep_ats) if dep_ats else None,
                                   "records": [], "note": None}
                else:
                    waiting = [d for d in s.depends_on
                               if cells[d] is None or cells[d]["state"] not in SATISFIED]
                    cells[s.id] = {"state": BLOCKED, "source": None, "at": None,
                                   "records": [], "note": None, "waiting_on": waiting}

            done = [s for s in wf.steps if cells[s.id]["state"] == DONE]
            finished = all(cells[s.id]["state"] in SATISFIED for s in wf.steps)
            if finished and not include_finished:
                continue
            dated = [s for s in done if cells[s.id]["at"]]
            last = (max(dated, key=lambda s: cells[s.id]["at"]) if dated
                    else (done[-1] if done else None))
            dates = [cells[s.id]["at"] for s in dated]
            since = max(dates) if dates else m["created"]
            nxt = [s.id for s in wf.steps if cells[s.id]["state"] in (STARTED, READY)]
            rows.append({
                "work": work,
                "label": m["label"] or work.rsplit("/", 1)[-1],
                "created": _iso(m["created"]),
                "disposition": dispositions.get(work),
                "finished": finished,
                "done_count": len(done),
                "last": last.id if last else None,
                "next": nxt,
                "since": _iso(since),
                "age_days": _age_days(since, now),
                "stalled": (not finished and since is not None
                            and (now - since).total_seconds() > config.stall_days * 86400),
                "cells": {sid: {**c, "at": _iso(c["at"]),
                                "age_days": (_age_days(c["at"], now)
                                             if c["state"] in (STARTED, READY) else None)}
                          for sid, c in cells.items()},
            })
        # Stalled first: the oldest last-movement leads.
        rows.sort(key=lambda r: (r["finished"], -(r["age_days"] or 0), r["label"]))
        out.append({
            "id": wf.id, "label": wf.label, "description": wf.description,
            "steps": [{"id": s.id, "label": s.label, "description": s.description,
                       "depends_on": list(s.depends_on), "manual": s.manual,
                       "action": s.action} for s in wf.steps],
            "rows": rows,
        })
    return {"workflows": out, "track_since": config.track_since,
            "stall_days": config.stall_days,
            "now": _iso(now), "include_finished": include_finished}
