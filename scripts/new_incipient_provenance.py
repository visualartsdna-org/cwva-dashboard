"""Write the incipient provenance for a work that does not have one.

    python scripts/new_incipient_provenance.py --work <guid> --dry-run
    python scripts/new_incipient_provenance.py --work <guid>
    python scripts/new_incipient_provenance.py --work <guid> --config config/production.rson

A profile form does this on submit. This is for a work entered before it did. It
runs the same `new_incipient` the form's tool runs, so one rule allocates the DI.

Refuses a work that already has an incipient record: rewriting one from here would
re-derive a DI that may have been written on a box. Written through `FileOps` and
left **uncommitted**: review it on Drafts and distribute it through the gated exit.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rdflib.namespace import RDF, RDFS

from cwva_dashboard import config as cfgmod
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.provenance_tools import (disposition_id, new_incipient,
                                                   read_record, storage_class_for)
from cwva_dashboard.tools.record_tools import SCHEMA, VAD, work_namespace
from cwva_dashboard.tools.workflow_tools import _content_graph
from cwva_dashboard.ux.affordance import load_model_live

# No --config and no CWVA_DASHBOARD_CONFIG: this installation's own config
# (config/config.rson, else the developer's dashboard.rson), resolved by
# load_config.
_CONFIG = cfgmod.DEFAULT_CONFIG_PATH


def main(argv: list[str]) -> int:
    if "--work" not in argv:
        print(__doc__)
        return 2
    work = argv[argv.index("--work") + 1]
    dry_run = "--dry-run" in argv
    config_path = str(_CONFIG)
    if "--config" in argv:
        config_path = argv[argv.index("--config") + 1]
    elif os.environ.get("CWVA_DASHBOARD_CONFIG"):
        # What selects the production instance for uvicorn. A script reading only
        # the flag would act on QA for an operator who had exported it.
        config_path = os.environ["CWVA_DASHBOARD_CONFIG"]

    cfg = cfgmod.load_config(config_path)
    root = cfgmod.sandbox_root(cfg, create=False)
    layout = cfgmod.active_layout(cfg)
    ops = FileOps(Sandbox.open(root, create=False),
                  git_content_extensions=cfgmod.git_content_extensions(cfg))
    work_ns = work_namespace(cfgmod.domain(cfg))
    work_dir, provenance_dir = layout.dir("work_ttl"), layout.dir("provenance_ttl")
    model = load_model_live(Path(root) / layout.dir("model_ttl"))

    print(f"config : {config_path}")
    print(f"qa     : {root}")

    subject = work_ns[work]
    provenance = _content_graph(ops, provenance_dir)
    held = [s for s in provenance.subjects(VAD.hasArtwork, subject)
            if (s, VAD.dispositionId, None) in provenance]
    if held:
        print(f"REFUSED: already has {provenance.value(held[0], VAD.dispositionId)} "
              f"on {held[0]}")
        return 1

    if dry_run:
        data = read_record(ops, work_dir, work)
        year = str(data.value(subject, SCHEMA.dateCreated) or "")[:4]
        item = max((int(o) for o in provenance.objects(None, VAD.itemId)), default=0) + 1
        cls = storage_class_for(set(data.objects(subject, RDF.type)), provenance, model)
        print(f"work   : {data.value(subject, RDFS.label)}")
        print(f"DI     : {disposition_id(cls, year, item)}  (not written)")
        return 0

    made = new_incipient(ops, work, work_dir=work_dir, provenance_dir=provenance_dir,
                         work_ns=work_ns, model=model)
    print(f"DI     : {made['disposition_id']}")
    print(f"owner  : {made['owner']}")
    print(f"path   : {made['path']}")
    print("left uncommitted: review it on Drafts, then distribute.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
