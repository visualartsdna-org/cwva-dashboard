"""Move provenance agents into the operations ontology — an operator migration.

    python scripts/migrate_agent_iris.py --dry-run
    python scripts/migrate_agent_iris.py
    python scripts/migrate_agent_iris.py --config config/production.rson \\
        --ontology-from config/dashboard.rson

`update_work_on_site.py` minted `<{domain}/agent/updateWorkOnSite>` and DTS
followed the convention, which turned out to be a namespace with nothing behind
it: no class said what an agent was, no role said what it did, and no list said
which models a deployment uses. Rick, 2026-09-30: "is this a new namespace? …
How about ops:curator, we add it to operations."

So this script does two things, and both are idempotent:

0. **Brings `operations.ttl` over when the deployment has none**
   (`--ontology-from <config>`). Production has none and is already using the
   vocabulary — its four artist profiles carry `ops:template` and friends from
   the QA import with nothing defining them — because the ontology is one of
   the paths QA holds deliberately ahead and it has never travelled.
1. **Adds the agency section to `operations.ttl`** — `ops:Role`, the roles,
   `ops:hasRole`, `ops:user`, and a `prov:SoftwareAgent` per model this
   deployment uses. Skipped when `ops:Role` is already there.
2. **Rewrites every `…/agent/X` IRI to `ops:X`**, with the one rename the new
   vocabulary implies: `agent/curator` becomes `ops:user`, because the user is
   an agent and `ops:Curator` is the role they act in. Conflating them would
   make "what did the curator decide" unanswerable without also knowing which
   model was in the chair.

Files are **re-serialized**, not patched, which is deliberate: a text
substitution leaves the old prefix bindings in place, and an entity record that
gained a `vad:` property after it was written has nothing binding `vad:` — so
it serializes as `ns1:hasTensegrityPrinciple`, which is valid RDF and
unreadable to anyone who knows the vocabulary. Re-serializing binds the
deployment's prefixes on the way out.

It writes through `FileOps` like the other migrations here, so the path
chokepoint and the quotas apply, and it leaves the result **uncommitted**:
review it at Preview Staged and distribute it through the ordinary gated exit.
Re-serialization can reorder blank nodes, which is a large text diff and no
semantic change, so the script **skips a file whose graph it did not actually
alter** rather than handing the review stop churn to read past.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rdflib import Graph, URIRef
from rdflib.compare import isomorphic

from cwva_dashboard import config as cfgmod
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.record_tools import bind_standard

# No --config and no CWVA_DASHBOARD_CONFIG: this installation's own config
# (config/config.rson, else the developer's dashboard.rson), resolved by
# load_config.
_CONFIG = cfgmod.DEFAULT_CONFIG_PATH

OLD_BASE = "http://visualartsdna.org/agent/"
OPS = "http://visualartsdna.org/operations/"

#: The one rename the new vocabulary implies. Everything else keeps its local
#: name and only changes namespace.
RENAMES = {"curator": "user"}

#: The agency section, owned here so the migration is reproducible against any
#: deployment rather than being a paste someone did once by hand.
AGENCY_SECTION = '''

################################################################
# SECTION 2 - Agency and provenance
################################################################
#
# Who or what did a thing, and in what capacity. Written by the dashboard on
# every record an agent drafts and every stage a curator closes (law 9), and
# read by anyone asking "where did this come from".
#
# A ROLE is not an AGENT. `prov:wasAttributedTo` points at the agent that did
# the work; the role it acted in is a separate, queryable fact. Conflating
# them would make "what did the curator decide" unanswerable without also
# knowing which model was in the chair that day.

ops:Role a owl:Class ;
  rdfs:label "Role" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "The capacity in which an agent acts. Distinct from the agent itself: the same model may act as a curator agent in one workflow and something else in another." ;
.

ops:hasRole
  rdf:type owl:ObjectProperty ;
  rdfs:domain prov:Agent ;
  rdfs:range ops:Role ;
  rdfs:label "has role" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "The capacity this agent acts in." ;
.

ops:Curator a ops:Role ;
  rdfs:label "curator" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "Decides what a workflow proposed is kept. The judgement of intent, which no gate certifies." ;
.

ops:CuratorAgent a ops:Role ;
  rdfs:label "curator agent" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "Proposes for a curator to decide on. Never decides." ;
.

ops:Scraper a ops:Role ;
  rdfs:label "scraper" ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "Observes an external source and reports what it found, asserting nothing the source did not say." ;
.

# THE USER, named by role and never by identity. CE v1 is single-user, so a
# role identifies them exactly - and these records reach a published
# catalogue, where a name or an address would be a personal detail nobody
# asked to publish.
ops:user a prov:Person, prov:Agent ;
  rdfs:label "the user" ;
  ops:hasRole ops:Curator ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
  rdfs:comment "This deployment's single user, identified by role rather than by identity." ;
.

# THE MODELS, enumerated. A record also declares inline whatever agent it
# cites, so it stays self-describing when read alone and when this list lags
# behind a configured model.
ops:claude-sonnet-5 a prov:SoftwareAgent ;
  rdfs:label "Anthropic claude-sonnet-5" ;
  ops:hasRole ops:CuratorAgent ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
.

ops:claude-opus-5-5 a prov:SoftwareAgent ;
  rdfs:label "Anthropic claude-opus-5-5" ;
  ops:hasRole ops:CuratorAgent ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
.

ops:updateWorkOnSite a prov:SoftwareAgent ;
  rdfs:label "updateWorkOnSite scraper (observed-by-scraper)" ;
  ops:hasRole ops:Scraper ;
  rdfs:isDefinedBy <http://visualartsdna.org/operations/> ;
.
'''

PROV_PREFIX = "@prefix prov:   <http://www.w3.org/ns/prov#> .\n"


def _ontology_from(config_path: str) -> str:
    """`operations.ttl` as another deployment holds it.

    Read-only against that sandbox: this brings a vocabulary file one way,
    from the deployment that is ahead to the one that is behind, and never the
    reverse.
    """
    other = cfgmod.load_config(config_path)
    other_root = cfgmod.sandbox_root(other, create=False)
    other_layout = cfgmod.active_layout(other)
    path = (Path(other_root) / other_layout.dir("model_ttl").strip("/")
            / "operations.ttl")
    if not path.exists():
        raise SystemExit(f"{config_path} has no operations.ttl at {path}")
    return path.read_text(encoding="utf-8")


def target_iri(old: str) -> URIRef:
    """`…/agent/X` as `ops:X`, applying the one rename."""
    local = str(old)[len(OLD_BASE):]
    return URIRef(OPS + RENAMES.get(local, local))


def rewrite(graph: Graph) -> int:
    """Replace every agent IRI in subject or object position. Returns the
    number of triples touched."""
    touched = 0
    for s, p, o in list(graph):
        new_s = target_iri(s) if str(s).startswith(OLD_BASE) else s
        new_o = target_iri(o) if str(o).startswith(OLD_BASE) else o
        if new_s is s and new_o is o:
            continue
        graph.remove((s, p, o))
        graph.add((new_s, p, new_o))
        touched += 1
    return touched


def add_agency(text: str) -> str:
    """The agency section, plus the `prov:` prefix it needs. Idempotent."""
    if "ops:Role" in text:
        return text
    if "@prefix prov:" not in text:
        anchor = "@prefix dct:"
        if anchor in text:
            text = text.replace(anchor, PROV_PREFIX + anchor, 1)
        else:
            text = PROV_PREFIX + text
    return text + AGENCY_SECTION


def main(argv: list[str]) -> int:
    dry_run = "--dry-run" in argv
    config_path = str(_CONFIG)
    if "--config" in argv:
        config_path = argv[argv.index("--config") + 1]
    elif os.environ.get("CWVA_DASHBOARD_CONFIG"):
        # The variable that SELECTS the production instance for uvicorn. A
        # script that read only the flag would act on QA for an operator who
        # had exported it and said nothing.
        config_path = os.environ["CWVA_DASHBOARD_CONFIG"]
    source_config = (argv[argv.index("--ontology-from") + 1]
                     if "--ontology-from" in argv else "")

    cfg = cfgmod.load_config(config_path)
    root = cfgmod.sandbox_root(cfg, create=False)
    layout = cfgmod.active_layout(cfg)
    ops = FileOps(Sandbox.open(root, create=False),
                  git_content_extensions=cfgmod.git_content_extensions(cfg))

    print(f"config : {config_path}")
    print(f"qa     : {root}")

    # -- 1. the ontology ----------------------------------------------------
    ontology = f"{layout.dir('model_ttl').rstrip('/')}/operations.ttl"
    imported = False
    try:
        before = ops.read_text(ontology)
    except Exception:
        # PRODUCTION HAS NONE, and it is already using the vocabulary: its
        # four artist profiles carry `ops:template`, `ops:field`, `ops:order`
        # and `ops:required` from the import, with nothing defining any of
        # them (measured 2026-09-30). The ontology is one of the paths QA
        # holds deliberately ahead (`shadow_sot.qa_only`), so it has never
        # travelled — which is the gap Rick anticipated: "these same
        # distributed files will need to be saved and moved to prod".
        #
        # Brought over deliberately and only when asked, from a named
        # deployment, the way `split_aggregate.py --from` imports records.
        if not source_config:
            print(f"\nREFUSED — {ontology} does not exist in this deployment, "
                  "and its data may already use the vocabulary. Bring the "
                  "ontology over first:\n\n"
                  f"    python {Path(sys.argv[0]).name} --config {config_path} "
                  "--ontology-from config/dashboard.rson --dry-run\n")
            return 1
        before = _ontology_from(source_config)
        imported = True
        print(f"\nontology imported from {source_config} "
              f"({len(Graph().parse(data=before, format='turtle'))} triples)")
    after = add_agency(before)
    # An IMPORTED ontology is always written, even when nothing is added to it.
    # The first cut compared `after` with `before` and skipped the write when
    # they matched — which is correct for a local file and silently wrong for an
    # imported one, because QA's copy already HAS the agency section. So the
    # production run reported "already present" and left the deployment with no
    # operations.ttl at all (caught 2026-10-01 by a preview showing 0 adds).
    if after == before and not imported:
        print(f"\n{ontology}: agency section already present")
    else:
        parsed = Graph()
        parsed.parse(data=after, format="turtle")  # refuse what will not parse
        added = len(parsed) - len(Graph().parse(data=before, format="turtle"))
        print(f"\n{ontology}: "
              + (f"written from the import ({len(parsed)} triples"
                 + (f", + {added} for the agency section" if added else "")
                 + ")" if imported
                 else f"+ agency section ({added} triples)"))
        if not dry_run:
            ops.write_text(ontology, after, make_parents=True)

    # -- 2. the IRIs --------------------------------------------------------
    changed, skipped, scanned = [], [], 0
    for path in sorted(Path(root).rglob("*.ttl")):
        rel = str(path.relative_to(root))
        if rel.startswith(".qa/"):
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8")
        if OLD_BASE not in text:
            continue
        graph = Graph()
        graph.parse(data=text, format="turtle")
        original = Graph()
        original.parse(data=text, format="turtle")
        touched = rewrite(graph)
        if isomorphic(graph, original):
            # Re-serializing would reorder blank nodes for no semantic gain,
            # and hand the review stop a large diff to read past.
            skipped.append(rel)
            continue
        bind_standard(graph)
        changed.append((rel, touched))
        if not dry_run:
            ops.write_text(rel, graph.serialize(format="turtle"), make_parents=True)

    print(f"\nscanned {scanned} TTL file(s)")
    if not changed and not skipped:
        print("no `…/agent/` IRIs found; nothing to rewrite")
    for rel, touched in changed:
        print(f"  {rel:58} {touched} triple(s)")
    for rel in skipped:
        print(f"  {rel:58} unchanged (skipped)")

    if dry_run:
        print("\nDRY RUN — nothing written.")
        return 0
    print("\nThe QA tree is UNCOMMITTED. Review it at Preview Staged and "
          "distribute it there.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
