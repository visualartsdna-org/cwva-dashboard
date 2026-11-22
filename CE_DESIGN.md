# CE_DESIGN.md — CWVA Community Edition Dashboard

Design record for the CE dashboard: an AI-assisted QA environment for CWVA
data development and maintenance. This document consolidates the settled
architectural decisions; CLAUDE.md carries the working conventions;
PROJECT_PLAN.md carries sequencing.

---

## 1. Vision

The dashboard is a **QA environment owned by an agent**. The agent manages
everything inside a disk sandbox: takes user input (instructions, text, data,
voice), runs all data-development workflows, maintains a full RDFS instance
for testing, and **emits only to the user's source of truth (SOT)** — their
CE content and metacontent folders — through a single gated channel.

The user's window into QA is twofold:
1. **The prompt** — dialog with the agent.
2. **The data browser** (reused from cwvaServer-py) pointed at the QA store —
   the user views an artwork instance with all its fields and follows links
   (e.g. to criticisms) exactly as they would in their production CE instance.

On discovering an issue in the browser, the user turns to the prompt.

Rationale: the CE adoption barrier is the mental model (stage tree, queue
state machine, SPARQL, SHACL, ontology), not the software. The agent absorbs
the mental model; the browser makes results legible; the gate makes the
arrangement safe.

## 2. Sandbox model — single gated exit

### 2.1 Architecture

- The LLM never touches the OS. It emits structured tool calls; a Python
  **executor** performs them. Security is enforced in the executor and the
  OS, **never in prompts** — file contents the agent reads (markdown, TTL,
  user data) are a prompt-injection vector, so the system must be safe even
  if the model is fully adversarial.
- **No shell / arbitrary-exec tool, ever.** The agent's vocabulary is a
  fixed, small set of file operations (list, read, write, mkdir, move, copy,
  delete-to-trash) plus domain tools (validate, query, derive, promote…),
  each implemented in Python, deny-by-default.
- The sandbox root **is** the QA stage tree (`stage_root` in config). The
  security boundary and the application working set are the same thing.
- **Exactly one write channel out of the sandbox: the promotion tool** (§3).
  Everything else the agent does is contained.

### 2.2 Enforcement layers

**Layer 1 — path confinement in the executor (cross-platform):**
- Join request against sandbox root; canonicalize (`Path.resolve()` /
  `realpath`); containment check via `is_relative_to` on the resolved path,
  case-normalized on Windows.
- Reject (never sanitize): traversal, absolute paths, null bytes, Windows
  reserved names (CON, NUL, COM1…), trailing dots/spaces, alternate data
  streams, UNC paths, drive-relative forms, long-path prefixes.
- Symlinks forbidden inside the sandbox (create and follow). On Linux,
  prefer kernel help: `openat2(RESOLVE_BENEATH)` (5.6+) or `O_NOFOLLOW`.

**Layer 2 — OS-enforced boundary (defense in depth):**
- Executor runs as a separate least-privilege broker process.
- Linux: **Landlock** (kernel 5.13+, unprivileged) restricting the broker to
  the sandbox path. Alternatives: bwrap, systemd ReadWritePaths, container.
- Windows: dedicated low-privilege local user + NTFS ACLs granting modify on
  the sandbox only (scripted at CE install). WSL2/Docker path preferred when
  available, not required.
- Layers compose: a validation bug is contained by the OS identity; an ACL
  gap is contained by validation.

### 2.3 Operational hardening

Quotas (file size, count, ops/minute); soft delete to in-sandbox trash;
confirmation gates for bulk/destructive ops; **append-only audit log of
every tool call** (arguments + outcome) — dovetails with provenance (§8).

### 2.4 Assurance bar for release

Adversarial path corpus in CI on Linux and Windows (traversal chains,
symlink escapes, short names, ADS, reserved names, Unicode tricks, mixed
separators), plus property-based testing (Hypothesis). Pass criterion:
every case rejected at Layer 1, **and** a deliberately broken Layer 1
still cannot escape Layer 2.

## 3. Promotion lifecycle — the heart of the system

The pattern is a staging environment with a CI-style promotion gate,
applied to RDF data. The central object is the **promotion unit**.

### 3.1 Promotion unit

A manifest of everything one workflow produced (entity TTL, work records,
tag updates, queue-file moves) that promotes to SOT **atomically** — all or
nothing. Partial promotion is the failure mode that corrupts a SOT.
Generalizes the concept_agent staging-graph + atomic-promotion pattern from
"concept batch" to "any workflow's output set." The queue-directory state
machine delimits what belongs to a workflow instance.

### 3.2 Gates (in order)

1. **Parse gate** — all TTL compiles (syntactic correctness).
2. **Semantic gates** — SHACL shapes (content completeness, referential
   integrity), plus SPARQL assertion queries. These verify **conformance**.
3. **Change preview** — agent-generated diff summary per unit ("adds one
   work, modifies two criticism links, touches nothing else"). Catches the
   "agent did more than asked" class of error.
4. **User review** — via change preview initially; via the data browser once
   it lands (Phase 7). **Intent is the user's job, not the gates'** (§3.5).

### 3.3 Push channel — transport-specific state convergence

SOT deployment varies per CE user. Four supported transports:
1. **GCP bucket** — upload changed objects, delete removed ones
   (rsync-with-delete semantics).
2. **Git platform (e.g. GitHub)** — commit + push to the user's remote;
   their production pulls.
3. **Local git** — commit in the SOT repo.
4. **Plain files on disk** — write changed files, delete removed ones.

There is **no uniform transactional undo across these transports**, so the
design does not implement rollback against SOT. Instead, promotion "apply"
is **state convergence**: SOT is made to match QA's committed content state
via a transport adapter. Pushes are idempotent and full-state, computed
from the QA git diff manifest (adds / modifies / **deletes**).

Deletion is therefore part of the exit channel. Consequences: deletions are
confined to the managed content/metacontent paths, always listed explicitly
in the change preview, and (v1) require user confirmation above a small
configurable count.

### 3.4 QA-side git — system of record for history and rollback

**QA content** (mirror of SOT content/metacontent + work in progress) is a
**private git repo inside the sandbox** — invisible to the user, zero setup,
no requirement that their SOT be git-able.

**Two git repos, never conflated.** The *project repo* versions the
dashboard's own code and design documents; it is the developer's, it is
pushed to GitHub, and its history is development history. The *QA content
repo* described here is runtime machinery: the dashboard initializes it at
the QA content root inside the sandbox, its commits are promotion units, its
history is data-publication history, and it never leaves the machine or is
pushed anywhere. The two must never nest or interact — the sandbox (hence the
QA repo) lives **outside** the project tree, and `qa_git.py` operates only on
its own repo root. A QA repo nested inside the project repo, or vice versa,
is a setup error the dashboard refuses.

- Each promotion = QA commit (manifest as message) + transport push. After
  a successful push, QA HEAD ≡ SOT state.
- **Rollback** = `git revert`/reset in QA to the pre-work commit, then push
  the reverted state to SOT (may delete files there). Rollback is "restore
  known-good state and converge," never "undo in place." Coarse-grained
  only; the promotion unit is the undo granule.
- Beyond rollback, the QA git supplies: the uniform promotion audit trail
  (the only one available for bucket/plain-file SOTs); drift detection
  (§4); change preview at the file level via git diff (the isomorphic RDF
  diff remains the semantic layer on top); and crash recovery of QA
  content.
- **Binary asset policy** (images, pdf — in SOT scope, large, never
  revised only replaced; extension list in config, default images + pdf;
  **md is tracked as ordinary git content** for line-level history unless
  practice argues otherwise):
  - Binary lives at its real path in the QA content tree (true SOT
    mirror for browser, QA store, and convergence); git ignores it and
    tracks a **sidecar pointer** (`<name>.ptr`: sha256, size, timestamp)
    — the LFS pattern, hand-rolled, no filter machinery.
  - `fileops.py` is the consistency chokepoint: every write/move/delete
    of a pointer-managed file atomically updates its sidecar (all agent
    ops already funnel through it).
  - On replacement, the superseded binary moves to a content-addressed
    **attic** outside the mirrored tree (`.qa/attic/<sha256>`). The
    content tree therefore always equals desired SOT state — no
    accumulation in QA or SOT — while rollback restores the pointer via
    git and re-materializes the binary from the attic. Attic GC by
    policy (age / reachable-from-last-N-promotions).
  - Hashes double as the convergence/drift comparison key on every
    transport (stored as object metadata on GCP to avoid re-downloads).
- Git here is dashboard implementation machinery, invoked by promotion/sync
  code — it is **never an agent tool**.
- Primary assurance remains the gates + user review (§3.2); the QA git is
  the safety net behind them, not a substitute.
- **QA repo = mirrored trees + a non-converged `evidence/` area** (amended
  for TCAP, Phase 4.5). The QA repo tracks, alongside the mirrored
  content/metacontent, a top-level `evidence/` directory holding curation
  artifacts — e.g. consumed tag TTL with grounding phrases (the annotation/
  TCAP pipeline; see TCAP_README.md).
  It is versioned in the QA git for audit but **excluded from transport
  convergence**: the convergence manifest computes over the mirrored subtrees
  only, so `evidence/` never pushes to SOT. Evidence commits in the same
  promotion unit as the outcome it justifies, binding the two atomically.

### 3.5 Intent stance

Gates certify conformance (well-formed, complete per shapes, referentially
consistent). They do not certify intent (the medium field says what the user
meant). **QA does not police intent unless the user raises it.** The browser
+ prompt loop is the intent channel; the publish-then-revise loop (§5) is
the repair channel.

### 3.6 SOT layout & placement — kind-routing at composition

**SOT layout = QA mirror layout.** The QA content repo mirrors the SOT folder
structure. Which artifact belongs in which folder — work/proof TTL, branded
images, documents, vocab — is decided **at promotion-unit composition**, where
the manifest is built, and **never in the transports**. Transports are
kind-blind: they converge whatever relative paths the manifest names. The Groovy
push's sorting logic (`distributeData` / `distributeMetadata`) is **reference
material for the placement map, not code to port.**

Workflows compose in a sandbox **working area outside the mirrored tree**
(equivalent to the legacy `stage/data`); **"finish the workflow" = move each
finished artifact into the mirror at its final SOT-layout address.** A branded
image moving into the images folder picks up its `.ptr` sidecar automatically
via fileops. Convergence then has nothing to know — the knowledge lives one
layer earlier, where the manifest is built rather than where bytes are pushed.

**Layout translation is READER-SIDE, not sync-side** (settled 2026-08-12, first
forced by the shadow target). Sync writes SOT relpaths **verbatim** into the QA
root: the QA mirror adopts whatever layout its target uses (the shadow bucket is
flat — `ttl/data`, `ttl/model`, `ttl/vocab`), and nothing rewrites paths in
transit. Everything that addresses mirror content — readers (the ontology and
vocabulary loaders behind the affordance layer) and writers (promotion-unit
composition) alike — resolves through the **active target's** placement map
rather than a module-constant default. Two reasons this beats translating on
sync: (1) a translating sync makes QA paths differ from SOT paths, so drift
detection, the diff manifest, and convergence would each need the same mapping
applied consistently in both directions — the "two mechanisms disagreeing" shape
that every bug in the storage area has had; (2) `sync()` stays a byte-faithful
mirror of the target, which is what makes "SOT ≡ QA" checkable by comparing
paths directly. The cost is that the placement map becomes a **runtime value
bound to the target**, not a constant — `MIRROR_LAYOUT` in `promotion/layout.py`
is demoted to the *default target's* map. Tracked as gate item B1 in
PROJECT_PLAN Phase 4.6 §5; until it lands, `config/dashboard.rson`'s
`shadow_sot.mirror_layout` is declared and read by nothing.

The **placement map** (kind → mirror path) is a small config-adjacent constant
(`promotion/layout.py`). Consequence: the entry workflow and proof workflow 2
each end by placing into the mirror, so both are ordinary **multi-folder
promotion units** — which the unit model has handled since §3.1. The four side
effects decomposed out of the authoring tools (gdoc download, proof, image
stamp, QR generation) land here, as placements into the mirror during
composition — each a home, none a transport concern.

## 4. SOT sync, refresh, and drift

- **SOT→QA sync** is a first-class dashboard process: the transport adapter
  pulls current SOT state into the QA working tree (bucket: list/download
  by object hash or generation; git: pull; files: copy by hash manifest).
- **Drift detection**: after sync, `git status` against QA HEAD reveals
  out-of-band SOT edits (direct user changes, other publishers). The agent
  reports them; the user either **adopts** (committed as an "external
  change" commit, becoming the new baseline) or investigates first.
- **Orphan report**: SPARQL the QA store for all image/document URIs
  referenced from TTL, map to content paths, diff against the pointer set.
  Unreferenced binaries surface in the agent's summary; user-confirmed
  deletions land in an ordinary promotion unit and converge to SOT. The
  same report run against SOT listings during sync catches historical
  accumulation on the SOT side.
- **Refresh** = sync + reset of work in progress; also crash recovery.
- Rules: **sync before every workflow start**; **re-sync and compare
  immediately before every push**, aborting on unexpected drift. This
  replaces the single HEAD-stamp check — the effective stamp is
  per-transport (object generations/hashes, remote HEAD, file hash
  manifest), and the pre-push sync makes it uniform.
- In-flight workflow state survives refresh via the workflow-state file
  (§7); the agent is reconstructable from disk state at any time.
- CE v1 concurrency: single user, single workflow at a time.

## 5. Optimistic concept publication + merge/demote

**Decision: no mandatory curation gate before concepts go to SOT.** Upfront
curation is exactly the step a CE user will skip or rush; a gate routinely
waved through is false assurance plus friction. SKOS makes the common error
(published concept should have been an altLabel) cheaply reversible, and
cheap reversal beats expensive prevention.

**Merge/demote is a first-class workflow.** "X should be an altLabel of Y"
triggers: retire X as skos:Concept → attach X's label to Y as skos:altLabel
→ **rewrite every tag/annotation reference from X to Y** across affected
instances → republish all touched files as **one promotion unit**. The SHACL
referential-integrity gate verifies completeness (no dangling references).
The agent makes a one-sentence user interaction hide a multi-file rewrite.

The optional expensive path — agent review of the vocabulary for merge
candidates — exists as an explicitly invoked task, never a required step.

## 6. Duplicate-concept policy (lexical matching)

- **Metric:** normalized Levenshtein via rapidfuzz — score =
  `max(ratio, token_sort_ratio)` after normalization (lowercase, strip
  hyphens and possessives). Preserves the calibration feel of the Groovy
  Levenshtein scores (1.0 exact / ~0.59 unrelated). Lemmatized comparison is
  a deferred third signal, added only if morphological dups ("massing" vs
  "mass") prove common.
- **Threshold:** > 0.9 default, user-overridable in config.
- **Label set:** match against the union of `skos:prefLabel`, `skos:altLabel`,
  and `rdfs:label` per concept, from day one.
- **Behavior:** non-blocking. Derivation-time near-matches are reported in
  the agent's output ("'tonal massing' resembles 'tonal mass' — publish
  anyway / use existing?"); the user does hygiene or continues.
- **Hygiene ledger:** unresolved near-matches persist in a small TTL file in
  the sandbox so "show me pending concept dups" works weeks later.
- **Annotation-time remedy** (the remedy positioned with the problem): the
  concept picker runs the same matcher over its current candidates; on a
  near-synonym pair it offers the merge inline — one click launches the
  merge/demote workflow, annotation proceeds with the survivor.

## 7. Agent orchestration

- Chat loop (text; voice = commodity speech-to-text feeding the same
  channel), tool registry (every dashboard function is a tool with schema),
  and a **workflow-state file** on disk as durable memory — queue
  directories + state file are the ground truth; the agent context is
  reconstructable from disk (crash-safe, session-spanning).
- The multi-step workflows documented in the legacy dashboard notes
  (derive → curate → promote → distribute → tag → annotate) become
  agent-managed: the agent narrates state from `stageStatus`, runs
  mechanical steps, pauses at user gates.
- Tool layer designed to be exposable as an **MCP server** later (same
  schemas), making any MCP client a possible driver. Not a v1 deliverable;
  a design constraint on the tool schemas.
- Agent-led first-run setup wizard (config, stage tree, one full record →
  validate → promote cycle) is the highest-leverage onboarding feature.

## 7.1 Workflow state & open items

### Principle: compute obligations, record only dismissals

Workflow state must never drift from reality, so it is **derived, not
tracked**, wherever derivation is possible. The dashboard's workflow panel
(successor to the legacy `stageStatus` queue badges) renders results of
**standing queries** over sources the system already maintains:

- **Graph-derived obligations** — SPARQL over the QA store. Canonical example:
  works promoted to SOT with no `vad:workOnSite` assertion = the open
  updateWorkOnSite items. The pattern generalizes (works without
  interpretations, entities without images, `conceptsExtracted false`, …).
- **Filesystem-derived state** — the legacy queue badges unchanged:
  conceptQueue and processed/* population counts.
- **QA-git/audit-derived state** — uncommitted WIP; drift awaiting adoption;
  **staleness** checks (e.g. "last site scrape predates the most recent work
  promotion").

The only recorded state is the **exception**: a dismissal ("work X is
intentionally on no site — stop reporting it"). Dismissals live in the hygiene
ledger (same TTL container as concept-dup dismissals, §6). Open items =
standing-query results − dismissals.

### Standing query definitions are data, not code

Each open-item type is a definition: {id, source (sparql | fs | git | audit),
query/check, description, severity, resolving action (the registry tool or
workflow that closes it)}. Definitions load from config/content, so new item
types can be added by the user or the agent without dashboard code changes —
the same extensibility posture as the legacy `addFunctionCard`.

### One source of truth, two windows

The workflow panel and the agent's narration render the **same standing-query
results**. The agent's opening summary ("2 markdowns awaiting derivation, 3
works with no site link, scrape 12 days stale") and the panel are two views of
one computation — the prompt+browser philosophy applied to workflow state.
Open items in the panel are clickable; each fires its resolving action.

### Panel contents (three groups)

1. **Pipeline queues** — filesystem counts (legacy badges).
2. **Open obligations** — standing-query results minus dismissals, each with
   its resolving action.
3. **In-flight workflow** — the single active workflow instance (v1) and its
   pending gate, from the workflow-state file.

The workflow-state file remains confined to genuinely in-flight instances;
everything else is recomputed, preserving the law that the agent is
reconstructable from disk state.

## 7.2 Function rebuild note — updateWorkOnSite

Ports as a **rebuild**, not a port; the Groovy DOM-structure scraper is not
carried forward. Purpose unchanged: passively observe which works appear on the
external artwork sites and assert `work:<guid> vad:workOnSite <site>`, one TTL
per site. Passive observation is deliberate — observed truth over user-declared
truth; posting to sites remains outside dashboard scope.

Effect pattern: outbound **read-only HTTP** to config-listed sites (the
sanctioned network-effect class, CLAUDE law 11) + a QA write terminating in a
**promotion unit**.

**Extraction — layered, structure-free:** (1) structured metadata first —
sitemap.xml for page discovery, OpenGraph/JSON-LD per page (SEO-load-bearing,
stable across redesigns); (2) AI fallback — fetch page → cheap model extracts
`{title, image_url}` into schema-validated JSON (T0/T1 profile; stubbed until
Phase 5).

**Matching (scraped page → work GUID) — code before AI:** (1) perceptual image
hash (pHash) of site images against cached hashes of SOT originals — survives
scaling/branding; (2) title match via the shared lexical matcher (§6); (3)
below threshold on both → surfaced in the run report for one-click confirmation,
never silently guessed; (4) forward-looking convention — embed the work GUID in
image filenames/slugs to turn future matching into lookup.

**Semantics: full snapshot per run.** Regenerate each per-site TTL entirely and
promote as a unit — idempotent, convergence-friendly; the preview reads well
(appearing works are adds, vanished works are removals = takedown signal).

**Provenance:** scrape-derived triples carry `prov:` observed-by-scraper, with
model identity where the AI fallback produced the extraction. **Companion
standing queries** (§7.1): "SOT works with no workOnSite" + "scrape staleness".

## 8. Provenance

Every agent-executed action and AI-drafted record carries `prov:`
attribution including model identity, consistent with the existing
blinded-provenance discipline in the criticism pipeline. The audit log
(§2.3) and QA git history (§3.4) are the operational complements.

### 8.1 Two senses of the word, and only one of them is `prov:` (2026-10-05)

**`prov:` is this store's DATA-LINEAGE vocabulary and nothing else.** Measured
in production: 34 `prov:wasAttributedTo`, three `prov:SoftwareAgent` (the two
models and the scraper), one `prov:Person`/`prov:Agent` (`ops:user`), and two
`prov:Entity` — the scraped websites in the workonsite snapshots. All of it
answers "what produced or observed this data".

**Artwork ownership stays `vad:Provenance`** (`ttl/provenance/provenance.ttl`:
`vad:Provenance`, `vad:ArtworkOwner`, `vad:hasArtwork`, `vad:hasArtworkOwner`,
`vad:hasPrivacyRestriction`). Rick, 2026-10-05, having considered aligning it
with `https://www.w3.org/ns/prov`: "I'll stick with my current vad:Provenance
for tracking artifact ownership."

Settled for two reasons, so it is not re-opened:

1. **PROV cannot say "owned".** Confirmed against the namespace document: there
   is no ownership or title/custody-transfer property. `prov:wasAttributedTo` is
   "the ascribing of an entity to an agent" — responsibility or credit — so
   using it for ownership would assert that the collector MADE the work, which
   is false and collides with the real `foaf:maker` attribution.
2. **It would overload a vocabulary already in use here.** Typing owners as
   `prov:Person` makes `?x a prov:Person` return the curator beside the
   collectors; typing artworks as `prov:Entity` returns them beside the scraped
   websites.

What was considered and not taken: modelling the acquisition as a
`prov:Activity` with `prov:qualifiedAssociation` / `prov:hadRole`, which is
honest PROV but says "an activity involving this agent" rather than "this agent
owned it"; and CIDOC CRM / Linked Art (`E8 Acquisition`, `P22 transferred title
to`), which is the cultural-heritage standard and the right target IF
interoperating with the art world ever becomes a goal. Both remain available
— they would sit alongside `prov:` rather than replacing it, because the two
senses are about different things.

## 9. AI service layer — provider-agnostic, cost-competitive

- **One module owns every AI call.** Providers: Anthropic API (development)
  + OpenAI-compatible endpoint (OpenRouter et al. for testing/CE users).
  Two wire formats cover the field; LiteLLM acceptable as the shim.
- **Task profiles** in config (RSON): each task (sparql-generation, tag-proposal,
  violation-explanation, diff-summary, form-drafting…) maps to model tier,
  token budget, and output schema. Provider/model swaps are config edits.
- **Model-defensive prompting:** every structured output is schema-validated
  with retry/repair; budget ~20–30% overhead per AI feature for cross-model
  robustness. That is the true cost of agnosticism.
- **Context assembly is its own layer:** trimmed task-relevant ontology/SKOS
  subsets as the baseline (works on every provider); provider-native prompt
  caching as an optimization where available (semantics vary — do not
  depend on it).
- **Cost levers:** small-model-first routing (classification, extraction,
  summarization on cheap tiers; frontier models reserved for SPARQL
  generation and curation reasoning); batch APIs (~50% discount) for the
  conceptQueue pipeline, which is already batch-shaped; validation is code,
  not tokens — the QA gates cost nothing per run.

### 9.1 Routing policy (Phase 5)

- Task profiles declare **capability floors** (tiers), never model names.
  Suggested tiers: T0 extraction/classification; T1 summarization and
  violation-translation; T2 structured generation (SPARQL, form drafting);
  T3 orchestration and curation reasoning.
- A **provider catalog** (config) maps tiers → concrete models with current
  prices; price changes are catalog edits (optionally refreshed from published
  pricing), never profile or code changes. Catalog review on a cadence (e.g.
  monthly); no live spot arbitrage in v1.
- **Admission by scenario:** models enter tiers empirically, by passing the
  tier's scenario suite (the Phase 4.5/5 corpus) — never by spec sheet.
- **Escalation ladder:** floor tier first; a *validated* failure (schema repair
  exhausted, gate rejection) escalates one tier, capped N attempts. Validation
  is code and free, so cheap-model failures are caught, not shipped. Escalation
  rate per model is the demotion signal.
- **Metering:** model identity, token usage, and computed cost on every call,
  tagged by profile/tier/model in the audit stream (provenance §8 and cost
  attribution share plumbing). Per-episode cost report.
- The router picks the **cheapest model satisfying the floor** for a task.
  Three layers: profiles → floors (stable); catalog → tier/model/price
  (volatile, config); router → selection.

## 10. AI feature backlog (post-fundamentals, priority order)

1. **NL → SPARQL** in the console (schema-aware; show generated query beside
   results; "explain results" follow-up). The single largest adoption lever.
2. **Form drafting** for record entry (image + one sentence → pre-filled
   record; vision extraction; vocabulary-constrained concept suggestions;
   human curates rather than authors).
3. **Tag curation UI** over the existing concept-agent capabilities
   (evidence spans, confidence sort, review-only-the-uncertain).
4. **SHACL violation translation** + offered patches; draft shapes from
   example instances.
5. **Diff/sync/report narration** (graph diffs, directory comparisons,
   stats anomaly summaries).
6. Keep-notes account-mismatch sniffing; alt-text generation; certificate
   narrative drafting.
7. **Video description from the file itself** (Rick, 2026-09-16): sample frames
   from the MP4 and draft `schema:description` for the `VideoObject`, with the
   record as context — its title, class, the artist profile, the still image
   beside it. A turntable render of a sculpture is a handful of near-identical
   frames, so sampling is cheap and the description is largely determined;
   Rick's bound is explicit — **short clips, not feature-length movies** — which
   is what keeps sampling honest rather than a summarisation problem in
   disguise.
   Three constraints it inherits rather than invents: frames come out
   trusted-side by ffmpeg exactly as the duration already does (the confined
   worker has no exec, law 2), the draft reaches the record through a registry
   tool as ordinary data, and the user edits it — which is why **editing the
   video description (§14.7) is the prerequisite, not the follow-up**. A
   generated description nobody can correct is worse than none.
   Note for whoever builds it: `ai_service` is not yet in law 11's sanctioned
   network-effect class, because it does not exist. It becomes the fifth member
   the day it does, and the class is enumerated in CLAUDE.md for exactly this
   reason.

## 11. Testing doctrine

- Sandbox: adversarial corpus + property-based tests, both OSes (§2.4).
- Promotion: unit tests over fixture targets for all four transports
  (local dirs, fake bucket, throwaway git repos); assert convergence with
  deletions, pre-push drift-abort, and QA revert→converge round-trip.
- AI outputs: **assert structure and semantics, never exact strings**
  (SPARQL validity + expected bindings; tags ∈ vocabulary; TTL parses and
  passes SHACL). Recorded-response doubles are provider-neutral.
- Workflows: end-to-end tests scripting full pipelines against a fixture
  stage tree with mocked AI and fake transport targets.

## 12. Relationship to sibling projects

- **cwvaServer-py**: hosts `cwva_core` (config, RDF utilities, Exec, GUID/
  clock providers) and the data browser this project reuses. Core changes
  happen upstream with production tests green (see cwvaFunction-py rules;
  same discipline applies here).
- **cwvaFunction-py**: the faithful port of the legacy function server.
  This project is the **redesign**, not a port; it shares cwva_core and
  ideas, not the frozen URL contract. (As of Phase 4.5, cwvaFunction-py is
  absorbed into the dashboard and shelved — see CLAUDE.md.)

## 13. Identity & namespaces

Data-model doctrine for CE deployment. (Cross-ref from Phase 11 onboarding.)

### 13.1 Doctrine

**URIs are identifiers first, addresses second.** A work URI is a permanent
name; whether and where it dereferences is a serving concern. Most namespace
pain comes from conflating the two.

- **Cool URIs don't change.** Renaming identifiers is the worst operation in
  linked data: every TTL, cross-reference, and criticism tag — and the physical
  world (QR codes on printed labels encode these URIs; a namespace change
  orphans every label already printed). The identity decision is made **once, at
  first-run setup, with tradeoffs stated** (Phase 11 wizard).
- **Shared vocabulary, sovereign instance namespaces.** The commons/sovereign
  split (§13.3) is what lets independent catalogs stay mutually intelligible —
  the precondition for the federated-catalog vision.
- **Data speaks domain; servers speak host.** Canonical URIs live in the data,
  always. Host mapping is presentation-only (§13.4).

### 13.2 The setup-time identity decision (Phase 11 wizard)

Three honest options for the deployer's instance namespace (`work:` + siblings):
(1) **own domain** (preferred) — `work: <http://theirDomain.art/work/>`, one
field; (2) **communal** — mint under `http://visualartsdna.org/work/`, GUID
uniqueness makes it collision-safe, tradeoffs stated (identifiers in a namespace
they don't control; later move is a rebase, §13.6); (3) **defer** — communal
now, migrate when serious, legitimized by the rebase workflow existing.

### 13.3 The commons/sovereign split (firm rule)

| Namespace | Status | Deployer may rename? |
|---|---|---|
| `work:` (instances) | **Sovereign** — the deployer's | Yes — the identity decision (§13.2) |
| `vad:` (ontology, cwva.ttl) | **Commons** — shared semantics | **Never** |
| `the:` (thesaurus + entity.ttl) | **Commons** — shared semantics | **Never** (extend instead, §13.5) |

TCAP annotations, the navigation query, SHACL shapes, the topic scheme, and
cross-catalog intelligibility are all keyed to `vad:`/`the:` URIs. Renaming them
forks the ontology unintentionally — nothing validates, nothing federates.
Rewriting `the:`/`vad:` prologs is **not needed, and actively harmful**.

### 13.4 Host mapping (presentation-only)

`host` = where the server answers (e.g. `http://[IP:port]`); `domain` = what the
data says (e.g. `http://theirDomain.art`). The domain→host rewrite happens
**only in the serving path** (cwvaServer-py responses; the QA browser) and is
**never persisted into data** (persisting creates two spellings of one identity
and breaks every comparison). Both cwvaServer-py and the QA browser read the same
host/domain pair from config.

### 13.4a `domain` is CONFIGURED on the dashboard, never derived (settled 2026-09-09)

The dashboard needs the deployer's `domain` to recognise a work URI — that is
what updateWorkOnSite (§7.2) matches a site's catalog links against. The same
fact is declared in cwvaServer-py's own config, and nothing reconciles the two.

Two ways to close that were considered and **rejected, both for the same
reason**: they assume the two components sit on one machine.

- *Detect* — compare the dashboard's `domain` against cwvaServer-py's config at
  startup and warn on mismatch.
- *Derive* — infer `work:` from the store, since every record's subject URI
  already declares it.

Rick's deployment is the general case, not an exception: **content management
runs on a workstation and the production instance runs on GCP.** The dashboard
cannot read the server's config, and a QA tree may legitimately be a partial or
stale copy, so neither cross-check is available where it would be needed.

So: **the deployer configures the dashboard**, and `domain`/`host` in
`config/dashboard.rson` are authoritative for it. **There is no default domain
in code** — `config.domain()`, `build_default_registry()` and `create_app()` all
refuse rather than assume. A fallback was one deployment's identity reachable by
omission, and the failure it produces is the worst kind: records minted under
the wrong sovereign `work:` namespace are perfectly valid RDF, so nothing
complains, and the only correction is a namespace rebase (§13.6). Tests declare
their own identity (`tests/conftest.py`). The cost is a
misconfiguration that no component can detect for another — which is why the
mitigation is *legibility*, not detection: when a site is read successfully and
declares nothing, the UX names the base it was looking for, so a wrong `domain`
reads as a wrong domain rather than as an empty site.

### 13.4b Deployment settings vs. curation: config vs. data (settled 2026-09-10)

§13.4a settles that `domain` is configured on the dashboard. The converse case
is **which concept schemes the annotation picker offers** — and that one belongs
in the DATA, as an `the:Operation` record carrying both `the:topic the:Thesaurus`
and `the:topic the:Annotation`, whose `the:tag` values name the schemes.

The distinction is not where a value is easiest to put, it is what kind of thing
it is:

| | `domain`, `sites`, quotas | which schemes to annotate with |
|---|---|---|
| kind | deployment identity/wiring | **curation** |
| who decides | whoever installs | whoever curates the vocabulary |
| must travel between machines | no — each install has its own | **yes** — same answer on workstation and host |
| edited how | a text file, by hand | the Entity form, like any other record |
| reaches SOT | never | through the gated exit, like any record |

Curation in `dashboard.rson` would strand the choice on one machine (the same
co-location problem §13.4a hits from the other direction) and hide it from the
tooling that exists to edit records.

**The marker is a topic PAIR, not a purpose-built concept.** A concept like
`the:annotationSchemes` would appear as a checkbox on the Entity form and mean
nothing to anyone filling one in. `the:Thesaurus` and `the:Annotation` are both
ordinary topics; carrying BOTH is what means "dashboard / annotation". Six
Operations in the store carry `the:Thesaurus` alone, so the pair discriminates.

Semantics are chosen so the record can only narrow, never break: **no record →
no filter** (a fresh deployment needs no setup, and absence cannot silently
empty the picker); **several records → the union** of their tags, with the page
naming which contributed; **a tag that is not a `skos:ConceptScheme` is ignored
and reported**, since `the:tag` is general-purpose.

### 13.4c Model/vocabulary divergence: publish to both, don't protect (2026-09-11)

Shadow and production can differ on a model or vocabulary path in three ways:
production ahead (**sync resolves it**), shadow ahead (**the dashboard's own
modeling, which must not be lost**), or both diverged (**a merge**).

`shadow_sot.qa_only` exists to hold a path deliberately ahead of production, and
it is **deliberately empty**. The policy is to publish a model or vocabulary
change to *both* places, at the cost of updating two stores — which is cheap,
needs no configuration, and no documentation beyond this note.

**The "shadow ahead" window is not necessarily short.** A model change is
evaluated in QA before it is committed to production, and that evaluation takes
as long as it takes: `schemaSupplement.ttl` carried the RDF Digital video field
label from 2026-09-04 and was published upstream on 2026-09-11, a week later.
The window is a deliberate soak, not a lag to be minimised — which is exactly
why the seed-time check below is load-bearing rather than a nicety. Protecting
a path instead stops production changes flowing to the shadow and hands the
reconciliation back to a human, which is the merge the policy exists to avoid.

The accepted exposure: a seed run *during* that window — after editing the
shadow, before publishing upstream — overwrites the shadow copy, and
convergence is adds-only so the previous content is gone. Over a week-long soak
that is a real chance, not a theoretical one.
`scripts/verify_shadow.py --compare` reports the divergence, so the discipline
is to check before seeding rather than assume. **Never infer "was in step" from
"is identical now"** — a shadow file older than its production twin is equally
consistent with a soak that was just published.

`qa_only` is the escape hatch for a change that genuinely cannot go upstream.
Reach for it then, not before.

### 13.5 Local vocabulary: extension schemes, not renames

A deployer's own concepts (their paint inventory, local techniques/topics) go in
a **local extension scheme** minted under their domain (e.g.
`<http://theirDomain.art/thesaurus/>` with its own `skos:ConceptScheme`). Local
concepts link into the shared thesaurus via `skos:broader`/`skos:inScheme` and
inherit TCAP typing from shared ancestors (the navigation algorithm works
unchanged). The concept pipeline mints derived concepts into the **extension
scheme**, never the shared thesaurus; the shared thesaurus updates only via CWVA
releases. (The pipeline's scheme allow-list therefore includes the deployer's
extension scheme for CE; the current hardcoded watercolor list stays for the
faithful-first port per the deferral already recorded.)

### 13.6 Namespace rebase (deferred workflow; do not build now)

Moving a catalog from communal to an own domain is supported by existing
machinery: (1) full-snapshot **graph-level** rewrite in QA — walk triples with
rdflib and rebind URIRefs old-ns→new-ns; **never textual substitution** (full
URIs appear outside prologs: `schema:image` objects, qrcode URLs, workOnSite
targets); (2) verification gates (triple-count preserved, only the intended
namespace touched, all gates pass); (3) one promotion unit, QA git holds the
before-state for rollback; (4) out-of-band consequences surfaced as a checklist,
not automated (reprint QR labels; external inbound links; optional redirect on
the old domain). This workflow is what makes the communal on-ramp honest.

### 13.7 Implementation by component

- **Dashboard (Phase 4.5, now):** record tools derive `work:` (and the image
  base) from `domain` in config; `vad:`/`the:` are fixed commons. Default
  `domain = http://visualartsdna.org` — no behavior change for the current
  deployment.
- **cwvaServer-py:** the host/domain seam in the serving path (no change for
  current production).
- **QA browser (Phase 7):** consumes the same host/domain config.
- **Setup wizard (Phase 11):** presents §13.2, writes config, scaffolds the
  extension scheme.
- **Rebase workflow (post-v1):** §13.6 on existing promotion machinery.

---

## 14. Profile-driven entry forms (Rick, 2026-09-14)

**The problem.** RDF Entry and RDF Digital are tailored to one artist's work —
watercolour paper, Blender compositions, a fixed field order. That is a release
blocker for anyone else, and it cannot be fixed by adding config knobs to two
hand-written forms. Rick's proposal (`dashboardEntryFormApproach.txt`): the
**artist profile carries a template**, the dashboard builds the form from it,
and the cards in Content Management become the profiles' own labels ("Watercolor
materials profile") rather than `RDF Entry` / `RDF Digital`.

### 14.1 Why it works — two of three layers already do this

- `ux/forms.py` chooses a widget from a field's **declared affordance**
  (`x-vocabulary`, `x-entity-ref`, `x-file-ref` + `x-file-kind`, `enum`,
  `type: array`), never from the field's name. Captions and hints already come
  from the ontology at render time.
- The submit pipeline derives its file handling from the schema: `file_fields`
  is computed from `x-file-ref`, and collision checking, ingest, QR generation,
  markdown `[id=]` stamping, the duration probe and branding all loop over it.
  Naming `image` literally is a bug this project already fixed once, when a
  `.glb` passed through unchecked.

### 14.2 What a list of predicates cannot supply — the property map

A template says *which* properties and in what order. It cannot say **how a
value becomes triples**, and that is where the per-form code actually lives.
`record_tools.py` writes eight distinct shapes:

| shape | example |
|---|---|
| literal | `rdfs:label`, `schema:description`, `skos:note` |
| typed literal | dates → `xs:date` |
| file IRI (base + filename) | `schema:image`, `vad:image3d` |
| vocabulary IRI | `vad:hasPaper` → `the:…` |
| record IRI | `vad:hasArtistProfile` → `work:…` |
| **blank-node quantity** | `schema:height` + unit → `QuantitativeValue`(`unitCode`, float `value`, label `"12 inches"`) |
| derived, never typed | `vad:qrcode`, `schema:identifier` |
| **composite from one filename** | `schema:video` → thumbnail, name, contentUrl, uploadDate, ffprobe duration |

`tools/property_map.py` is that table: one row per property, carrying its form
field name, its JSON-schema fragment (affordance included) and its shape. **A
template selects from the map; it cannot be the map.** That is also the law-3
answer — a profile is stored data, stored data is hostile, and a template naming
an unknown property is refused rather than improvised into a widget.

**The schema is generated from the same template as the form.** Enforcement
lives in `validate_args`; generate the form from a template and hand-write the
schema and the offered set and the enforced set are two things again. So
`record.new_work` / `new_digital` collapse into one tool taking a profile plus
values.

### 14.3 Ordering: per-field blank nodes, not a comma list

`vad:templateFields a, b, c` in Turtle is **three unordered triples**. RDF gives
no order to repeated predicates, so field order would be whatever the parser
returns — unstable across serializations. A parallel `vad:required true, false,
…` list is worse: positional correspondence between two unordered sets survives
nothing. The template therefore carries one blank node per field, which also
gives `required` and `dependsOn` a home:

```turtle
vad:template [
    rdfs:label "Input Form Spec" ;
    vad:templateType vad:Watercolor ;
    vad:field [ vad:property rdfs:label     ; vad:order 3 ; vad:required true ] ;
    vad:field [ vad:property vad:background ; vad:order 6 ; vad:dependsOn vad:image3d ] ;
] .
```

### 14.4 Settled decisions

1. **`vad:templateType` is the picker's DEFAULT, not its only value**, and the
   picker offers the subclasses of that type's **immediate parent** — so a
   watercolour profile can still record the mixed-media piece the work turned
   into, without opening onto the whole ontology. `picker_root()` reads the
   parent from the model; this replaces the per-form `type_root` in
   `entry_forms` config.
2. **Everything is required**, until a form builder exists to offer a checkbox —
   *except* where a property only applies when another is filled in.
   `ops:dependsOn` carries that rule in the template. A flat required-flag
   cannot express it, and it is checked where both values are in hand rather
   than in the JSON schema, which has no "required if".
   **Put `ops:dependsOn` on BOTH fields, each naming the other, and the rule is
   mutual** (Rick, 2026-09-16): neither is demanded alone, and filling in either
   one makes the other required. That is what a 3D object and its background
   actually are to each other, and it needs no new construct — only that neither
   side is also marked unconditionally required, which would make its partner's
   dependency inert.
3. **Cardinality comes from the property map, not the template.** Repeated
   triples, *not* an `rdf:List`: order is not meaningful for tags or images, and
   a list would make Edit Record rebuild cells to change one member.
4. **Units come from the profile's `vad:measurementSystem`**, so `units`
   disappears as a field — the one field this approach removes.
5. **A profile must be coherent before it is saved**: a SHACL shape over
   `vad:ArtistProfile` (one artist, a resolvable `templateType`, known
   properties, unique orders), enforced at save, and the template failing at
   **build** time with a reason rather than rendering half a form.

### 14.5 Branding follows from the artist record

`vad:brand` on the artist (reached through the profile) replaces the signature
picker: brand if the artist declares a brand, otherwise don't. It does **not**
remove the other two rules — only files a save copied in are stamped, and the
review reports what happened — because branding twice is still branding twice.

### 14.6 Status

`tools/property_map.py` exists and **both entry forms are proven against their
hand-written tools** (`tests/tools/test_property_map_proof.py`): the same fields
with the same affordances, the same enforced set, and — compared isomorphically
against the TTL `record.new_work` / `record.new_digital` actually write — the
same triples, the `schema:video` VideoObject included. Two differences are
deliberate and asserted: `units` is gone, and `location`/`note` become required
per decision 2.

The composite shape delegates to `_add_video` rather than restating it: a second
copy of a shape is a second thing to keep in step, and this one derives four
properties from the filename and the day.

**The reader and the shapes exist** (`profiles.py`,
`config/shapes/artist_profile.ttl`, 2026-09-16) and read Rick's four real
profiles: label, artist, brand, unit code and an ordered, validated template.
Reading IS validating — SHACL for structure, the property map for vocabulary,
and two checks SHACL cannot make (two fields at one position; a dependency on a
property the template does not carry). `list_profiles` returns the broken ones
*with reasons* rather than omitting them, because a card that silently fails to
appear looks exactly like a profile nobody created.

The shapes live in `config/`, not in the SOT beside the ontology: the ontology
says what the art world is and belongs to the deployment, while these say what
the **dashboard** requires in order to build a form at all. `shapes_dir` in
config points elsewhere for a deployment adding its own.

**The promotion SHACL gate is armed from the same shapes (2026-09-16).** It had
been written, tested and passed `None` from `driver.py` — the only place that
runs it — since Phase 4: a gate nobody ran, and "gates passed" meaning "no gates
ran". `config.load_shapes` returns **None** rather than an empty graph for an
empty directory, because a SHACL gate with no shapes conforms to everything and
would read as armed. The gate sees one promotion unit, so the whole-store check
is `scripts/gate_baseline.py`, which now runs SHACL alongside the asset and
vocabulary gates.

**The tools and the cards exist (2026-09-16).** `tools/profile_tools.py`
generates one registry tool per profile — `record.new.<guid>`, named by GUID
because a label is the card's text and may be edited — and the hub's Content
cards are one per profile, `Watercolor materials profile` rather than `RDF
Entry`. A profile becomes an entry in the SAME form table as the three
hand-written ones, so the submit route's whole pipeline (collision check,
ingest, QR, markdown stamp, duration probe, branding, review stop) applies with
no new code: it was already derived from the schema.

Deliberately **one tool per profile, not one `record.new(profile, values)`**. A
single generic tool could only declare `values` as an open object, enforcing
nothing, leaving the rules to a handler the agent does not go through — and a
rule only the form knows is a rule the agent does not have.

`RDF Entry` / `RDF Digital` / `RDF Entity` keep their routes but lose their
cards, per Rick's "the names go away"; a deployment with no profiles falls back
to offering them, since an empty Content tab is worse than the forms that have
always been there. A profile that cannot build a form gets a **dead card with
its reason**.

**`vad:brand` drives branding on a profile form (2026-09-16).** The profile
names the artist, the artist declares a brand or does not, and that settles it —
so the form shows no signature picker at all. An artist who declares none gets
no stamp; absence is a decision. The hand-written forms keep the picker, because
they do not know whose work it is until the profile field is answered. The
`image.brand` tool's enum is now the union of configured `sites` and the brands
artists declare: a tool whose enum came only from `sites` would refuse the very
value the dashboard was about to send.

### 14.8 The housekeeping set

`schema:identifier`, `vad:qrcode` and `vad:hasArtistProfile` are **mandatory
housekeeping** (Rick, 2026-09-16): "part of a healthy record… All records have
these fields in the TTL… The user doesn't need to see them and shouldn't have
the display or not decision to make."

So the dashboard **supplies** all three, server-side, and no generated form shows
any of them. A template may list them — Rick's four do — and it changes nothing;
omitting them changes nothing either, so a profile written by hand cannot produce
an unresolvable record by forgetting. They are written from what the caller
already knows: the minted GUID, the QR URL derived from it, and the profile whose
card the form belongs to.

**Supplied, not hidden.** An earlier cut carried `vad:hasArtistProfile` as a
hidden input, which is a field the browser posts back and therefore a field the
browser can change — for the record's own provenance. The generated schema does
not declare it at all now, so a crafted POST carrying one is **refused** by
`additionalProperties: false` rather than ignored.

`ops:display` was proposed and **withdrawn** by Rick in the same breath, and the
reason is worth keeping: display is not a per-profile choice if the set is
mandatory. A flag would have invited profiles to disagree about something that
has one right answer.

What a template must still say for itself is `rdf:type` and `rdfs:label` — the
class of thing being made and what to call it. `ops:templateType` gives the type
a default, but nothing can invent a work's name.

`units` is the fourth thing a generated form does not ask, for a different
reason: the profile's `vad:measurementSystem` supplies it, and the measurement
fields say which unit instead ("The height of the work in inches") — appended to
the ontology's own comment rather than replacing it, exactly as the date format
is.

### 14.8b OPEN: the builder cannot express a dependency (2026-09-17)

Rick built a template with `vad:image3d` and no `vad:background`, which the
mutual-dependency decision (§14.4) says should not be possible — a 3D object is
displayed against a background, and each requires the other.

Nothing is broken; the rule simply never fires. The builder writes
`ops:required true` on every ticked field and **no `ops:dependsOn` at all**, so
a hand-written profile can state the pair and a built one cannot. With
`vad:background` absent from the template entirely there is no field for the
dependency to guard.

Left as it is for now, at Rick's word, and recorded rather than fixed quietly.
Three ways out, for whoever takes it:

1. **Pairs, like the locked minimum.** Ticking one of a known pair ticks the
   other and writes `ops:dependsOn` both ways. Cheapest, and it reuses a
   mechanism the builder already has; it hard-codes which properties pair.
2. **A dependency column** in the builder. Fully general, and asks an artist to
   think about a relationship the ontology arguably already knows.
3. **Refuse at save**, the way a missing `rdf:type` is refused: a template
   containing one of a pair must contain the other. Says nothing about ORDER or
   about who guards whom, so it is the smallest rule that closes the hole.

The question underneath is whether pairing belongs in the profile at all, or in
the model — `vad:background` has a domain and a range, and "these two travel
together" is the kind of thing SHACL says well.

### 14.9 The bootstrap (2026-09-17)

Two forms are hand-written and always will be: **New artist** and **New artist
profile**. Generation cannot reach them, because a new deployment's first act is
creating the profile everything else is generated from.

The profile form is also the **form builder** Rick asked for — "a simple form
builder with a list of the properties available to select from to populate the
template and a means of ordering". A tick and a position per property, which is
the shape of `ops:field [ops:property … ; ops:order …]`, so the widget and the
record it writes have the same structure and there is no translation layer to
get wrong. Orders prefill ten apart, so inserting a field later needs no
renumbering. The properties offered are derived from the property map; adding
one there makes it available to every new profile.

**The browser's minimum is locked on** (Rick, 2026-09-17): `rdfs:label`,
`schema:description`, `schema:dateCreated`, `schema:datePublished`,
`schema:image` and `rdf:type` are the properties cwva-py's works browser needs
in order to display a record at all, so the builder ticks them and disables the
tick. Their ORDER is still the artist's — the requirement is that the property
is there, not where it sits. Everything else follows alphabetically from 70.

Locking `rdf:type` closed a real gap rather than tidying a list: a template
without it built a perfectly good profile whose every record then failed at
creation, because `graph_from_template` refuses a template that cannot say what
it makes. The failure was as far as possible from the mistake. It is refused at
profile-creation time now as well, since the locked ticks stop the form but not
a crafted POST.

**Properties are described, not named.** The first cut listed `height —
schema:height`, which tells an RDF-literate reader what they already know and
everyone else nothing; "the user typically is not RDF literate". Each row now
reads `height, the height of the work` — the property's own `rdfs:label` and
`rdfs:comment`, from the model as usual, with the field name (underscores opened
out) standing in where the model is silent. One consequence worth expecting: the
model labels `schema:dateCreated` **"created date"**, where Rick's note called it
"completed date". The model wins, and changing it is a model edit.

Three decisions worth keeping:

- **An artist comes first, and the dashboard says so.** Asking for a profile
  with no artist in the store answers 409 with a link, rather than rendering a
  form whose picker is empty — an empty picker reads as a bug, and the remedy is
  one click.
- **A bootstrap record takes effect at once.** Both forms re-read artists and
  profiles and rebuild the registry on submit, so a new artist is in the next
  picker and a new profile is a clickable card immediately — while the record is
  still in QA awaiting review. The review stop governs what reaches the SOT, not
  what the dashboard can see in its own store.
- **The artist picker is an `enum` with labels, NOT an `x-entity-ref`.** The
  referents table is shared with the vocabulary gate, and that gate matches a
  type exactly — so a `vad:Painter` would fail a `vad:VisualArtist` condition
  and every profile would be reported as referencing a non-artist. The enum
  keeps offered == enforced without claiming a guarantee the gate cannot make.

Two things the first QA pass corrected (Rick, 2026-09-17). An artist picker
showed **URIs instead of names**: the field carries an `enum` (what
`validate_args` enforces) alongside labelled options (how a person reads it),
and the renderer preferred the enum — the enforced set displayed instead of the
offered one, which is the same set said unhelpfully. And the builder's order
column was **a column of unexplained numbers**; it has a header and a sentence
now.

Rick also asked for the profile form's `description` caption to be reworded,
then withdrew it on learning the words are the ontology's — `schema:description`
says "A description of a work", which is the wrong subject on a profile form and
exactly right on the three work forms that share it. **The fix belongs in the
model, not in an override**, and leaving it there keeps one rule: the form says
what the model says.

**The shapes are parsed before the worker forks** (`warm_shapes()`). Reading
profiles is part of building the registry, the registry is rebuilt inside the
confined worker, and the worker cannot see `config/` — so a save of a new artist
died with `PermissionError: … artist_profile.ttl` (2026-09-17). The parsed graph
crosses the boundary as inherited memory, which is why the warming is an
explicit startup step rather than a lazy read: a deployment with no profiles yet
would otherwise fork cold and fail the first time one appeared.

**The cards are read from DISK on every hub render**, not from app state.
State was refreshed only when a bootstrap record was written, so a profile
trashed at the review stop (Edit form) left its card standing — and clicking it
minted records citing a profile that was no longer there. The read is the same
cheap candidate scan `load_from_dir` is built for, and the hub is not polled.
The converse also holds now: a profile that appears — synced down, or written
while the dashboard runs — gets a card, and the first request for its form
rebuilds the registry once rather than answering 404 for a card the hub is
showing.

**A profile that exists only in QA says so on its card** ("draft — not
distributed yet"). It works like any other, and it is also the one a refresh, a
discard or an Edit form takes away: Rick lost one that way and asked the right
question, which was not about the record but about the card that had been his
route to the form (2026-09-17). Whether a profile is distributed is a question
about the FILE it came from, so `Profile.source` records it and `QAGit.
uncommitted_paths()` answers it — `git status --porcelain` alone collapses an
untracked directory to `content/`, which is a summary where a list was needed.

A profile's form spec is resolved **when asked**, not built once at startup: a
profile created through the bootstrap form must be usable immediately, and a
table fixed at startup gave the new card a 404. The cache is dropped whenever
profiles are re-read, so an edited template is never served from the shape it
used to have.

### 14.7 Edit Record consults the property map (fixed 2026-09-16)

Edit Record classifies a field from **the shape of the data**, not from the
property map, and a `schema:video` node carries an `rdfs:label` — so it lands in
the labelled-blank-node branch and renders as a one-line text box reading
`Last Supper Orbit`. Two consequences, both measured 2026-09-14:

- **The video file cannot be changed.** The filename lives in
  `schema:contentUrl`, which that field never shows.
- **Editing the label leaves `schema:name` stale.** `_rebuild_bnode` copies
  every property it did not derive, so the node ends up labelled one thing and
  named another.

**Done.** A predicate whose property-map shape is composite now renders as a
**file picker over the drop folder**, like any other file reference, and a save
rebuilds the whole node from the new filename:

| recomputed, because it describes the file | carried over, because the user said it |
|---|---|
| `rdfs:label`, `schema:name` (together — that was the defect) | `schema:description` |
| `schema:thumbnailUrl`, `schema:contentUrl` | `schema:uploadDate` — when this work's video entered the record, not when the file was last swapped |

**A video with no typed description gets a derived one** (Rick, 2026-09-16:
"something relatively generic, I'm more concerned about the video object
metadata being missing than not being specific enough"). It states what the
record already knows — `Video of the Blender Composition "Last Supper". Running
time 34 seconds.` — and claims nothing about the footage, because claiming
would need the file. A typed description always wins; derivation fills a hole
and never argues. It applies on every path that builds the node: both entry
forms, the template, and Edit Record when a replaced file finds the node had no
description.

Only the duration shapes the ffprobe path actually emits are parsed, and an
unreadable one is left out rather than reported: a description is not the place
to discover that a duration was malformed.

**The video's own `schema:description` is editable as of 2026-09-29** (see §14.14), and
that is a deferral rather than an oversight (Rick, 2026-09-16: "in a later phase
editing the video description will become necessary, but this is good for now").
The whole node is one field, so the only text on offer is the filename; the
description survives a file swap untouched. Making it editable means the
composite rendering a small group of fields rather than one — the file, plus
whatever the shape marks as the user's to say — which is the shape of the
problem for `ops:template` to express later.

The **duration is re-read, never carried over**: a player told the wrong length
is a defect the record vouches for. It is probed trusted-side and passed to the
tool as data (`derived={predicate: {duration}}`), the same split as the entry
route, because a registry tool cannot exec (law 2). An unchanged video keeps its
own duration, so a save for an unrelated reason disturbs nothing — which is also
what happens on a machine with no ffmpeg.

This is the first thing the property map buys outside the writers, and the
pattern generalises: any future composite shape becomes editable by being in the
map, with no further editor changes. Old records stay openable: Edit Record is
file-based and predicate-agnostic, which is what "editable but not structurally
changed" needs.

### 14.10 Editing an artist and a profile (Rick, 2026-09-19)

Both bootstrap records need editors. The artist is straightforward; the profile
is not, and the reason is worth stating before the work starts.

**Scope for now: minimal impact on existing data.** Rick: "finish the dashboard
with minimal impact to existing data, gain some experience and consider a phase
two as needed." So the decisions below are deliberately conservative, and the
migrations they imply are noted, not performed.

#### The artist association is READ-ONLY on the profile form

A work reaches its artist only by joining through its profile
(`work → vad:hasArtistProfile → profile → vad:artist → artist`). Changing a
profile's artist therefore re-attributes **every work ever made under it** —
187 works for the Watercolor profile, nearly all already converged to the SOT.
Worse, the images those records cite are already stamped with the old artist's
`vad:brand`: the record would end up disagreeing with the pixels.

So the profile editor shows the artist as a read-only label. Moving a profile to
a different artist means creating a new profile, which is the honest operation —
the old works were made under the old one.

**The structural fix, deferred.** Write `vad:artist` onto each WORK at entry, as
housekeeping beside `schema:identifier`, `vad:qrcode` and `vad:hasArtistProfile`
(§14.8). Attribution then belongs to the record instead of to a join through a
mutable document, the profile's artist becomes a default for new records, and
editing it becomes forward-only like everything else on that form. The store
already half-does this: **35 works carry `vad:artist` directly** alongside their
profile reference, and 184 do not. Back-filling the 184 is deterministic
(work → profile → artist) and would go through the ordinary review stop. Phase
two, with a "Duplicate this profile for another artist" action as its natural
companion: same template, new GUID, old works untouched.

#### The artist's NAME is read-only too (2026-09-19)

Same reason, one level down. The name identifies the persona: every work ever
made under that artist is shown under it — on the site, on a certificate, in a
registry printout — and the artist's `vad:brand` is already burned into the
pixels of those works' images. Renaming is a retroactive re-attribution wearing
the clothes of a typo fix.

Enforced in the SCHEMA, not on the form. `record.edit_artist` has no `name`
argument at all, so a stale tab or a hand-made POST cannot supply one; the page
shows the name with the reason it is fixed, because a field that simply vanishes
reads as a field the system forgot.

To correct a new artist's name: discard the draft and create it again. Once it
has been distributed, it is a fact of the record. Rick: "the truly desperate can
always edit TTL from the SOT, but we don't support that, or dealing with its
implications."

#### Template edits apply going forward, and that is free

Nothing validates an existing work against its profile's template — the gates
check parse, SHACL against `config/shapes/`, SPARQL assertions and referential
integrity, none of which consults `ops:template`. So a template edit changes the
FORM and nothing else, which is the required behaviour.

**The hazard to remember**: if a gate is ever added that checks a work against
its profile's template, it must check against the template **as of entry**, and
nothing currently records which version of a template a record was made under.

#### A profile editor must PRESERVE what its form does not own

This is the real work, and it is not the widget. The builder owns
`ops:property`, `ops:order` and `ops:required`. The store's profiles carry more:

- **`ops:dependsOn`** on the Blender profile's fields — the mutual
  image3d/background dependency, authored by hand, which the builder cannot
  express (§14.8b);
- `schema:sameAs`, `rdfs:comment`, `foaf:maker`, `skos:note` on various
  profiles, none of which the bootstrap form offers.

"Reopen the creation form with values prefilled and re-submit" would silently
delete all of it. The editor must work the way Edit Record's read-only fields
work: apply what the form owns, preserve everything else verbatim. The same rule
applies to the artist editor, where the personas carry `schema:creator`,
`foaf:name` and `schema:identifier` that the form never asks about.

#### How the profile editor keeps its promises (built 2026-09-19)

- **The template is EDITED, not regenerated.** Each submitted field reuses the
  existing `ops:field` node when one carries that property, so `ops:dependsOn`
  and anything else hand-written on it survives a change of order. Rebuilding
  from the grid would delete every statement the grid cannot express, and the
  grid has no way to put one back.
- **Removing the target of a dependency is refused**, with the two field names
  in the message. `read_profile` rejects a profile whose dependency can never be
  satisfied, so writing one would kill its own card — refused here, where it can
  still be explained.
- **One validation, shared with creation** (`_validated_fields`), so a template
  cannot be created one way and edited into a shape creation would have refused.
- **One grid spec, shared by both forms**, for the same reason one property map
  drives the entry forms: two copies of a closed set is how the offered set and
  the enforced set come apart.
- **`vad:measurementSystem` and the template blank nodes are updated in place**,
  not replaced, so a note or a type hung on either of them survives.
- Editing rebuilds the registry, exactly as creating does: an edited template is
  a different form behind its card, and waiting for a refresh to see it would be
  the "I changed it and nothing happened" that nobody believes.

#### Two thesaurus concepts are typed `vad:Artist`

"John Singer Sargent Watercolors" and "Winslow Homer" are `skos:Concept`s in a
scheme that also carry `vad:Artist`. `list_artists` matches any type ending in
`Artist` or `Painter`, so both appear in the artist pickers as if they were
personas of this deployment. They are vocabulary, not personas: a concept in a
`skos:ConceptScheme` is excluded.

### 14.11 What the record picker offers: two groups, named (Rick, 2026-09-27)

Edit Record's picker listed **works only** — records typed as a subclass of `vad:ArtForm` — on the rule that "entities, artists and artist profiles do not belong in a picker whose form edits works" (2026-09-18). That rule was right about artists and too strict about entities, and the cost was concrete: repointing the Pillars background image at a 4k JPEG could be done only by typing `/edit/open?path=…` into the address bar.

**The editor never needed changing.** It is file-based: it renders everything in the file, writes the whole file back, and preserves verbatim what it cannot render faithfully. That is exactly what an entity needs, since `skos:inScheme`, `the:conceptsExtracted` and a `skos:note` are no entry form's fields. Only the LIST was closed, and only the list changed.

**But the ONE-NAMED-SUBJECT rule is load-bearing for both, and DTS broke it silently (2026-10-02).** Every stamp inlined `ops:<agent> a prov:SoftwareAgent ; rdfs:label "…"` so the record stayed self-describing — written before the operations ontology existed. That gave a processed entity three extra named subjects, so `_is_editable` said no: the picker stopped listing DTS entities and the editor refused to open them. Nothing reported it, because a record vanishing from a derived list looks exactly like a record that was never in it. It surfaced from the Drafts page instead, where Rick could see two criticisms he had just made listed as `<guid>.ttl (4 subjects)` with no link back in.

Two things worth keeping from it. A record CITES vocabulary and declares none of it — `ops:claude-opus-5-5` resolves through `operations.ttl` exactly as `the:Prestress` resolves through the thesaurus, and the inline copy was not merely redundant but wrong, typing `ops:user` as a `prov:SoftwareAgent` against the ontology's `prov:Agent, prov:Person`. And a declaration cannot be nested out of the way: RDF has no scope, so a triple with `ops:user` as its subject makes it a named subject of the file wherever it is written. A reference can move under the status node; a declaration cannot exist there.

So the picker offers a second group rather than a looser filter:

- **Works** — typed as an `vad:ArtForm` subclass, from the ontology (`art_form_names`), unchanged.
- **Entities** — `skos:inScheme the:entities`, which `record.new_entity` writes on every entity it makes and nothing else in the store carries (161 of production's records, none of them a work or an artist).

Both are **derived**, never listed. A type list would be wrong on its face here — `the:Image` names a work's image as readily as an entity — and would drift the day a new entity type appeared.

**Artists and artist profiles stay out of both**, which is the part of the original rule that was load-bearing: they have editors that know what a persona owns and what may not change about it (§14.10), and offering an artist to a form built for works is precisely what that rule prevented.

The group is a filter applied **after** the one-named-subject rule, never instead of it, so an aggregate in the entities scheme is still refused. It rides through the routes as `?kind=`, and an unrecognised value reads as works — a mistyped query string should show a list, not a refusal.


### 14.12 A reference field takes a list; a literal field does not (Rick, 2026-09-28)

Edit Record's arity rule is that **arity is a property of the data**: a field holding one object writes back one object, commas and all. It exists because `schema:location "Woodstock, GA"` is one address, and splitting it on the comma made two literals out of it on 194 of 326 records during a save that changed nothing.

Applied to IRIs, the same rule had the opposite cost. `the:tag` on the Prestress Images collection held one reference, so nine background CURIEs typed into it became **one IRI with eight commas in it**. That is legal enough to parse and legal enough to serialize, so it was written, committed, and converged to the real production SOT with no gate objecting — the same shape of defect as a relative IRI (§ "Things to never do"). Typed with spaces after the commas it failed differently: `URIRef` accepted it, the Turtle serializer did not, and the user got a raw exception out of a save.

So there are two rules, not one:

- **Literals** keep the arity rule exactly as it was. The text may contain commas; only the data says how many objects there are.
- **References** split on commas **when every part is itself a reference** — a CURIE with a known prefix, or an absolute IRI. A comma is a legal URI character, and 29 IRIs in the real store carry one (all `#:~:text=` fragment links into Getty and Wikipedia), so the discriminator is what the parts ARE, never the presence of a comma. Measured over both stores: all 29 are left whole, and the only value that splits is the one that is wrong.

**A value that cannot be an IRI is refused at the field.** `URIRef` accepts any string; the serializer refuses `<>" {}|\^``. The gap between them is where an unwritable record gets written, so the check belongs where the user can act on it.

**And the verbatim rule yields to a mis-stored reference.** An untouched field is normally copied across rather than re-derived from its own rendering — that is what keeps `"9"` from becoming `"9.0"`. It also preserved the defect: opening the damaged record and saving it wrote the damage back. For reference fields only, where the round trip is exact, a stored value that disagrees with what its own rendering now parses to is treated as changed and separated, and the separation is **reported at the review** — a save the user believes changed nothing has just changed a field they are about to distribute. The exactness is measured, not assumed: **2,828 of 2,829** reference fields across both stores re-parse to precisely the objects on disk, and the one that does not is the damaged record. Over the whole production tree a no-op save changes exactly one more file than it did before, and that file is the damaged one.


### 14.13 Verbatim means the whole structure (2026-09-28)

The editor's safety rule is that anything it cannot render faithfully is preserved rather than risked. The preservation walked exactly **one** level of blank node, which is faithful for the two shapes it was written against — a `schema:QuantitativeValue` dimension and a `vad:NFT` provenance node are both flat — and silently lossy for anything deeper. An artist profile's `ops:template` is deeper: a list of `ops:field` blank nodes hung off a node that is itself blank. A no-op save on a real profile record wrote back **29 of its 78 triples**, and the result parsed cleanly and passed every gate.

**Preserving is the answer, not refusing.** Refusing a record whose blank nodes nest would also block editing its label, which is a legitimate thing to want to do to a record whose internals must not be touched — and it would trade silent loss for a dead end rather than for correctness. The three places that preserve (read-only fields, untouched fields, and the properties a labelled node carries through a rebuild) now copy the transitive closure, terminating on a seen-set because RDF permits a blank node to reach itself and a template is a chain rather than a tree.

Measured after: a no-op save over both real trees changes nothing beyond the 36 intended empty-blank-node drops per store. Before, six records per store changed — five artist profiles and the `rdf:List` in `topics2.ttl`.

**Reachability is not the same as safety.** Profiles are in neither of Edit Record's two groups (§14.11) and have an editor of their own, so this took a hand-typed `/edit/open?path=…` to hit. That is a reason it went unnoticed, not a reason it was acceptable: the fault was in the preservation rule, which every record relies on.


### 14.14 Finishing Edit Record (2026-09-29)

Five things were outstanding, four of them found by measuring the editor against the real store rather than by using it. All five are done.

**The video description is editable** — the debt §14.7 left. A composite now renders a small group: the file picker, plus whatever the shape marks as the user's to say. The description was preserved across a file swap and had nowhere to be typed, so the only way to set one was to enter the work again. Changing it does not touch the file, and changing the file does not discard what was typed in the same save. Clearing it falls back to the DERIVED sentence rather than to nothing, which needs the work's label and type — taken from what was submitted, so renaming the work and clearing the description in one save does not describe the record by the name it just stopped having. This is the pattern generalising as promised: a composite becomes editable by being in the property map.

**A multi-valued file field gets one picker per file.** It rendered as a single select whose only option was every filename joined, so choosing a replacement swapped them all for one — silently, and the entity form writes a list of images, so it is reachable the moment a record has two. Slots are named `<predicate>::<i>` and re-joined at one point, so the collision check, the untouched comparison and the parser all see the same value. A single-valued field keeps the predicate as its form name: the common case does not learn a new spelling.

**The editor can re-read the drop folder in place.** The Refresh list control that entry forms got on 2026-09-27 was missing here, and the note said "reopen this record" — which discards everything typed. On an edit form the refresh must put the record's own file back as the selected first option, carried in `data-unchanged`: a refresh that replaced it with an empty "choose one" would turn the next save into a cleared reference.

**A labelled blank node is a dimension only when the label IS the content.** The branch assumed labelled meant dimension, which is true of 906 blank nodes in the store and false of 43: a profile's `ops:template` is labelled "Input Form Spec" and a `the:document` node "gdoc source". Those were offered as an editable one-line box that warned, on save, that the value was not "number unit" — an invitation to edit a whole form template through its title. The test is now whether the node carries anything the label does not account for.

**A read-only structure shows its nesting.** It printed the object directly, so a nested blank node read as its rdflib id (`ops:field=N7a3f9c…`), which tells a person nothing and looks like corruption. Nested nodes render inline in braces to a small depth, because the point of that field is to show what is being preserved.

**Still open, and it needs a decision rather than a fix: the editor cannot ADD a predicate.** It renders what is in the file, so a record with no `the:tag` cannot be given one, and a record with no `skos:note` cannot be annotated. That is the same property that makes overwriting safe, so the answer is not "free text": it would be a closed set of addable predicates, most likely the property map's, offered as "add a field". Worth doing before the collection work goes much further.
