> **MERGED into CE_DESIGN.md (§13 Identity & namespaces) on 2026-07-17 —
> historical provenance only, not normative.** The Phase 4.5 code action
> (`work:` from config `domain`) is implemented. Canonical docs are the source
> of truth; do not treat anything below as pending work.

# DESIGN_REVISION — Identity & Namespaces (CE deployment)

Merge-ready fragment for CE_DESIGN.md (repo copy is source of truth).
Suggested placement: new top-level section after §5 (or wherever the
data-model doctrine reads best), cross-referenced from the Phase 11
onboarding items. After merging, stamp this fragment "MERGED — historical
provenance only" per the fragment convention.

Immediate action item (Phase 4.5, do not defer): the namespace constants
hoisted into the record tools must come from config, not constants —
`work:` derives from `domain` in dashboard.yaml. Cheap now, painful after
twenty tools bake it in. Everything else in this section is doctrine and
later-release work.

---

## §X. Identity & namespaces

### X.1 Doctrine

**URIs are identifiers first, addresses second.** A work URI is a
permanent name; whether and where it dereferences is a serving concern.
Most namespace pain comes from conflating the two. Consequences:

- **Cool URIs don't change.** Renaming identifiers is the worst operation
  in linked data: every TTL, every cross-reference, every criticism tag —
  and the physical world (QR codes on printed labels encode these URIs;
  a namespace change orphans every label already printed). The identity
  decision is therefore made **once, at first-run setup, with the
  tradeoffs stated** — a setup-wizard responsibility (Phase 11).
- **Shared vocabulary, sovereign instance namespaces.** The commons/
  sovereign split (§X.3) is what lets independent catalogs remain
  mutually intelligible — the precondition for the federated-catalog
  vision.
- **Data speaks domain; servers speak host.** Canonical URIs live in the
  data, always. Host mapping is presentation-only (§X.4).

### X.2 The setup-time identity decision

At first run, the wizard offers three honest options for the deployer's
instance namespace (`work:` and siblings):

1. **Own domain** (preferred): `work: <http://debbiesDomain.art/work/>`.
   One wizard field. The deployer's identifiers live under authority
   they control.
2. **Communal namespace**: mint under
   `http://visualartsdna.org/work/`. GUID uniqueness makes this
   collision-safe across all deployments. Tradeoffs stated plainly by
   the wizard: identifiers live in a namespace the deployer does not
   control; dereference authority is elsewhere; a later move to an own
   domain is a namespace rebase (§X.6) — supported, but real work.
   *Federation option (future): a small resolver/registry at
   visualartsdna.org redirecting communal URIs to registered hosts
   would turn the shared namespace from a liability into a federation
   feature.*
3. **Defer**: communal now, migrate when serious — legitimized by the
   fact that the rebase workflow (§X.6) is buildable on existing
   machinery. The wizard discloses the migration cost anyway.

### X.3 The commons/sovereign split (firm rule)

| Namespace | Status | CE deployer may rename? |
|---|---|---|
| `work:` (instances) | **Sovereign** — the deployer's | Yes — this is the identity decision above |
| `vad:` (ontology, cwva.ttl) | **Commons** — shared semantics | **Never** |
| `the:` (thesaurus + entity.ttl) | **Commons** — shared semantics | **Never** (extend instead, §X.5) |

Rationale: TCAP annotations, the navigation query, SHACL shapes, the
topic scheme, and cross-catalog intelligibility are all keyed to
`vad:`/`the:` URIs. A deployer who renames them has forked the ontology
without meaning to — nothing validates, nothing federates. The original
scenario notes hedged with "# if needed" on rewriting `the:`/`vad:`
prologs; the answer is **not needed, and actively harmful**.

### X.4 Host mapping (presentation-only)

For deployments where DNS does not (yet) point at the serving box:

```
"host":   "http://[IP:port]"        # where the server actually answers
"domain": "http://debbiesDomain.art" # what the data says
```

- The domain→host rewrite happens **only in the serving path**
  (cwvaServer-py responses; the QA data browser), so published links in
  data referring to the current site resolve locally.
- The rewrite is **never persisted into data**. Persisting it creates two
  spellings of one identity and breaks every downstream comparison.
- Both cwvaServer-py and the dashboard's QA browser consume the same
  host/domain pair from config.

### X.5 Local vocabulary: extension schemes, not renames

The legitimate need underneath "rename the thesaurus" is the deployer's
*own* concepts (their paint inventory, local techniques, local topics).
The answer is a **local extension scheme** minted under the deployer's
domain:

- e.g. `<http://debbiesDomain.art/thesaurus/>` with its own
  `skos:ConceptScheme`;
- local concepts link into the shared thesaurus via `skos:broader` /
  `skos:inScheme` (and thereby inherit TCAP typing from shared
  ancestors — the navigation algorithm works unchanged);
- the concept pipeline for a CE deployer **mints derived concepts into
  their extension scheme**, never into the shared thesaurus;
- the shared thesaurus updates only via CWVA releases.

CE thesaurus structure is therefore *core + local extension*. (Design
consequence for the concept pipeline's scheme allow-list: for CE it
includes the deployer's extension scheme; the current hardcoded
watercolor-specific list remains for the faithful-first port per the
deferral decision already recorded.)

### X.6 Namespace rebase (deferred workflow; do not build now)

Moving a catalog from the communal namespace to an own domain — or any
future domain change — is supported by existing machinery and is
deliberately boring:

1. Full-snapshot **graph-level** rewrite in QA: walk triples with rdflib
   and rebind URIRefs under the mapping old-ns → new-ns. **Never textual
   substitution**: full URIs appear outside prefix prologs
   (schema:image objects, qrcode URLs, workOnSite targets); prolog
   editing silently misses them.
2. Verification gates: triple-count preserved; only the intended
   namespace touched; all gates (parse/SHACL/assertions) pass on the
   rewritten graph.
3. One promotion unit; convergence pushes the new state; the QA git
   holds the before-state as the rollback record.
4. Out-of-band consequences surfaced to the user as a checklist, not
   automated: reprint QR labels; external sites linking the old URIs;
   optional redirect service on the old domain if the deployer controls
   it.

The existence of this workflow is what makes the communal on-ramp (X.2
option 3) honest rather than a trap.

### X.7 Scenarios (from the originating notes, resolved)

**Scenario A — new CE user, no domain.** Data minted under
`http://visualartsdna.org/work/` (communal). Config:
`host = http://[IP:port]`; domain = communal. GUIDs guarantee
cross-site uniqueness. Serving path rewrites domain→host so links
return to the local server. Identity tradeoff disclosed at setup;
rebase available later.

**Scenario B — deployer with own domain (Debbie).** Setup wizard takes
`http://debbiesDomain.art`; `work:` prolog and all minting use
`<http://debbiesDomain.art/work/>`. Config carries host + domain; the
serving rewrite applies while DNS/hosting catches up. `vad:` and `the:`
remain the shared namespaces **unchanged**; Debbie's own concepts go to
her extension scheme `<http://debbiesDomain.art/thesaurus/>` per X.5 —
the "context-sensitive substitution" from the original notes resolves
to: substitute `work:` (sovereign), never `vad:`/`the:` (commons),
extend locally instead.

**Scenario C — communal user later gets a domain.** Namespace rebase
per X.6: graph rewrite in QA, gates, one promotion, QR-label checklist.

### X.8 Implementation notes by component

- **Dashboard (Phase 4.5, now):** record tools derive `work:` from
  `domain` in dashboard.yaml (replace the hoisted constant). Default
  config for the current deployment: `domain =
  http://visualartsdna.org` — no behavior change for Rick.
- **cwvaServer-py:** confirm the host/domain seam exists in the serving
  path for CE deployments; no change for the current production setup.
- **QA browser (Phase 7):** consumes the same host/domain config.
- **Setup wizard (Phase 11):** presents X.2; writes config; for option
  1/2 initializes the extension scheme scaffold.
- **Rebase workflow (post-v1):** X.6, on existing promotion machinery.
