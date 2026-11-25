"""Run the two content gates over the whole synced QA tree — READ-ONLY.

The activation checkpoint's last measurement (project plan Phase 4.6 §5): with
real content in QA, what do the asset-reference and vocabulary-reference gates
actually say? Recorded as a baseline *before* triage, so partial-copy artefacts
are never later mistaken for real defects.

    python scripts/gate_baseline.py            # summary
    python scripts/gate_baseline.py --verbose  # list every finding

This is a **scan, not a promotion**: it loads the QA tree's data graph and calls
the gate functions directly. Nothing is written, no promotion unit is composed,
no transport is constructed.

Two expectations, and the difference between them is the point:

- **absent** image references are the recorded known-partial. The shadow carries
  no images by decision, so every well-formed image-family reference dangles.
  Expected ≈469; a change in this number is informational.
- **malformed** image references must be **0**. A bare-filename value (no
  image-base join) is a data-*shape* defect independent of which assets exist —
  it is how the qrcode base-join bug would surface. **Any malformed value is a
  real finding**, and keeping the two classes apart is what stops ~469 expected
  danglers from burying one genuine defect.
- The **vocabulary** gate is expected **clean**: those references resolve inside
  the synced vocab, so a dangling one is a real finding, not a partial-copy
  artefact.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from cwva_dashboard import config as cfgmod
from cwva_dashboard.promotion import gates
from cwva_dashboard.tools.record_tools import documents_base, image_base

# Was 469 — the count from when the shadow carried no images at all. Production's
# images were seeded on 2026-09-11, so every reference now resolves and the
# expectation is zero. A baseline that still predicts 469 absences teaches its
# reader to skim past the number, which is the opposite of what it is for.
EXPECT_ABSENT = 0
EXPECT_MALFORMED = 0
#: One known: `documents/CupsStudyCriticism.pdf`, cited by
#: `work:552759c6-b155-499f-8709-6d7db265ca9b`, whose `the:mdDocument`
#: sibling holds the same text and reads fine. Dropping the reference AND
#: the file is on the fix list; this becomes 0 then, and the gate class can
#: become fatal at the same time.
#: 0 since 2026-11-01: the reference was dropped (the zero-byte file itself
#: is still on the SOT, cited by nothing — verify_shadow.py still lists it).
EXPECT_EMPTY = 0


#: `--config`, else `CWVA_DASHBOARD_CONFIG`, else this repo's default. The same
#: precedence `sync_shadow_to_qa.py` and `split_aggregate.py` use.
#:
#: **It was missing, and the omission was silent.** This script called
#: `load_config()` with no argument, so it honoured neither the flag nor the
#: environment variable that SELECTS the production instance — it was hardwired
#: to QA, and a `--config config/production.rson` was accepted and ignored. I
#: ran it that way myself and read QA's numbers as production's (2026-10-01).
def _config_path(argv: list[str]) -> str:
    if "--config" in argv:
        return argv[argv.index("--config") + 1]
    return os.environ.get("CWVA_DASHBOARD_CONFIG") or cfgmod.DEFAULT_CONFIG_PATH


def main(argv: list[str]) -> int:
    verbose = "--verbose" in argv

    config_path = _config_path(argv)
    cfg = cfgmod.load_config(config_path)
    print(f"config : {config_path}")
    qa_root = cfgmod.sandbox_root(cfg, create=False)
    layout = cfgmod.active_layout(cfg)  # the target's map (B1)
    exts = cfgmod.git_content_extensions(cfg)
    domain = cfgmod.domain(cfg)

    data_dir = qa_root / layout.dir("work_ttl")
    if not data_dir.is_dir():
        print(f"error: no content at {data_dir} — run scripts/sync_shadow_to_qa.py first")
        return 2

    ttl = sorted(p for p in data_dir.rglob("*.ttl") if p.is_file())
    print(f"qa     : {qa_root}")
    print(f"data   : {layout.dir('work_ttl')} ({len(ttl)} TTL files)")

    graph = gates.load_graph(ttl)
    print(f"graph  : {len(graph)} triples\n")

    asset = gates.asset_reference_gate(
        graph,
        qa_root,
        image_base=image_base(domain),
        image_dir=layout.dir("image"),
        # The DOCUMENT family was never armed here, so "baseline clean" covered
        # no `the:mdDocument` or `the:pdfDocument` reference at all -- 58 of the
        # latter alone. `promotion/driver.py` passes both of these; this script
        # did not, which is the "a gate built without its arguments silently
        # runs nothing" trap one layer out from the fixtures CLAUDE.md records
        # it for. Armed 2026-10-29, and it immediately found the zero-byte
        # document the gate had just learned to look for.
        document_base=documents_base(domain),
        document_dir=layout.dir("document"),
        git_content=exts,
        require_present=False,  # the image-less shadow: report, do not fail
    )
    absent = asset.details.get("absent", [])
    malformed = asset.details.get("malformed", [])
    empty = asset.details.get("empty", [])
    resolved = asset.details.get("resolved", 0)

    print("-- asset-reference gate --")
    print(f"  resolved  : {resolved}")
    print(f"  absent    : {len(absent)}  (expected {EXPECT_ABSENT}; the shadow now carries production's images)")
    print(f"  malformed : {len(malformed)}  (expected {EXPECT_MALFORMED}; ANY is a real finding)")
    # Zero-byte assets are REPORTED by the gate, not fatal (gates.py explains
    # why). Printed unconditionally and named in full, because the one known
    # instance was invisible here for months while this script said
    # "baseline clean" -- an empty file resolves.
    print(f"  ZERO-BYTE : {len(empty)}  (expected {EXPECT_EMPTY}; the reference resolves, the asset is unusable)")
    for x in empty:
        print(f"    [ZERO-BYTE] {x}")
    if verbose:
        for x in absent[:40]:
            print(f"    [absent] {x}")
    for x in malformed:
        print(f"    [MALFORMED] {x}")

    vocab_dirs = [layout.dir("vocab_ttl"), layout.dir("tags_ttl")]
    vocab = gates.vocabulary_reference_gate(graph, qa_root, vocab_dirs)
    dangling = vocab.details.get("dangling", [])
    print("\n-- vocabulary-reference gate --")
    print(f"  vocab dirs: {vocab_dirs}")
    print(f"  resolved  : {vocab.details.get('resolved', 0)}")
    print(f"  dangling  : {len(dangling)}  (expected 0)")
    for x in dangling[:40]:
        print(f"    [DANGLING] {x}")

    # SHACL, over the same graph. The promotion gate only ever sees the files in
    # one unit, so this is the only place the WHOLE store is checked against the
    # shapes — which is what you want before arming anything, and after a sync
    # that brought other people's edits down.
    shapes = cfgmod.load_shapes(cfg)
    print("\n-- SHACL gate --")
    if shapes is None:
        print(f"  shapes    : none found in {cfgmod.shapes_dir(cfg)} — gate NOT armed")
        violations = []
    else:
        shacl = gates.shacl_gate(graph, shapes)
        violations = [] if shacl.ok else list(shacl.messages or [])
        print(f"  shapes    : {len(shapes)} triples from {cfgmod.shapes_dir(cfg)}")
        print(f"  conforms  : {shacl.ok}")
        for x in violations[:40]:
            print(f"    [VIOLATION] {str(x)[:160]}")

    findings = []
    if malformed:
        findings.append(f"{len(malformed)} malformed image reference(s)")
    if dangling:
        findings.append(f"{len(dangling)} dangling vocabulary reference(s)")
    if violations:
        findings.append(f"{len(violations)} SHACL violation(s)")

    print()
    if findings:
        print("FINDINGS — these are real defects, not partial-copy artefacts:")
        for f in findings:
            print(f"  - {f}")
        return 1
    print(f"baseline clean: 0 malformed, 0 dangling, SHACL conforms "
          f"({len(absent)} absent image references)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
