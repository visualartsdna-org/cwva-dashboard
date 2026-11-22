# GROOVY EXTRACTION — record group (RDF Entry / Digital Entry / Entity Entry)

**Status: extraction for review. No code change yet.** Per the Groovy-extraction
convention (PROJECT_PLAN Phase 4.6 §2): this precedes the port/renderer work for
this function group, Rick reviews it, and each quirk is classified
**load-bearing** vs **candidate-bug** vs **obsolete-artifact** vs
**already-diverged**. It is the semantics reference feeding affordance-layer
step 3 (qrcode) and step 4 (author the closed sets).

## Sources

Two roles kept distinct (§2):

- **Layout** — `html/function.html` (tab/card structure), not analyzed here.
- **Semantics** — the Groovy generators + on-submit handlers, read in full:
  | Dashboard tool | Groovy form (affordances) | Groovy on-submit (TTL semantics) |
  |---|---|---|
  | `record.new_work` (#1) | `support/HtmlForm2Ttl.groovy` | `support/ParseRDF.groovy` |
  | `record.new_digital` (#2) | `support/HtmlForm2DigitalTtl.groovy` | `support/ParseDigitalRDF.groovy` |
  | `record.new_entity` (#3) | `support/EntityEntry.printHtml` | `support/EntityEntry.handleQueryParams` |

Dashboard current state read from `src/cwva_dashboard/tools/record_tools.py`
(`_new_work`, `_new_digital`, `_new_entity`) and verified against the real
shadow content (327 `ttl/data` records).

## Closed sets — pins the `?` sets left open in AFFORDANCE_DESIGN.md

Authoritative membership, from the Groovy form source. **Namespace matters** —
work/digital types are `vad:`, entity types are `the:`.

| Field | Tool(s) | Members (in form order) | Default | Namespace |
|---|---|---|---|---|
| `type` | new_work | Watercolor, Drawing, EggTempera, Sculpture | **Watercolor** | `vad:` |
| `type` | new_digital | PaintApplicationImage, LindenMayerSystemImage, BlenderComposition | **none** (see Q1) | `vad:` |
| `type` | new_entity | AI, Article, Artist, Collection, Concept, Entity, Image, Operation, Organization, Posting, Series, Study, Work | none | `the:` |
| `units` | new_work | cm, inch, meter, pixel | **inch** | — |
| `units` | new_digital | cm, inch, meter, pixel | **meter** | — |
| `file_format` | new_digital | GLB, JPEG, TIFF, PNG, GIF, OBJ | **GLB** | literal |
| note `type` | new_entity | note, changeNote, editorialNote, example, historyNote, scopeNote | note | `skos:` |

Two "sets" that are **not static enums** — they are dynamic vocabularies
(affordance `x-vocabulary`, not `enum`):

- **`hasPaper`** (new_work) → rendered from a live query `?s a vad:WatercolorPaper ; rdfs:label ?l` ordered by `schema:position`. Enforced by the vocabulary-reference gate (already built).
- **`media`** (new_entity) → **this field is `the:topic`**, rendered from `?s a skos:Concept ; skos:inScheme the:TopicScheme`. Dynamic multi-select, **required**. See "Affordance feedback" — this needs the same gate treatment as `hasPaper`, against TopicScheme.

## Field → TTL semantics (the reference behaviour)

Shared shape (all three): subject `work:<guid>`, `rdfs:label`, `schema:identifier`,
description, `schema:datePublished` from recordedDateTime (`^^xs:date`).

**Dimensions (new_work, new_digital):** height/width[/depth] are NOT plain
literals — each is a `schema:QuantitativeValue` blank node with `rdfs:label`
"`<v> <unitName>`", `schema:unitCode`, and `schema:value ^^xs:float`. Units map
to **UN/CEFACT codes**: `cm→CTM, inch→INH, meter→MTR, pixel→E37`, and to
label names `cm→cm, inch→inches, meter→meters, pixel→pixels`. ✅ The dashboard
`_UNITS` map and blank-node structure replicate this **exactly** — verified.

**new_work extras:** `vad:hasPaper` (CURIE), `schema:image <imgbase+file>`,
`vad:qrcode <url>`, `schema:height/width`. location/note optional.

**new_digital extras:** `vad:fileFormat` (literal), `vad:image3d <imgbase+glb>`
(conditional), `vad:background <curie>` (conditional), `schema:depth`. note
**required**. No hasPaper.

**new_entity extras:** `a the:<type>`, `the:topic` (multi, from media),
`skos:definition`, typed `skos:<noteType>` notes (repeatable), `the:mdDocument`
/`the:pdfDocument`, `the:document` blank node, `schema:sameAs` (primarySite),
`the:wikipedia`/`the:dbpedia`, multi `schema:image`, `the:tag` (opaque user
data), always `the:conceptsExtracted false` + `skos:inScheme the:entities`.

## Divergences: dashboard vs Groovy — CLASSIFIED (the core deliverable)

| # | Field/behaviour | Groovy | Dashboard | Classification |
|---|---|---|---|---|
| D1 | **qrcode** | derived readonly `{imgbase}qrc_{guid}.jpg`; JPEG generated on submit; written `<url>` | optional free param, written **raw** `URIRef(qrcode)` (no base join) | **candidate-bug (confirmed)** — fix in step 3 |
| D2 | **workOnSite** | verified but **commented OUT** of TTL in BOTH work and digital | writes `vad:workOnSite` when provided | **load-bearing quirk?** (Q2) |
| D3 | **image required** | `assert m.fileupload` — required, work & digital | optional (`image=None`) | **already-diverged, deliberate?** (Q3) |
| D4 | **prefixProtocol** (md/pdf) | buggy `!has("http://")‖!has("https://")` → almost always prepends `visualartsdna.org/documents/$s` | `s if "://" in s else "http://"+s` → prepends **only** `http://`, wrong base | **candidate-bug in DASHBOARD** (Q4) |
| D5 | **hasArtistProfile** | hardcoded default GUID in form (different per work/digital) | required, no default | already planned (affordance step 4 config default) |
| D6 | **units default** | inch (work) / meter (digital) | none (required) | fold into the `enum` default, step 4 |
| D7 | **sig** {visualartsdna.org,art.visualartsdna.org,left,right} | branding param → ImageMgt stamping, NOT in TTL | absent from record tool | **correct** — out of record scope (brand #7) |
| D8 | **digital media** {Graphics,Video,Audio,Text} | form checkboxes, but `vad:media` **commented out** of TTL | absent | **correct** — faithful to suppressed output |
| D9 | **substring(5)** `m.id.substring(5)==m.guid` | id/guid consistency assert | N/A — URI built from guid | **obsolete-artifact** (plan already classified) |
| D10 | **gdoc download** (entity) | `DwnLdGDocMD`/`DwnldGDocPdf` + `sleep 20s`, sets md/pdf URLs | URLs are inputs; download decomposed out | **correct** — network effect, out of confined tool (law 11) |

## Quirks worth naming (not divergences, but review material)

- **Q-typo:** the gdoc download writes `virtualartsdna.org` (note: *virtual*, not
  *visual*) into md/pdf URLs, yet real data holds `visualartsdna.org`. The
  buggy source path never matched production — evidence the download path was
  bypassed/hand-corrected in practice. Reinforces D4 (documents-URL handling is
  unreliable in the original) and D10 (decomposing the download out loses
  nothing real).
- **HTML id collisions:** repeated `id="type2"`, `id="media4"` in the forms.
  Cosmetic (radios/checkboxes bind by `name`); dies with the flat form.
- **hasPaper render-vs-enforce class:** the picker queries `a vad:WatercolorPaper`;
  the vocabulary gate checks `a skos:Concept`. All papers in the data are both,
  so enforcement is a valid (slightly looser) superset — a `skos:Concept` that
  is not a `WatercolorPaper` would pass the gate but not appear in the picker.
  Acceptable; noted so it is a decision, not a surprise (Q5).

## Feedback into AFFORDANCE_DESIGN.md (what this extraction changes)

1. **qrcode is NOT `x-file-ref`.** The design (and my earlier note) leaned toward
   a file picker; the Groovy truth is a **derived, readonly** value
   (`{imgbase}qrc_{guid}.jpg`) whose JPEG is generated on submit. Reclassify:
   qrcode is a **derived field**, not user-input — removed from the input
   surface, computed in the record tool from guid + image base. The
   asset-reference gate already covers `vad:qrcode`, so its resolution is
   enforced; step 3 is "derive it correctly," not "pick it."
2. **new_entity `media` = `the:topic` is `x-vocabulary` (TopicScheme), required,
   multi.** Add it to the vocabulary-reference gate alongside `hasPaper` — a
   second property whose object must be a declared concept, checked against the
   TopicScheme vocabulary. The gate is already property-parameterized; this is a
   config addition, not new code, but the reference set is TopicScheme not
   watercolorPaper.
3. **`type` closed sets are now pinned** (table above) for step 4, with correct
   namespaces (`vad:` for work/digital, `the:` for entity) and per-form defaults.
4. **A documents base exists, distinct from the image base** (D4). If md/pdf
   inputs may be bare names, the tool needs a `documents_base` join analogous to
   `image_base` — currently absent. Otherwise require full URLs and drop
   `_prefix_protocol` entirely.

## Review outcome (2026-08-03 — decided)

- **Q1 — digital `type` default = `vad:BlenderComposition`.**
- **Q2 — stop writing `vad:workOnSite`** from the record tools (Groovy-faithful;
  updateWorkOnSite #9 is the one writer). `work_on_site` param removed.
- **Q3 — image is REQUIRED** (Groovy-faithful) in new_work and new_digital.
- **Q4 — documents URLs are uniformly `{domain}/documents/<name>.<ext>`.** Derive
  a `documents_base` (from config domain, like `image_base`), join bare names,
  leave full URLs; the middle-state `_prefix_protocol` is removed.
- **Q5 — tighten the vocabulary gate for `hasPaper` to `vad:WatercolorPaper`**
  (matches the picker). The gate becomes per-property: `hasPaper →
  vad:WatercolorPaper`; `the:topic → skos:Concept` in TopicScheme (step 4).

## Open questions for Rick's review — RESOLVED (see above)

- **Q1 — digital `type` has no default in the Groovy form** (no `checked`). Pick
  a default for the enum, or leave it required-with-no-default? (work_type
  defaults Watercolor; digital had none — likely an oversight.)
- **Q2 — workOnSite (D2):** Groovy deliberately suppressed `vad:workOnSite` in
  the record TTL (updateWorkOnSite #9 owns site links). Should the dashboard
  record tools **stop** writing it, matching Groovy? I lean yes — one writer per
  fact — but it changes current behaviour.
- **Q3 — image required (D3):** Groovy required an uploaded image; the dashboard
  made it optional (stamping decomposed out, and the shadow has no images so
  requiring it would block real-content entry). Keep optional? I lean yes, but
  it is a genuine fidelity gap, not an oversight to fix silently.
- **Q4 — prefixProtocol (D4):** the dashboard's `_prefix_protocol` neither
  matches Groovy nor produces the documents-base URLs the real data shows (bare
  `x.md` → `http://x.md`, not `…/documents/x.md`). Fix to a real
  `documents_base` join, or require full URLs and remove the helper? Real data
  is uniformly full `visualartsdna.org/documents/*` URLs, so either is safe;
  the current middle state is the only wrong one.
- **Q5 — hasPaper enforce class:** leave the gate on `skos:Concept` (looser
  superset) or tighten to `vad:WatercolorPaper` to match the picker exactly?

## Findings from step-4 authoring — real data exceeds the form's closed sets

Authoring the enums against the real shadow surfaced that the Groovy form's
radio/select sets are **entry conveniences, not exhaustive constraints** — real
data legitimately holds values outside them. Since a dispatch `enum` only gates
*new* entries (existing data is never re-validated), a strict enum would not
corrupt history, but it *would* block legitimate new entries and freeze a casing
fork. So the split: **strict `enum`** where the set is truly closed and
real-data-verified; **`x-enum-suggested`** (render a dropdown, allow other) where
it is not.

**Meta-finding (from Rick's Financial-Winds correction):** my first pass treated
*every* `vad:`-typed subject as an entry, so the "real data exceeds the form
sets" claim was polluted by **non-entry objects** — `NFT` (×33, bnodes with no
label), `Proof` (×20, proof-workflow records), profiles, owlrl-materialized
supertypes (`Art`/`ArtForm`/`CreativeWork`/…), and an **archived one-off**.
Filtered to actual active entries, the data conforms to the form's closed sets.
The right analysis is over active entries, not all typed subjects.

- **F1 — work/digital `type`: casing fork RESOLVED (Q6); set-openness OPEN (Q9).**
  Casing: data used `Lindenmayer**S**ystemImage` (lower *m*, ×15) vs the form's
  `LindenMayer`. **Q6 decided: canonical `Lindenmayer`** — suggested set, schema,
  test updated. The `NFT`/`Proof` "extra types" are **not** entry types (NFT are
  bnodes; **0** NFT subjects carry an entry-form type; Proof is the proof
  workflow). So active work/digital entry types DO conform to the form sets.
  Kept `x-enum-suggested` **only pending Q9** below — the data no longer argues
  against strict.
- **F2 — `file_format` IS a closed set → strict `enum` (corrected).** My first
  F2 rested on a regex that matched only the first quoted value per
  `vad:fileFormat`. **Q7 answer:** the sole `HTML` is on `work:1b79e09d…`
  ("Financial Winds — EURUSD M15"), a `schema:SoftwareApplication` whose
  `fileFormat` is multi-valued `"HTML","GIF","JPEG"` — and **Rick confirms that
  work is an archived one-off, no longer active.** No `schema:image`/`vad:image3d`
  references an `.html` file anywhere (its image is `treeCycle.gif`). So among
  active data `file_format ∈ {JPEG,GLB}` ⊂ the form set → **strict `enum`
  {GLB,JPEG,TIFF,PNG,GIF,OBJ}**, dispatch-enforced. HTML now rejected.
- **F3 — WITHDRAWN.** "fileFormat is multi-valued" came solely from that archived
  one-off; active records are single-valued. No multi-select needed. (That record
  also carries archaic quirks — `vad:media "Graphics"` as a literal, a height
  bnode missing `a schema:QuantitativeValue` — consistent with being pre-current-
  convention and archived.)
- **Entity `type` IS closed** — all asserted entity types conform to the 13-value
  form list (the extras seen, `skos:Concept`/`rdfs:Resource`, are materialized
  supertypes) → strict `enum`, dispatch-enforced. The prior test's
  `type="Criticism"` was unrealistic (Criticism is a *topic*, not an entity
  type) and was corrected.

## F4 — can `type` be vocabulary-backed at the gate (like has_paper)? NOT YET.

The externalization instinct is correct for `type`: its valid set is the
ontology's business, not the code's — the same kind of fact as `has_paper`
(thesaurus) and `media` (TopicScheme), both already gate-backed. The question is
purely whether the ontology defines the work-class set **queryably and cleanly**.
Investigated `ttl/model/*` (2559 triples) — it does **not**, on three counts:

- **No `vad:Work` root.** `?c rdfs:subClassOf vad:Work` → empty. The form types
  hang off unrelated parents: Watercolor→PaintingForm, Drawing→VisualArtForm,
  EggTempera→TemperaPainting, Lindenmayer→GenerativeArt, BlenderComposition→
  DigitalSculpture. No single class to select subclasses of.
- **No clean structural selector.** "Leaf classes" (no subclasses) = 208 classes,
  almost all noise (ArtCritic, ArtGallery, Aquatint, Chisel, ColdPressedPaper…),
  and inconsistent for the form set anyway: Watercolor/EggTempera/Lindenmayer/
  BlenderComposition are leaves but **Drawing is not** (it has subclasses). Any
  `subClassOf*` roll-up pulls in the abstract intermediates (PaintingForm,
  VisualArtForm, GenerativeArt…) — the very materialized-supertype noise that
  polluted the F1 outlier count.
- **Two form types aren't defined classes at all:** `Sculpture` and
  `PaintApplicationImage` have no ontology definition. A gate keyed on "declared
  work class" would reject them — legitimate form entries.

So `type`-at-the-gate is **not** the same afternoon's work as the has_paper gate
(where WatercolorPaper is a flat class with instances). It needs **ontology
shaping first**: an explicit, queryable marker for the enterable set (e.g. a
`vad:WorkClass` / `vad:DigitalWorkClass` marker class, or membership in a
`the:WorkTypeScheme`), applied to exactly the enterable classes, plus defining
the two currently-undefined types. That marker is data — promoted through the
same gated exit — after which `type` gate-checks with the existing
per-property-requirements machinery (`vad:<type>` must carry the marker).

**Corrected tier map** (the externalization instinct applies to ONE field):

| Field | Tier | Home | Status |
|---|---|---|---|
| `has_paper` | vocabulary (thesaurus) | gate | done |
| `media`/`the:topic` | vocabulary (TopicScheme) | gate | done |
| `type` | vocabulary (ontology classes) | **dispatch enum, resolved from ontology at build time** (per-form `subClassOf*` root) | **done (Q9)** |
| `file_format` | controlled literal — **NO ontology backing** (0 `vad:FileFormat`) | static enum | done (strict) |
| `units` | genuine constant (no ontology class for "inch") | static enum | done |
| note `type` | fixed SKOS property set | static (render hint) | done |
| `background` | work cross-reference (→`work:`) | deferred | — |

**Q9 RESOLVED (Rick, 2026-08-05) — a fourth option neither of us had named:**
the ontology *is* queryable via a per-form **root**, not a global work-class
selector. `?type rdfs:subClassOf* vad:PaintingForm` (RDFS-materialized, **parent
included**) yields exactly the 11 painting types; `…subClassOf* vad:SculptureForm`
the 9 sculpture types; the two placeholders (Sculpture, PaintApplicationImage,
never-used form stubs for anticipated model work) drop out for free — they are
under neither root. So:

- **`type` is model-backed, resolved as the RDFS subclass closure of a per-form
  `type_root`** — `vad:PaintingForm` for RDF Entry (painting), `vad:SculptureForm`
  for RDF Digital (digital sculpture). Set comes from the ontology; adding a work
  kind is an ontology edit, not code (Rick's externalization instinct, answered).
- **Enforced at DISPATCH, not the promotion gate** — the third locus the earlier
  A/B/C framing missed: the candidate set is *materialized into the schema enum
  at registry-build time*, so the validator stays pure/store-free AND the
  per-form root is honored (a `SculptureForm` value is rejected on the painting
  form). The gate can't do per-form (records are just `a vad:X` in a manifest);
  dispatch can (each tool built with its root).
- **`allow_abstract_root: true`** keeps the abstract parent selectable as an
  honest fallback for a novel medium not yet modeled (a "TeaBagPainting" is
  entered as `vad:PaintingForm`, not forced to become a class first). This makes
  `type` certify *membership*, not *specificity* — a deliberate design choice.
  **Specificity is a UX concern, never a gate/enum constraint:** the picker (step
  5) sorts children above the parent and can label it "other painting"; nothing
  rejects a vague-but-valid parent, because the enum can't distinguish "correctly
  used parent (child unmodeled)" from "lazily used parent." Recorded so a later
  session does not "fix" the selectable parent as a bug.
- **`type_root` + `allow_abstract_root` are per-form config** (`entry_forms` in
  `dashboard.rson`), single-select, **no default** (Rick: keep it simple). A
  future agent-driven entry-form-design workflow generalizes to 1-N forms.

Corrected tier map above: `type` moves from "blocked" to **done (model-backed,
dispatch-enforced)**. Fallback to an unenforced suggested set only when the model
is not yet loaded (fresh sandbox before the §5 sync).

## For the future entry-form-design phase (record now, worked examples included)

CE-in-the-wild has 1-N entry forms; work types, defaults, branding, profile,
artist site, and more become configuration, written by an **agent-driven
entry-form-design/configuration workflow** (a CE user won't hand-edit these).
This extraction generated two concrete worked examples the redesign should carry
rather than rediscover abstractly:

- **Abstract-root selectability is a per-form config knob, not a universal.**
  Rick wants `allow_abstract_root: true` for painting (novel media are common in
  his practice); a CE user cataloging a fixed archive might want it `false` to
  force specificity. The parent-included-vs-excluded choice is `allow_abstract_root`
  — a parameter, not a hardcoded rule.
- **Multi-parent classification is the open modeling limitation, and
  BlenderComposition/DigitalSculpture is the motivating case.** They sit under
  `vad:SculptureForm` by Rick's artistic intent ("I think about these in a
  sculptural context") — a real modeling rationale, chosen over
  `vad:DigitalArtForm` (medium-is-digital) because single inheritance forces one
  axis. The form conforms to the model as-is; the model was **not** reshaped for
  the form's convenience (the UX tail must not wag the ontology dog). When
  entry-form config is designed, "which parent does a form's `type_root` draw
  from" and "can a class appear under more than one form's dropdown" are the same
  question this decision posed — recorded here as the worked example.

## Build implications

- **[DONE — `9257e26`] Q1–Q5 + D1 applied.** qrcode derived + removed from input
  (D1/step 3); workOnSite no longer written (Q2); image required (Q3); documents
  base join replaces `_prefix_protocol` (Q4); vocabulary gate tightened to
  `vad:WatercolorPaper` (Q5). 434 passing; Q5 verified no-regression on real data.
- **[DONE — step 4 authoring] closed sets authored.** Strict `enum` (dispatch-
  enforced): `units` (+defaults inch/meter), entity `type`, and `format: date`
  on all date fields. `x-enum-suggested` (render hint, not enforced, per F1/F2):
  work/digital `type` (defaults Watercolor/BlenderComposition per Q1), and
  `file_format` (default GLB). `x-vocabulary`/`x-file-ref` render annotations
  added (`has_paper`→papers, entity `media`→topics; `image`/`image3d`/`images`).
  `the:topic`/TopicScheme added to the vocabulary gate (verified 0 dangling on
  real data). Note-type enum documented but not dispatch-enforced (validate_args
  does not recurse object array items).
- **[Q6 DECIDED]** canonical digital-type casing = `Lindenmayer` (applied).
- **[Q7 ANSWERED / F2 corrected]** HTML came from an archived one-off, not active
  data; `file_format` is now a **strict enum**. F3 (multi-valued) withdrawn.
- **[Q9 DONE]** `type` is model-backed: the RDFS subclass closure of a per-form
  `type_root` (`vad:PaintingForm` / `vad:SculptureForm`), materialized into the
  schema enum at registry-build time, dispatch-enforced, parent included as a
  fallback, no default. Config in `dashboard.rson` `entry_forms`. Verified
  against the real ontology (11 painting / 9 sculpture types; placeholders drop
  out). Falls back to an unenforced suggested set until the model is synced (§5).
- **[REMAINING]** the renderer upgrade (step 5) — the last affordance-layer piece.
  All design questions are now closed.
