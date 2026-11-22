"""Tidy the status node on existing records — an operator migration.

    python scripts/migrate_status_shape.py --dry-run
    python scripts/migrate_status_shape.py
    python scripts/migrate_status_shape.py --config config/production.rson

Rick, 2026-10-02, reading a criticism page in the browser after the production
DTS: "the criticism page in the browser contains too many status properties and
values. The grounding is meaningless here. Can the grounding be moved under
status? Then have one label for status, rather than 'summaryCurated' use
'curation complete' when DTS is complete. The property the:conceptsExtracted
should be removed going forward."

New records are born right; this brings the ones already written into line.
Three changes, each idempotent:

1. **Grounding moves under `ops:status`.** A grounding on the ENTITY is the
   run's account of why it tagged what it tagged, and the status node is the
   record of what the run did. Twelve `ground verified` nodes hung off the
   subject put twelve rows of nothing at the top of the page, above the
   concepts they are evidence for. Concept-side groundings are NOT touched:
   those are about the concept, which is why that vocabulary stayed in `the:`.

2. **The status label reads `curation complete`** once all six stamps are
   present, instead of naming whichever act happened to be last. Safe to
   rewrite because nothing reads it — the queue rules key off the stamps.

3. **`the:conceptsExtracted` is left alone EXCEPT where it contradicts
   itself** — `false` on a record whose own stamps say the run completed. New records no longer carry it —
   `record.new_entity` stopped writing it — but the ones that have it keep it.
   Rick, 2026-10-02: "I think I said delete `the:conceptsExtracted false` going
   forward. I'm not concerned with its historical use, it can remain in past
   records." The first cut of this script dropped 148 triples from 85 records,
   which was further than the instruction went.

4. **Inline agent declarations are stripped from records**, which is what makes
   a DTS-processed entity a one-named-subject file again.

Files are re-serialized, not patched, and a file whose graph did not actually
change is skipped — re-serialization reorders blank nodes, which is a large
diff with no change in it for the review stop to read past.

Written through `FileOps` and left **uncommitted**: review it at Preview Staged
and distribute it through the ordinary gated exit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rdflib import BNode, Graph, URIRef
from rdflib.compare import isomorphic
from rdflib.namespace import RDFS

from cwva_dashboard import config as cfgmod
from cwva_dashboard.dts.state import (OPS, THE, label_for, read_stamps,
                                      status_node)
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.record_tools import bind_standard

# No --config and no CWVA_DASHBOARD_CONFIG: this installation's own config
# (config/config.rson, else the developer's dashboard.rson), resolved by
# load_config.
_CONFIG = cfgmod.DEFAULT_CONFIG_PATH


def move_grounding(g: Graph) -> int:
    """Re-parent entity-side grounding nodes under `ops:status`.

    Returns the number moved. A grounding whose owner has no status node is
    LEFT WHERE IT IS: there is no run for it to belong to, and inventing a
    status node to hold it would assert that one happened.
    """
    moved = 0
    for subj, node in list(g.subject_objects(THE.grounding)):
        if isinstance(subj, BNode):
            continue  # already under a status node
        owner = status_node(g, subj)
        if owner is None:
            continue
        g.remove((subj, THE.grounding, node))
        g.add((owner, THE.grounding, node))
        moved += 1
    return moved


def relabel_status(g: Graph) -> int:
    """Recompute every status node's label from its stamps."""
    changed = 0
    for subj in set(g.subjects(OPS.status, None)):
        node = status_node(g, subj)
        if node is None:
            continue
        want = label_for(read_stamps(g, subj))
        if str(g.value(node, RDFS.label) or "") == want:
            continue
        g.remove((node, RDFS.label, None))
        g.add((node, RDFS.label, __import__("rdflib").Literal(want)))
        changed += 1
    return changed


def drop_inline_agents(g: Graph) -> int:
    """Remove agent declarations a record made about the operations vocabulary.

    A record describes ITS OWN subject. `ops:claude-sonnet-5 a
    prov:SoftwareAgent ; rdfs:label "…"` is a statement about the vocabulary,
    written into the record so it stayed self-describing when read alone —
    before the operations ontology existed. It has existed in both deployments
    since 2026-10-01, and the cost of the workaround only showed afterwards:

    - the record became a FOUR-SUBJECT file, failing the one-named-subject
      rule, so Edit Record would not open it and Drafts listed it as
      "<guid>.ttl (4 subjects)" with no link back in;
    - and the curator's declaration said `prov:SoftwareAgent` where the
      ontology says `prov:Agent, prov:Person`.

    Only SUBJECT position goes. `prov:wasAttributedTo ops:user` is the
    provenance and is the point of the whole structure.

    **Scoped to the RECORDS.** `operations.ttl` is nothing but statements about
    `ops:` subjects — that is its job — and an unscoped pass over the tree
    reported 151 triples to remove from it. The vocabulary files are left alone
    too: their agent declaration is redundant now and does no harm, because an
    aggregate has no one-named-subject rule to break.
    """
    rows = [tr for tr in g if str(tr[0]).startswith(str(OPS))]
    for triple in rows:
        g.remove(triple)
    return len(rows)


#: The declaration STAYS — 59 records still carry the predicate and a term in
#: use with nothing defining it is the defect this project spent a day fixing.
#: It is marked deprecated instead, which is the honest statement: present,
#: readable, and never written again.
DEPRECATION = """
the:conceptsExtracted
  owl:deprecated true ;
  rdfs:seeAlso <http://visualartsdna.org/operations/status> ;
.
"""


def deprecate_flag(text: str) -> str:
    """Mark `the:conceptsExtracted` deprecated in the ontology. Idempotent."""
    if "owl:deprecated" in text:
        return text
    if "@prefix owl:" not in text:
        text = ("@prefix owl:   <http://www.w3.org/2002/07/owl#> .\n"
                + text)
    return text + DEPRECATION


def drop_contradicted_flag(g: Graph) -> int:
    """Remove `the:conceptsExtracted false` from a record with a COMPLETE run.

    Not a tidy-up and not the blanket strip this script first did. The flag is
    kept wherever it records something: `true` agrees with "extraction
    happened" and is the evidence `backfill_dts_state.py` read, and `false` on
    a record DTS never touched is a true statement about 13 real entities —
    none of which carries a single `vad:*` placement, so none was extracted.

    What goes is the combination that CONTRADICTS ITSELF: `false` on a record
    whose own status node says derived, curated, tagged, curated, summarized
    and curated all completed. That is not history, it is a false statement
    three lines above the stamps that refute it — and the browser renders it
    as `derived false` on a finished criticism (Rick, 2026-10-02).
    """
    from cwva_dashboard.dts.state import state_of

    dropped = 0
    for subj, value in list(g.subject_objects(THE.conceptsExtracted)):
        if str(value) != "false":
            continue
        if (subj, OPS.status, None) not in g:
            continue
        if state_of(g, subj) != "complete":
            continue
        g.remove((subj, THE.conceptsExtracted, value))
        dropped += 1
    return dropped


def _config_path(argv: list[str]) -> str:
    if "--config" in argv:
        return argv[argv.index("--config") + 1]
    return os.environ.get("CWVA_DASHBOARD_CONFIG") or str(_CONFIG)


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    config_path = _config_path(argv)

    cfg = cfgmod.load_config(config_path)
    root = cfgmod.sandbox_root(cfg, create=False)
    ops = FileOps(Sandbox.open(root, create=False),
                  git_content_extensions=cfgmod.git_content_extensions(cfg))

    layout = cfgmod.active_layout(cfg)
    records = layout.dir("work_ttl").rstrip("/")
    model = layout.dir("model_ttl").rstrip("/")

    print(f"config : {config_path}")
    print(f"qa     : {root}")
    print("flag   : the:conceptsExtracted is LEFT ALONE on existing records")
    print(f"records: {records}  (inline agent declarations stripped here only)")

    # -- the ontology ------------------------------------------------------
    entity_ttl = f"{model}/entity.ttl"
    try:
        before = ops.read_text(entity_ttl)
    except Exception:
        print(f"\n{entity_ttl}: ABSENT, skipping the deprecation marker")
    else:
        after = deprecate_flag(before)
        if after == before:
            print(f"\n{entity_ttl}: already marks the flag deprecated")
        else:
            Graph().parse(data=after, format="turtle")  # refuse what will not parse
            print(f"\n{entity_ttl}: + owl:deprecated on the:conceptsExtracted")
            if not dry_run:
                ops.write_text(entity_ttl, after, make_parents=True)

    changed, scanned = [], 0
    totals = {"grounding": 0, "label": 0, "agents": 0, "contradicted": 0}
    for path in sorted(Path(root).rglob("*.ttl")):
        rel = str(path.relative_to(root))
        if rel.startswith(".qa/"):
            continue
        in_records = rel.startswith(f"{records}/")
        scanned += 1
        text = path.read_text(encoding="utf-8")
        if not any(k in text for k in ("the:grounding", "ops:status", "ops:",
                                       "the:conceptsExtracted")):
            continue
        g = Graph()
        g.parse(data=text, format="turtle")
        original = Graph()
        original.parse(data=text, format="turtle")

        counts = {"grounding": move_grounding(g), "label": relabel_status(g),
                  "agents": drop_inline_agents(g) if in_records else 0,
                  "contradicted": (drop_contradicted_flag(g) if in_records
                                   else 0)}
        if isomorphic(g, original):
            continue
        for k, v in counts.items():
            totals[k] += v
        bind_standard(g)
        changed.append((rel, counts))
        if not dry_run:
            ops.write_text(rel, g.serialize(format="turtle"), make_parents=True)

    if "--list" in argv:
        for rel, counts in changed:
            print(f"  {rel:56} {counts}")
    print(f"\nscanned {scanned} TTL file(s), changed {len(changed)}")
    print(f"  grounding moved under ops:status : {totals['grounding']}")
    print(f"  status labels recomputed         : {totals['label']}")
    print(f"  inline agent declarations gone   : {totals['agents']}")
    print(f"  `conceptsExtracted false` on a    : {totals['contradicted']}"
          "\n    COMPLETE run (self-contradictory)")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0
    print("\nThe QA tree is UNCOMMITTED. Review it at Preview Staged and "
          "distribute it there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
