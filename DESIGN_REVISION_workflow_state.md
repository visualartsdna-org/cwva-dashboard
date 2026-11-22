> **MERGED into CE_DESIGN.md (§7.1, §7.2, §3.4) and PROJECT_PLAN.md (Phase 4.5)
> on 2026-07-16 — historical provenance only, not normative.** The canonical
> docs are the source of truth; do not treat anything below as pending work.

# DESIGN_REVISION — Workflow state panel + updateWorkOnSite rebuild

Merge-ready fragment (repo copies are source of truth). Three parts:
1. New CE_DESIGN.md section — Workflow state & open items (insert as §7.1
   under Agent orchestration, or as its own section after §7).
2. CE_DESIGN.md addition — updateWorkOnSite rebuild spec (fits under a
   "function rebuild notes" heading near §10, or alongside the Phase 4.5
   material).
3. PROJECT_PLAN.md Phase 4.5 checklist additions.

---

## 1. CE_DESIGN — Workflow state & open items

### Principle: compute obligations, record only dismissals

Workflow state must never drift from reality, so it is **derived, not
tracked**, wherever derivation is possible. The dashboard's workflow panel
(successor to the legacy stageStatus queue badges) renders results of
**standing queries** over sources the system already maintains:

- **Graph-derived obligations** — SPARQL over the QA store. Canonical
  example: works promoted to SOT with no `vad:workOnSite` assertion = the
  open updateWorkOnSite items. The pattern generalizes (works without
  interpretations, entities without images, …).
- **Filesystem-derived state** — the legacy queue badges unchanged:
  conceptQueue and processed/* population counts.
- **QA-git/audit-derived state** — uncommitted WIP; drift awaiting
  adoption; **staleness** checks (e.g. "last site scrape predates the most
  recent work promotion").

The only recorded state is the **exception**: a dismissal ("work X is
intentionally on no site — stop reporting it"). Dismissals live in the
hygiene ledger (same TTL container as concept-dup dismissals, §6).
Open items = standing-query results − dismissals.

### Standing query definitions are data, not code

Each open-item type is a definition: {id, source (sparql | fs | git |
audit), query/check, description, severity, resolving action (the registry
tool or workflow that closes it)}. Definitions load from config/content, so
new item types can be added by the user or by the agent without dashboard
code changes — the same extensibility posture as the legacy
addFunctionCard.

### One source of truth, two windows

The workflow panel and the agent's narration render the **same
standing-query results**. The agent's opening state summary ("2 markdowns
awaiting derivation, 3 works with no site link, scrape 12 days stale") and
the panel are two views of one computation — the prompt+browser philosophy
applied to workflow state. Open items in the panel are clickable: each
fires its resolving action/workflow.

### Panel contents (three groups)

1. **Pipeline queues** — filesystem counts (legacy badges).
2. **Open obligations** — standing-query results minus dismissals, each
   with its resolving action.
3. **In-flight workflow** — the single active workflow instance (v1) and
   its pending gate, from the workflow-state file.

The workflow-state file remains confined to genuinely in-flight instances;
everything else is recomputed. This preserves the law that the agent is
reconstructable from disk state.

---

## 2. CE_DESIGN — updateWorkOnSite rebuild spec

Ports as a **rebuild**, not a port; the Groovy DOM-structure scraper is not
carried forward. Purpose unchanged: passively observe which works appear on
the external artwork sites and assert `work:<guid> vad:workOnSite <site>`,
one TTL per site. Passive observation is deliberate — observed truth over
user-declared truth; posting to sites remains outside dashboard scope.

Effect pattern: outbound **read-only HTTP** to config-listed sites (falls
under the sanctioned network effect class, alongside post-promotion
refresh) + QA write terminating in a **promotion unit**.

**Extraction — layered, structure-free:**
1. Structured metadata first: sitemap.xml for page discovery; OpenGraph
   (og:title, og:image) / JSON-LD per page. SEO-load-bearing, therefore
   stable across platform redesigns.
2. AI fallback: fetch page → cheap model extracts {title, image_url} into
   schema-validated JSON (T0/T1 task profile). This is the generalizable
   path for arbitrary CE-user platforms; stubbed until Phase 5 provides
   the task profile.

**Matching (scraped page → work GUID) — code before AI:**
1. Perceptual image hash (pHash) of fetched site images against hashes of
   SOT originals (computed once, cached) — survives scaling and branding.
2. Title match via the shared lexical matcher (normalized Levenshtein +
   token-sort; same module as concept dedup).
3. Below-threshold on both signals → surfaced in the run report for
   one-click user confirmation; never silently guessed.
4. Posting convention (recommended, forward-looking): embed the work GUID
   (or first segment) in uploaded image filenames or page slugs, turning
   future matching into lookup.

**Semantics: full snapshot per run.** Regenerate each per-site TTL
entirely and promote as a unit — idempotent, convergence-friendly, and the
promotion preview becomes informative: appearing works are adds; vanished
works are removals (takedown/URL-change signal), not diff artifacts.

**Provenance:** scrape-derived triples carry prov: attribution marking them
observed-by-scraper, with model identity where the AI fallback produced the
extraction.

**Companion standing query:** "SOT works with no workOnSite assertion"
(open obligation) + "scrape staleness" (last run predates latest work
promotion) — see §1.

---

## 3. PROJECT_PLAN — Phase 4.5 checklist additions

- [ ] **Workflow panel** replacing stageStatus: pipeline queue counts +
      open obligations (standing queries − dismissals) + in-flight
      workflow/gate. Standing-query definitions load as data (config/
      content), not code.
- [ ] First standing queries shipped: conceptQueue counts (parity with
      legacy badges), works-without-workOnSite, scrape staleness, drift
      awaiting adoption, uncommitted WIP.
- [ ] Dismissals recorded in the hygiene ledger (shared container with
      Phase 9 concept-dup dismissals; ledger lands early as a result).
- [ ] Agent narration and panel consume the same standing-query engine
      (one computation, two renderings).
- [ ] **updateWorkOnSite rebuild** per spec: sitemap/OG extraction (AI
      fallback stubbed until Phase 5), pHash + lexical matching with
      confirmation queue for low-confidence pairs, full-snapshot per-site
      TTL, promotion unit out, prov: observed-by-scraper attribution.
- [ ] pHash cache of SOT originals built during shadow-SOT episodes.
