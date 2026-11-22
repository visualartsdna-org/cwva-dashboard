"""DTS, composed: the four steps and the context they share.

**Headless first, by Rick's instruction** — the workflow is library code here
and the UX binds it later, which is the same relationship `workflows/annotate.py`
has with the annotate routes. So nothing in this module knows about a request,
a form or a page; a caller supplies a dispatcher and the pieces around it.

Everything that WRITES goes through a registry tool (law 10). Everything that
reaches outside the sandbox — the drop folder, the model provider — is done by
the caller's trusted-side handles, because the confined worker can do neither
(it cannot read the drop folder at all, and it cannot resolve a hostname). That
split is not a style: a tool that called a provider would return nothing and
say nothing, which is how updateWorkOnSite's first real run wrote two empty
snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from rdflib import Graph

from ..inbox import normalize_filename
from .state import agent_iri, curator_iri

__all__ = ["DTS", "StageError", "EntityCreated", "create_entity"]


class StageError(RuntimeError):
    """A stage could not finish. The message is for a person."""


@dataclass
class DTS:
    """What every stage needs, gathered once.

    Built from `app.state` by the operator script and by the routes alike, so
    a headless run and a driven one cannot disagree about which sandbox, which
    drop folder or which layout they are working in.
    """

    dispatch: Callable
    layout: object
    domain: str
    inbox: object = None
    trusted_ops: object = None
    ai: object = None
    #: The sandbox tree, for the trusted-side reads a stage does directly (the
    #: whole thesaurus as one graph). Content reads still go through `fs.read`;
    #: this is for the bulk load, which as a tool call would be one dispatch
    #: per file and blow the ops quota — the fifth time that lesson has been
    #: learned in this project.
    root: object = None

    # -- helpers every stage uses ------------------------------------------

    def call(self, tool: str, args: dict) -> dict:
        """Dispatch a registry tool, or raise with what went wrong.

        Stages read better for it: a tool failure is exceptional and the
        alternative is an `if not ok` after every line, which is where a
        forgotten check becomes a stage that reports success having written
        nothing.
        """
        out = self.dispatch(tool, args)
        if not out.get("ok"):
            err = out.get("error") or {}
            raise StageError(
                f"{tool} failed ({err.get('code', 'error')}): {err.get('message', '')}"
            )
        return out.get("result") or {}

    def read_text(self, path: str) -> str:
        return str(self.call("fs.read", {"path": path}).get("text", ""))

    def document_text(self, name: str) -> str:
        """A document in the sandbox, by its bare filename."""
        return self.read_text(f"{self.layout.dir('document').rstrip('/')}/{name}")

    def expect_stage(self, entity_path: str, subject: str, stage: str) -> None:
        """Refuse a stage that is not next, BEFORE anything is written.

        The order check lives in `dts.stamp`, which a stage calls last — so a
        commit that ran in the wrong order wrote its concepts, wrote its
        evidence, and then failed, leaving the store changed by a stage that
        reported failure. That happened on the first real run of the corrected
        two-stamp flow.

        Checking first makes a stage all-or-nothing in the case that actually
        occurs. It is not a transaction — a write failing mid-sequence still
        leaves part of one — but order is the failure with a wrong operator
        command behind it, and it is cheap to catch before any cost is paid.
        """
        from .state import STAGES, state_of

        graph = Graph()
        graph.parse(data=self.read_text(entity_path), format="turtle")
        expected = state_of(graph, subject)
        if expected != stage:
            where = "complete" if expected == "complete" else f"waiting for {expected}"
            raise StageError(
                f"cannot {stage}: this entity is {where}. The stages run in "
                f"order ({' -> '.join(STAGES)}). Nothing was written.")

    def work_iri(self, guid: str) -> str:
        return f"{self.domain.rstrip('/')}/work/{guid}"

    def agent(self, model: str):
        return agent_iri(model)

    def curator(self):
        return curator_iri()


@dataclass(frozen=True)
class EntityCreated:
    """Queue 0 done: a document in the drop folder now has an entity."""

    guid: str
    uri: str
    path: str
    document: str
    ingested: bool
    renamed: str = ""


def create_entity(dts: DTS, *, label: str, topic: list, definition: str,
                  md_document: str, type: str = "AI", tags: list | None = None,
                  notes: list | None = None, recorded_date: str = "",
                  guid: str = "") -> EntityCreated:
    """Stage 0 — the document gets an entity, and the entity gets the document.

    Three things happen in a fixed order, and the order is the point.

    **Ingest first**, trusted-side, through `FileOps` so the `.ptr` sidecar is
    minted on arrival (law 12). A document copied in by hand is invisible to
    the git-derived manifest, so the record would reach the SOT while the
    markdown never followed — and every grounding phrase would then point at a
    document nobody downstream can read.

    **Then the record**, through `record.new_entity`, so the confinement, the
    audit entry and the schema check are the ones every other writer gets.

    **Then the CURIE stamp** on the markdown (`doc.set_id`), because the
    derivation and tagging steps read that line to find which entity a document
    belongs to. Only 5 of the 70 markdown files in the store carry it, and
    stamping it here is what stops DTS from inheriting that gap.

    The filename the record CITES is the normalized one (law 12): the dashboard
    owns names inside the system, the drop folder keeps its own.
    """
    final = normalize_filename(md_document)
    ingested = False
    if dts.inbox is not None and dts.trusted_ops is not None:
        res = dts.inbox.copy_into(
            md_document, dts.trusted_ops, dts.layout.dir("document"),
            kind="markdown", dest_name=final,
        )
        ingested = bool(res.get("copied"))

    created = dts.call("record.new_entity", {
        "type": type,
        "label": label,
        "topic": list(topic),
        "definition": definition,
        "recorded_date": recorded_date or date.today().isoformat(),
        "md_document": final,
        **({"guid": guid} if guid else {}),
        **({"tags": list(tags)} if tags else {}),
        **({"notes": list(notes)} if notes else {}),
    })

    curie = f"work:{created['guid']}"
    dts.call("doc.set_id", {
        "path": f"{dts.layout.dir('document').rstrip('/')}/{final}",
        "curie": curie,
    })

    return EntityCreated(
        guid=created["guid"], uri=created["uri"], path=created["path"],
        document=final, ingested=ingested,
        renamed=md_document if final != md_document else "",
    )
