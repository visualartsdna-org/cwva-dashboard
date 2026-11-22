"""Standing-query definitions — data, not code (CE_DESIGN §7.1).

Each definition names a source, a check/query, a human description, a short
plural phrase for agent narration, a severity, and the resolving action (the
registry tool or workflow that closes it). Definitions load from
``config/standing_queries.rson`` (RSON = JSON + ``#`` comments); the Python
defaults below are the shipped set and the schema of record.

Sources:
- ``fs``     — count files under a sandbox dir (pipeline-queue metric).
- ``sparql`` — SELECT over the QA content graph; each row (``?item``/``?label``)
  is an open obligation.
- ``git`` / ``audit`` — uncommitted WIP, drift, staleness. Declared for later;
  they need the orchestrator (git/audit) context and are not evaluated here yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["StandingQuery", "DEFAULT_STANDING_QUERIES", "load_standing_queries"]


@dataclass(frozen=True)
class StandingQuery:
    id: str
    source: str  # "fs" | "sparql" | "git" | "audit"
    description: str  # panel text
    summary: str  # short plural phrase for narration, e.g. "works with no site link"
    severity: str = "info"
    resolving_action: str | None = None  # tool/workflow that closes the item
    query: str | None = None  # sparql source
    params: dict = field(default_factory=dict)  # fs source: {dir, extensions}

    @classmethod
    def from_dict(cls, d: dict) -> "StandingQuery":
        query = d.get("query")
        if isinstance(query, list):  # RSON queries may be arrays of lines
            query = "\n".join(query)
        return cls(
            id=d["id"],
            source=d["source"],
            description=d.get("description", d["id"]),
            summary=d.get("summary", d.get("description", d["id"])),
            severity=d.get("severity", "info"),
            resolving_action=d.get("resolving_action"),
            query=query,
            params=dict(d.get("params", {})),
        )


def load_standing_queries(path) -> list[StandingQuery]:
    """Load definitions from an RSON file (a ``standing_queries`` list). SPARQL
    lives in separate ``.sparql`` files referenced by ``query_file`` (relative
    to the config), because RSON strips ``#`` and RDF namespaces contain it.
    Query text is read here in the orchestrator and embedded, so the confined
    worker never reads config. Falls back to the shipped defaults if absent."""
    import os

    from .. import rson

    if not os.path.exists(path):
        return list(DEFAULT_STANDING_QUERIES)
    raw = rson.load(path) or []
    items = raw.get("standing_queries", raw) if isinstance(raw, dict) else raw
    base = os.path.dirname(path)
    out: list[StandingQuery] = []
    for item in items:
        d = dict(item)
        qf = d.pop("query_file", None)
        if qf:
            with open(os.path.join(base, qf), "r", encoding="utf-8") as fh:
                d["query"] = fh.read()
        out.append(StandingQuery.from_dict(d))
    return out


_PREFIXES = """
PREFIX the: <http://visualartsdna.org/thesaurus/>
PREFIX vad: <http://visualartsdna.org/model/>
PREFIX schema: <https://schema.org/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
"""

DEFAULT_STANDING_QUERIES: list[StandingQuery] = [
    # --- pipeline queues (filesystem counts; legacy stageStatus badges) ---
    StandingQuery(
        id="concept_queue",
        source="fs",
        description="Documents awaiting concept derivation/tagging",
        summary="markdowns in the concept queue",
        resolving_action="workflow.derive_concepts",
        params={"dir": "conceptQueue", "extensions": [".md", ".txt"]},
    ),
    StandingQuery(
        id="concept_queue_processed",
        source="fs",
        description="Documents already processed",
        summary="processed documents",
        params={"dir": "conceptQueue/processed", "extensions": [".md", ".txt"]},
    ),
    # --- open obligations (graph-derived; standing SPARQL) ---
    StandingQuery(
        id="works_without_workonsite",
        source="sparql",
        description="Works with no vad:workOnSite assertion",
        summary="works with no site link",
        severity="warn",
        resolving_action="workflow.update_work_on_site",
        query=_PREFIXES
        + """
        SELECT ?item ?label WHERE {
          ?item schema:image ?img ; rdfs:label ?label .
          FILTER NOT EXISTS { ?item vad:workOnSite ?site }
        }""",
    ),
    # KEPT. New records carry no `the:conceptsExtracted`, so this never matches
    # a new one — but the flag stays on the records that have it, so the query
    # still names the legacy entities nobody ran concept extraction over. A
    # fixed set rather than a shrinking one.
    StandingQuery(
        id="concepts_extracted_false",
        source="sparql",
        description="Entities pending concept extraction (conceptsExtracted false)",
        summary="entities awaiting concept extraction",
        severity="info",
        resolving_action="workflow.derive_concepts",
        query=_PREFIXES
        + """
        SELECT ?item ?label WHERE {
          ?item the:conceptsExtracted false ; rdfs:label ?label .
        }""",
    ),
    # --- hygiene-ledger obligations ---
    StandingQuery(
        id="tcap_ties",
        source="ledger",
        description="TCAP ties awaiting structural vocabulary repair",
        summary="TCAP ties to investigate",
        severity="warn",
        resolving_action=None,  # resolved by investigation via the prompt (§6 tie policy)
        params={"kind": "tie"},
    ),
    # --- declared for later (git/audit context; not evaluated yet) ---
    # uncommitted WIP, drift awaiting adoption, scrape staleness,
    # incipient-proofs-awaiting-collection (24h) — arrive with the orchestrator
    # tool context / updateWorkOnSite / proof.
]
