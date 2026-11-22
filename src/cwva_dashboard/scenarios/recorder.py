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
import re
import threading
import time
from dataclasses import dataclass, field

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
    """

    name: str
    description: str = ""
    started_at: float = field(default_factory=time.time)
    steps: list = field(default_factory=list)
    dropped: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def step(self, op: str, args: dict | None = None) -> None:
        """Record one act. Reads are counted and discarded."""
        if is_read_only(op):
            with self._lock:
                self.dropped += 1
            return
        with self._lock:
            self.steps.append({"op": str(op), "args": _plain(args or {})})

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
