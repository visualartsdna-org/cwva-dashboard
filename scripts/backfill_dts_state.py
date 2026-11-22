"""Stamp the pre-DTS entities complete — an operator migration, run once.

    python scripts/backfill_dts_state.py --dry-run
    python scripts/backfill_dts_state.py
    python scripts/backfill_dts_state.py --all        # include the unevidenced
    python scripts/backfill_dts_state.py --config config/production.rson

**The queue rules key off the stamps and nothing else** (Rick, 2026-09-30:
"conceptsExtracted is a deprecated workflow boolean, follow the new audit
stamp rules"). That is the right rule and it has one consequence: every
entity that predates DTS carries no stamps, so every one of them reads as
*pending derivation*. On the real store that is 77 entities filling the first
queue of a surface built to show what needs attention — which makes the
surface useless on the day it ships.

The design record settles what is true of them: "the prod SOT is to be
**assumed up to date** with all expected concept processing" (decision B). So
they are complete, and saying so in the vocabulary the queues read is this
script's whole job.

**What it refuses to touch.** An entity that already has a status node is
mid-flight and is left alone — a backfill that overwrote one would destroy the
record of a run in progress.

**Two grounds for the same stamp, kept apart.** An entity may carry its own
evidence (`conceptsExtracted true`, or a summary), or it may be complete
because a person says it was never a candidate (`--all`). "The old workflow
said so" and "the curator said so" are different answers to "why is this
complete", and collapsing them would make the second unanswerable.

**An entity with no evidence of the pre-DTS flow is reported, not stamped**,
because claiming it was processed would assert something nobody checked. On
the real store that is 8 of 77. `--all` stamps them too, and records them on
different grounds: the question a reader will ask later is "why is this
complete", and *the old workflow said so* and *the curator said so* are
different answers. Collapsing them would make the second unanswerable.

The stamps are attributed to `ops:updateWorkOnSite`... no — to **nothing**,
deliberately. A backfill did not derive, tag or summarize anything; it
records that a previous workflow did, and inventing an agent for work this
code never did would be a provenance lie. The stamp carries the date the
backfill ran and an `rdfs:comment` saying what it means.

Written through `FileOps` and left **uncommitted**: review it at Preview
Staged and distribute it through the ordinary gated exit.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef
from rdflib.namespace import RDFS, XSD

from cwva_dashboard import config as cfgmod
from cwva_dashboard.dts.state import OPS, STAGES, THE, status_node
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.record_tools import bind_standard

# No --config and no CWVA_DASHBOARD_CONFIG: this installation's own config
# (config/config.rson, else the developer's dashboard.rson), resolved by
# load_config.
_CONFIG = cfgmod.DEFAULT_CONFIG_PATH

BACKFILL_NOTE = ("processed under the pre-DTS flow; stamped by a backfill, "
                 "not by a run of DTS")

#: The same stamp on different grounds, and the difference is kept. An entity
#: with `conceptsExtracted true` or a summary carries its own evidence; one
#: with neither is complete because a person said so (Rick, 2026-10-01: "All
#: 77 get a backfill stamp. None including the 8 are current DTS candidates").
#:
#: Recorded separately because the question a reader will ask later is "why is
#: this complete", and "the old workflow said so" and "the curator said so"
#: are different answers. Collapsing them would make the second unanswerable.
ASSERTED_NOTE = ("not a DTS candidate; stamped on the curator's assertion, "
                 "with no evidence of the pre-DTS flow in the record")


def evidence_of_prior_processing(graph: Graph, subject) -> str:
    """Why we believe this entity was already processed, or "".

    Two independent signs, either of which is enough: the retired
    `the:conceptsExtracted true`, which is what the old workflow set when it
    finished, and a `the:summary`, which only the old summarizer wrote.
    """
    if graph.value(subject, THE.conceptsExtracted) == Literal(True):
        return "conceptsExtracted true"
    if graph.value(subject, THE.summary) is not None:
        return "has a summary"
    return ""


def stamp_complete(graph: Graph, subject, *, when: str,
                   note: str = BACKFILL_NOTE) -> int:
    """All six stamps at once, with no agent. Returns triples added."""
    node = BNode()
    graph.add((subject, OPS.status, node))
    graph.add((node, RDFS.label, Literal(STAGES[-1])))
    graph.add((node, RDFS.comment, Literal(note)))
    added = 3
    for stage in STAGES:
        record = BNode()
        graph.add((node, OPS[stage], record))
        graph.add((record, OPS.at, Literal(when, datatype=XSD.dateTime)))
        added += 2
    return added


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    # Stamping without evidence is an ASSERTION, so it takes a flag: the
    # default refuses and reports, and a person who has looked says so.
    stamp_all = "--all" in argv
    config_path = str(_CONFIG)
    if "--config" in argv:
        config_path = argv[argv.index("--config") + 1]
    elif os.environ.get("CWVA_DASHBOARD_CONFIG"):
        # The variable that SELECTS the production instance for uvicorn. A
        # script that read only the flag would act on QA for an operator who
        # had exported it and said nothing.
        config_path = os.environ["CWVA_DASHBOARD_CONFIG"]

    cfg = cfgmod.load_config(config_path)
    root = cfgmod.sandbox_root(cfg, create=False)
    layout = cfgmod.active_layout(cfg)
    ops = FileOps(Sandbox.open(root, create=False),
                  git_content_extensions=cfgmod.git_content_extensions(cfg))
    when = datetime.now(timezone.utc).isoformat()

    print(f"config : {config_path}")
    print(f"qa     : {root}")

    data = Path(root) / layout.dir("work_ttl").strip("/")
    stamped, in_flight, unproven, asserted = [], [], [], []
    for path in sorted(data.rglob("*.ttl")):
        rel = str(path.relative_to(root))
        graph = Graph()
        try:
            graph.parse(path, format="turtle")
        except Exception:
            continue
        subjects = sorted(set(graph.subjects(None, THE.AI)), key=str)
        if not subjects:
            continue
        touched = 0
        for subject in subjects:
            label = str(graph.value(subject, RDFS.label) or subject)
            if status_node(graph, subject) is not None:
                in_flight.append(label)
                continue
            why = evidence_of_prior_processing(graph, subject)
            if not why:
                if not stamp_all:
                    unproven.append((label, rel))
                    continue
                touched += stamp_complete(graph, subject, when=when,
                                          note=ASSERTED_NOTE)
                asserted.append((label, rel))
                continue
            touched += stamp_complete(graph, subject, when=when)
            stamped.append((label, why))
        if touched and not dry_run:
            bind_standard(graph)
            ops.write_text(rel, graph.serialize(format="turtle"), make_parents=True)

    print(f"\nstamped complete : {len(stamped)}")
    for label, why in stamped[:8]:
        print(f"   {label[:52]:54} ({why})")
    if len(stamped) > 8:
        print(f"   … {len(stamped) - 8} more")
    if in_flight:
        print(f"\nleft alone (already have a status node): {len(in_flight)}")
        for label in in_flight[:5]:
            print(f"   {label}")
    if asserted:
        print(f"\nstamped on your assertion (no evidence in the record): "
              f"{len(asserted)}")
        for label, rel in asserted:
            print(f"   {label[:46]:48} {rel}")
    if unproven:
        # REPORTED, NOT STAMPED. Claiming these were processed would assert
        # something nobody checked, and they are few enough to look at.
        print(f"\nNOT stamped — no evidence of the pre-DTS flow: {len(unproven)}")
        for label, rel in unproven:
            print(f"   {label[:46]:48} {rel}")
        print("   These will appear in 'pending derivation'. Run DTS on them, "
              "or stamp them by hand if they are in fact done.")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0
    if not (stamped or asserted):
        print("\nNothing to do.")
        return 0
    print("\nThe QA tree is UNCOMMITTED. Review it at Preview Staged and "
          "distribute it there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
