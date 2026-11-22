"""Workflow state — compute obligations, record only dismissals (CE_DESIGN §7.1).

Workflow state is **derived, not tracked**: the panel and the agent's narration
are two renderings of the *same* standing-query results over sources the system
already maintains. The only recorded state is the exception — a dismissal — kept
in the hygiene ledger. Open items = standing-query results − dismissals.

Standing-query definitions are **data, not code** (`definitions.py` +
`config/standing_queries.rson`), so item types can be added without touching the
engine. This package ships the sandbox-derivable sources (filesystem counts and
SPARQL obligations over the QA content); git/audit/drift sources are added when
the orchestrator-tool context lands.
"""

from .definitions import DEFAULT_STANDING_QUERIES, StandingQuery, load_standing_queries
from .engine import OpenItem, QueueCount, WorkflowState, evaluate

__all__ = [
    "StandingQuery",
    "DEFAULT_STANDING_QUERIES",
    "load_standing_queries",
    "evaluate",
    "WorkflowState",
    "OpenItem",
    "QueueCount",
]
