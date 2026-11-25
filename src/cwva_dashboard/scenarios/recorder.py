"""Record a human session as a replayable scenario.

Phase 5 measures agent competency by **replaying recorded human sessions
through the agent driver, never by a model's self-report** — and the
recordings did not exist. Eight acceptance runs were lost, and so was the
2.5-hour production run that took one watercolour from the drop folder to two
curated criticisms.

Rick, 2026-10-07, on why he waited: he wanted the code to be at a point where a
recording captures behaviour he intends to KEEP. That is the right criterion
and sharper than "a clean run" — an appropriate refusal (a gate catching a
dangling reference, a stage refused out of order) is durable and worth having,
while a recording made over a bug encodes the bug and the workaround around it.

**What a recording is.** The same `Scenario` the four committed smoke episodes
use: a list of `{op, args}` the `StepExecutor` can run, plus the end state
`assert_end_state` checks. Driver-agnostic by construction — a human made these
steps and an agent can be asked to produce them.

**Where the steps come from.** Two places, because the dashboard does two kinds
of thing:

- every registry tool, captured in `Dashboard.dispatch` — the one wrapper the
  whole UX goes through, in the trusted parent, with the arguments unredacted;
- the trusted-orchestrator acts the executor also knows — `workflow.promote`,
  `sot.sync`, `sot.adopt` — recorded at the routes that perform them, because
  those are law 1 machinery and deliberately not tools (law 10).

**Not the audit log.** It looked like the obvious source and it is not: the
audit records argument NAMES and elides their values (`"definition":
"<315 chars>"`), which is correct for an audit and useless for a replay. The
two answer different questions — what happened, and what to re-run.

**Reads are dropped.** Production logged 1622 tool calls in a day, 23 of them
authoring; the rest was the panel polling `workflow.state`. A replay does not
need them: the state a read observes is produced by the writes around it, so
keeping them would bury the episode and make the diff unreadable.

**A recording is not a fixture.** It is written into the sandbox under
`.qa/scenarios/`, which is gitignored and never converges — the dashboard
cannot write to the project tree (law 1), and whether a session becomes a
committed test is a decision a person makes afterwards by copying it into
`tests/scenarios/`. It also means a recording may hold whatever the session
held, including personal detail, until someone chooses otherwise.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Recorder", "is_read_only", "read_only_names", "SCENARIO_DIR"]

#: Where a recording lands. Under `.qa/`, so it is gitignored, never converges,
#: and is not mistaken for a committed fixture.
SCENARIO_DIR = ".qa/scenarios"

#: A read is identified by its VERB, derived from the name rather than listed,
#: so a new `record.list_something` is classified without anybody remembering.
_READ_PREFIXES = ("list_", "read_", "check_", "current_")

#: The reads whose names carry no verb. Listed because they cannot be derived —
#: and a test asserts every registry tool is classified, so this staying
#: current is not a matter of discipline.
_READ_EXACT = frozenset({
    "fs.list", "fs.read",
    "rdf.sparql", "rdf.validate", "rdf.diff",
    "workflow.state",
    "record.resolve_tags",
})


def is_read_only(op: str) -> bool:
    """Does this op only observe? Reads are dropped from a recording."""
    if op in _READ_EXACT:
        return True
    local = str(op).rsplit(".", 1)[-1]
    return local.startswith(_READ_PREFIXES)


def read_only_names(names) -> set:
    """The subset of ``names`` a recording drops — for the test that asserts
    the classification covers the registry."""
    return {n for n in names if is_read_only(n)}


@dataclass
class Recorder:
    """One session, accumulating steps until it is stopped.

    Thread-safe because the dashboard serializes dispatch on a lock but the
    routes do not, and a recording that lost a step under concurrency would be
    a replay that fails for a reason nobody can find.

    **Saved as it goes** (2026-11-24). With a ``journal``, every step is
    appended to it and flushed to disk the moment it is recorded, and
    :meth:`resume` rebuilds the recording from it. A recording held only in
    memory was erased by the production restart at 09:25 that morning, a whole
    session — a watercolour's entry, an annotation and its correction, two
    criticisms through DTS — gone with nothing to show for it. Now a restart,
    planned or not, costs nothing: the dashboard picks the recording up again
    when it starts, and the restart itself is noted in the recording.
    """

    name: str
    description: str = ""
    started_at: float = field(default_factory=time.time)
    steps: list = field(default_factory=list)
    dropped: int = 0
    journal: Path | None = None
    resumed: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        if self.journal is not None and not Path(self.journal).exists():
            self._append({"type": "start", "name": self.name,
                          "description": self.description,
                          "started_at": self.started_at})

    def _append(self, entry: dict) -> None:
        """One line, flushed and fsynced: a step is on disk before the request
        that made it returns."""
        if self.journal is None:
            return
        path = Path(self.journal)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def step(self, op: str, args: dict | None = None) -> None:
        """Record one act. Reads are counted and discarded."""
        if is_read_only(op):
            with self._lock:
                self.dropped += 1
            return
        with self._lock:
            entry = {"op": str(op), "args": _plain(args or {})}
            self.steps.append(entry)
            # the reads dropped so far ride along, so a resumed recording's
            # count is right to the last step without writing on every poll
            self._append({"type": "step", **entry, "dropped": self.dropped})

    @classmethod
    def resume(cls, journal) -> "Recorder | None":
        """The recording a journal holds, or None if there is none. A line cut
        short by the crash that made a resume necessary is skipped, not fatal."""
        path = Path(journal)
        if not path.is_file():
            return None
        rec = None
        steps, dropped, resumed = [], 0, []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            kind = entry.get("type")
            if kind == "start":
                rec = cls(name=entry.get("name") or "session",
                          description=entry.get("description") or "",
                          started_at=float(entry.get("started_at") or time.time()),
                          journal=None)
            elif kind == "step":
                steps.append({"op": entry.get("op"), "args": entry.get("args") or {}})
                dropped = int(entry.get("dropped") or dropped)
            elif kind == "resumed":
                resumed.append(entry.get("at"))
        if rec is None:
            return None
        rec.steps, rec.dropped, rec.resumed = steps, dropped, resumed
        rec.journal = path
        at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        rec.resumed.append(at)
        rec._append({"type": "resumed", "at": at, "steps": len(steps)})
        return rec

    def discard_journal(self) -> None:
        """After the scenario is written: the journal has done its job."""
        if self.journal is not None:
            Path(self.journal).unlink(missing_ok=True)

    # -- finishing ---------------------------------------------------------
    def to_scenario(self, expected: dict | None = None) -> dict:
        """The scenario document, in the shape the committed episodes use."""
        with self._lock:
            steps = [dict(s) for s in self.steps]
        return {
            "name": self.name,
            "description": self.description or (
                f"Recorded session, {len(steps)} step(s)."),
            "recorded": {
                "at": time.strftime("%Y-%m-%dT%H:%M:%S",
                                    time.gmtime(self.started_at)),
                "seconds": round(time.time() - self.started_at, 1),
                "reads_dropped": self.dropped,
                # each time the dashboard restarted mid-session and picked the
                # recording back up; empty for an uninterrupted one
                "resumed": list(self.resumed),
            },
            "steps": steps,
            "expected": expected or {},
        }

    def summary(self) -> dict:
        with self._lock:
            ops = [s["op"] for s in self.steps]
        return {
            "name": self.name, "recording": True,
            "steps": len(ops), "reads_dropped": self.dropped,
            "seconds": round(time.time() - self.started_at, 1),
            "ops": ops,
            "saved_as_it_goes": self.journal is not None,
            "resumed": list(self.resumed),
        }


def _plain(value):
    """JSON-safe arguments, verbatim.

    A recording keeps what the audit log redacts — the whole point is to be
    able to run it again — so nothing is summarised here. Only types that
    cannot be written are converted.
    """
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def safe_name(raw: str) -> str:
    """A filename for a session the user named. Not `normalize_filename`: this
    is not content entering the system, it is an operator artifact, and a
    scenario name is conventionally lower_snake."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", str(raw).strip()).strip("_")
    return (cleaned or f"session-{int(time.time())}").lower()[:60]
