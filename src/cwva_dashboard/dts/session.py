"""The DTS session: what a run of DTS is, and what it names.

**One vocabulary file per SESSION, not per entity** (Rick, 2026-09-30): the
per-entity naming reads better than the `concepts<date>.ttl` it replaced, and
it still inflates the vocab folder by one file per document forever. A session
is what a person means by "a run of DTS" — the documents they sat down to
process — and it is the right granule for the file because it is the granule
they would look for later.

`evidence/` stays PER ENTITY. The two directories answer different questions:
the vocabulary is read as a body of terms, where one file per run keeps it
legible, while the evidence is read as "what happened to this document", which
is a path rather than a search.

A session is a name and a timestamp, held in `.qa/` — gitignored, because a
session is machinery rather than a record, and the record of what a session
did is the evidence and the git history.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

__all__ = ["Session", "current", "start", "SESSION_FILE"]

SESSION_FILE = ".qa/dts/session.json"


@dataclass(frozen=True)
class Session:
    """A run of DTS, with a name a person can recognise later."""

    id: str
    started: str
    label: str = ""

    @property
    def vocab_name(self) -> str:
        return f"dts-{self.id}.ttl"


def _new(label: str = "") -> Session:
    # Date first so a directory listing sorts chronologically, and four hex
    # digits so two sessions in one day do not collide. Not a uuid in full:
    # the name appears in a filename a person reads.
    return Session(id=f"{date.today():%Y%m%d}-{uuid.uuid4().hex[:4]}",
                   started=datetime.now(timezone.utc).isoformat(), label=label)


def current(dts, *, create: bool = True, label: str = "") -> Session:
    """The session in progress, started on demand.

    Started on demand rather than declared, because requiring `dts.py session
    --new` before anything else would be a step people forget and a failure
    mode — a run that refuses until you name it. Naming one is possible and
    optional (`start`).
    """
    try:
        held = json.loads(dts.read_text(SESSION_FILE))
        return Session(id=held["id"], started=held["started"],
                       label=held.get("label", ""))
    except Exception:
        if not create:
            raise
        return start(dts, label=label)


def start(dts, *, label: str = "") -> Session:
    """Begin a new session. The previous one simply ends — nothing closes it,
    because a session is a naming convention rather than a transaction."""
    session = _new(label)
    dts.trusted_ops.write_text(
        SESSION_FILE,
        json.dumps({"id": session.id, "started": session.started,
                    "label": session.label}, indent=2),
        make_parents=True)
    return session
