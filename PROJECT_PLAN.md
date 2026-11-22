# PROJECT_PLAN.md — CE Dashboard

## ▶ CURRENT POSITION — updated 2026-11-22

**Maintenance rule: this block is updated in the SAME commit as any change to
phase state.** It is the one place allowed to answer "where am I", and it earns
that only by never drifting — the deleted `SESSION_HANDOFF.md` was three weeks
stale precisely because it was updated separately from the work. Keep it to
facts that are cheap to re-verify; put reasoning in the phase body, not here.

- **Phase:** **4.7** (wire the real dashboard UI, one function at a time).
  Phases 1–4 complete; 4.5 closed at unit-test level; 4.6 closed by
  supersession, its carried gates B1/B2/A0 **all cleared**.
- **🚧 VERSION 1.0.0, THE COMMUNITY EDITION (2026-11-22).** Three steps,
  agreed with Rick 2026-11-21; macOS and native Windows are phased in later.
  1. ✅ **A collection in a folder or a git repository**, not only a bucket
     (`promotion/targets.py`), tested end to end with cwva-py's sample
     collection; a new collection's model and vocabulary from
     `reference_model`.
  2. ✅ **One environment**: config resolution ending at `config/config.rson`,
     a `developer` switch for the hub's extras, this machine's configs no longer
     in the repository.
  3. ✅ **The docs for CE**: About rewritten (folder first, git, bucket as
     advanced, a page on bringing in an existing collection) and
     `docs/ASSISTANT_GUIDE.md` generated from it; a README.
  **Before going public**, still open: the identity and secrets scrub
  (including git history, which still holds this machine's configs), and
  the *Using it* / *Under the hood* / *References* parts of About. The
  LICENSE is MIT, as cwva-py's is (2026-11-22).
- **⏸ PARKED HUB FUNCTIONS (2026-11-19).** Taken off the hub because nothing
  was ever built behind them (each form pointed at a route that does not
  exist) and the first public release does not need them; kept verbatim in
  `html/parked.html` (not served) so they are not lost, and listed here so they
  are not forgotten. FUNCTION_INVENTORY.md says what each did in Groovy.
  - Content: **Open Author Page** (#21), **Extract Keep Notes** (#40, the one
    most likely to come back)
  - Tools: **RDF Graph Editor**, **Generate GUID**
  - Files: **Query TTL**, **Difference**, **SHACL Validation**, **Image
    Synchronization** (Check Synchronization and Compare Folders)
  Bringing one back means building it like any card (a registry tool and a
  route, law 10) and rewriting the form: accounts in config, uploads through
  the drop folder, writes toward the SOT through a promotion.
- **✅ QA WAS STARTED FRESH FROM PRODUCTION (2026-11-19).** `seed_shadow_sot.py
  --mirror` made the shadow equal to production (1978 objects; 20 QA-only
  objects deleted, `operational/` included, because nothing of QA's is meant to
  survive a clone), and the QA sandbox was rebuilt from it with new git
  history. The old tree was kept aside and deleted once the new one checked
  out (2026-11-19). The baselines in `verify_shadow.py`,
  `sync_shadow_to_qa.py` and `gate_baseline.py` were re-frozen to match; all
  gates pass. Procedure: LegacyToNewDashboardProcedure.md.
- **✅ CWVA-PY RUNS OVER A SANDBOX, READ-ONLY (2026-11-19).** The "cwva-py
  view" card starts cwva-py itself over the instance's own sandbox, drafts
  included (QA :8091, production :8093), so a change is seen before it is
  distributed. Landlocked to write only its scratch folder, loopback only, no
  bucket or credentials (`viewer.py`). **Open, in cwva-py:** its gallery
  thumbnails need a bucket even when the image is on disk, so the viewer shows
  none; Rick has put the fix on cwva-py's list.
- **✅ A WORKFLOW BOARD (2026-11-18).** `/workflows` shows each work in
  workflows A (Watercolor) and B (Blender) against its steps, derived from the
  records (`config/workflows.rson`). The external-website step is ticked by
  hand; any step can be dismissed as not needed for one work. Both are dated
  entries in the hygiene ledger, which the QA backup carries since 2026-11-19
  (`operational/qa-ledger.ttl`). Workflows C–G are not modelled yet.
- **✅ INCIPIENT PROVENANCE AT ENTRY, AND A SANDBOX SPARQL BROWSER
  (2026-11-16).** A profile form writes the work's provenance record and shows
  its Disposition Identifier at the review; `provenance_gate` refuses reused
  ids. The SPARQL card queries the whole sandbox, drafts and provenance
  included. FileOps quota raised to 2000 ops/min.
- **✅ WIRING CYCLE 1 (RDF ENTRY) COMPLETE AND QA-PASSED (2026-09-04).** Two
  entries driven end to end against the real shadow — drop folder → entry →
  four gates green → preview → approve → converged — and the form itself
  accepted by Rick. Six objects on the shadow SOT; QA git `017859e`.
  Everything the cycle turned up is closed: the missing QR generator, the
  sidecar-less hand-placed binary, the picker offering generated artifacts,
  the panel blowing the ops quota, the dead leave-guard JavaScript, the
  reload-losing-your-data collision message.
- **✅ THE SHADOW NOW CARRIES PRODUCTION'S IMAGES (2026-09-11).** 1093 objects,
  3.72 GB, seeded in full at Rick's instruction; the shadow had been image-less,
  so every synced work carried a dangling `schema:image` and could never pass
  the asset gate. `verify_shadow.py`'s frozen baseline was **re-frozen** the same
  day (1,647 objects / 3.86 GB) — a baseline that reports an authorized change
  as a finding trains its reader to skim past the real one.
- **✅ QA HISTORY IS BACKED UP (2026-09-13).** `scripts/backup_qa.py`, a QA
  Backup card, and **automatically after every successful promotion**. Content
  and `.ptr` sidecars come back from a sync; the commit history law 6 rollback
  depends on, and `.qa/attic`, do not. Written to the target's `operational/`
  prefix — excluded from sync **and from the drift stamp**, or the backup a
  promotion writes makes the next one abort with DriftError. A failed backup
  never fails the promotion but is reported. See `GIT_IN_THE_SANDBOX.md`.
- **✅ BOTH SOTs CARRY THE SAME VOCABULARY, AND BOTH TREES ARE CLEAN (2026-10-01).**
  The DTS state vocabulary moved to `ops:` and the grounding vocabulary was
  declared where it already was, in `the:` — twenty terms, sixteen of which had
  been in use with no ontology behind them. Applied to QA, then to production,
  where it folded into the unit already staged there: one promotion carrying
  `operations.ttl`, `entity.ttl`'s grounding block, 75 backfill stamps, the two
  `workonsite_*` files and the namespace rewrite. **Rick approved it in
  production the same day.** Both model graphs are 2797 triples; QA and prod
  sandboxes both report zero uncommitted. Production's own gates: 495 assets
  resolve with **0 absent**, 498 vocabulary references with 0 dangling, SHACL
  conforms.
- **✅ THE WHOLE CHAIN RAN IN PRODUCTION ON ONE WORK, BY HAND, IN ~2.5 HOURS
  (Rick, 2026-10-05).** Not a function exercised in isolation — every link from
  a photograph in the drop folder to two curated criticisms in the SOT:
  **work entry** (`work:035abb7e` `a vad:Watercolor`, "Covered Bridge", 15x11 on
  300 lb cold press, branded image); **work edit** (the image repointed when the
  camera's filename turned out to be what the website would publish);
  **annotation** (five TCAP placements — `hasAdditive`, `hasArtistProfile`,
  `hasPaper`, `hasWatercolorPaint`, `hasWatercolorTechnique`); **installed on
  site** and **updateWorkOnSite** (`vad:workOnSite <https://visualartsdna.org>` in
  the scraper snapshot — inventory #9, a sanctioned network effect);
  **DTS twice**, on the chatGPT and Claude criticisms of the same painting, both
  `curation complete`; and **distribution**, including the session's first real
  DELETE through the channel, verified gone from the production bucket.
  **The 2.5 hours is the number Phase 5 needs, and it DECOMPOSES.** Competency is
  to be measured by replaying recorded human sessions through the agent driver,
  never by a model's self-report — so the first end-to-end human timing matters,
  and it matters more that it is honest about what is inside it. Those 150
  minutes are not 150 minutes of authoring:
  - **two defects found and fixed mid-flight**, each a full cycle of
    investigate / fix / test / commit / restart — the attachment embedded in a
    `skos:definition`, and a discarded draft that would not leave the Drafts
    list. Development, not data work.
  - **~21 minutes of REFRESH WALL TIME**, measured from the audit log rather
    than estimated: 17 `instance.command` refreshes totalling **1239 s** across
    three targets (`localhost:80` ×5, `localhost:8081` ×7, `visualartsdna.org`
    ×5), at ~73 s each. The dashboard blocks on every one.
  - **verifying arrival and connectedness through three browsers** — two QA
    servers, a cwva-py and the legacy Groovy, plus production on GCP. Rick:
    "Just to give a complete picture" (2026-10-05).
  So the authoring itself is a fraction of the figure, and an agent replay that
  beat 2.5 hours would mostly be beating a wait. The refresh number is the one
  to act on first: it is already the single largest measured block, and it is
  the same blocking-request problem the review flagged for the proposing stages.
  The two criticism definitions in the SOT are the proof the first fix took:
  both read "write an art criticism of this watercolor, Covered Bridge, 15x11 on
  300 lb cold press" and neither carries a signed URL.
- **✅ THE PRODUCTION DTS IS DONE AND THE RECORD SHAPE IS SETTLED (2026-10-02).**
  Both Three Graces criticisms ran in production and were distributed. Rick then
  read one in the browser and the page, not the pipeline, found four things:
  the grounding nodes moved under `ops:status` (twelve `ground verified` rows
  above the concepts they evidence), the status label reads `curation complete`
  rather than naming the last act, `the:conceptsExtracted` is no longer written,
  and the inline agent declarations are gone — which is the one that mattered
  beyond the page, because three extra named subjects per record had been
  silently excluding every DTS entity from Edit Record and the Drafts index.
  QA and production both carry it; both trees are clean. Rick: "Checked the
  results in the browser, looks clean."
- **✅ RESOLVED 2026-11-19 by the mirror**, which deleted the three QA entities
  and the two QA-only DTS vocabulary files; QA now holds production's two.
  Kept for the history: **QA AND PRODUCTION HELD DIFFERENT CRITICISM ENTITIES
  FOR THE SAME TWO DOCUMENTS (2026-10-02).** DTS was run separately in each, so QA has three
  (`1600f5f9`, `4ed4ff55`, and `74b8c108` from the renamed-copy rehearsal) and
  production two (`5a4a09f7`, `2e82c116`) — same source documents, different
  guids, different derived concept sets. **A refresh will not reconcile them**:
  all three QA entities were distributed to the shadow, and the shadow is QA's
  own SOT, so a sync brings them back. The only way one leaves is a deletion
  promoted through the channel. The same shape as the eight test records that
  kept returning in September.
  **DECIDED: leave it (Rick, 2026-10-02).** "Leave 74b8c108 in QA, there's no
  urgent need to delete it. Besides the thesauri would still be out of synch."
  That is the part a deletion would not fix: the QA run derived its own
  concepts into the thesaurus — `Convex mirror`, `Specular highlight`,
  `Statics`, `Vanishing point`, `Load path`, `Eccentric loading`, `Mudra` — and
  removing the entity would orphan them rather than reconcile anything. The
  two stores diverge in their VOCABULARIES, not just in their records, and
  that is the real statement about what the shadow is.
- **✅ THE SCENARIO RECORDER EXISTS (2026-10-08).** Phase 5 measures competency
  by replaying recorded human sessions through the agent driver, never by a
  model's self-report — and the recordings did not exist, so the measurement
  could not happen. `POST /api/record/start` … work … `POST /api/record/stop`
  writes a `Scenario` to `.qa/scenarios/<name>.rson`.
  Four things it took to be worth keeping, each the answer to something that
  would otherwise have made the corpus useless:
  - **Not the audit log**, which looked like the obvious source. It records
    argument NAMES and elides their values (`"definition": "<315 chars>"`) —
    correct for an audit, useless for a replay. The two answer different
    questions.
  - **Two capture points**, because the dashboard does two kinds of thing:
    every registry tool in `Dashboard.dispatch` (one wrapper, trusted parent,
    unredacted args), and the orchestrator acts the executor also replays —
    `workflow.promote`, `sot.sync`, `sot.adopt` — at the routes, since those
    are law 1 machinery and deliberately not tools.
  - **Reads dropped.** 1622 tool calls in a production day, 23 of them
    authoring; the rest the panel polling `workflow.state`. Classified by VERB
    from the name, so a new `list_*` needs no one to remember.
  - **The ingest recorded as a STAND-IN.** `copy_into` is trusted-side and not
    a tool (law 12), so an ingest leaves no dispatch — and a replay without it
    fails the asset gate on a file that never arrived. Written as an `fs.write`
    of a marker, the convention the committed episodes already use: a recording
    is a shape to re-run, not a copy of the artist's photographs.
  **A recording is NOT a fixture.** It lands in the sandbox under `.qa/`, which
  is gitignored and never converges — the dashboard cannot write to the project
  tree (law 1) — and promoting one to `tests/scenarios/` is a decision a person
  makes. Which is also the honest place for the fact that a recording holds
  whatever the session held.
  The test that matters is the round trip: record a session, replay it into a
  FRESH sandbox, assert the same end state. A recorder whose output does not
  replay is a log.
- **⚠ EIGHT ACCEPTANCE RUNS ARE NOW UNRECORDED** (Entry, Digital, Entity,
  updateWorkOnSite, Annotate, Edit Record, Instance Control, Brand-on-ingest). The
  episode recorder is still unwired, so the reserved human-entry recordings —
  the routing-policy admission seed Phase 5 replays against — do **not** exist.
  This block previously said "wire the recorder before the next acceptance run";
  that instruction has been overtaken twice and is restated here as fact rather
  than left reading like a live plan. **It is a deliberate deferral, not a
  slip:** Rick's sequencing is all record-entry workflows first, recorder after
  (2026-09-04). The cost is known and accepted — capturing live is nearly free,
  reconstructing afterwards is retyping from memory — and it grows by one
  episode per accepted cycle.
- **✅ WIRING CYCLE 4 (updateWorkOnSite #9) COMPLETE AND QA-PASSED (2026-09-10).**
  **The strategy was replaced on evidence.** Both prior designs INFERRED which
  works a site shows: the Groovy matched rendered text against `rdfs:label`
  between hardcoded markers, and the 4.5 rebuild read `/sitemap.xml` +
  OpenGraph. Measured against the real sites: the sitemap 404s on both, and
  OpenGraph is site-level (`og:title` is the site name), so the rebuild found
  **nothing** — while the pages already carry **97 and 25 explicit links** to
  `visualartsdna.org/work/<guid>`, which the Groovy was stepping over as noise.
  Identity is now **declared by the site, never inferred**, and by exactly ONE
  form: the catalog URI `<domain>/work/<guid>`, derived from `work_namespace()`
  so it cannot disagree with the records' own subject URIs. The `?work=work:`
  viewer link and a bare `work:<guid>` in text were matched at first and both
  dropped (Rick, 2026-09-09): the viewer link is an *invocation*, not a claim to
  catalogue the work, and it carried no host requirement; the bare CURIE was an
  invented convention nobody follows. `host` is accepted alongside `domain` for
  a deployment serving its catalogue elsewhere. There is no confidence score
  because there is nothing to be unsure about, and no page image is fetched.
  Narrowing cost **one** work on the real sites, and that turned out to be a
  **broken link on the site** (`…/work/%09<guid>`, a pasted tab) which the loose
  pattern had been papering over via the viewer link — now reported as malformed
  rather than tolerated. `workflows/perceptual.py` is consequently **unused** —
  retained, not deleted, since CE_DESIGN §7.2 still describes the strategy.
  Google Sites offers no metadata channel (every `<meta>` is Google-generated,
  zero HTML comments), so "link each work to its canonical URI" is the CE
  convention — which is what the site already does.
  Works the site names that the store lacks are **reported, never asserted**: a
  triple about a subject nobody can resolve is a dangling reference of our own
  making. **The 6 and 1 seen on the first real read are SHADOW LAG, not a data
  defect** (Rick, 2026-09-09): production is in sync with the sites and is ahead
  of the shadow, so those works exist upstream and simply have not been cloned
  down. Expect a handful of them in dev for as long as the shadow is behind;
  against production the same list means something real, which is why it is
  reported rather than suppressed. **A shadow sync is NOT needed to complete the
  workOnSite TTL** — the snapshot asserts only what the QA store holds, and the
  next sync brings the rest.
- **⚠ THE SANDBOX BREAKS DNS, and that reshaped #9 (2026-09-09).** The first
  real run wrote two EMPTY snapshots. Cause: Landlock confines the worker's
  filesystem, so glibc's resolver cannot read `/etc/resolv.conf` and every
  named-host fetch fails with `EAI_AGAIN` — proven by an IP-literal fetch from
  the worker succeeding. The fetch therefore moved to the **trusted
  orchestrator** (beside ingest, the promotion tail and the ffprobe probe) and
  only a list of GUIDs crosses into the tool: data, not capability. Law 11 in
  CLAUDE.md is corrected — the three sanctioned effects are NOT in the tool
  vocabulary. **This applies equally to the other two members** (post-promotion
  refresh #25, OriginStamp POST #5); neither is wired yet, and both must be
  split the same way. Verified end to end after the fix: **91 and 25 works**
  staged from the real sites, against the legacy Groovy's 87.
- **✅ WIRING CYCLE 5 (Annotate Work #6/TCAP) — DRIVEN END TO END (2026-09-11).**
  An annotation of *Near El Soplador* converged to the shadow and carries its
  `vad:hasWatercolorPaint` triples there. Rick has not given a formal verdict.
 Two pickers and a result: choose a work, choose concepts, and TCAP
  decides which typed property each concept lands on. The user never picks a
  property — offering `vad:hasWatercolorTechnique` directly would ask them to do
  the ontology navigation by hand and be right about it. The review page shows
  what was **placed**, what **tied** (equally specific candidates → hygiene
  ledger, a vocabulary defect not a user error), and what **nothing accepted**.
  Only `vad:`-typed `work:` subjects are offered — 240 of them, disjoint from
  the 136 entities, which belong to the batch path (#15).
  **All 17 concept schemes are offered, not the Groovy's hardcoded six**: that
  list hid five schemes' worth of vocabulary with nothing saying so.
- **✅ EDIT RECORD — QA-PASSED (built 2026-09-11, driven 2026-09-14).** Rick's
  design: editing is **file-based, not instance-based**, because a subject's
  triples are spread across files. That constraint is what makes it safe — the
  editor renders EVERY predicate in the file, so writing the file back whole
  cannot drop what it never showed. A form with a fixed field list would have to
  merge, and on a real watercolour it owns a minority of the predicates.
  Editability is **derived**: one named subject = editable (326 of 334 real
  files); the 8 that are not are exactly the aggregates and system output, so a
  newly generated one is protected the day it appears. Blank nodes by shape —
  labelled edited through the label ("12 inches" → value + unitCode), unlabelled
  READ-ONLY (NFT provenance has no faithful one-line form), empty dropped.
  Verified across all 326: **290 byte-identical after a no-op save, 36 differing
  only by the intended empty-node drop, 0 otherwise.**
  Refined over the QA rounds that followed: `rdf:type`, `schema:identifier`,
  `vad:qrcode` and `schema:dateModified` are **read-only** system fields, each
  stating its own reason; **every save stamps `schema:dateModified`**
  (xs:dateTime, accumulating, sub-second so two quick saves both leave a trace);
  all date fields stay editable so `dateCreated` can be corrected. File fields
  (image / 3D / markdown / PDF, derived by joining each form's `x-file-ref` to
  its predicate) offer **the drop folder only** and **saving ingests** — which is
  what turns "picked the wrong IMG_1234 at entry" from a dead end into a fix.
  `schema:video` is deliberately unreachable: its file sits in a blank node
  beside a thumbnail and title computed from it. The collision check runs
  **before** the ingest, as entry does, with `exclude_subject` so a record does
  not collide with itself — without it a drop-folder file normalising onto a
  stored name silently overwrote another work's image and every gate passed.
  **QA-PASSED 2026-09-14** ("The edit QAs just fine"), including the branded
  image arriving through it.
- **✅ INSTANCE CONTROL (Monitoring tab) — QA-PASSED (built and driven
  2026-09-13/14).** Status, **Refresh** (was "Reload") and **Metrics** (was
  "Stats") against the three servers Rick named: visualartsdna.org (instance-1),
  localhost:80 (pc) and localhost:8081 (wsl). The old card 2 was *labelled*
  `localhost` while its buttons already pointed at :8081, which is how the first
  wiring put card 2 on port 80 and got connection refused with **nothing in the
  server's log** — `localhost` inside WSL2 is the VM, so the request never left
  it. The PC is reached through the VM's default gateway, resolved per call from
  the symbolic host `wsl-host` because that address changes when WSL restarts.
  **The PC runs the original Groovy server (Jetty 11), and the two generations
  put Status in different places** — Python `/status/os`, Groovy
  `/cmd?cmd=stats`, with `/cmd` accepting only refresh|cestfini on the Python
  side. The flavour is declared per target (`api`), never sniffed: the Groovy
  answers a route it does not have with an **empty 200**, so a wrong guess reads
  as a healthy server. An empty body is reported as such for that reason.
  **A drifted clock is indistinguishable from a bad secret** until someone says
  so: the token IS a timestamp accepted within ±30 s, and the PC's Windows clock
  was found 29 s behind — right on the boundary, hence "works intermittently".
  Each result now measures the skew from the response's own `Date` header and
  names it above ~20 s. The remedy is on that machine (`w32tm /resync`).
  **The hub's Monitoring tab IS this page** (Rick, 2026-09-13: "the two pages
  must be resolved into one"). The tab was a second, static copy of Instance
  Control whose buttons only linked here, and it still advertised Stop, Charts
  and :8080 — two descriptions of one thing, drifting exactly as they always do.
  The tab is deleted, `Metrics & Reports` with it at Rick's word, along with the
  card factory and styles that served it. Nothing runs on arrival: a GET that
  reloads an RDF store would also fire on a browser prefetch. **Stop and Charts are gone**, and gone means
  unreachable: no action, no route, no client function, `cestfini` nowhere in
  the source — a dashboard that can shut the production server down is one
  mis-click from an outage, and the button bought nothing a terminal cannot do.
  The three run **in parallel with results displayed individually** (a thread
  per target, `instances.call_all`): a refresh is a full RDF store reload, so
  serial meant waiting through three of them, and one unreachable server must
  not cost the other two their answers. The token scheme is **ported** from
  `tools/cwva_cmd.py`, not imported — dashboard and server need not be
  coresident — and verified against the server's own unmodified
  `util/token.py:validate`, which accepts a dashboard-minted token and refuses a
  two-minute-old one. **A target is resolved by configured NAME, never by a URL
  in the request**: the token authenticates against whatever host it reaches, so
  a caller who could name a URL could spend the user's credential on it. The
  audit record carries action, target and elapsed ms — never the token.
  Two facts worth knowing: the server does **not** validate the token on
  `/metrics` (marked internal in `servlet_base.py`), and `~/.secrets.rson` is
  mode 644 and also holds `geminiKey`.
  **QA-PASSED 2026-09-13/14.** Two defects came out of the run, both about where
  the dashboard was looking rather than what it did: card 2 addressed
  `localhost` from inside WSL2 (the PC is the VM's gateway), and the PC turned
  out to run the ORIGINAL Groovy server, which puts Status at `/cmd?cmd=stats`
  and has no `/status/os`. The third finding was not ours at all — the PC's
  clock was 29s behind against a ±30s token window, which reads as "works
  intermittently"; the dashboard now measures the skew from the response's own
  `Date` and says so.
- **✅ BRAND IMAGE (#7) — DONE AS A PROPERTY OF INGEST, not a page (2026-09-14).**
  Rick: "we don't need brand image anymore because edit record does everything
  needed. It takes a new file, associates it with the record and brands it on the
  way in." Two of the three were true. **The image he tested with arrived already
  branded** — from the legacy Groovy server still running on his PC — and the
  dashboard's copy was byte-identical to the drop-folder file, sha256 and all;
  nothing in `src/` drew a signature. So the conclusion held and the reason did
  not: Brand Image as a *page* is gone (card removed), and the stamp now lives on
  the **ingest path**, which is why RDF Entry gets it too — branding only in Edit
  Record would mean creating a work, then editing it just to brand, which is
  Brand Image again in a different hat.
  `support/ImageMgt2` is ported to the `image.brand` registry tool, verified by
  re-branding Rick's own file: the new stamp landed **pixel-identical** over the
  existing one (size 30, light gray, Arial read from `/mnt/c/Windows/Fonts`).
  Signatures are **derived from `sites`** — `https://visualartsdna.org` →
  `visualartsdna.org`, exactly the Groovy's radio values — and that derived list is
  the tool's `enum`, so offered == enforced. The control is **blank by default**
  because branding is destructive and NOT idempotent, and because Rick's images
  arrive pre-branded today; the review stop reports each branded file by name and
  signature, so the choice is visible rather than remembered. Only files a save
  actually copied in are stamped, never the drop-folder original. The QR +
  `rsart.jpg` overlay (`ImageMgt`, sig=left|right) is deliberately **not** ported:
  its own caller disabled it (`if (false)`), and every work already carries
  `vad:qrcode`.
  **QA'd the same day and corrected once:** Rick changed a record's image to an
  unbranded file and reached the review with it unstamped. The mechanism was
  right — the control rendered, offered both signatures, and the audit showed no
  `image.brand` call because the select was left blank — but the AFFORDANCE was
  wrong twice over: the control sat at the foot of the form below every
  predicate, and the review said nothing about an image that had just arrived
  unbranded. It now sits directly under the image field, and every ingested image
  is reported at the review as branded-with-X or **not branded**.
- **Four infrastructure bugs closed 2026-09-10/13, each invisible until the
  store got big enough to notice.** `refresh()` synced from SOT and never
  adopted, so everything it pulled sat uncommitted and the next promotion swept
  it up (1093 sidecars, nearly 3.7 GB pushed back whence it came). Sync compared
  sha256-hex against a bucket's base64 MD5, so **every** sync re-downloaded the
  whole store — 3.7 GB twice per Approve, which presented as "seems hung". The
  content gates parsed `manifest.all_paths()`, which includes deletes, so a unit
  containing a deleted RDF file crashed the preview. And the ops-quota bug
  recurred a fourth time (`list_editable`); `workflow_tools.file_graphs` now
  exposes the per-file cache for per-file questions.
- **⚠ Annotating a work whose IMAGE is not in QA fails the asset gate.** Not a
  bug — the reference genuinely dangles in this tree — but it means dev QA of
  annotation needs a work whose image is present (132 assets are). Same shadow
  lag as everywhere else; against production it does not arise.
- **▶ PROFILE-DRIVEN ENTRY FORMS — designed and the core PROVEN (2026-09-14).**
  Rick's `dashboardEntryFormApproach.txt`: the entry forms are tailored to his
  artwork, which blocks release; an **artist profile carries a template** and the
  dashboard builds the form from it, with the cards named by profile label. The
  answer to "is that doable" is yes, because two of the three layers already work
  that way — the renderer dispatches on declared affordance, and the submit
  pipeline derives file handling from the schema. The missing third is **how a
  value becomes triples** (eight shapes, hand-written per form), now
  `tools/property_map.py`. Settled in CE_DESIGN §14: templateType is the picker's
  DEFAULT with the picker offering the immediate parent's subclasses; all-required
  plus `vad:dependsOn` for cross-field rules; cardinality from the map, repeated
  triples not `rdf:List`; units from `vad:measurementSystem`; SHACL on the profile.
  **`vad:templateFields a, b, c` was a real bug** — Turtle's comma list is an
  unordered set, and the parallel `vad:required` list cannot survive at all; the
  template carries one blank node per field instead.
  **Proven, not asserted** (`tests/tools/test_property_map_proof.py`): a template
  regenerates RDF Entry with the same fields, the same affordances and the same
  enforced set, and writes a graph **isomorphic to the TTL `record.new_work`
  actually produces**. Two deliberate differences: `units` is gone, and
  `location`/`note` become required.
  **The eighth shape — `schema:video` — is done (2026-09-14), and with it RDF
  DIGITAL regenerates too**: same fields, same affordances, and a graph
  isomorphic to `record.new_digital`'s, VideoObject included. It delegates to
  `_add_video` rather than restating four derived properties.
  **Edit Record now consults the property map, which fixes video editing**
  (CE_DESIGN §14.7, done and **QA-PASSED 2026-09-16** — "The video edit looks
  good"). The editor had typed fields from the
  DATA's shape alone, so a video node — which carries an `rdfs:label` — rendered
  as a one-line text box: the file could not be changed at all, and editing the
  label left `schema:name` stale. A composite predicate is now a file picker,
  and a save rebuilds the node — label and name together, thumbnail and
  contentUrl recomputed, description and uploadDate preserved, duration re-read
  trusted-side rather than carried over. **Deferred by Rick:** editing the video's
  own description, which needs the composite to render a small group of fields
  rather than one.
  Still to build: template parsing from the profile record, the generic
  `record.new`, profile-labelled cards, the artist + artist-profile forms (the
  bootstrap, hand-written).
- **✅ RICK'S TEMPLATE DATA IS IN THE SHADOW SOT (2026-09-16).** `artists.ttl`
  replaced by one file per instance (7 subjects in, 7 out, same GUIDs — the 215
  works citing a profile all still resolve), plus `operations.ttl`: a new
  ontology for UI-and-service definitions, deliberately separate from the visual
  arts model. Every profile carries an `ops:template` — an ordered, per-field
  blank-node list — and every artist carries `vad:brand`. Distributed by hand,
  which is the §13.4c path for model/vocab (the drop folder's allowlist has no
  `.ttl`, and copying into the sandbox is what law 12 forbids), then adopted by
  `api/refresh` — adoption being the part that re-stamps the baseline and keeps
  the next promotion from aborting on drift.
  Reviewed in two rounds before it landed. The first found five files that did
  not parse — a comma for a semicolon in every template, which would have been
  WORSE had it been legal (`ops:property a, b` is one field claiming two
  properties and no order) — plus `vad:dependsOn` for `ops:dependsOn`, two
  classes typed `owl:class`, three profiles sharing one `templateType`, and a
  measurement system stating its unit only in prose. The second round found a
  class that did not exist. All fixed; all four profiles now read.
- **✅ THE READER, THE SHAPES AND THE ARMED GATE (2026-09-16).**
  `profiles.py` turns a profile record into a validated `Template`;
  `config/shapes/artist_profile.ttl` says what a coherent profile is. Reading IS
  validating, because the caller is about to render a form — SHACL for
  structure, the property map for vocabulary (law 3: a template may order and
  select, never define), and two checks SHACL cannot make because they concern
  siblings rather than nodes. `list_profiles` reports the broken ones WITH
  REASONS: a card that silently fails to appear looks exactly like a profile
  nobody created.
  **The promotion SHACL gate is armed at last.** It had been written, tested,
  and passed `None` from the one place that runs it since Phase 4 — a gate
  nobody ran. `load_shapes` returns None rather than an empty graph for an empty
  directory, because a SHACL gate with no shapes conforms to everything and
  would read as armed. Checked before arming: the whole store (423 files, 20,053
  triples) conforms.
- **⚠ FIXTURES CANNOT SEE CONFINEMENT FAULTS (2026-09-16).** Every UX fixture
  builds the app with `enforce_landlock=False`, so the worker reads whatever it
  likes and a whole class of fault is invisible to the suite. It surfaced the
  only way it could: Rick opened a record and got `PermissionError … property_map.py`
  — a handler deferring a first-party import, read from the project tree for the
  first time WHILE CONFINED, where only `sys.prefix` and `/usr` are readable.
  Fixed by importing at module level; guarded by a scan whose scope is derived
  from the registry. A real landlocked smoke dispatch is still not in the suite,
  and that is the actual gap.
- **✅ PROFILE-DRIVEN ENTRY IS QA-PASSED, AND THE CONTENT TAB IS RICK'S
  (2026-09-17/18).** Records created through generated forms; the hub reordered
  to the working set (profile cards, Edit Record, Update workOnSite, Annotate
  Work, Entity, Proof, then the bootstrap forms), SPARQL and the RDF Graph
  Editor moved to Tools, Interpretation and Distribute Data retired — the
  second because every form already ends at the review stop and approving
  promotes the whole staged tree, so a separate publish card was the same button
  with less context. **Preview Staged** gives that tree a door of its own.
- **✅ LEAVING WITHOUT SAVING PUTS THE SANDBOX BACK (2026-09-18/19,
  `promotion/episode.py`).** The behaviour Rick called "counterintuitive and no
  user will understand it": a submit wrote into QA immediately and the review
  stop gated only the SOT, so changing your mind and going to the dashboard left
  the record changed. **Approve & distribute is now the save.** A workflow's
  first write snapshots the tree (staged + `write-tree` + `commit-tree` on
  `refs/qa/episode`, never `git stash create`, which misses an untracked draft
  edited today); an explicit Discard restores it; approving drops it. Scoped to
  what the session touched, so other uncommitted work is untouched, and binaries
  follow their sidecars back out of `.qa/attic`.
- **✅ DRAFTS ARE FIRST-CLASS (2026-09-18/19, `promotion/drafts.py`).** A draft is
  a RECORD, not a pile of paths: the hub shows a count, `/drafts` lists them by
  label, kind and age with the way back into the editor that made each one, and
  `/drafts/view` shows one record's triples and its diff against the last
  distributed version. **Two discards, deliberately different**: *Discard
  changes* undoes the session, *Discard draft* undoes everything uncommitted
  about that record.
- **✅ ANNOTATE WORK EDITS AN ANNOTATION (2026-09-18).** It opens on the work's
  current concepts and replaces rather than appends. Two corrections the real
  store forced: ticking asked the placement rule itself, which needs the
  RDFS-materialized store — **24.3s on Rick's data**, which is why opening the
  page took sixteen — and replacement discarded concepts the picker never
  offered, which silently deleted `vad:hasPaper` from a work because the picker
  was narrowed to two schemes and the paper sat in a third.
- **✅ EDIT ARTIST AND EDIT ARTIST PROFILE (2026-09-19).** Both preserve what
  their form does not own — the personas carry `schema:creator` and
  `foaf:name`, the Blender profile carries a hand-written `ops:dependsOn` — and
  both refuse to touch identity: no `name` argument on the artist editor, no
  `artist` argument on the profile editor, enforced in the tool schema rather
  than on the form. Template edits apply to works made from now on. CE_DESIGN
  §14.10 records the deferred structural fix (`vad:artist` on each WORK at
  entry; 35 of 219 works already carry it) as phase two, at Rick's instruction:
  "finish the dashboard with minimal impact to existing data."
- **✅ A PRODUCTION INSTANCE IS LIVE, AND HAS WRITTEN TO THE REAL SOT
  (2026-09-27).** QA on :8100 against the shadow, PRODUCTION on :8102 against
  `GCP_BUCKET`, selected by `CWVA_DASHBOARD_CONFIG=config/production.rson`.
  Separate sandboxes (`sandbox-prod`, seeded at 2,865 files / 3.9 GB), separate
  audit logs, and a banner on **every** HTML response — amber PRODUCTION, green
  QA — because the two render identical pages against the same `work:`
  namespace and only one of them cannot be undone. **This deliberately gave
  production a writable transport**: it had been openable only as a
  `ReadOnlySource`, which has no `converge`.
  **First production change, converged and verified:** `artists.ttl` (7 subjects,
  no `ops:template` on any of its 4 profiles, so all 4 were unreadable to
  `read_profile`) replaced by per-GUID records imported from QA, which carry
  templates built through the form builder. `+237 -13` triples, every one of the
  13 losses listed and cleared by Rick (deprecated `vad:media`, superseded
  measurement prose). `artists.ttl` is gone from the bucket, the four cards and
  their forms work, and `operational/qa.bundle` exists — the post-promotion QA
  history backup, the one prefix this dashboard creates in production.
  Procedure for using the two instances alongside the legacy dashboard:
  `LegacyToNewDashboardProcedure.md`.
- **✅ TWO FIXES FROM THE FIRST PRODUCTION ENTRY SESSIONS (2026-09-28).**
  *A record collided with its own video.* `Edit form` → fix a typo → submit
  refused the entry, naming "another record" that was the same GUID's first
  attempt, with nothing the user could rename. `exclude_subject` compared the
  SUBJECT OF THE STATEMENT holding the URL, which works for `vad:image` (on the
  work) and cannot work for `schema:video` (on a `schema:VideoObject` blank
  node). Each hit now resolves to the named record that owns it; a different
  work reusing the file still collides, because it would still overwrite it.
  *Edit Record offers entities.* The picker was works-only, so repointing the
  Pillars background image at a 4k JPEG could be done only by typing
  `/edit/open?path=…` by hand. The editor never needed changing — it is
  file-based and preserves verbatim what it cannot render, which is exactly what
  an entity needs. A second group (`skos:inScheme the:entities`, derived like
  the art-form rule), not a loosened filter: artists and artist profiles stay
  out of both, since they have editors that know what a persona owns.
  CE_DESIGN §14.11.
- **⚠ A REFERENCE LIST WENT INTO PRODUCTION AS ONE IRI (2026-09-28, fixed).**
  Nine background CURIEs typed into `the:tag` on the Prestress Images collection
  became one IRI with eight commas in it, because the editor's arity rule —
  right for literals, since `"Woodstock, GA"` is one address — was applied to
  references too. It parses and it serializes, so it was written, committed and
  **converged to the real SOT** with no gate objecting: the same shape as a
  relative IRI. Typed with spaces it failed differently, as a raw serializer
  exception out of a save. Reference fields now split on commas when every part
  is itself a reference, a value that cannot be an IRI is refused at the field,
  and a mis-stored reference is separated on the next save and **reported at the
  review** rather than preserved verbatim. CE_DESIGN §14.12.
  **The damaged record is still in production** until Rick opens it (Edit Record
  → Entities → Prestress Images), saves, and approves; the save reports the
  separation.
- **✅ NESTED BLANK NODES ARE PRESERVED WHOLE (found and fixed 2026-09-28).**
  A no-op save on an artist-profile record through the generic editor wrote
  back 29 of its 78 triples: preservation went exactly one level down, which is
  faithful for the two shapes the editor was written against (a
  `schema:QuantitativeValue` dimension, a `vad:NFT` node — both flat) and not
  for a profile's `ops:template`, a list of `ops:field` nodes hung off a node
  that is itself blank. The file parsed and every gate passed with the template
  gone. **Preserving is the answer, not refusing** — the editor's rule is that
  what it cannot render faithfully is kept verbatim, and verbatim means the
  whole structure however deep; refusing would also block editing the label of
  a record whose internals must not be touched. A no-op save over both real
  trees now changes **nothing** beyond the 36 intended empty-blank-node drops
  per store — the six that changed before (five profiles and the `rdf:List` in
  `topics2.ttl`) are clean.
- **✅ EDIT RECORD IS FINISHED (2026-09-29, CE_DESIGN §14.14).** Five
  outstanding items, four of them found by measuring the editor against the
  real store rather than by using it: the video description is editable (the
  §14.7 debt); a multi-valued file field gets one picker per file, where one
  select over two images swapped both for whichever was chosen; the drop folder
  can be re-read in place, with the record's own file put back as the selected
  option; a labelled blank node is treated as a dimension only when the label
  IS the content, which 906 of the store's 949 are and 43 are not; and a
  read-only structure shows its nesting instead of an rdflib blank-node id.
  A no-op save over both real trees remains clean — 356 and 330 records
  unchanged, 36 intended empty-blank-node drops each, nothing else.
  **One item is deliberately NOT built, because it needs a decision:** the
  editor cannot ADD a predicate. It renders what is in the file, so a record
  with no `the:tag` cannot be given one. Free text is not the answer — the same
  property is what makes overwriting safe — so it would be a closed set of
  addable predicates from the property map. Worth settling before the
  collection work goes further.
- **✅ DTS RUNS HEADLESS, END TO END (2026-09-29/30).** Both Three Graces
  criticisms taken through all six stamps against the real QA store:
  `ai_service/` (law 7, trusted-side, key never retained), the state model,
  the reconciled grounding node, `dts/` stages composing registry tools, and
  `DTS_WORKFLOW.md` as the process spec. Rick's verdict: "the headless DTS
  mechanism looks solid", and — the part that matters beyond DTS — "you've
  demonstrated one of the major goals of this whole development effort, that
  is the AI agent management of the most complex workflows in the dashboard.
  This bodes well for the next phase where agency management is the theme."
  What the real runs taught, all fixed and tested: a reply cut off at
  `max_tokens` is not the same failure as one that spent the whole budget
  REASONING and returned nothing (`effort: low` fixes the second); a derived
  concept must not compete for a tagging slot, because it is discussed in the
  document by construction; a criticism export is a CONVERSATION and a phrase
  from the artist's turn is not the critic's evidence; and DTS is where text
  hygiene stands, because it imports the widest variety of text in the system.
- **✅ DTS IS QA-PASSED AND DISTRIBUTED (2026-10-01).** Rick: "Much happier with
  the tag results. Both summaries are fine. DTS QA is completed." Both Three
  Graces criticisms ran end to end through the CURATION UX — queue surface,
  include/exclude/demote per proposal, accept-or-nothing on the summary — and
  the result is in the shadow SOT across three promotions. Final tally: 3
  derived concepts kept of 24 proposed, 17 TCAP placements with a grounding
  node each, two summaries of 156 and 150 words.
  What the run cost in fixes, each of which is a test now: the curation screen
  re-assesses against the store as it is NOW (curating one document minted a
  concept the other still offered as new, which 500'd on the mint guard); a
  `StageError` speaks on the form rather than as an Internal Server Error; and
  re-assessment is scoped to what the STORE can change, because re-deriving
  grounding against a document that may since have been deleted turns a
  verified proposal into an unverified one.
  **The curation screen shows the sentences around the grounding phrase**
  (Rick's request, and the single highest-value change of the session). It
  caught three defect classes a phrase alone cannot: a concept derived from a
  NEGATION ("Yet the effect avoids becoming a simple symbolic diagram"), twice;
  a concept grounded in the ARTIST's turn rather than the critic's; and a label
  that contradicts its own context (`Kinetic art` on a static sculpture), which
  no check can catch and only a reader can.
- **DERIVATION VARIANCE, MEASURED (2026-10-01).** Rick, on a derivation of a COPY of an already-processed document coming back with a disjoint concept set: "Your derived concept set finding is disturbing. I don't expect repeatability but I do require consistency."
  **The disjointness from the FIRST run is by design, and it is his own rule.** Derivation is given the existing thesaurus in its prompt and proposes what is NOT already there — so once the first Three Graces run minted `Three Graces`, `Prestress`, `Self-Stress State`, `Tensegrity Prism (Tn)`, `Figure as compression member`, `Topology as iconography`, `Cable (Tension Member)`, `Round dance` and `Rotational Symmetry`, the copy's derivation correctly went looking elsewhere and found the optics and statics layer instead. That is why it reported **zero duplicates**. The overlap did not vanish: all nine of those concepts came back in **TAGGING**, 14 of the 22 tags being pre-existing concepts. Which is exactly decision 2026-10-01: "Let's not support second groundings on existing concepts … A subsequent use of a concept should show up in tagging of the document." The consistency is real; it just lives across the derive/tag boundary rather than inside derivation.
  **Run-to-run variance on IDENTICAL input, separately.** Measured by accident — three derivations of the same document against the same store, since derivation writes no concepts and a reset restores the input exactly. Runs 2 and 3 share **8 of 12** labels verbatim (`Figura serpentinata`, `Golden apple`, `Convex mirror`, `Specular highlight`, `One-point perspective`, `Load path`, `Eccentric loading`, `Image-based lighting`), and two more are the same observation under different labels (`Sustained looking`/`Slow looking`, `Gesture of indication`/`Mudra`), so semantic agreement is ~10 of 12. The structural and optical core is stable; the iconographic tail is where it moves. Recorded because it is the number the criteria conversation will want and it is expensive to collect deliberately.
- **▶ POST-DTS, POSSIBLY POST-DASHBOARD: revisit concept DERIVATION CRITERIA
  (Rick, 2026-10-01).** Deliberately deferred — "This is the wrong time to
  challenge the prompt or other derivation criteria, we need to get through DTS
  QA" — and recorded here with its evidence, because the evidence is what will
  make the conversation short.
  Rick read the chatGPT criticism by hand and collected eight concepts with
  grounding: *kinetic coherence, prestress, oscillating experience, traditional
  imagery departure, equilibrium through opposing forces, economical geometrical
  relationship, metaphor and mechanics coincide, differences held in balance*.
  **Opus proposed one of the eight and generified it** (`Kinetic art`), the rest
  of its set being textbook vocabulary: Allegory, Triad, Attribute
  (iconography), Color symbolism, Asymmetrical balance, Centrifugal composition.
  **Sonnet, on the same document, proposed five of the eight** nearly verbatim —
  `Mechanics-metaphor coincidence`, `Difference within balance`, `Athletic
  reinterpretation of classical subject`, `Structure holding the figure
  ambiguity`, `Interdependence as subject` — **and I rejected every one**,
  citing the prompt's own rules.
  So the lever is the CRITERIA, not the model. Rule 8 forbids "ad hoc critic
  phrasings, rhetorical constructions, and invented compound terms" and requires
  an authoritative reference; rule 4 requires reusability across works. Rick's
  target is the propositions a criticism CONTRIBUTES, several of which have no
  Wikipedia article and are not reusable in the obvious sense. The prompt is
  tuned against it, and a stronger model complies harder. Nothing depends on the
  criteria staying as they are: `dts/prompts.py` is one module, ported verbatim
  so it could be changed deliberately rather than drifting.
- **▶ OPEN: `tag_limit` IS ADVISORY, NOT ENFORCED (Rick, 2026-10-01).** "Hit Tag, it came back with 22 candidates, I thought there was a limit of like 10 or 12, I've never seen this many before." The config says 15. The limit reaches the model as a sentence in the prompt (`tagging_message`) and nothing truncates what comes back, so it is a request the model may decline — and on this run it did: **22 tags against `tag_limit: 15`**, while `derive_limit: 12` was obeyed exactly (12 of 12) in the same session on the same document. So it is model compliance variance, not a code path that lost the number.
  The decision is whether a configured limit should be a cap. Enforcing it means truncating the model's own ranking — the prompt asks for "the N most substantively discussed", so taking the first N respects that order — and it means a curator never sees what was dropped. Leaving it advisory means the number in config does not mean what it says. The middle option, and the likely answer, is to clip and SAY SO on the curation screen, so the limit holds and the curator knows a longer list existed.
  **DECIDED: do not clip yet (Rick, 2026-10-01).** "Don't clip the tags yet, the curation is so much better now given the context with the grounding perhaps I can handle more tags. I'll need more experience with it." So the limit stays advisory on purpose, and the thing that changed the calculation is the paragraph context on the curation screen — 22 candidates is a different proposition to review when each one shows the sentences around its grounding phrase than when it shows a bare phrase. Revisit once there is experience of curating a long list, not before.
- **✅ AN IMAGE IS NAMED AFTER THE WORK (2026-10-07).** The rules, as Rick
  stated them, and what each cost to get right:
  1. *On initial entry, the file is renamed to the label.* `IMG_2104.JPG` for
     "Covered Bridge" becomes `CoveredBridge.jpg` — restoring
     `ImageMgt.groovy:179`, reusing `normalize_filename` so there is one naming
     rule, and keeping the real extension rather than the Groovy's forced
     `.jpg`.
  2. *A name collision takes an ORDINAL, not a refusal.* My first cut refused,
     which contradicted a decision already settled the other way — "titles
     legitimately repeat, worth surfacing, never worth blocking". Resolved
     against what is on disk AND what another record cites, minus what THIS
     record cites, or a re-submitted draft bumps its own image every pass.
  3. *On edit, a one-for-one replacement keeps the name it replaces — no RDF
     update, the binary is overwritten.* Which removed a hazard rather than
     guarding it: an edit can no longer write to any name but its own, so
     "editing one record overwrites another's image" is now impossible rather
     than refused. The superseded bytes go to the attic.
  4. *Entity forms do NOT rename* — "Entity has its own rules". An entity's
     image is a REFERENCE to something that already has a name, which the
     entity spec had already half-said about branding. Names are still
     normalized there: "the entity image names must be changed to make them URL
     compatible, i.e., no whitespace".
  Two conditions gate it, deliberately orthogonal: the FORM decides whether a
  file is named after the record (spec flag, beside `qrcode` and `brands`), and
  CONFIG decides which kinds within such a form (`entry_forms.name_from_label`,
  `["image"]`). A document keeps its export name because
  `ChatGPT-…-20261005-1348.md` says which assistant and when.
  **One thing the tests caught that reasoning did not:** a file ALREADY IN THE
  SANDBOX must not be renamed. The ingest has nothing to copy for one, so the
  derived name dangles — law 12's "existing content is never re-processed",
  arrived at from the other direction.
- **✅ AN UPDATED DOCUMENT KEEPS ITS NAME (2026-11-05).** Rule 3 above now covers a PDF or markdown on any record: in Edit Record, whichever drop-folder file is picked supplies the bytes and the cited name stays, because that name is the URL people already hold (Rick: "I'd prefer not to rename an updated document"). The file with the same name gets its own picker option, offered only when its bytes differ, because the drop folder keeps its files and could otherwise put an old copy back. The cost is accepted: this picker can no longer point a record at a differently named document. Two faults fell out with it: Refresh list returned raw names, so a name with a space could be submitted, and a refused save had already copied its file in, where the next approval would have distributed it. The save now validates first, then ingests. **▶ OPEN:** a replaced markdown leaves the record's DTS stamps describing the earlier text. **Added the same day:** Entity Edit offers an empty picker for a PDF or markdown the entity does not cite yet, and a markdown arriving through Edit Record gets its `[id=…]` line, as entry always did.
- **▶ DEFERRED, named by Rick 2026-10-07:** multiple image files on entry;
  multiple image files on edit; and an option to use the drop folder's filename
  "if it passes muster". The first two are why rule 3 is scoped to a genuine
  one-for-one — a multi-slot field has no one-for-one to speak of. The third is
  the inverse of rule 1 and would be a third value for
  `entry_forms.name_from_label` rather than a new mechanism.
  Note the ordinal machinery is ALREADY exercised: the Entity form's `images`
  is an array today, so two files in one field already get `-2`. What is
  missing is multiple images on the WORK forms, which are single-valued.
- **▶ OPEN: AN IMAGE KEEPS ITS CAMERA NAME; the Groovy named it after the WORK (Rick, 2026-10-05).** "I forgot dashboard is not renaming files uniquely after the work's label the way the old dashboard did. I didn't like seeing the google photos name IMG_2104 when I pulled it up in the browser, I was about to grab a copy to post on my site."
  The old rule is one line, `support/ImageMgt.groovy:179`: `def fname = "${util.Text.camelCase(title)}.jpg"` — the work's label, camel-cased, always `.jpg`. And it lived INSIDE `makeStampedFile`, so naming and branding were a single operation: overlay the QR and the signature onto the uploaded file, write the result out under the title-derived name.
  The port split that deliberately — ingest stays a verbatim copy, `image.brand` stamps in place, which is what makes the unbranded original recoverable from `.qa/attic` — and the NAMING did not survive the split. So the record cites whatever the camera called it.
  **The cost is not cosmetic, because the filename is published.** It is the last segment of the IRI the record cites and of the URL on the artist's site, so `IMG_2104.jpg` is what a visitor sees and what a search engine indexes. Renaming after the fact is the awkward path this item was raised from: delete the branded copy, rename the unbranded original in the drop folder, re-ingest, re-brand, edit the work — and the old binary is then an ORPHAN that nothing removes (below).
  Two things to settle, neither obvious. **Uniqueness**: `camelCase(title)` is unique only as far as titles are, and two works may share one; the guid is unique and unreadable. **When**: the name must be decided where the label is known, which is the entry submit, not the drop folder — and `normalize_filename` already runs at exactly that one call site, so there is a place for it to go.
- **▶ OPEN: `vad:hasPrivacyRestriction` DOCUMENTS AN INTENTION NOTHING ACTS ON
  (2026-10-05).** `ttl/provenance/provenance.ttl` holds owner names, email
  addresses and delivery addresses, and carries `vad:hasPrivacyRestriction` to
  say so. The restriction is an assertion INSIDE a file that converges, so it
  travels with the data rather than preventing it travelling. The file is in
  both sandboxes, in the QA git history (permanently — law 6 never rewrites it),
  in the production bucket and in the shadow/test bucket.
  **Not currently exposed**, and verified rather than assumed: neither bucket
  has an `allUsers`/`allAuthenticatedUsers` binding, and no object ACL is public
  — checked on the provenance file, an image and a record. Production has
  uniform bucket-level access DISABLED, so per-object ACLs are live there and
  that check is the one that matters. The protection today is the public cwva-py
  not loading the file, plus private storage; neither is the dashboard's doing.
  Two ways to make the restriction real. `LOCAL_ONLY_DIRS` is the mechanism the
  design already has — add `provenance` beside `evidence` and the file keeps its
  QA git history and never converges; existing copies in both buckets would then
  need a deliberate deletion through the channel. Or a GATE that refuses to
  converge a record carrying the restriction, which generalises beyond one
  directory and is arguably conformance rather than intent (law 5), since the
  record declares the constraint itself. The first is smaller; the second is the
  one that would still work when the next private record is not in that folder.
- **▶ OPEN: `orphan_binaries` IS REACHABLE FROM NOTHING (2026-10-05).** `sot_sync/orphans.py` computes managed binaries no term in the graph references, and it is exported in `__all__` and called by no route, no script and no tool. So an image that stops being referenced — by a repointed `schema:image`, by a discarded record, by a rename — stays in the tree and converges to the SOT with nothing able to report it. Found while working out what happens to `images/IMG_2104.jpg` after the work is repointed at a renamed copy: the answer is that it stays, and that there is no way to ask.
  **A SHARPER VERSION, found 2026-10-29: a file whose NAME Layer 1 rejects is unreachable by the whole tool vocabulary, by construction.** `images/IMG_2056 (1).JPG:Zone.Identifier` — a Windows alternate-data-stream artifact, 25 bytes, promoted to the shadow by accident on 2026-09-14, cited by nothing. `sandbox/paths.py` refuses the path with `RejectReason.INVALID_CHAR` because of the colon, and refuses its `.ptr` sidecar for the same reason, so **`fs.trash` cannot touch it and neither can `fs.read`, `fs.move` or anything else**. It was removed with `rm` and promoted, which is the only route: the `.ptr` is git-tracked so the deletion is visible, previewed and gated like any other.
  Law 10 says a capability is reached by dispatching a registry tool. Here there is no tool to dispatch, because Layer 1 is correctly refusing a name that it would also refuse on the way in — `normalize_filename` at the single ingress would never mint it today. So the class is: **anything that entered before the drop folder was the sole ingress, under a name the sandbox now rejects, is permanent hand-maintenance.** It cannot be listed by an orphan report either, since a report would have to name the path to a tool that will not accept it.
  Two consequences worth holding together. The orphan report above is *missing*; this class would be *unreportable even if it existed*. And a colon in a filename is not merely awkward — it is unusable on Windows, where it marks an alternate data stream, and CE targets both platforms.
  It rides with the naming item above, because a rename is the thing that creates orphans fastest.
- **▶ NEXT PHASE: WHICH TYPE/TOPIC CRITERIA GET DTS (Rick, 2026-10-02).** "There are many entities for documents other than crits that didn't get concepts extracted. I've been drawing a somewhat arbitrary line between criticisms and other types of documents. This is another topic for review in the next phase, what type/topic criteria gets DTS."
  The 13 entities carrying `the:conceptsExtracted false` with no DTS run are the evidence, and they are a list of the line as it stands: `Artist's Statement`, `Pillars` (a background image), `Last Supper Supplement`, `Prestress Series`, `Cenacle HDR`, two cwvaServer-py architecture documents, `Prestress Images`, `Annotation Schemes`, `CWVA Server Retooling`, `Three Graces Legend`, `CWVA retooling summary`, `Sculpture Catalog`. None carries a single `vad:*` placement, so none was ever extracted — the flag is accurate on all 13.
  Some are plainly not candidates (an HDR, a background image). Some are arguable and interesting: `Sculpture Catalog` has 15 `the:tag` references and no placements, and a catalog is exactly the record a CORPUS criticism would attach to — which is the open item about common concepts belonging to the corpus rather than to a work. `Artist's Statement` and `CWVA retooling summary` are prose documents that would derive concepts perfectly well; whether they SHOULD is the question.
  The decision is a rule over type and topic, and it has a natural home: the `concepts_extracted_false` standing query already lists exactly this set, so whatever rule is settled can be expressed as a narrowing of it rather than as new machinery. It rides with the derivation-criteria and thesaurus-hierarchy revisits.
- **▶ POST-DTS: research the THESAURUS HIERARCHY where concepts land oddly
  (Rick, 2026-10-01).** Scheme inheritance is right in principle — a derived
  concept joins the scheme its broader term is in, which 523 of 670 real
  concepts already do — and it mis-files reliably in one case: a GENERIC
  HEADING. `Historical and Conceptual Terms` and `Structural and Analytical
  Terms` live in `the:tensegrityTerms`, so anything parented there inherits
  tensegrity, and `Multiple viewpoints` lives in
  `the:WatercolorCriticismScheme`. Three instances so far, all on digital
  sculpture criticism: `Three Graces` and `Carole (dance)` to
  `tensegrityTerms`, `Occlusion as sculptural device` and `Triad` to
  `WatercolorCriticismScheme`. The question is about the hierarchy rather than
  the rule — whether a generic heading belongs in a material scheme at all —
  so it is modelling research, not a code change, and it rides with the
  derivation-criteria revisit.
- **✅ EVERY WORK IN PRODUCTION NOW HAS A PROVENANCE RECORD (2026-11-02).** 222 records and 3 `vad:StorageSolution`s, generated into `/mnt/c/stage/metadata/provenance/` and distributed by Rick: 31 `vad:FileProvenance` for the digital works from his own `fileProvenanceList.txt`, 190 incipient `vad:Provenance` for the paper works, and one more for `finwin`. `vad:itemId` runs 1–222 unique and contiguous, every `dispositionId` is distinct, and the DI's storage-class component agrees with what the work's type resolves to through the solution records — which is the real content of `PROVENANCE_PLAN.md` §2 made checkable. Coverage is **222 of 222**, verified against the production tree rather than QA's.
  **Validating against PRODUCTION, not QA, is what made the batch correct**, and it caught three things a QA-side check could not. `junk`, `Top VR` and a **duplicate `Fairy Pool 3`** (`f28b42d3`, 2026-09-03 — production has a different one, `0e5bef85`, 2026-08-31, on the same `FairyPool3.jpg`) are QA-only, so a provenance for any of them would have shipped a dangling `vad:hasArtwork` to the SOT; the Fairy Pool record was written and then removed. And `finwin` (`7fa9876c`, a `vad:DigitalPainting` **in** production) had fallen through both batches — absent from Rick's file list, and excluded from the non-digital sweep by its type. Its `DigitalPainting` was in no storage solution either, so its DI came out class-less; Rick added the type to the digital solution and made it `digital.2022.219`.
  **The 6 pre-existing provenance records are TRANSFER records and carry no DI** (§11), so production holds 228: each has a distinct `vad:hasArtworkOwner` — a recipient, not the artist — and their `schema:startDate` is a transfer date, not the work's `dateCreated`. The six works each have a second, incipient record for the disposition. A storage report that filtered on type rather than on "has a two-part `dispositionId`" would wrongly include them.
- **✅ THE PROOF COLLECTION IS INDEPENDENTLY VERIFIABLE, AND IT WAS NOT BEFORE (2026-11-01, distributed 2026-11-02).** `src/cwva_dashboard/proof/` — `merkle.py`, `certificate.py`, `validate.py`, 44 tests — plus `config/shapes/proof_event.ttl` and `PROOF_VERIFICATION.md`. All **24** certificates extract via the JSON route with the search route agreeing, and all 24 records were regenerated with their Merkle paths (18,133 characters of them) and distributed. **The reason this mattered is that every one of the 24 hand-transcribed records was defective**: all 24 timestamps were twelve hours early (a 12-hour clock with the PM dropped), three carried wrong or illegal UTC offsets including a `-21:00`, one borrowed its sibling's transaction, and three `vad:sha256` values matched no file on disk while `vad:dataHash` matched all 24. Rick, on reading the extractor's output: "This is 'proof' I would never manually get these right!" The combining rule is OriginStamp's, not Bitcoin's — `sha256` over the concatenated ASCII **hex strings**, not the raw bytes — which no amount of care would have guessed and which the first real path verified in eleven levels. **Still not built**: the registry tool that writes the record, the standing query for the pending queue, the trusted-side chain lookup for gate 3 (injected, so the gate is exercised without it and reported **not run** rather than passed), and the API adapter if the key request lands. Original framing: Supersedes the API-only framing of the item below. The API would be better for anyone who has a key, but **OriginStamp issues keys by hand after an emailed request**, and a CE user cataloguing their own paintings may be declined — a feature that works only for people who can talk a vendor into an account is not a CE feature. So the **PDF scraper is the baseline and the API an accelerator**, behind one validator. Demonstrated feasible in ~40 lines of stdlib: the certificate's text is two-byte glyph IDs against subset fonts whose ToUnicode CMaps sit in compressed streams, and decoding through them yields the proof JSON intact.
- **▶ DEFERRED, named by Rick 2026-10-31: read proofs from the OriginStamp API instead of transcribing them.** Every one of the 24 `vad:Proof` records has a `vad:timestamp` **12 hours early**, because the certificate renders a 12-hour clock and the PM was lost in copying. Three also carry an offset that is wrong for their date, one of them (`-21:00`) not a legal offset at all. Rick: *"This situation points out the frailty of human data interpretation."*
  originstamp.com exposes an API and a free test key, so the submission and the resulting transaction could be read rather than retyped. **Not a priority** — proof (#5) is itself deferred, and the mitigation is cheap: *"the timestamp is not a required input for finding the proof on the blockchain, just the transaction hash."* So the transcribed dates are convenience, and the verifiable part was never at risk.
  Worth pairing with the standing network rule when it is built: an API call is a network effect, so law 11 puts the fetch trusted-side and hands the pure result to a registry tool — split the way the ffprobe duration probe is, and the way the AAT lookup above would have to be.
  **And one thing no gate can see today:** `rdflib` accepts `"…T08:21:36-21:00"^^xs:dateTime` with `ill_typed=False`. It parses, serializes, round-trips and passes the parse gate. An offset outside XSD's −14:00…+14:00 range is invisible to every check in the system, like a relative IRI or a date lexical form under a dateTime datatype. A literal-sanity check over incoming RDF would catch the class.
- **▶ OPEN: the asset gate's coverage is a HAND-MAINTAINED LIST, and nothing says when a property falls outside it (2026-10-30).** Three instances of one pattern in two days. `scripts/gate_baseline.py` never armed the document family, so 155 `the:mdDocument`/`the:pdfDocument` references were ungated for months while it printed "baseline clean". A zero-byte asset counted as resolved, because "present" meant "exists". And **`vad:asset`** — carried by all 24 `vad:Proof` records, pointing at real `.glb` and `.jpg` files — is not in `_ASSET_PROPERTIES` at all, so those 24 references are unchecked today; they all resolve, and nothing would report it if one stopped.
  All three instances are now fixed — `vad:asset` joined `_ASSET_PROPERTIES` on 2026-10-31, with three mutation-verified tests. **The class is not.** `_ASSET_PROPERTIES` is four properties written by hand, with `schema:thumbnailUrl` excluded in a comment, and a new file-valued property joins the ontology without anything noticing it is unwatched.
  **What would close it:** a test that derives the file-valued properties FROM the ontology — an `owl:ObjectProperty` whose range is a file reference, or more cheaply any property whose values in the store start with the image or documents base — and asserts each is either in a gated family or on an explicit exclusion list. Same shape as `tests/test_script_config_selection.py`, where the scope is derived so a new script cannot miss it, and as the offered-set == enforced-set rule for forms. Deriving the scope is the whole point: a hand-kept list of hand-kept lists has the same defect one level up.
- **✅ DONE by Rick 2026-11-01: dropped the `the:pdfDocument` reference on `work:552759c6-b155-499f-8709-6d7db265ca9b`.** It went out with the proof distribution — "I did remember to put Cups... back, and the pdf ref therein is gone." The zero-byte PDF itself stays on the SOT, now cited by nothing; the asset gate's new zero-byte class is what will name it next time. Original finding: "Cups Study Criticism" cites `documents/CupsStudyCriticism.pdf`, which is **zero bytes** on the SOT. Its `the:mdDocument` sibling, `CupsStudyCriticism.md`, holds the same text at 32,934 bytes and reads fine, so nothing is lost by removing the PDF reference. Accessing the PDF currently fails gracefully, which is why this is a fix rather than an incident.
  **It is a singleton, not a class.** Of **58 `the:pdfDocument` triples, 0 are absent from disk and exactly 1 is zero-byte** — this one. And only that one record cites either file, so the blast radius is one triple.
  **Delete the FILE in the same change, not just the triple.** A zero-byte PDF cited by nothing becomes an orphaned managed binary, and the orphan report that would list it is itself reachable from nothing (see the orphan item above). So removing the reference alone converts a visible defect into an invisible one.
  **And the asset gate cannot see this**, which is the reusable part. The gate resolves a reference by asking whether the file EXISTS, so a zero-byte file passes — 504 resolved, 0 absent, 0 malformed, with an unusable document among them. The only thing that noticed is `verify_shadow.py`, and only because it carries a hand-declared `known:` for this one file. A zero-byte check in the asset gate would be a few lines and would have found this without anyone declaring it.
- **▶ ONTOLOGY HOUSEKEEPING, from the 2026-10-29 QA refresh.** Four findings from running the six-step refresh, three settled with Rick and one blocked.
  **`vad:Proof` joins the model — AGREED 2026-10-29, and SUPERSEDED 2026-10-30 by `ONTOLOGY_PLAN.md` §14**, which makes it `vad:ProofEvent` under `vad:ArtEvent` and finds that the one undeclared class is really an undeclared sub-vocabulary of ten properties. It is typed on 24 records and declared nowhere, the same defect as `vad:PaintApplicationImage`. `vad:DigitalImage` was the other, on one record (`ea8bfb76…`, "Da Vinci"), and Rick is retyping it `vad:GenerativeArt` rather than declaring it — which keeps it inside `vad:ArtForm`, so the §12 storage-class map still reaches it.
  **`vad:fileFormat` is DEPRECATED, NOT DELETED — revised 2026-10-31.** Rick's reason for retiring it stands (a file extension tells a sufficient story), but the term and its 19 triples stay: `owl:deprecated true` in the model, never written again, data untouched. That removes the question of what to do with the 19 triples, and it closes `ONTOLOGY_PLAN.md` §12's list by retirement rather than by a domain change. It was also the thirteenth property on `ONTOLOGY_PLAN.md` §12's open list and the only one never done, so this retires that loose end instead of resolving it. It is in use on **19 triples across 16 records**, which is exactly why deprecation beats deletion: deleting the declaration while the triples remain would recreate the undeclared-term defect above on purpose, and deleting the triples would discard real statements to tidy a term nobody has to use again. Two things to know: `Financial Winds - EURUSD M15` carries three values (JPEG, HTML, GIF) for three artifacts of one work, which extensions on the record alone do not convey; and **`schema:encodingFormat` is already in the data** (`image/jpeg` on the Da Vinci record), so that is the term to reach for if the capability is ever wanted back.
  **`vad:hasCriticism` is NOT safe to delete — BLOCKED 2026-10-29.** Proposed for deletion on the grounds that the `the:tag` method relates work and criticism so the property will never be used. **The property is in use on 50 triples and it is not that relationship.** Its subjects are AI criticism entities and its objects are `skos:Concept`s — "Observational Fidelity", "Structural detail as subject" — so it records which critical concepts a criticism raises. **None of the 50 is duplicated by `the:tag`**, which relates work↔criticism instead. Deleting it loses 50 statements nothing else carries. The name is what misleads; if anything here is wrong it is the name, not the property. **RESOLVED 2026-10-29: rename, do not delete** — recorded as cwva-side debt in `ONTOLOGY_PLAN.md` §13, with the candidate names and the blast radius. It is **DTS output**: TCAP writes it when placing a criticism-flavoured concept, selecting the property by `rdfs:range vad:ArtCriticism` rather than by name — so the rename is safe for navigation, but 9 references across 4 test files hardcode the name, and the range must not move with it.
  **✅ BOTH OPERATOR-SCRIPT CONSTANTS ARE FIXED** — `seed_shadow_sot.py`'s cost note on 2026-10-29, and `verify_shadow.py`'s baseline re-frozen twice since: 2026-10-29 after the full re-seed, and **2026-11-02 (`b81c429`) after a PARTIAL one**, which is what finally made the per-path freeze boundary load-bearing. `ttl/` was taken from production on 11-02 and the other roots on 10-29, and one date cannot describe both: the `--compare` classifier keys an object's `time_created` against the moment its path was cloned, so a single boundary would read either 382 fresh records or three months of image drift as the wrong thing. `METACONTENT_PREFIXES` became `RESEEDED_PREFIXES` — `ttl/data` is 382 records and calling them metacontent would misdescribe them. Baseline 1,761 → 1,985 objects. The original finding: dates from 2026-07-19 content / 2026-09-04 metacontent, so `--compare` now reports every legitimate change as a deviation and its shadow-only classifier reads a deliberate re-seed as 1128 dashboard promotions — it keys on `time_created`, which a re-seed resets. Re-freeze to 1766 objects / 3,938,716,223 bytes to make the check mean something again. And `seed_shadow_sot.py`'s cost note records 392 objects / 1.5 MB / 119 s and says the clone is latency-bound so time scales with object count; the 2026-10-29 run was **1741 objects / 3.93 GB / 960 s at a steady 4.09 MB/s**, i.e. bandwidth-bound. Anyone budgeting from that docstring is off by roughly eight times. **Its prefix argument is the mitigation and is not mentioned where it matters:** `seed_shadow_sot.py ttl/` skips 1115 image objects and nearly all the bytes, which is the difference between sixteen minutes and a moment for a metadata-only change.
- **▶ DECLINED by Rick 2026-10-27: three legacy aggregate record files stay aggregated.** `ttl/data/art.ttl` (33 subjects), `ttl/data/archivo.ttl` (9) and `ttl/data/digitalRspates.ttl` (5) — 47 records that Edit Record cannot open (one named subject required) and that the Drafts page can only list as `art.ttl (33 subjects)`. `scripts/split_aggregate.py` would do it. **Do not, unless a significant structural change affects them**; these are very early CWVA legacy and the chance of needing to edit any one is indistinguishable from zero.
  The criterion has already been tested: the 2026-10-27 ontology lift *was* a significant structural change, it did touch `digitalRspates.ttl` (Da Vinci needed `vad:CreativeWork`), and the edit was applied in place without splitting. `art.ttl` and `archivo.ttl` were not touched at all. So the rule holds — raising this again needs a change that cannot be made in situ, not merely one that reaches these files.
- **▶ SUPER-LOW PRIORITY, declined by Rick 2026-10-27: 70 entities carry materialized ancestry.** They are typed leaf + `the:Entity` + `skos:Concept` + `rdfs:Resource` where the newer 87 carry the leaf alone. Deliberately NOT part of the ontology lift. Rick's reasoning, and it is sound: **the hierarchy is not wrong** — `the:AI rdfs:subClassOf the:Entity` is real, `skos:Concept` is entailed by `skos:inScheme` whose SKOS domain it is, and `rdfs:Resource` is RDFS — so these are true statements, merely redundant. Redundant-but-true ancestry only costs anything if the hierarchy later moves, and `the:Entity`'s is not going to. It is also a **closed set**: `record.new_entity` writes exactly one `rdf:type` (guarded by `test_an_entity_carries_EXACTLY_ONE_rdf_type`), so it cannot grow.
  Note this is the OPPOSITE action to the work forms, where `vad:CreativeWork` is written explicitly — there it is a *sibling* of the leaf under `vad:ArtRealization`, so nothing entails it. Same leaf rule, opposite consequence. Applying the work habit to entities would re-add what this item would remove.
  **One genuinely different case rides along, 7 records**: `Artistic Style`, `Artistic Aesthetic`, `Watercolor Methodology`, `Tensegrity Toroid`, `Tensegrity Prism Chirality Aesthetics`, `Tensegrity Prism Chirality Physics` (all `skos:Concept` only) and `FX Fluke` (`the:Entity` only). These have **no leaf at all**, so stripping is not the fix — a type has to be chosen. Harmless today because Edit Record's group rule reads `skos:inScheme the:entities` rather than the leaf, but it is likely to surface when the deferred **DTS type/topic eligibility criteria** are defined, since that is the first thing that will ask what kind of entity a record is.
- **▶ DEFERRED, named by Rick 2026-10-24: align the THESAURUS to GETTY AAT.** `skos:exactMatch` / `skos:closeMatch` from the project's own concepts to the Getty Art & Architecture Thesaurus, so a locally-defined concept becomes a globally-identified one. Raised out of the CIDOC-CRM discussion and recorded in `ONTOLOGY_PLAN.md` §10, which rejects CRM *class* alignment for now and names this as the external alignment with the better ratio.
  **The habit already exists and is pointed at encyclopaedias.** The QA store holds **947 `skos:Concept`s** and **245 external `skos:*Match` triples** — but they go to Wikipedia 192, DBpedia 28, CAMEO 18, Tate 2, and **Getty 4, AAT 2, VIAF 0, ULAN 0**. Wikipedia is good for a human reader and weak for machine interoperability with cultural-heritage systems, which is the whole gap. The 18 **CAMEO** matches are the right instinct already applied once — a conservation-science vocabulary for material concepts — so this is extending an established practice rather than starting one.
  **Why this and not CIDOC-CRM class alignment.** A CRM alignment is inert inside the dashboard (no reasoner, and the gates do not resolve external IRIs), so it is a publication decision whose value arrives only when a submission to an aggregator is contemplated — and it does not get more expensive with time, which is the argument for deferring it indefinitely. AAT alignment is incremental, additive, needs no hierarchy change and no migration, and pays per concept.
  **Scope caution, because forcing a match would be worse than none.** Many of these concepts are deliberately practice-specific — `happyAccident`, `IterativeGlazing`, `Lantana_20250918` — and have no AAT equivalent by design. The candidates are the general terms, which are roughly the set already matched to Wikipedia; an `exactMatch` asserted where only a family resemblance exists would corrupt the thesaurus more than the absence does.
  **It belongs with the DTS/vocabulary cluster above**, because the natural shape is DTS *proposing* a match for confirmation rather than hand work over 947 concepts — which makes it an AI feature subject to the structure-not-strings test, and which also waits on the **vocabulary authoring surface that does not exist** (nothing in the dashboard can author a vocabulary change today). Proposing an external IRI also touches law 11: resolving an AAT candidate is a network effect, so the lookup would have to be trusted-side with the pure result handed to a registry tool, the way the ffprobe probe is split.
- **FIXED, and the test is the point: an operator script must be POINTABLE (2026-10-01).** `gate_baseline.py`, `backup_qa.py` and `reset_to_baseline.py` called `cfgmod.load_config()` with no argument, so they honoured neither `--config` nor `CWVA_DASHBOARD_CONFIG` — the variable that selects the production instance. They were hardwired to QA and accepted a `--config` in silence. I ran `gate_baseline.py --config config/production.rson` and read QA's gate numbers as production's.
  The dangerous one is `reset_to_baseline.py`, which OPERATIONS.md marks **destructive, both sides**: pointed at production it would have rolled back QA and reported success. Three more scripts took the flag but ignored the environment variable, so the two ways of selecting a deployment disagreed — including `migrate_dts_vocabulary.py`, written in this same session.
  `tests/test_script_config_selection.py` derives its scope from the scripts directory, so a new script cannot miss it, and it checks the two shapes separately: that the flag exists, and that no `load_config()` is called with no path — because a script can parse the flag and still call the bare form, which is exactly what `dts.py` did.
- **▶ OPEN: MANAGING TAGGING NEEDS TO BE REVISITED (Rick, 2026-10-01).** Raised as a note for later, from the entity form after a queue-0 generation: "on this entity form for the tag I would expect to see the label for the work rather than the CURIE, however, that may not be true of all entity forms in all situations." Both halves are the item — the CURIE is the symptom, and the caveat is the reason it is not a one-line fix.
  A reference field renders its raw value, which reads as `work:4dd85266-…` for the work a criticism is about. Edit Record resolves a reference to its label where it has one to resolve (`affordance.py` for `x-vocabulary`, the referents table for a picker), and `the:tag` on an entity gets neither, so it falls back to the value. Resolving it is the same lookup `_dts_works` already does, which is what makes it look trivial.
  **DISPLAY ONLY.** Rick, correcting a reading of this: "I never intended for the label to inhabit the:tag property — just the label w/r.t. that CURIE." The property keeps the IRI; the form shows the label beside it. Nothing about this item changes what is written to a record.
  **Measured before guessing.** `the:tag` is general-purpose: 331 statements in the QA store across eleven type signatures — 90 Watercolors, 56 Images, 40 BlenderCompositions, 31 AI entities, 9 ConceptSchemes, 8 Operation records, Studies, bare Concepts — so the object is often not a work. But **327 of the 331 carry an `rdfs:label`**, so resolving one never needed to know which kind of thing it points at, and the display fix does not wait on the tagging model. A label alone can be ambiguous where a CURIE is not (an Image and a Watercolor may share one, and 4 objects have no label), so the answer is the label *beside* its identity rather than in place of it.
  **THE RANGE BELONGS IN SHACL, NOT IN THE ONTOLOGY (Rick, 2026-10-01).** "`the:tag` has a broad range; in conventional use it only refers to objects, not xsd datatypes. SHACL would be the right place to rein that in, rather than a constraint on an ontology that will never meet an owl reasoner." The convention holds in the data today — **331 of 331 objects are IRIs, none a literal and none a blank node** — so a shape would be a guard against the first violation rather than a repair of existing ones.
  And the reason is sharper than "OWL is inert here": `rdfs:domain` and `rdfs:range` are RDFS, which this stack *does* run ("the rdfs reasoner adds the related types"), and RDFS range does not CONSTRAIN — it ENTAILS. An `rdfs:range` on `the:tag` added to restrict it would silently assert that every object is a member of whatever class was named, which is the opposite of reining it in, and nothing would report a violation because there is no violation to report. Only SHACL rejects. The dashboard already runs a SHACL gate on every promotion, armed from `config/shapes/` — which today holds `artist_profile.ttl` alone, so a `the:tag` shape would be the first shape there asserting general record conformance rather than the dashboard's own requirement about a profile.
  Rick's framing is the scope: **"Managing tagging needs to be revisited."** It sits with the derivation-criteria and thesaurus-hierarchy revisits, and shares a boundary with the demotion queue below, since all four are places where DTS and vocabulary management overlap with no settled owner.
- **▶ OPEN, AND WIDER THAN IT LOOKED: THE NEW DASHBOARD CANNOT AUTHOR A
  VOCABULARY CHANGE AT ALL (Rick, 2026-10-05).** Correcting a first reading of
  this as a missing merge/demote tool: "the edit was made in the old dashboard
  staging because new dashboard has no means to distribute a manually edited
  vocab file." Measured, both halves:
  - **Edit Record refuses a vocabulary file**, correctly — `watercolor.ttl` has
    **111 named subjects** and the editor is instance-scoped by the
    one-named-subject rule (§14.11). It is not a bug in the editor; a vocab
    file is an aggregate and the editor is deliberately not one.
  - **The drop folder allowlists no `.ttl`** — image, model3d, video, markdown,
    pdf. Also deliberate: law 12 treats the folder as hostile, and a dropped
    TTL asserts arbitrary triples anywhere in the graph, which is a different
    trust proposition from a JPEG. Widening the allowlist is therefore NOT the
    obvious fix.
  So the only things that write vocabulary are the tools DTS calls
  (`dts.write_concepts`, the derivation curation UX). A person who wants to fix
  a definition, correct a label, re-parent a concept, retire one or merge two
  has **nowhere to go in the new dashboard** and must use the Groovy one — which
  then writes the same SOT out of band and costs a `/refresh` on both instances.
  **The surface, sketched by Rick (2026-10-05).** Not fields — OPERATIONS, which
  is what separates it from Edit Record: the user states intent once and the
  tool keeps the graph consistent.
  - *add a concept* · *edit a concept* · *delete a concept*
  - *merge two concepts*, "which would handle the edit/delete for you"
  - *scheme membership*
  - *broader assignment* — an association between two concepts
  - *an RDF graph editor over a file or set of files, to visually understand the
    relationships, as in old desktop*
  Four things already settled that will shape it, so they are not rediscovered:
  **(1)** Each operation is a registry tool and the UX composes them (law 10);
  `concepts/merge_demote.py` is the placeholder that has been waiting for this.
  **(2)** Delete and merge are REFERENCE-AWARE or they are wrong — retiring a
  concept a record cites leaves a dangling term. The `vocabulary_reference` gate
  catches it at the review stop, but a gate is the backstop; the editor should
  say what cites the concept BEFORE the act, which is the `referents.py` rule
  that the offered set and the enforced set are one answer to one question.
  **(3)** The write is CONCEPT-SCOPED INSIDE AN AGGREGATE — a new shape here.
  Edit Record writes a whole file with one subject; this touches one subject
  among 111 and must leave the other 110 byte-identical, which is the verbatim
  rule turned inward.
  **(4)** *broader assignment* is the lever the thesaurus-hierarchy research
  needs (below): concepts land in odd schemes because scheme is INHERITED from
  the broader term, so a surface that makes the broader edge visible and
  editable is how that gets fixed rather than studied.
  The merge Rick ran by hand on 2026-10-05 — altLabel onto the survivor, the
  loser's five triples removed from `watercolor.ttl`, reference rewrite checked
  and empty — is the worked example to build against.
  **The live instance**: `the:chargingClear` retired and merged into its
  survivor, edited in the old dashboard's staging and NOT yet distributed. Both
  new sandboxes still carry it, both clean.
  Two consequences that are not about the merge itself. Distributing out of band
  writes the same SOT, so the next promotion from either new instance hits the
  `DriftError` in `apply.py` — correct, and confusing if the reason has been
  forgotten; the recovery is `/refresh` on BOTH instances, which is destructive
  of work in progress and therefore wants a clean tree first. And the reference
  half has a backstop even while the tool is missing: a record still citing a
  retired concept fails the `vocabulary_reference` gate on the next promotion,
  so the store cannot quietly keep a dangling term. (No rewrite was needed this
  time — "the work references the survivor concept of the merge".)
- **▶ OPEN: concept DEMOTION needs a status and a queue (Rick, 2026-09-30).**
  DTS curation and vocabulary management overlap, and the overlap has no home.
  A curator looking at a proposal sometimes wants a third answer beyond keep
  and reject: *this is an altLabel of something we already have*. That is a
  workflow item, so it needs a way to assert the status during curation and a
  queue that carries it until someone acts. **The concrete instance to carry:
  `the:SelfStressState` is redundant with `the:Prestress` and should be an
  altLabel on it** — from the first DTS run, recorded here so it is not lost
  with the discarded draft. Acting on it is `concepts/merge_demote.py`, still
  NOT YET.
- **A COMMON concept belongs on the CORPUS, not on a work (Rick, 2026-09-30).**
  Correcting my reading: `the:Node` and `the:Cable` are not absent from most
  works because they were passed over — they are *true of all of them*, which
  is exactly why they do not differentiate. "Those concepts would be better
  placed on a catalog of the works or more likely a criticism of the catalog.
  That would distinguish the works as a corpus." So the differentiator rule is
  deliberately NOT mechanized, and the implication is a criticism whose subject
  is the corpus rather than one work — which decision G (criticism of a
  collection is out of scope) currently excludes.
- **▶ DTS (derive / tag / summarize) IS IN DESIGN, NOT BUILT (2026-09-25/26).**
  `Workflows2.txt` is Rick's specification; **`Workflows2_REVIEW.md` is the live
  design record** — settled decisions with attribution, open questions, and the
  measurements they rest on. Three rounds are done. Settled so far: one rule per
  queue state; per-entity state as stamps in an `ops:status` blank node;
  distribution implied by finishing a step; tagging through TCAP; include /
  exclude curation rather than editors; the concept agent (`/mnt/c/work/python/
  concept_agent.py`) integrated directly with its thesaurus read **from the QA
  store**, not from the running server's SPARQL endpoint; grounding recorded in
  blank nodes carrying phrase, match, match TYPE and source entity; the orphaned
  -concept backlog in `evidence/`. **Still open and blocking: the state model**
  — the exact stamp sequence, who writes the computed label, and whether a
  re-run overwrites or accumulates. The queue rules cannot be written until
  those exist. Two things must be fixed before the first run: `evidence/` is
  **not** excluded from convergence (only `operational/` is), and there is no
  ingress for a `.ttl` — the drop folder allowlists image, model3d, video,
  markdown and pdf, so hand-authored model and vocabulary files have no
  legitimate way into the sandbox.
- **⚠ OPEN: a built template can name a 3D image and no background**
  (2026-09-17, CE_DESIGN §14.8b). The builder emits `ops:required` and never
  `ops:dependsOn`, so the mutual-dependency rule — which works, and is tested —
  can only be stated by hand-writing a profile. Rick: "Let's leave it for now but
  make a note to review the approach." Three candidate fixes are written down,
  the cheapest being to treat known pairs the way the browser minimum is already
  treated.
- **NEXT, in order:**
  1. **Profile-driven entry forms are DONE and QA-passed** (CE_DESIGN §14,
     closed 2026-09-17/20). The property map, reader, shapes, armed gate,
     per-profile tools, cards, `vad:brand`-driven branding, the bootstrap forms
     and now the two editors. What remains around them is listed in §14.10 as
     phase two, not as unfinished work.
  1b. **Editing the video description is DONE** (§14.14, 2026-09-29), which
     unblocks AI-drafted video descriptions (§10.7) — a draft nobody can
     correct is worse than none.
  2. **Entity creation's AI-gated inputs**, then the AI-dependent workflows
     (critical analysis derivation, Derive Concepts, Tag Markdowns, Summarize).
     These need `ai_service/` — Phase 5 Stage A — and are the natural boundary
     of 4.7.
  3. Carried from 4.5, still open: mid-convergence failure per transport, the
     Windows CI runner (**CI is disabled on GitHub**, failures uninvestigated),
     the SOT-side orphan report test, three deferred standing queries.
- **Done:** the affordance layer (enforcement *and* rendering, through the real
  forms), the shadow→QA sync, the layout binding, the human-driven promotion
  tail with its review stop, **RDF Entry wired from `function.html`**, the drop
  folder (law 12), discard-work-in-progress, and Edit-form (replaced Reject:
  repopulates and trashes the draft, so a correction is not a retype).
- **The form takes its wording from the ONTOLOGY**, resolved per render:
  `rdfs:label` captions each field, `rdfs:comment` explains it, and editing the
  model changes the form with no restart. Date fields append the format, read
  from the **browser's** Intl data so the hint cannot disagree with the picker.
- **Uniqueness at entry:** a reused asset filename is an **error** (it would
  overwrite an existing work's file on convergence) checked *before* the
  ingest, with an in-place "Refresh list" so renaming does not cost the form;
  a reused label within a type is **advice**, shown and overridable. Covers
  **every** ingested file — image, 3D object, video — since 2026-09-06, when a
  reused `.glb` was found to pass unchecked beside a correctly refused `.jpg`.
- **✅ WIRING CYCLE 3 (RDF ENTITY) COMPLETE AND QA-PASSED (2026-09-09).** The
  first genuinely MULTI-VALUED form: topics as a checkbox grid from the
  TopicScheme (the Groovy's own layout), images as a multi-select that keeps the
  Refresh-list control, tags as free text, and notes as repeating {kind, text}
  rows. No QR — an entity is not a work, and minting one would leave an orphan
  JPEG the next promotion sweeps up.
- **Two manual operations absorbed by the dashboard (2026-09-07).**
  **Filenames are normalized on entry** for every file field on every form —
  `Unmoored Swing.jpg` → `UnmooredSwing.jpg`, by the Groovy's own camelCase +
  ASCII-fold rule. The reason is not tidiness: the name is joined to the image
  or documents base and becomes the IRI the record cites, where a space is
  invalid. Uniqueness is checked AFTER the rename, two files normalizing to one
  name are refused (neither is in the store yet, so no record-level check can
  see it), and the rename is reported on the review page where Edit form is one
  click away. The drop folder keeps its own names.
  **Markdown is stamped with the record's CURIE** — `[id=work:<guid>]` on line
  2, the convention 5 of the 70 documents in the store follow — via the new
  `doc.set_id` registry tool, so the derivation workflow has the same capability.
- **Tag references are resolved and REPORTED at the review stop (2026-09-09).**
  `record.resolve_tags` looks up each `the:tag` in **both** stores — 175 of the
  186 real tag triples point at content records, 11 at thesaurus concepts — and
  the review page shows each one's label, since `work:53bfd31d-…` tells a
  reviewer nothing about whether the right thing was tagged. **Advisory, not a
  gate:** a tag may legitimately run ahead of what it names (a work tagged into
  a series collection created afterwards), and the store already holds one
  dangling tag among 186. A record with NO tags gets its own explicit line —
  the commonest tagging mistake is forgetting, and silence reads as success.
- **Filename collision is checked CASE-INSENSITIVELY (2026-09-07).** As IRIs
  `Sunset.jpg` and `sunset.JPG` differ, and on Linux/GCS they are two files —
  but on Windows and default macOS they are one, so the second ingest overwrites
  the first work's image with no warning. CE targets both, so the answer must
  not depend on the platform. **The store already holds the case in point:**
  `Sunset.jpg` ("Sunset") and `sunset.JPG` ("Just past 6 pm") are two different
  paintings, neither image currently present in QA. Worth resolving before those
  two records are ever promoted from a case-insensitive machine.
- **Cycle 3 field revisions (2026-09-07, from the first look at the form).**
  `media` renamed **`topic`** — it was the Groovy's name for the field and put
  the word "media" above a grid of topics, matching nothing in the record.
  **`the:document` removed**: it held a Google Docs link, and those references
  are not dependable enough to record. **`the:dbpedia` removed**: the wikipedia
  link covers the same referent readably, and a dbpedia URI fits `primary_site`
  (`schema:sameAs`). Old records keep both; neither is gated.
- **Two Groovy behaviours deliberately NOT reproduced in cycle 3.** The gdoc
  download (`md`/`pdf` fetched from Google Docs) is network I/O outside the
  three sanctioned effects (law 11) *and* would name a document that never
  reaches SOT; the CE shape is law 12 — drop the file, the dashboard ingests it,
  so `md_document`/`pdf_document` are drop-folder pickers. `markdown` and `pdf`
  are separate inbox KINDS, because one "document" kind let the .md picker offer
  a .pdf. The asset gate gained the DOCUMENT family to match, with the
  managed-binary test relaxed for it (.md is git content, .pdf is pointer-
  managed, and both must resolve).
- **`validate_args` now recurses into object items.** Note kinds were a
  form-only closed set — the schema said so in its own description — so
  `skos:<anything>` was mintable by any caller that was not the form. Offered ==
  enforced needs the enum to be real.
- **⚠ FOUND AGAINST REAL DATA, and fixed: `schema:contentUrl` is context-
  dependent.** Seven records use it on the WORK to name the site page it appears
  on (`https://www.art.visualartsdna.org/`); the video work added it as an asset property
  unconditionally, which would have failed the asset gate on all seven the
  moment one was promoted. It is now gated only when its subject is a
  `schema:VideoObject`. The whole real store now reports **0 malformed**. Note
  those seven look like an early form of updateWorkOnSite (#9) — worth a look
  when that cycle comes up.
- **`vad:fileFormat` DROPPED from the digital form and new TTL (2026-09-06).**
  Rick checked cwva-py: the property is never read — every file-format decision
  at serving time comes from the file extension and its mimetype. It was a
  display-only literal restating the filename, so the form was asking for a
  value nothing consumes. Old records keep theirs; absence breaks nothing
  downstream. **This supersedes EXTRACTION F2** (which tightened `file_format`
  to a strict enum on the evidence of the active data) and the AFFORDANCE_DESIGN
  rows that cite it as a static-enum example — both are correct as history and
  stale as description. A faithful port is faithful to what the system *does*.
- **✅ WIRING CYCLE 2 (RDF DIGITAL) COMPLETE AND QA-PASSED (2026-09-09).** Adds
  `image3d` (glTF/GLB), `schema:video` (MP4/WebM/Ogg, duration probed from the
  file with ffprobe trusted-side), and `background` as a **content-sourced
  picker**: entity records typed `the:Image` with `the:topic the:Background`,
  37 of them in the real store. A 3D object now **requires** a background —
  a cross-field rule, so it is enforced in the tool (the agent authors these
  records too) and surfaced on Create record, not by an asterisk that would lie.
- **Referent conditions live in `referents.py`, read by BOTH the picker and the
  gate.** They were two hand-kept tables agreeing only by comment; that is the
  same drift that let the `.glb` past the collision check the same week. The
  gate now also checks `vad:background` — deferred until now for being
  *undefined*, not expensive — loading content dirs lazily, only when a
  content-sourced referent is actually referenced.
- **DEFERRED, by explicit decision (2026-09-06): background COLLECTIONS.** The
  fuller story is that a digital work is displayed with *alternate* backgrounds,
  reached by tagging the work into a `the:Collection` (e.g. "Unmoored
  Collection"), which is itself tagged to a collection of background images
  (e.g. "Unmoored Background Collection" — three such collections exist in the
  store today). So the background chosen at entry *ought* to belong to the
  collection associated with the work's eventual series — an association that is
  usually created **after** the record exists. Entry therefore offers **all**
  backgrounds and checks only that the referent is a background. Revisit digital
  works when collections are developed; do not bolt a half-rule on before then.
- **`GET /api/refresh` → `{"status":"OK"}`** now makes the running server
  current: sync SOT→QA, reload the ontology and thesaurus, rebuild the registry
  **and** the worker's, so what the form offers is what dispatch enforces.
  `?detail=1` for the evidence. **Two hops, not one** — production reaches the
  shadow only via `seed_shadow_sot.py`; refresh alone will not see a production
  edit.
- **`shadow_sot.qa_only`** holds model changes deliberately ahead of production:
  the seed refuses to overwrite them, and `verify_shadow --compare` lists them
  as a reconcile set instead of calling them clone defects.
- **Next action — SEQUENCING DECIDED 2026-09-03 (Rick): all dashboard
  workflows first, scenario recorder after.** Wire RDF Digital, Update work on
  site, Annotate Work, Entity creation, then the AI-dependent workflows
  (critical analysis derivation, tagging, summary), and only then the recorder.
  **Why this beats recorder-first**, which was the earlier recommendation:
  `reset_to_baseline.py` makes acceptance runs repeatable on both sides, so an
  un-recorded run is a run that can be re-driven, not lost work — and a recorder
  designed against the full set of function areas will fit them better than one
  fitted to RDF Entry alone.
  **The cost, stated so it is a choice and not a surprise:** every acceptance
  before the recorder exists must be re-driven to be captured, and the 4.7 exit
  gate still requires an episode per accepted step. The debt grows one episode
  per cycle.
- **Blocking gates:** none.
- **Entry defaults** come from config: `type` preselects Watercolor
  (`entry_forms.work.type_default`, validated against the ontology enum) and
  `has_artist_profile` prefills from `artist_profile`.
- **Discard work in progress** (`/wip/discard`, hub card): a promotion unit is
  everything uncommitted since the baseline (law 4), so abandoned submissions
  accumulate and ride along with the next entry. This empties the pile —
  QA working tree only, never history, never SOT.
- **The dev loop (rehearsed end to end 2026-08-25):**
  `uvicorn cwva_dashboard.main:create_app --factory --port 8100` →
  http://127.0.0.1:8100/ → RDF Entry → approve →
  `python scripts/verify_shadow.py --compare` →
  `python scripts/reset_to_baseline.py` puts **both** sides back so the same
  entry can be run again. Verified: the bucket returns byte-identical to
  baseline.
- **THE AFFORDANCE LAYER IS LIVE; the activation checkpoint is COMPLETE**
  (every box measured, none inferred): `type` is a strict enum of 11 / 9 from
  the synced ontology, the vocabulary picker returns 11 real thesaurus
  candidates, the file-ref picker hides `.ptr` sidecars, and the two-gate
  baseline is 469 absent / **0 malformed** / **0 dangling**.
- **Drop folder:** `~/cwva-py/stage/data` — where the user puts JPEGs and MD
  destined for the repository (law 12). **The user never touches the sandbox**;
  the entry form lists **only** this folder and copies the selection in on
  submit. Holds `FairyPool3.jpg` and `Test-EasternTigerSwallowtail.jpg`.
  (Offering the sandbox too was a design error — it surfaced generated QR codes
  as selectable source images; fixed `32379b3`.)
- **Sandbox:** `~/.local/share/cwva-dashboard/sandbox` — QA git `ded277c`
  (the accepted entry), 328 records, **working tree clean**. System-managed:
  nothing goes there by hand.
- **Shadow SOT:** seeded 2026-07-19, metacontent refreshed 2026-08-22, **plus
  the objects from the accepted entries**. Baseline **542 objects /
  134,752,648 B** — deliberate promotion is the only thing that moves this, and
  `scripts/verify_shadow.py` is green at the new figure. `reset_to_baseline.py`
  walks a promotion back off both sides if you want a clean re-run.
- **Tests:** `pytest -q` → **626 passed** with `GCP_TEST_BUCKET` set;
  **619 passed + 7 skipped** without it. The lower number is not a regression.
- **CI is DISABLED** on GitHub (`disabled_manually`, 2026-09-03) with its
  failures uninvestigated. **Absence of red is not green** — the local suite is
  Linux-only, so the Windows half of the Phase 1 release gate is unexercised.
  Re-enable: `gh workflow enable CI --repo visualartsdna-org/dashboard`.
- **Repo:** branch `main`, pushed to the **private** remote
  `visualartsdna-org/dashboard`. Confirm with `git remote -v`; verify HEAD with
  `git log --oneline -5`.

---

Sequencing for cwva-dashboard. Phases 1–8 are the fundamentals; 9+ builds
the concept-hygiene system on top of them (items 9–14 of the originating
priority list). AI features from CE_DESIGN.md §10 interleave after Phase 5.

Restructuring notes vs. the original priority list:
- Original items 2, 3 (parenthetical), and 5 are one epic: the parenthetical
  of item 3 (manifest, validation gates, browser-review gate, atomic apply,
  rollback record) *is* the promotion-unit architecture, and git-backed
  rollback is not a later add-on — atomic apply IS a git commit. They are
  merged into Phase 3 here. Item 3 proper (refresh) becomes Phase 4.
  (Historical note: "atomic apply IS a git commit" reflects the original
  SOT-git framing; the settled design commits to a private QA git and then
  converges SOT via a transport adapter — see CE_DESIGN §3.3–3.4 and the
  current Phase 3 body below, which are authoritative.)
- The browser-review gate depends on the data browser (Phase 7). Until then
  the review gate ships as the change preview (diff summary); it upgrades
  to browser review when Phase 7 lands.
- Reserved slots 6–8 are filled with missing fundamentals that items 9–14
  assume: agent orchestration core, QA store + data browser, and the concept
  pipeline as agent tools.

---

## Phase 1 — Sandbox model with single gated exit  [priority 1]

The foundation; nothing agent-facing ships before this is trusted.

- [x] Repo scaffolding per CLAUDE.md; `config/dashboard.rson` (RSON configs).
- [x] `sandbox/paths.py`: canonicalization, containment, reject rules
      (traversal, absolute, null bytes, reserved names, ADS, UNC,
      drive-relative, long-path prefixes, symlink prohibition).
- [x] `sandbox/fileops.py`: list/read/write/mkdir/move/copy/trash, all
      through the path chokepoint; quotas; soft delete.
- [x] `sandbox/broker.py`: least-privilege executor process. Linux: Landlock
      self-restriction at startup (done, ABI 1–3; direct syscalls, no dep).
      Windows: install script for dedicated user + NTFS ACLs still pending
      (deferred to install-time, Phase 11; Linux path first).
- [x] Append-only audit log of every operation (args + outcome); hash-chained
      + tamper-evident (`audit.py`, `verify()`).
- [x] **Adversarial test corpus + Hypothesis properties, CI on both OSes.**
      Corpus (`test_paths_reject.py`), invariants (`test_paths_properties.py`:
      never-escapes / determinism / no-sanitize / fileops-contained), GitHub
      Actions matrix over {ubuntu, windows} × {3.11, 3.12}. Cross-OS run
      pending first push to a repo.
- [~] Exit gate: all corpus cases rejected at Layer 1; with Layer 1
      deliberately broken, Layer 2 still contains every escape attempt.
      Linux criterion met and tested (`test_layer1_broken_layer2_contains`);
      Windows Layer-2 assurance deferred with the ACL install script
      (Phase 11).

## Phase 2 — Tool registry skeleton

Small connective phase (was implicit in priority 1).

- [x] Tool schema convention (name, params, description, result shape) —
      JSON-Schema `inputSchema`, MCP-exposable (`tools/base.py`,
      `registry.schemas()`).
- [x] Registry + dispatcher wiring tool calls to sandbox fileops
      (`tools/registry.py`, `fileops_tools.py`): deny-by-default arg
      validation, sandbox-exception → error-code mapping, one audit event
      per call with payload redaction.
- [x] No AI yet: a REPL harness invokes tools directly for testing
      (`tools/repl.py`, `python -m cwva_dashboard.tools.repl`).
- [x] **Hardened worker process** (`sandbox/worker.py`): forked
      least-privilege executor self-restricts via Landlock, then serves the
      dispatcher over a socketpair (JSONL); parent `WorkerClient` persists
      audit events to an out-of-sandbox log. (Composes the Phase-1 broker +
      fileops + audit — the cross-phase item.)

## Phase 3 — Promotion lifecycle  [priorities 2 + 3(parenthetical) + 5]

The heart of the system. All components of one epic, built in order:

- [x] **Manifest / promotion unit** (`promotion/unit.py`): the output set of
      one workflow instance, delimited by the queue state machine.
      ChangeManifest (adds/modifies/deletes), GateResult, PromotionStatus
      lifecycle, provenance, commit_message() with machine block.
- [x] **Validation gates** (`gates.py`): parse gate (all RDF compiles,
      per-file attribution); SHACL shapes via pyshacl (completeness + ref
      integrity); SPARQL assertion queries (ASK/SELECT expectations). Gate
      results attach to the unit.
- [x] **QA git** (`qa_git.py`): private repo over QA content inside the
      sandbox; commit per promotion unit (manifest as message); name-status
      diff manifest; restore_to (rollback tree). Dashboard machinery only —
      never an agent tool. Asserts at init it does not nest with any other
      git repo / the project root (CE_DESIGN §3.4).
- [x] **Binary assets** (policy settled, CE_DESIGN §3.4): sidecar pointers
      (`.ptr`: sha256/size/timestamp) tracked in git, binaries gitignored
      at their real paths (`sandbox/pointers.py`); pointer/binary
      consistency enforced in `fileops.py` (write/move/copy/trash);
      replaced binaries → content-addressed `.qa/attic/`; convergence
      pushes real binaries not `.ptr` (`promotion/binaries.py`); rollback
      re-materializes from the attic via `reconcile`. Config extension list
      (default images + pdf; md as git content). TODO: attic GC by policy.
- [x] **Change preview** (`preview.py`): git diff for the file-level
      manifest (adds/modifies/**deletes**) + isomorphic graph diff
      (`rdflib.compare.graph_diff`) for the semantic summary — triples ±,
      subjects added/modified/removed, by-rdf:type counts ("adds 1 Work,
      1 Criticism"). Bnode relabel / reorder / whitespace are provably not
      changes. Serves as the review gate until the browser lands (Phase 7).
- [x] **Transport adapters** (`transports.py`): gcp_bucket (upload changed,
      delete removed), git_remote (commit+push), git_local (commit),
      plain files (write+delete). Push = idempotent full-state convergence
      from the QA git diff manifest; per-transport `current_stamp()` for
      drift. TODO: deletion-count confirmation above a configurable threshold.
- [x] **Apply** (`apply.py`): gates-passed guard → authoritative manifest
      from QA → pre-push drift check (abort on unexpected SOT stamp) → QA
      commit → converge SOT via adapter; returns new SOT stamp as next
      baseline. Runs in the trusted orchestrator (single gated exit).
- [x] **Rollback** (`rollback.py`): compute inverse manifest (QA HEAD →
      pre-work commit), drift-check, restore QA to pre-work + record a
      rollback commit, converge the reverted state to SOT (may delete
      files). Never in-place SOT undo; coarse-grained only. Round-trip
      tested (files + git_local).
- [ ] Tests against fixture targets for all four transports (local dirs +
      fake bucket + throwaway git repos): convergence with deletions,
      partial-failure abort, drift-abort, revert→converge round-trip.

## Phase 4 — SOT sync, refresh, drift  [priority 3 proper]

- [x] **SOT→QA sync** via the transport adapters (`sot_sync/sync.py`;
      transports gained `snapshot()`/`fetch()`/`pull_remote()`): pulls SOT
      into the QA content tree, rebuilds `.ptr` sidecars, reports drift.
- [x] **Drift detection**: post-sync QA diff vs HEAD surfaces out-of-band
      SOT edits (add/modify/delete, incl. binary changes at the `.ptr`
      level); `adopt_external` commits them as a new baseline.
- [x] **Orphan report** (`sot_sync/orphans.py`): managed binaries present
      but unreferenced by the RDF (basename heuristic v1; sharpens to a
      SPARQL URI→path map when the QA store lands, Phase 7).
- [x] **Refresh** = reset WIP + reconcile binaries + sync; doubles as crash
      recovery.
- [~] Policy wiring: re-sync/compare before every push is owned by
      `apply.py` (transport stamp, done). Sync-before-workflow-start is
      enforced by the agent orchestration (Phase 6).
- [ ] In-flight workflow state survives refresh via the workflow-state file
      (created in Phase 6).

## Phase 4.5 — Dashboard UX + framework function port

Goal: every framework function working under a human-driven UX, proven by real
workflow episodes against real data on multiple transports, before any AI wraps
it. Enforces CLAUDE law 10 (UX handlers = thin registry bindings). See
CE_DESIGN §7.1 (workflow state) and §7.2 (updateWorkOnSite rebuild).

**Scoping decisions (settled):**
- cwvaFunction-py is **absorbed entirely**; the separate faithful-port project
  is shelved. The framework functions are ported here as registry tools.
- Shadow SOTs are cloned from the **live GCP bucket** (disposable copies).
- Smoke episodes run on **gcp_bucket (a disposable test bucket) + git_local**.
- UX basis is the repo's `html/function.html` (function2.html is historical).
- Groovy source: `/mnt/c/temp/git/cwvaServer/src/main/java`, functions in
  `support/` (AnnotateWork, TagModel, UpdateWorkOnSite, StageStatus, Proof, …).

Port surface & UX:
- [x] FastAPI app (`main.py`) serving the UX (`ux/dashboard.html`); every route
      dispatches through the tool registry only (law 10), verified by the
      synthetic-tool contract test + Landlock-enforced HTTP e2e. (UX is a
      registry-driven shell; templating the full function.html cards from config
      is a later polish, not a blocker.)
      **⚠ SUPERSEDED by 4.7 D1 (2026-08-24):** `ux/dashboard.html` and the
      synthetic-tool *renderer* contract test no longer exist — `function.html`
      is served directly and each form is wired per function. The law-10 claim
      still holds for tool dispatch; the promotion tail is the law-1 exception.
      Left as the record of what 4.5 shipped, not as current state.
- [~] Port the Groovy functions supporting the UX to registry tools. **Ported:**
      record authoring #1/#2/#3, SPARQL #17, md→html #29, diff #30, SHACL
      validate #31, image #32/#33, updateWorkOnSite #9, TCAP #6/#15. **Remaining
      (dependency-gated):** reports #19/#20/#22/#23 (need the QA store, Phase 7);
      concept pipeline #12/#13/#14/#16 (AI, Phase 5/8); proof #5 + brand #7
      (deferred); distribute #10/#11 → the promotion workflow already covers.
- [x] **Two Groovy-extraction items** (everything else is rebuild/replace/
      reuse): #6 Annotate Work + #15 Annotate Document Instances share
      `concepts/tcap_navigation.py` (navigate/annotate; query is the Fuseki
      spec, algorithm implemented in Python for rdflib) + `workflows/annotate.py`
      (annotate_work / promote_markdown_tags). ALGORITHM.md approved; acceptance
      suite (3 cases + CrowdHingeBand + tie) green. Ties → hygiene ledger;
      #15 flips `conceptsExtracted false→true` and preserves consumed tags in
      the non-converged `evidence/` area; instance-file `the:tag` untouched.
- [x] Register the isomorphic diff (`rdf.diff`, preview machinery) and SHACL
      (`rdf.validate`, `gates.py`) as agent tools — #30/#31 capability retained
      as tools, not UX cards.
- [~] Config for 4.5: `sites` for updateWorkOnSite (visualartsdna.org,
      art.visualartsdna.org) + `domain`/`host` done in RSON; sanctioned network-effect
      class amended (law 11). TODO: inject the instance URL into the served HTML
      (config-templated UX).

Workflow panel (replaces stageStatus, CE_DESIGN §7.1):
- [x] **Workflow panel**: pipeline queue counts + open obligations (standing
      queries − dismissals) + in-flight workflow/gate (in-flight stub until
      Phase 6). Standing-query definitions load as data
      (`config/standing_queries.rson`), not code. `workflow.state` tool +
      `/api/workflow-state` panel endpoint + UX panel.
- [~] First standing queries: conceptQueue counts + processed,
      works-without-workOnSite, `conceptsExtracted false` shipped. Scrape
      staleness, drift awaiting adoption, uncommitted WIP declared but deferred
      (need the git/audit orchestrator-tool context). **Now exit-gated** — a
      panel that cannot show drift, WIP, or staleness reports a cleaner world
      than exists. **Design settled (2026-07-19):** the deferral was never
      worker *visibility* — the worker could in fact read the QA `.git`, which
      was the sandbox escape fixed in `a1f834f`. The real constraints are that
      git is not an agent-side capability (law 6) and the worker cannot exec
      (law 2). So git/audit-backed queries are **computed orchestrator-side and
      merged at the trusted panel/narration boundary**; `evaluate()` is already
      pure (injected `graph` / `count_fn` / `ledger`), so the seam exists.
      Explicitly rejected: passing git-derived inputs *into* the worker — that
      would route trusted state across the boundary just thickened.
      The drift query gets asserted on the existing drift-adoption episode via
      the per-step `expect`.
- [x] Dismissals recorded in the hygiene ledger (`concepts/ledger.py`,
      `.qa/hygiene_ledger.ttl`; shared container with Phase 9 concept-dup
      dismissals; ledger landed early). `workflow.dismiss` tool.
- [x] Agent narration and panel consume the same standing-query engine
      (`workflow_state/engine.py` `narrate()` / `to_dict()`) — one computation,
      two renderings.

updateWorkOnSite rebuild (CE_DESIGN §7.2):
- [x] Rebuild (`workflows/update_work_on_site.py`): injectable fetcher
      (sanctioned network effect); sitemap discovery + OG/JSON-LD extraction
      (AI fallback stubbed until Phase 5); pHash (`workflows/perceptual.py`,
      dHash) + lexical (`concepts/matcher.py`, rapidfuzz) matching with a
      confirmation queue; deterministic full-snapshot per-site TTL + prov:
      observed-by-scraper. Registry tool + config `sites`. Promotion-unit
      composition (place TTL in mirror, apply) is the workflow step.
- [~] pHash of SOT originals computed on demand in `build_sot_index`; caching
      the hashes across runs is a deferred optimization.

Proving it works:
- [x] **Shadow SOT** per smoke transport. git_local + files + in-memory
      FakeBucket = CI regression armor. **gcp_bucket now also runs against a
      real disposable GCS bucket** (`tests/live_gcs/`, opt in via the
      `GCP_TEST_BUCKET` env var; skipped otherwise so CI and offline runs are
      unaffected). Each test is scoped to a unique random prefix under
      `cwva-dashboard-tests/` and deletes that prefix afterwards, so it never
      touches anything else in the bucket and concurrent runs cannot collide.
      Closes the live-bucket smoke open since the Phase 3 review.
- [~] **Scenario capture**: replayable scenarios in `tests/scenarios/`.
      **Driver-agnostic by construction** — steps are registry-tool invocations
      with args (never HTTP/UI), so Phase 5's "same scenarios, two drivers"
      (human UX vs agent) comparison falls out for free. **Scenario #1 slot
      reserved for a real recorded human entry session** (admission-test seed
      for the routing policy).
- [x] Smoke episodes (entry/commit/refresh, drift adoption, ≥1 rollback, binary
      replacement) on git_local + files + FakeBucket, and the **same corpus
      replayed against the real bucket** (the live module imports `_SCENARIOS`
      from the fake-bucket module — one corpus, two backings, never a parallel
      live-only set). Drift adoption is built
      (`tests/scenarios/drift_adoption.rson`): an out-of-band SOT write via the
      `env.external_sot_*` perturbation ops, `sot.sync` detecting it, `sot.adopt`
      making it the baseline. The sync step carries a per-step `expect` so the
      episode asserts the *detection*, not only the end state.

**The CONDITIONAL gcp_bucket condition is DISCHARGED** (2026-07-19): the smoke
episodes and the transport-level smoke both ran green against a real disposable
GCS bucket (US / STANDARD, non-versioned), closing both obligations. The
FakeBucket episodes remain as regression armor, not as evidence.

Phase 4.5 exit still needs the items below; the live-bucket condition is no
longer one of the blockers.

**Exit item 0 — HARD BLOCKER, gates everything credential-adjacent:**
- [x] Layer-1 denial of trusted-side control state + adversarial corpus
      coverage (`a1f834f`). A confined-surface sandbox escape to arbitrary code
      execution as the orchestrator: `.git` sits inside the sandbox because
      `stage_root` IS the QA repo root, git ships `hooks/*.sample` at 0755,
      `copy` preserves mode and `write_text` overwrites in place, so the exec
      bit was reachable without a `chmod`. Fixed by scoping the deny rule to
      the mechanism (what git reads as configuration or code), not to the two
      files that revealed it, plus `core.hooksPath` hardening on the QA repo as
      the second layer this class otherwise lacks — hooks run in the trusted
      process, so Layer 2 is no backstop.
- [x] **Sibling item, same class but NOT the same severity** — pointer sidecar
      hardening (`b4c8ac4`). Sidecars were agent-authorable and verified
      nowhere, while `binaries.py` translated a changed `<x>.ptr` into a push of
      `<x>` on trust. Fixed in two halves: Layer 1 refuses `.ptr` as an
      agent-supplied path (structural — fileops' own maintenance never re-enters
      `resolve()`), and `pointer_gate` recomputes sha256 for the manifest's
      managed binaries at the exit, failing rather than repairing.
      **Read the distinction, do not flatten the two:** this one is *bounded
      content substitution*, not execution. A forged sidecar could never push
      wrong bytes to SOT — transports upload the real file — so the exposure was
      manifest visibility plus `reconcile()` restoring from the attic by a
      forged sha. The escape above was a hard stop because it was arbitrary code
      execution as the orchestrator; this was sequenced ahead of the shadow
      clone for a different reason: the clone is what first exercises mass
      sidecar creation over real content, with the attic newly populated by
      things that matter.
- **No production credentials, no shadow clone, and no Scenario #1 recording
  proceed until both are closed.** Both are closed; the ordering stands as the
  reason the rest of Phase 4.5 sequenced behind them.

Persistent shadow SOT (§2 of the merged fragment) — settled mechanisms:
- [x] **Transport entry** — `shadow_sot` in `config/dashboard.rson`: stable
      `shadow-sot/` prefix on the test bucket, distinct from the ephemeral
      `cwva-dashboard-tests/<uuid>/` the suite creates and deletes. Bucket names
      come from the environment, never the file.
      **Placeholder hazard confirmed in real data, not hypothetical:** the
      production bucket contains ten zero-byte `dir/` objects (`ttl/`,
      `documents/`, `ttl/model/`, …) from the GCS console's "Create folder".
      `GcpBucketTransport.snapshot()`/`current_stamp()` now filter them, so they
      can never enter a snapshot and make sync write a file where a directory
      belongs. Verified: none propagated into the shadow.
- [x] **Seeded by cloning production** — read-only against production, writes
      only under `shadow-sot/`. Re-runnable entry point at
      `scripts/seed_shadow_sot.py` (re-seeding is recurring, not one-off);
      idempotent. Production verified unchanged afterwards (1619 objects).
- [x] **Cloned through the sync machinery** (`sot_sync/clone.py`): `snapshot()`
      to enumerate, `fetch()` to read, the target's own `converge()` to write,
      staged in bounded batches so peak disk does not scale with the SOT.
- [x] **Safety invariant, structural** (§2e): `ReadOnlySource` exposes only
      `snapshot`/`fetch`/`pull_remote`, is deliberately not a `Transport`
      subclass, and has no `converge` method — pushing to production is not
      expressible. `clone_source_to_target` additionally refuses a source that
      has one.
- [x] **Measured** (§2d, 2026-07-19): the clone is **latency-bound, not
      bandwidth-bound** — time scales with object COUNT, not bytes. `ttl/`: 392
      objects, 1.5 MB, 119 s (~0.30 s/object). `documents/`: 125 objects,
      68.9 MB, 52 s (1.33 MB/s). `stats/`: 17 objects, 61.8 MB, 12 s
      (5.15 MB/s). Extrapolated `images/`: ~1075 objects, 3.7 GB, **~46 min** —
      which is why the image corpus was deliberately excluded (see coverage
      caveat below).
      **§2d is RESOLVED WITH DATA, not deferred — strike it from the watch
      list.** The concern was that GCS md5 vs QA sha256 forces a full re-fetch
      on every sync. At ~0.30 s/object *regardless of size*, that re-fetch costs
      essentially nothing: cost tracks object count, not bytes, so the hashing
      mismatch is not the bottleneck and no md5 bridge or hash cache is
      warranted. If re-sync ever bites, the lever is per-object parallelism.
- [x] **Second-order benefit of the per-target layout:** the shadow's flat
      production layout (`ttl/data`, `ttl/model`) differs from the QA mirror, so
      Scenario #1 and the triage exercise the layout *translation* path rather
      than the identity case the fixtures use — the harder configuration, for
      free. This also vindicates putting kind-routing at promotion-unit
      composition rather than in transports (§3.6): the first real target needed
      a config change, not a code change.

**⚠ Shadow coverage caveat — the shadow is TTL/documents/stats-only (534
objects, 132 MB). It contains NO images.** Re-syncing happens repeatedly, and a
3.7 GB image corpus makes each pass impractical. A green run against this shadow
therefore does **not** exercise, and these must not be ticked off on its
evidence:
- [ ] pHash matching against real originals.
- [ ] The orphan report's basename heuristic at corpus scale.
- [ ] Binary promotion at real image sizes.
These are deferred to a later dedicated measurement pass over the full corpus
(images, stats, documents, ttl sync). Partial mitigation: the shadow carries 55
real PDFs, which are pointer-managed by default, so sidecar/attic behavior can
be exercised on genuine binary content without the image corpus.

- [x] **`pointer_managed_extensions` settled BEFORE first contact** — `.heic`,
      `.glb`, `.zip` added (production holds 19/17/2, all under `images/`, none
      in the shadow yet). Investigating this turned up a worse bug than
      non-retroactivity: `.gitignore` was written once at `QAGit.init()` and
      never revisited, so extending the list **silently double-tracked new
      files**, committing the binary *and* its `.ptr`. `QAGit.reconcile_gitignore`
      now rewrites it on open; `tracked_managed_binaries` reports files git
      already tracks (which a `.gitignore` change cannot fix) and `untrack`
      clears them via `git rm --cached` — future tracking only, never a history
      rewrite, since rollback depends on history being immutable (law 6).
      Why this list is **security-adjacent, not housekeeping**:
      1. **Rollback authority.** ~~git is the general case~~ — **superseded
         2026-07-21 by the policy inversion below.** The **attic is now the
         general case** (pointer is truth; `reconcile()` re-materializes by sha)
         and git-content rollback is the *enumerable exception*. This is the
         better arrangement: one mechanism owns almost everything and the
         exceptions are a finite list rather than an open complement.
      2. **`pointer_gate` certifies pointer-managed files**, so post-inversion
         this list defines the small set that is **not** gate-checked at the
         exit, rather than the set that is.
      3. Blobs of a git-tracked binary live in history permanently; getting the
         list right before content syncs is cheap, and afterwards is not.

- [x] **Binary policy INVERTED (2026-07-21)** — `git_content_extensions`
      enumerates what stays ordinary git content; **everything else is
      pointer-managed**. The old direction listed binaries, so any type nobody
      anticipated (`.svg`, `.heic`, `.glb`, `.zip`, `.mp4`) silently became a
      permanent blob in an unrewritable history. Omission now fails safe: a
      forgotten text type merely stops being diffable, fixable by listing it.
      The criterion is **editorial intent, not detectable structure** — `.svg`
      is the proving case: valid UTF-8, structurally diffable, meaningless to
      diff. No content sniffing; the judgment lives in a list.
      - **Machinery carve-out was required, not a clean default flip:** `.ptr`
        sidecars and `.gitignore` share the content path space and would have
        been swallowed (a sidecar for a sidecar). Extensionless files count as
        text. The hygiene ledger needed nothing — `/.qa/` is gitignored, a
        genuinely separate path space.
      - `.gitignore` generation inverted too (`*.*` then re-admit), with tests
        asserting git's view and the Python rule **agree** — disagreement is
        what produces the tracked-nowhere and double-tracked bugs.
        **Found exactly that on review:** `*.*` matches single-dot dotfiles
        (`*` matches the empty string, so the leading dot satisfies the
        pattern's dot), so `.env`/`.npmrc`/`.dockerignore`/`.editorconfig` were
        ignored by git while the Python rule called them text — tracked nowhere,
        no sidecar either. `.gitignore` was safe only by being re-admitted by
        name. Fixed with a `!.*` carve-out in the glob (not a Python-side
        change); `/.qa/` stays last so QA-internal still wins.
      - **Escape hatch if `.html` ambiguity ever bites** (e.g. `stats/` grows
        more generated pages): classify by **path**, using the per-target
        placement map that already exists, *not* a second extension table. The
        one-classification-one-mechanism property is what keeps this area
        debuggable — every bug here has been two mechanisms disagreeing. Not
        worth building now; recorded so the instinct isn't to add a rival list.
      - **Deliberate enumeration found a real omission:** `ttl/topics/topics.tsh`,
        a hand-authored DSL that the "derive it from what exists" approach would
        have missed. `.html` is genuinely ambiguous in production (authored
        prose *and* generated pages share the extension); diffability of prose
        wins.
      - `QAGit.migrate_to_pointer_management` mints the sidecar and seeds the
        attic **before** untracking, closing the gap where a file is
        managed-by-extension with no `.ptr` and is owned by *neither* rollback
        mechanism. Idempotent; reports files tracked but missing from the
        worktree rather than untracking them into that gap.
      - **No migration needed for the shadow:** the sandbox has never been
        initialized, so nothing was ever tracked. Dry-run over the real 534
        objects: 463 files / 3.9 MB become git content, 71 files / 128.4 MB
        become pointer-managed — of which ~62 MB (16 `stats/*.json`, one 17 MB)
        is kept out of history specifically by the inversion.

**⚠ SCHEDULED FIRST RUN — `migrate_to_pointer_management` is UNEXERCISED
AGAINST REAL CONTENT.** The shadow's QA repo will initialize under the current
list, so it never migrates. That means the first genuine run happens on some
future change to `git_content_extensions`, in a session that will not be
thinking about migration at all — the exact profile of the write-once
`.gitignore` bug: correct code, first exercised long after the context that
produced it is gone. **If you are changing that list, slow down here:** run the
migration explicitly, check the returned report (`sidecars_minted`,
`attic_seeded`, `missing_from_worktree`) against expectations before committing,
and remember that untracking cannot be undone by re-adding — the blobs stay in
history either way (law 6). Unit-tested including partial-failure and
idempotency; never yet run over a real corpus.

- [→ 4.6] **conceptsExtracted backlog triage** — RE-HOMED to Phase 4.6
      (needs synced production content; cannot complete at unit-test level).
      Rick-executed: on the first panel run against real content, flip done
      items to `true` and dismiss the rest — the first real exercise of
      `workflow.dismiss` and the dismissal half of the obligations model.

**Phase 4.5 now closes at UNIT-TEST LEVEL** (merged from
`PLAN_FRAGMENT_phase46.md`, 2026-07-24). Everything provable by test stays in
4.5; everything needing synced real content or a human at the dashboard moves
to Phase 4.6, so nothing falls into the gap between phases.

Close carried Phase 1–4 gaps before exit (test-level, stay in 4.5):
- [ ] Mid-convergence failure per transport family (inject failure mid-push;
      re-converge heals to SOT ≡ QA).
- [ ] Windows CI runner for the Layer-1 corpus + fileops tests.
      **⚠ GitHub Actions CI is DISABLED (2026-09-03, `gh workflow disable CI`).**
      Every run since the first push has failed and the cause is uninvestigated
      — deferred deliberately, not fixed. Re-enable with
      `gh workflow enable CI --repo visualartsdna-org/dashboard`.
      **Do not read the absence of red as green:** the local suite is the only
      thing currently proving anything, and it runs on Linux only, so the
      Windows half of the Phase 1 release gate (Layer-1 corpus on both OSes) is
      unexercised — which is what this checkbox was always about.
- [ ] SOT-side orphan report test (pre-seeded orphan in a SOT fixture).
- [ ] The three deferred standing queries (scrape staleness, drift awaiting
      adoption, uncommitted WIP), built in the orchestrator-computed shape
      settled above (`evaluate()` stays pure and sandbox-derived; the trusted
      panel/narration path enriches with git/audit items — no git input crosses
      into the worker).

Re-homed to Phase 4.6 (cannot complete at test level):
- Scenario #1 human recording — needs a driveable UX (4.6 §6).
- Shadow→QA sync itself — 4.6's opening move (4.6 §5).
- conceptsExtracted triage — needs synced content (above).

Revised 4.5 exit: exit item 0 (landed) + carried gaps + standing queries, all
at test level. The image-dependent items (pHash against real originals, orphan
heuristic at corpus scale, binary promotion at real sizes) and the migration
first-run remain **explicitly unexercised, carried forward as-is** — not
silently discharged by the phase close.

## Phase 4.6 — Existing-dashboard replication  [merged 2026-07-24]

**Goal:** the new dashboard supports the functionality of the existing (Groovy)
dashboard, driven by a human, against real synced content. Parity, not polish —
the improvement pass (config-templated UX, richer cards) stays a later phase.

**Two reference sources, distinct roles:**
- `html/function.html` = **layout** reference (tab/card structure, field
  grouping/ordering, which controls sit together). Preserve it.
- The Groovy HTML-generating + request-handling code = **semantics** reference
  (closed sets and their members, file choosers, defaults, derived values,
  validation, what the handler does per field on submit). Reimplemented over the
  existing registry tools — behaviours, not a code port.

**Scope = the intersection** of function.html's surface and what is already
ported. Out of 4.6 (dependency-gated): reports #19/#20/#22/#23 (QA store,
Phase 7), concept pipeline #12/#13/#14/#16 (AI, Phase 5/8), proof #5, brand #7.

**Groovy-extraction convention applies:** one extraction doc (ALGORITHM.md-style)
per function group precedes the port, Rick-reviewed, quirks classified
load-bearing vs. candidate-bug. The gate has paid for itself three times already
(owl:ObjectProperty constraint, substring(5), the conceptsExtracted erratum).

### The affordance layer (§3 — schema-first, BUILT 2026-08-11)

> **The next two paragraphs are the PROBLEM STATEMENT, in the past tense as of
> `9b17858`.** They are kept because the diagnosis is the rationale — delete
> them and the next reader relitigates schema-first-vs-bespoke-UI — but nothing
> in them describes the code today. Current state starts at "COMPLETE" below.

Every registry tool schema **typed** its fields as `string` (plus a few
`number`s); the closed sets **survived** only as prose in `description`. The
generic renderer therefore **emitted** a text box per field, and the Groovy
form's affordances (the `type` radios, `hasPaper`/`units` selects, site choice,
file chooser) **were** lost at the **schema** layer during the port — not the UX
layer.

**Decision: affordances live in the tool schemas; the generic renderer honours
them.** Bespoke UI only where a schema cannot express the affordance (concept
picker — known exception). Rationale is as much Phase 5 as UX: a schema
constraint binds **both** drivers and is enforced at Phase-2 arg validation; a
hand-written `<select>` binds only the human and reappears in Phase 5 as
malformed AI output plus a vocabulary the agent cannot enumerate. Schema-first
preserves the zero-UX-code property (synthetic-tool contract test) and keeps
law 10 meaningful. Term of art: **affordance layer**, never "semantic layer"
(RDF collision).

**⚠ Enforcement locus is per-field-type. `enum` was NOT enforced when this was
written — it IS now (`84a0c99`); the warning is kept for the mapping it
teaches.** `validate_args` (base.py) is hand-rolled: it enforced
`additionalProperties`, `required`, and `type`, and **ignored `enum`/`format`**.
So a schema `enum` bound the renderer but not the dispatcher until
`validate_args` was extended — otherwise the second driver sends
`units:"metre"` straight through. The design
doc (`AFFORDANCE_DESIGN.md`) states, per field-type, **where each constraint is
enforced (dispatch vs. gate)**, not only where it renders — that mapping is what
keeps the second driver from reopening the hole. Dynamic-vocabulary fields in
particular cannot be enforced at dispatch (the confined worker must not
enumerate the store), so they are a **gate** concern (SHACL), not a dispatch one.

**The affordance layer is COMPLETE (2026-08-11, `9b17858`).** Built, tested,
and **inert until the §5 sync** — the layer's activation is a checkpoint, not a
build step (see the activation checkpoint in §5). Build order and rationale live in
`AFFORDANCE_DESIGN.md`; commits in parentheses.

- [x] `AFFORDANCE_DESIGN.md` written and Rick-reviewed **before** renderer work
      (`a1b8505`, approved `df6b7a9`): affordance annotations
      `x-vocabulary`/`x-file-ref`, the enum/format dispatch extension, and the
      enforcement-locus table.
- [x] Extend `validate_args` to enforce `enum` and `format` at dispatch
      (`84a0c99`), with adversarial tests — it is the deny-by-default surface.
- [x] `enum` authored on the record schemas (`9257e26`), split by real-data
      evidence: **strict `enum`** where the set proved closed (`units`, entity
      `type`, `file_format` — F2 corrected to strict in `fa7c7b6`) and
      `x-enum-suggested` (render hint, unenforced) where real data exceeded the
      form set. Config-sourced sets materialize at registry-build.
- [x] **`type` is ontology-backed** (`4aea4ea`, Q9): per-form RDFS subclass
      closure of `entry_forms[*].type_root`, materialized into the schema enum
      at registry-build and dispatch-enforced. Adding a work kind is an ontology
      edit, not code. Falls back to an unenforced suggested set until the model
      is synced — which is what the §5 checkpoint measures (11 / 9).
- [x] `x-vocabulary` annotation resolved trusted-side via the read-only store
      path (`31a44e8`), the picker querying **exactly what the gate enforces**.
      **`background` reclassified out** — it points at `work:` URIs, so it is a
      work cross-reference, not a thesaurus reference; its integrity check is
      deferred.
- [x] `x-file-ref` annotation rendered as a picker over `fs.list` (`image`,
      `image3d`). **`qrcode` is NOT an input** — reclassified as a derived field
      (D1, `9257e26`), so the base-join bug is resolved at the source
      (`qrcode_url(guid, img_base)`) rather than guarded downstream; a
      bare-filename qrcode remains the asset gate's malformed discriminator.
- [x] Generic renderer upgraded to honour all of the above (`a29f899`); the
      all-text *rendering* is retired, the registry-driven renderer is **upgraded
      not replaced**. One `widgetKind(spec)` shared by build and collect, no
      per-field special-casing; zero-UX-code asserted by
      `test_affordance_annotations_survive_to_the_renderer`.
- **Governing rule (approved):** *no dynamic-affordance form ships before its
  shape is armed.* A Gate-locus field (`x-vocabulary`/`x-file-ref`) must not
  render its picker until the SHACL shape enforcing it is armed in
  `run_promotion` — else the picker implies a guard that does not exist.
  Dispatch-locus fields (`enum`/`format`) are bound as soon as `validate_args`
  is extended and may ship with that step. The `qrcode` base-join fix precedes
  the `qrcode` picker for the same reason. See `AFFORDANCE_DESIGN.md`.

**Referential-integrity — the 2026-07-24 investigation that scoped it.**
**Superseded by the outcome below: it did NOT land as a SHACL shape, and
`vad:hasPaper` IS validated now (`31a44e8`).** As found then: **there were no
SHACL shapes at all** — `shacl_gate` wired but never armed
(`run_promotion(shapes=None)`, nothing ever passing a graph), and `record_tools`
writing `vad:hasPaper` with no validation. The Groovy dropdowns
were the *sole* guard against dangling `vad:hasPaper`/`vad:background`
references; a misspelled `the:StrathmoreColdPres` yields valid TTL that clears
the only live gate (parse). The affordance enums and the ref-integrity shape are
therefore **two halves of one guarantee** — enums block bad values at dispatch,
the shape catches store-relative danglers at the gate — and are built/reviewed
together.
- [x] **Landed as TWO gates, and NOT as a SHACL shape** — the "one shape for
      both" framing above was wrong, and the correction is the finding: asset
      presence is a *filesystem* fact and vocabulary membership is a *graph*
      fact, so they are separate mechanisms.
      - **Asset-reference gate** (`c0265b4`): `schema:image`/`vad:image3d`/
        `vad:qrcode` must resolve to a **managed asset** — a real file **or** a
        `.ptr` sidecar with recoverable bytes, the pointer layer's notion of
        "present", not the filesystem's. Absent and malformed are discriminated
        (the bare-filename case is malformed, not absent).
      - **Vocabulary-reference gate** (`31a44e8`): decision (a)+(c) — load the
        vocab dirs from the QA tree via `vocab_dirs` and enforce with a
        SPARQL-style SELECT of violations, reusing the existing graph idiom
        rather than introducing SHACL. The reference-graph load is load-bearing:
        the manifest alone false-dangles every reference, and that is tested.
      - `shacl_gate` therefore **remains wired but unarmed**. That is now a
        deliberate state, not an oversight — nothing currently needs shape
        semantics. `background` (a `work:` cross-reference) is the open
        remainder.

### Opening move (§5) — BUILD the sync path, then sync  [revised 2026-08-12]

**Prose corrected.** This section read "4.6 begins by syncing the shadow …
before UX work", which described the sync as a runnable step gated only on
sequencing. It is not: **the shadow→QA sync path does not exist in code.**
Verified 2026-08-11 against `9b17858` — `sync()` is called only from the
scenario harness and `promote.refresh`, nothing constructs a `QAGit` at
`sandbox.stage_root` plus a transport at the `shadow-sot/` prefix, and
`config.py` has no `shadow_sot` accessor (`scripts/seed_shadow_sot.py` reads the
block directly, and clones production→shadow — the other direction). The
affordance/UX work that "before UX work" sequenced against is meanwhile
**done**. So the opening move is **build, then sync**, and the gate below is the
build.

**Verified prerequisite (2026-08-11, read-only):** the shadow is seeded and
faithful — 534 objects / 132.26 MB at `shadow-sot/`, seeded 2026-07-19; both
dirs the affordance layer needs are present (`ttl/model/` 4 files incl.
`cwva.ttl`; `ttl/vocab/` 27 files incl. `watercolorPaper.ttl`). Compared
name+size against production: zero stray objects, the 10 zero-byte `dir/`
placeholders correctly filtered, 15 objects missing and 2 differing — **all 17
are post-seed production drift** (created/updated 7/26–8/11), not clone defects.
Storage split confirms the dry run to the object: 463 git content / 71
pointer-managed.

#### ⛔ B1–B3 — the gate. The sync does not run until these are closed.

- [x] **B1 — layout translation. DONE 2026-08-22: reader-side map**
      (decision 2026-08-12, recorded at CE_DESIGN §3.6). `promotion/layout.py`
      gained a `Layout` object bound at runtime; `config.active_layout(cfg)`
      resolves it from the active target (`sot` if present, else `shadow_sot`,
      else the default map). It is threaded through `create_app` **and** every
      tool builder that names a mirror path — `build_record_tools`,
      `build_workflow_tools`, `build_scrape_tools`, `build_annotate_tools` —
      **so the corollary landed with the reader half, not after it**: the
      `dest_dir` a record is written to is now the same string the
      workflow-state query counts, asserted by
      `tests/tools/test_layout_binding.py`. `MIRROR_LAYOUT` is demoted to *the
      default target's* map; unknown kinds raise rather than defaulting to a
      plausible-but-wrong path. Original statement follows.
      ~~DECISION SETTLED, IMPLEMENTATION OPEN: reader-side map~~ `sync()` writes
      SOT relpaths **verbatim** into the QA root, so the QA tree adopts the
      *target's* layout (flat `ttl/model`, `ttl/vocab`, `ttl/data` for the
      shadow) — no translation on sync. Readers resolve through the **active
      target's** placement map instead of the module-constant default. Today
      they do not: `main.py:114-117` reads `MIRROR_LAYOUT["model_ttl"]` =
      `metacontent/model` and `vocab_ttl` = `metacontent/vocab`, so a straight
      sync lands the model where nothing looks for it and **the §3 activation
      checkpoint fails with the content sitting right there**. Note
      `shadow_sot.mirror_layout` in `config/dashboard.rson` is currently read by
      **nothing** (zero hits across `src/`, `scripts/`, `tests/`).
      **Corollary to settle while implementing, not after:** writers compose
      through the same constant, so promotion-unit composition must resolve
      through the per-target map too — otherwise new records land at
      `content/ttl/data` while synced content sits at `ttl/data`, and the mirror
      is two trees pretending to be one.
- [x] **B2 — the sync runner. DONE 2026-08-22.** `sot_sync/runner.py`
      (`sync_into_qa`) + `scripts/sync_shadow_to_qa.py` + the `config.shadow_sot`
      / `config.target_layout` accessors. **The source is read-only by default:**
      `sync()` only ever calls `pull_remote`/`snapshot`/`fetch`/`current_stamp`,
      so a `ReadOnlySource` satisfies it completely, and the runner *refuses* a
      writable source unless explicitly overridden — the safe path is the
      default rather than the disciplined one. Paths are copied **verbatim**
      (§3.6), the report carries the git-content/pointer split, and the sync is
      left **uncommitted** unless `--adopt` is passed, because adopting an
      unexamined SOT state as a baseline is what the checkpoint exists to
      prevent. Re-runnable: a second sync of an unchanged target reports no
      drift (tested).
      - **Latent bug found and fixed on the way:** `config.git_content_extensions`
        read `pointer_git_content_extensions`, a pre-inversion key name, while
        the config file, CLAUDE.md and this plan all say `git_content_extensions`.
        The configured list was therefore **ignored** in favour of the built-in
        default. The two lists were identical, which is precisely why nothing
        caught it — the same "edit the config, nothing happens" shape as the
        write-once `.gitignore` and the unread `mirror_layout`. Now reads the
        documented key (legacy name still accepted).
- [x] **B3 — snapshot FROZEN (decided 2026-08-12).** The 2026-07-19 534-object
      seed **is the baseline of record; do not re-seed.** The §3 checkpoint
      figures (327 records; 469 absent / 0 malformed) are computed against it,
      and re-seeding would silently shift them. The 15 post-seed production
      objects are deliberately out of scope for 4.6 acceptance. Standing
      constraint: **never re-seed after a checkpoint is recorded** — if a refresh
      is ever wanted, re-seed first, then recompute every baseline.

Checkpoint at first sync — record, do not assume:
- **Pre-sync baseline: the sandbox is EMPTY.** Verified 2026-08-14 at
  `f72994e` — `sandbox.stage_root` holds 0 files, no `.git`, no `.qa/`; the QA
  repo has never been initialized. This is the comparison point the first sync
  is measured against. **If a later session finds it non-empty, a run happened
  (possibly a partial or interrupted B2): reconcile that state deliberately —
  do not sync on top of it**, since a half-populated tree makes the split
  figures below meaningless and drift unreadable.
- QA repo initializes under the current git-content list, so the storage policy
  applies from the start and `migrate_to_pointer_management` does **not** run
  (remains the scheduled-first-run item).
- Expected split (dry run): ~463 files / 3.9 MB git content; ~71 files /
  128.4 MB pointer-managed. **Deviation is a finding.**
- The shadow's **flat** production layout is the first real exercise of §3.6 —
  but **only once B1 lands**. Corrected 2026-08-12: this bullet previously read
  as though the translation path already existed and the shadow would exercise
  it for free. It did not exist; the flat layout is what *forced* B1, not what
  tests it. Read it as the acceptance criterion for B1, not as a property of
  the sync.
- Capture the post-sync baseline (gate findings, orphan report, panel
  obligations) **immediately, before triage.** The shadow has no images, so TTL
  references absent assets; that baseline keeps partial-copy artefacts from being
  read as real defects (and a clean-looking orphan report from being read as
  evidence the heuristic works at scale).
- **qrcode-legacy-baseline decision (verified 2026-07-29):** the ref-integrity
  shape, once armed, will flag every image-family reference (`schema:image`,
  `vad:image3d`, `vad:qrcode`) as unresolved on first sync — because the images
  were not cloned, NOT because the data is wrong. The 202 `vad:qrcode` values in
  the shadow are well-formed absolute URIs (`{domain}/images/qrc_<guid>.jpg`),
  same shape as `schema:image`; **no qrcode-specific legacy dangler exists.** So
  the baseline expects all image-family refs to dangle as one known-partial
  class (images-absent), and a qrcode value that is a *bare filename* rather than
  a full URI would be a real finding (the new-tool base-join bug leaking into
  data), not part of the expected partial. Do not arm the shape against the
  image-less shadow expecting a clean pass — arm it knowing the whole image-
  reference class is a recorded known-partial until the full-corpus sync.

#### FIRST SYNC — RUN 2026-08-22, result recorded

Ran against the frozen shadow, 62 s, `scripts/sync_shadow_to_qa.py` (no
`--adopt`; the tree is deliberately left uncommitted for inspection).

- **535 objects → 606 files** in `sandbox.stage_root` (132.3 MB): the 535 SOT
  objects plus 71 `.ptr` sidecars.
- **Split matches the prediction exactly: 464 git content / 71 pointer-managed
  / 71 sidecars.** Every managed binary has its sidecar; no deviation to chase.
  (464 rather than the earlier 463 because the metacontent refresh added one
  `.ttl` — D2.)
- Drift **+535 / ~0 / -0**, uncommitted. QA repo initialized on this run, so
  `migrate_to_pointer_management` did **not** run — it remains the
  scheduled-first-run item, still unexercised against real content.
- Top level: `ttl` 393, `documents` 180, `stats` 33 (the latter two include
  their sidecars).
- **Layout landed verbatim, as designed:** the model is at `ttl/model`, *not*
  `metacontent/model`. This is the reader-side-map decision working as intended
  and is why B1 is still required — see below.

#### Activation checkpoint — the affordance layer goes live HERE

The affordance layer is built, tested, and **inert** until content arrives *and*
the readers can address it. Capture this explicitly rather than assuming — same
"wired-but-inert until its input arrives" shape as the write-once `.gitignore`.
**Sync alone does not activate it:** with B1 unbuilt the content lands at
`ttl/model` while the loaders read `metacontent/model`, and every box below
fails with the data sitting on disk. B1 + sync, then measure.

- [x] **Model dir present in QA and addressable by the loader** (2026-08-22,
      after B1): `ttl/model`, 4 files, 2601 triples, resolved through the active
      target's map. Before B1 it was present but unreadable — `main.py` looked in
      `metacontent/model` and `load_ontology_model` returned `None` **with the
      correct ontology on disk**, which is the failure B1 existed to fix,
      observed rather than predicted.
- [x] **`type` resolves from the ontology — MEASURED LIVE through `/api/tools`:**
      `record.new_work.type` is a strict `enum` of **11** (no
      `x-enum-suggested` fallback present), `record.new_digital.type` is **9**
      and contains `BlenderComposition`. Exactly the predicted numbers, now
      reaching the form rather than merely computing.
- [x] **`x-vocabulary` pickers resolve**: `/api/affordance/vocabulary/papers`
      returns **11** real thesaurus candidates (`the:ArtezaSketchbook`,
      `the:CansonMixedMedia`, …) from the synced vocab, by the same query the
      gate enforces.
- [x] **`x-file-ref` pickers resolve** over `fs.list`, sandbox-contained:
      `documents` returns **125** candidates with **`.ptr` sidecars correctly
      hidden** (the 55 PDFs appear as `.pdf`, not `.pdf.ptr`). `images` returns
      **0** — correct and expected, the shadow carries no images by decision.
- [x] **Two-gate baseline recorded — RUN 2026-08-22** over the whole synced tree
      (327 TTL files, 8361 triples, 3 s) via `scripts/gate_baseline.py`:
      - **asset-reference gate: 469 absent / 0 malformed / 0 resolved.** The 469
        is the predicted number exactly, and it is the recorded known-partial —
        no images were cloned, so every well-formed image reference dangles. 0
        resolved is correct for the same reason.
      - **`0 malformed` is the load-bearing half.** It confirms the
        qrcode-legacy-baseline decision on real data: there is no bare-filename
        qrcode in the shadow, so that floor stays a live discriminator for the
        base-join bug rather than being lost among the expected danglers.
      - **vocabulary-reference gate: 417 resolved / 0 dangling — clean**, as
        predicted, against `ttl/vocab` + `ttl/tags` resolved through the active
        layout.

**✅ ACTIVATION CHECKPOINT COMPLETE (2026-08-22).** Every box measured, none
inferred. The affordance layer is proven **live**, not merely built — which is
what this checkpoint existed to establish before any workflow run could be
trusted. A green run from here is testing the real thing, not the fallback.

#### First contact — RECORD these, do not misread them as defects

Distinct from the B1–B3 gate above: nothing here blocks the sync. These are
things the first sync **will** produce that look like bugs and are not, written
down now so they are recognized in the moment rather than diagnosed. Verified
against the frozen shadow, 2026-08-11.

- **A 0-byte pointer-managed binary.** `documents/CupsStudyCriticism.pdf` is
  zero bytes **in production too**; the shadow copied it faithfully. The first
  sync mints a `.ptr` over empty content, which the asset-reference gate and the
  attic meet on day one. This also vindicates `_is_folder_placeholder`'s note
  that the predicate is the **trailing slash and deliberately not zero length**
  — a length-based filter would have dropped a real file and produced phantom
  absence (sync deleting a file that is really there, converge re-uploading it
  forever). The 0-byte PDF is that note's live counterexample.
- **`ttl/tko/` exists in production as a placeholder only**, no content behind
  it — correctly absent from the shadow and from QA. An empty prefix is not a
  failed copy.
- **The whole image-reference class dangles**, per the qrcode-legacy-baseline
  bullet above: images were not cloned. The **bare-filename** qrcode value is
  the discriminator that would be a real finding against the 0-malformed floor.

### Per-function acceptance (§6) — produces the scenario corpus

Each function is built, then Rick tests it and its workflow before the next
starts. RDF Entry first: enter a newly-finished work → promote → land on shadow
SOT → verify. **Instrument the recording before the first test:** Rick's manual
RDF Entry session *is* the reserved Scenario #1 (recorded human entry,
routing-policy admission seed). The harness is driver-agnostic, so capturing the
step sequence while he drives is nearly free; reconstructing it after is retyping
from memory. Each subsequent function test adds an episode — 4.6 yields the
human-driven scenario corpus as a by-product.

#### ⛔ A0 — the promotion tail needs a driver. A1 cannot run until it does.

**Deliberately NOT in the B1–B3 gate**: A0 does not block the sync, it blocks
the *acceptance runs*. Found by confirming the inventory before planning A1
(2026-08-12), which is precisely the class of thing that confirmation is for —
a "built" checkmark hiding a missing surface.

`run_promotion` and `refresh` are **library-complete and tested, but
UX-unreachable.** The HTTP surface is `/`, `/api/health`, `/api/tools`,
`/api/workflow-state`, the two `/api/affordance/*` endpoints, and
`POST /api/tool/{name}`; `run_promotion` is called from exactly one non-test
place, `scenarios/harness.py` (`workflow.promote`). Every A/B step below ends
in **+ Distribute Data + Server refresh** — "the real payload" — so with no
driver, the human-driven half of 4.6 cannot start.

- [x] **A0 — trusted-side promotion driver. DONE 2026-08-22.**
      `promotion/driver.py` + four routes (`/api/promotion/preview|approve|
      reject|pending`) + `/api/refresh`. Not registry tools: they call the driver
      directly in the orchestrator, and `_build_promotion_driver` is the one
      place a **writable** transport is constructed.
      - **Two phases, not a blocking callback.** `on_preview` is synchronous, but
        the request that builds a preview must return for a human to read it, and
        parking a worker thread on an Event holds a thread hostage to a person.
        So `run_promotion` gained an explicit `preview_only` stop — the real
        gates and the real preview run, nothing converges — and approval is a
        second pass. `preview_only` is distinct from `rejected` so the audit log
        never records a decision nobody made.
      - **Approval is scoped to what was reviewed.** `approve` recomputes the
        preview and compares a fingerprint (base commit + manifest + semantic
        summary); a mismatch returns **`stale` / HTTP 409** and converges
        nothing. Between preview and approval the QA tree can move — another
        edit, a stray write, an interrupted workflow — and converging a manifest
        the human never saw is exactly what the review gate exists to prevent.
        Same shape as the pre-push drift check, pointed at the QA side.
      - **Reject leaves both sides consistent:** nothing was written, so nothing
        is undone; the QA work stays on disk to fix rather than being lost, and
        SOT was never touched. After convergence the remedy is rollback, not this.
      - A gate failure yields **no token**, so the stop cannot be walked past by
        holding one. 16 tests (8 driver, 8 HTTP) incl. the stale case.
      Original done-condition follows, all points met:
      1. A **trusted-side route** runs the promotion tail. It is **not** a
         registry tool: promotion is the single gated exit (law 1) and stays in
         the orchestrator. Mirror `workflow.promote`'s *shape*, not its
         auto-approve.
      2. **The preview step STOPS for human approval.** `run_promotion`'s
         `on_preview` hook is the seam; the harness supplies an auto-approving
         callback because episodes are unattended. A route that reuses that
         callback is a **fail**, not a shortcut — the change preview *is* the
         review gate until the browser lands (Phase 7), so a route without the
         stop silently deletes the only review the system has.
      3. **Convergence happens only on approve.** Gates → preview → *stop* →
         approve → commit + converge. No converge on any other path.
      4. **A reject path exists**, and it leaves QA and SOT consistent: reject
         before convergence abandons the unit without touching SOT; the
         rollback path (QA revert → converge the reverted state) remains the
         remedy after convergence. Exercised at least once during A1.
      5. Refresh is drivable, so the state-flow-across-refresh property the
         dependency-ordered runs depend on is actually exercised.

#### Wiring cycle 1 — RDF Entry. BUILT 2026-08-24, awaiting acceptance

- [x] **Extraction doc** — already written and applied (`EXTRACTION_record_group.md`).
- [x] **`html/function.html` served directly as the hub** (D1), plus
      `/stageStatus` answered from the standing-query engine so the hub's queue
      badges work — one computation, now three renderings (panel, narration, hub).
- [x] **`/rdf/entry`** renders the Groovy form's field set, order and defaults
      (`ux/forms.py`, `RDF_ENTRY_LAYOUT` from `support/HtmlForm2Ttl.groovy`):
      fresh guid, dates defaulting to today, `units` defaulting to **inch** (D6),
      derived readonly `qrcode` (D1), no `workOnSite` (Q2), no `sig` radios (D7).
- [x] **Widgets come from the schema, layout from the Groovy form.** Verified
      live against synced content: `type` offers **11** ontology-resolved values,
      `has_paper` offers **11** vocabulary candidates, `units` its four.
- [x] **Submit → record in QA → STOP at the Distribute review** (A0), with
      Approve/Reject. Nothing reaches SOT without an explicit approval.
- [x] **D1 executed:** `ux/dashboard.html` and
      `test_affordance_annotations_survive_to_the_renderer` are **deleted**, and
      the replacement contract landed in the same commit —
      `tests/ux/test_rdf_entry_form.py` asserts *the offered set IS the enforced
      set* (the rendered `<select>` equals the schema `enum` `validate_args`
      enforces; an out-of-enum value is refused at dispatch and redisplayed).
- [x] **B1 leak closed:** the `x-file-ref` annotation was hardcoded to
      `content/images`, so on the flat shadow layout the picker pointed at a
      directory that does not exist. It now follows the active layout (`images`).
- [x] **`image.qrcode` — the missing submit-time side effect (found by driving
      the form, 2026-08-25).** The first real run failed the asset gate with
      3 dangling references. Two causes, and only one was user error:
      **every** record derives `vad:qrcode` (D1) while *nothing generated the
      JPEG* — the Groovy did it on submit (`ImageMgt.qrcode`), the dashboard
      decomposed the side effect out of the record tool (correctly) and never
      built the replacement. So entry could never pass its own gate. Now a
      registry tool composed by the entry route, Groovy-faithful: encodes the
      **work URI**, `qrc_<guid>.jpg`, **125px** square, skips an existing file.
      The third dangling ref was a real data error the gate correctly caught —
      a record naming an image not on disk.
      **The gate was right; the workflow was incomplete.** Nothing was weakened.
- [x] **Fixture gap found by the same test:** the entry test's driver was built
      without `image_base`/`layout`, so the asset and vocabulary gates were not
      armed and "gates passed" meant far less than it read. The fixture now arms
      the driver exactly as `create_app` does, with a real ontology and vocab.
- [x] **Repeatable dev loop (`scripts/reset_to_baseline.py`, 2026-08-25).**
      Approve → inspect the bucket → reset **both sides** to the adopted
      baseline → run the same entry again. This is rollback, not deletion
      (law 6): QA is restored to the baseline tree and the restoration recorded
      as a *new* commit, then the bucket is converged to that state. Rehearsed
      end to end against the real shadow: bucket returned **byte-identical** to
      the baseline (535 objects / 132,277,964 B).
- [x] **Hand-placed binaries were invisible to promotion — FIXED.** A managed
      binary is gitignored, so its `.ptr` sidecar is the only thing the
      git-derived manifest can see. `fileops` mints one on write and sync
      rebuilds them after a pull, but a file dropped in by hand (`cp`) had
      neither: it passed the asset gate (the real file *is* there locally) and
      then simply never converged — **the record reached SOT referencing an
      image that would never be there.** Found on the first real approve. The
      driver now reconciles sidecars before building the manifest, so what is in
      the tree is what gets promoted, and the preview stop keeps that honest by
      showing a stray binary for a human to reject.
- [x] **Rick's acceptance run — PASSED 2026-09-03.** Drop folder → RDF Entry →
      four gates green → preview → approve → converged to the shadow SOT. Three
      objects landed (`ttl/data/f28b42d3-….ttl`, `images/FairyPool3.jpg`,
      `images/qrc_f28b42d3-….jpg`); QA git `ded277c`; shadow baseline moved
      535 → 538. **The first time a human drove this dashboard from form to
      SOT**, and the functional half of the 4.7 cycle-1 exit.
- [ ] **⚠ Scenario #1 — NOT recorded, and the run it was meant to capture is
      spent.** The episode recorder was never wired, so the reserved
      human-entry recording does not exist. The plan's own warning applies
      exactly: capturing live is nearly free, reconstructing after is retyping
      from memory. **Do not reconstruct this run.** Wire the recorder first,
      then capture the next acceptance (a second Entry, or RDF Digital) as the
      corpus seed — with its depends-on edges, which is what makes the Phase 5
      two-driver replay assert ordering rather than only end state.
      Consequence to state plainly: **the 4.7 exit gate requires each accepted
      step recorded as an episode, so cycle 1 is functionally done but
      formally owes one.**
- **Three defects found by driving it for real**, each a workflow gap rather
      than a wrong gate — the pattern is now consistent enough to expect:
      1. `image.qrcode` never existed (`8492138`) — every record derives
         `vad:qrcode`, nothing generated the JPEG, so entry could not pass its
         own asset gate.
      2. Hand-placed binaries had no sidecar (`d57181e`) — invisible to the
         manifest, so the record reached SOT and the image did not. This is why
         the drop folder exists.
      3. The image picker offered generated artifacts (`32379b3`) — a
         `qrc_*.jpg` appeared as a selectable source image after the first
         completed entry.

#### Wiring order (decided 2026-09-03) — and where it crosses into Phase 5

Rick's sequence: **all dashboard workflows first, scenario recorder last.** The
queue splits at a wall the inventory below already marks, and the split is the
thing to plan around:

**Cycle 1 — RDF Entry: COMPLETE, QA-passed 2026-09-04.** Two entries driven end
to end to the shadow SOT. Six defects found only by driving it for real (missing
QR generator; sidecar-less hand-placed binary; generated artifacts in the picker;
the panel's per-poll rescan blowing the ops quota; leave-guard JavaScript that
never parsed; a collision message telling the user to reload and lose the form)
— every one a workflow gap rather than a wrong gate, which is now the expected
shape.

**Wireable now — the registry tool exists, the cycle is UI + acceptance:**
1. **RDF Digital** (`record.new_digital`) — `SculptureForm` type set (9,
   incl. `BlenderComposition`), required `note`, `file_format` enum, `depth`.
2. **Update work on site** (#9) — **known partial**: exercises scrape /
   extraction / confirmation queue, but *not* pHash against real originals,
   because the shadow carries no image corpus. Record as partial when tested.
3. **Annotate Work** (#6 / TCAP) — first real-content exercise of the
   tie → hygiene-ledger loop.
4. **Entity creation** (`record.new_entity`) — built, but its *input* is AI
   criticism, so it is input-gated below.

**Blocked on `ai_service/`, which does not exist — this is Phase 5 Stage A, not
a wiring cycle:** critical analysis derivation (Generate AI criticism), Derive
Concepts, Tag Markdowns, Summarize. Building these means the provider seam, task
profiles, schema validation with retry/repair, and provider-neutral recorded
doubles, under law 7 (no handler touches an SDK) and law 8 (assert structure,
never exact strings). `TODO.txt`'s LibreChat/Kimi note is this same work.

**Still deferred regardless:** Proof (#5, OriginStamp key + 24 h wait), Brand
Image (#7). The digital path's workflow B also depends on **E → F → G** (Series,
Collection of Backgrounds, HDR Entry) — three entry forms that do not exist.

**The dependency that survives the reorder:** Phase 5's competency metric and
"admission by scenario" *replay recorded episodes*, so the corpus is required
before an agent can be **scored** — but not before AI features a human drives
are **built**. Those are separable, which is what makes this order work. What it
does not survive is skipping the recorder indefinitely: without episodes there
is nothing to admit an agent against, and that is the whole Phase 5 mechanism.

#### Built-vs-gated inventory — CONFIRMED against the live registry 2026-08-12

Checked against `build_default_registry(...)` (21 tools) at `9b17858`, not
assumed. Three rows corrected from the draft advisory this table absorbs.

| Function (from Workflows.txt) | Status | Gate if not built | Testable in 4.6? |
|---|---|---|---|
| RDF Entry (`record.new_work`) | built | — | **yes** |
| RDF Digital (`record.new_digital`) | built | — | **yes** |
| Distribute Data (`run_promotion`) | library-complete, **UX-unreachable** | **A0** | **after A0** |
| Server refresh (`refresh`) | library-complete, **UX-unreachable** | **A0** | **after A0** |
| Update work on site (`workflow.update_work_on_site`, #9) | built | — | **yes** (partial, §7) |
| Annotate Work (`concept.annotate_work`, #6/TCAP) | built | — | **yes** |
| Entity creation for criticism (`record.new_entity`) | **built — CORRECTED** | input only (needs AI criticism) | **input-gated** |
| Generate AI criticism | not built (no `ai_service/`) | Phase 5 | no |
| Derive Concepts / Tag Markdowns / Summarize | not built | Phase 5/8 | no |
| Proof Initiated / Completion (#5) | deferred | OriginStamp key + 24 h wait | no |
| **Brand Image (#7)** | **NOT BUILT — CORRECTED** | deferred; joins the gated set with Proof | **no** |

**Name-collision warning, do not let it mislead:** `concept.promote_markdown_tags`
exists in the registry, but it is the **TCAP evidence half (#15)** — it flips
`conceptsExtracted false→true` and preserves consumed tags in the non-converged
`evidence/` area. It is **not** the AI "Tag Markdowns" step Workflow C means,
which is unbuilt (Phase 5/8). The names are close enough that a reader will
conclude C is half-done; it is not.

**Brand Image #7 is not built** — verified: no tool, no workflow module; the only
"brand" occurrences in `src/` are comments recording that image branding was
*decomposed out* of the authoring tools as a deferred side effect. The
`image.scale`/`image.convert` primitives exist, so it is composable later.
**Workflow D is therefore not a 4.6 target** and joins the gated set with Proof.

**The honest 4.6 acceptance surface:** workflow A steps 1–4 and B steps 1–4,
with the Distribute+refresh tail under all of them — *after* A0. Everything past
those is Phase 5/7/8 or external-key gated. Naming it is what lets the test stop
at the wall on purpose rather than discovering it mid-session.

#### Workflow A (Watercolor) — the primary acceptance path

Testable **A1 → A4**; run as a **dependency-ordered sequence, not in isolation**,
because the dependencies force state to flow across the refresh between steps —
a refresh that silently dropped state breaks the next step, which is the
integration property the FakeBucket episodes could not prove.

- **A1 — RDF Entry** (+ Distribute + refresh). *This is Scenario #1 and the
  activation-checkpoint session — one sitting, both payoffs.* Enter a
  newly-finished watercolor → gates → preview → **approve** → converge to shadow
  → refresh. Verify it lands on the shadow SOT and survives refresh.
- **A2 — Update external website with URL + publish.** External-effect step;
  record what "publish" touches and whether it is in scope or a manual action
  outside the dashboard.
- **A3 — Update work on site** (depends on A2) (+ Distribute + refresh).
  **Known partial (§7)** — no pHash against real originals.
- **A4 — Annotate Work** (depends on A1) (+ Distribute + refresh). TCAP
  navigate/annotate over the entered work; ties → hygiene ledger → panel open
  item. First real-content exercise of the tie→ledger loop.
- **Planned stops:** A5 (AI criticism) is Phase 5; A6 (entity creation for
  criticism) is input-gated on A5. Continuation targets, not 4.6 failures.

#### Workflow B (Blender / Digital) — same spine, two extra gated steps

Testable **B1 → B4**, mirroring A with `record.new_digital` and the
`vad:SculptureForm` type set (the checkpoint's "9" case). B1 exercises the
digital form: required `note`, `file_format` enum, `depth`, **derived** qrcode,
and the SculptureForm dropdown incl. `BlenderComposition`. B2–B4 as A2–A4.
**Planned stops:** B5–B6 (AI, as A5–A6); **B8–B9 (Proof)** are gated on the
OriginStamp key *and* a 24-hour blockchain wait — untestable in a session
regardless of the key, so record them as **externally** gated, a different
category from AI-gated.

#### Scenario #1 — recorded as A1 is driven, WITH the dependency edges

A1 *is* the reserved human-entry recording; instrument before driving, not
reconstructed after. **Record the depends-on edges, not just the step list** (A3
depends on A2, A4 on A1): the edges are the order state must flow, and they are
exactly what Phase 5's agent driver must reproduce — so the episode encodes them
and the two-driver replay asserts ordering, not merely end state.

#### Workflow C (concept pipeline) — NOT a 4.6 target

C is almost entirely Phase 5/8 (Derive / Tag / Summarize are AI). TCAP
navigate/annotate is built (it is A4/B4), but the pipeline *around* it is not.
Recorded here only so C is not mistaken for 4.6 scope.

**Carry-forward for Phase 8 design (not 4.6 work):** C's notes describe
discarding the derived-concept TTL and tag TTL after distribution, preserving
curation notes only as dated zips under `conceptQueue/old`. That is the *same
pattern* as the settled TCAP evidence-preservation decision (tag evidence kept
in non-converged `evidence/`): a derived artifact carrying human judgment,
discarded after its product ships. **Phase 8 should unify these** rather than
let C reinvent a zip-based version of what TCAP already does structurally.
Flagged here because this is where the duplication is visible.

### Known partial (§7) — updateWorkOnSite

Its 4.6 test exercises scrape/extraction/confirmation-queue but **not** pHash
matching against real originals (the shadow carries no images). Record as a known
partial *at the time it is tested*, so it is not read as a full pass — it stays
one of the three items awaiting a full-corpus pass.

### Phase 4.6 exit gate

- **B1–B3 cleared** (§5), shadow content synced into QA, first-sync checkpoint
  recorded.
- **Activation checkpoint (§5) fully checked** — the affordance layer proven
  **live**, not merely built. A green run with unchecked boxes is a run against
  the fallback.
- **A0 cleared** (§6): the promotion tail drivable, with the preview stop and a
  reject path exercised.
- Every in-scope function from function.html working with its Groovy-sourced
  affordances and semantics, via the upgraded generic renderer.
- Extraction docs written and Rick-reviewed per function group.
- Rick's per-function acceptance passed, each session recorded as a scenario
  episode (Scenario #1 onward).
- Main workflows tested end-to-end against the shadow SOT: entry → gates →
  preview → promote → converge → refresh.
- Each tested step recorded as a scenario episode (Scenario #1 onward),
  **with its depends-on edges**.
- Known partials (§7) and the carried image-dependent items recorded as
  unexercised, **not discharged**. Planned stops (A5–A6/B5–B6 → Phase 5; C →
  Phase 8; Proof → OriginStamp; Brand → not built) documented as continuation
  targets, so the AI/external wall reads as scoped rather than as incomplete.

**Exit-criteria caution (from the finding that produced this phase):** the flat
text form accreted through deferral — no decision ever chose it, and no test
caught it, because "function works under a human-driven UX" is satisfied by a
text box that accepts a valid value. Exit criteria phrased in terms of
*function* rather than *fidelity* will pass on a degraded surface; 4.6's gate is
fidelity to function.html + Groovy semantics, not mere functionality.

Sequencing (revised 2026-08-12; the affordance half is done, so what remains is
the execution half): ~~confirm the built-vs-gated inventory~~ **done 2026-08-12,
now the §6 table** → clear the **B1–B3 gate** (§5: B1 reader-side map, B2
runner; B3 already decided) → run the sync → record the first-sync **and**
activation checkpoints → clear **A0** (§6) → A1 (RDF Entry = Scenario #1 =
activation proof, recorded with edges) → A2–A4, then B1–B4, as dependency-
ordered sequences → 4.6 exit → Phase 5 Stage A, which replays the A/B corpus
through the agent driver (the edges are why the two-driver comparison has
something to assert beyond end state). The 4.5 carried gaps (standing queries,
mid-convergence failure, Windows CI, orphan test) stay test-level work and can
interleave.

~~Superseded advisory: 4.5 close → sync + checkpoint → `AFFORDANCE_DESIGN.md`
review → enum/format dispatch + ref-integrity shape → renderer upgrade →
per-function acceptance.~~ Everything up to and including the renderer upgrade
landed 2026-07-29…08-11; the sync moved *behind* it and gained a build gate.

## Phase 4.7 — Wire the real dashboard UI, one function at a time  [new 2026-08-22]

**Goal:** the proven Groovy dashboard UI (`html/function.html`) becomes the
dashboard's actual surface. `function.html` is used **directly**; the Groovy
HTML-generating and request-handling code is the specification whose logic is
reproduced in Python over the existing registry tools. One major interface is
wired and working before the next starts — a short dev-test cycle per function,
with an enhancement pass deferred to a later phase.

**Why this supersedes 4.6's approach.** 4.6 built a *generic* renderer driven by
tool schemas, and the affordance layer that made it honest. That layer's
enforcement half is keeping (see below); its rendering half is not. The
realization behind the change is about the agent, not the UI: **the only way to
train an agent on dashboard work is for the complete dashboard to exist and for
the agent to watch a human use it.** A partial surface trains a partial agent.
The Groovy UI is complete and proven in daily use, so wiring it directly is the
fastest path to a full training ground.

**Second-order goal (this is the point, not a side effect):** the CE audience
gets an agent that learns *their* practice — how this user works, not how a
reference user works. The agent's contribution becomes: emulating the user,
mapping typed or spoken input onto the right form and TTL instance, drafting new
entry forms and eventually new processes, and orchestrating workflows that may
include other agents (e.g. concept derivation).

### Status of Phase 4.6 — closed by supersession, NOT by completion

Recorded honestly so no one reads a checkmark that was never earned:
- **Genuinely complete:** the affordance layer (schema-first affordances,
  dispatch enforcement, the asset and vocabulary gates, ontology-backed `type`).
  Its **enforcement** half is load-bearing in 4.7 and unchanged.
- **Never ran:** the execution half — the shadow→QA sync, the activation
  checkpoint, and every per-function acceptance run. At the close, the sandbox
  was still empty and HEAD was `6615ebb`.
- **Retired:** the generic schema-driven renderer and its zero-UX-code contract
  (decision D1 below).
- **Carried into 4.7 unchanged (B1, B2, A0):** these are not discharged by
  closing 4.6. 4.7 needs every one of them — metacontent cannot reach QA without
  a sync runner (B2), the QA tree cannot be addressed without the reader-side
  map (B1), and `function.html`'s **Distribute Data** button *is* A0 wearing a
  different hat. They remain the opening gate; see Phase 4.6 §5/§6 for their
  full statements and done-conditions.

### Decisions (2026-08-22)

- **D1 — the generic renderer is replaced outright.** `function.html` becomes
  the only UI; the schema-driven renderer and
  `test_affordance_annotations_survive_to_the_renderer` are deleted with the
  function that supersedes them. Consequence accepted deliberately: **new tools
  no longer appear in the UI for free**, and an unwired function is unreachable
  from the dashboard until its turn comes.
- **D2 — the shadow keeps all 534 content objects; metacontent is refreshed
  from production.** Done 2026-08-22: `ttl/model` + `ttl/vocab` re-seeded (32
  objects), so the baseline is now **535 objects / 132,277,964 bytes**. This was
  not hygiene — the model file backing the `type` enum had changed in production
  (`schemaSupplement.ttl`, 4663 → 6120 B) and a new vocabulary file
  (`concepts2026-08-21.ttl`) did not exist in the shadow at all. A stale model
  yields a wrong `type` set; a missing vocabulary file false-dangles every
  reference to its concepts. The 327 legacy work records stay in play during
  RDF-entry testing, with the image-family reference class dangling as the
  recorded known-partial.
- **D3 — images are placed in the sandbox, not gated around.** RDF Entry
  requires an image; the dev-test cycle puts the real image file into the QA
  sandbox before promoting, exactly as real use does. The asset-reference gate
  therefore gets its first honest exercise instead of being relaxed. No gate is
  weakened to make a cycle green.

### What replaces the zero-UX-code contract

D1 deletes a real guard, so name its replacement rather than discovering the
gap later. The property worth keeping was never "the UI is generated" — it was
**"what the form offers is what the system enforces."** After D1 that invariant
migrates:

- **Enforcement is unchanged and still binds both drivers.** `enum`/`format` at
  dispatch (`validate_args`) and the asset/vocabulary gates at promotion do not
  care what rendered the form. The affordance annotations stay in the schemas —
  they remain the *agent's* contract and the source the form's option lists are
  built from.
- **New contract test, per wired form:** the option list `function.html` offers
  for a store-backed field is built from **the same query the gate enforces**,
  and a value outside it is rejected at dispatch or at the gate. This is the
  picker-set == gate-set identity from the activation checkpoint, promoted from
  a one-time check to a standing test.
- **Law 10 still holds, and is the line not to cross:** handlers reproduce
  Groovy *semantics* by composing registry tool calls. No handler may touch
  `fileops`, git, or a transport directly. Note the law's wording ("thin
  bindings") describes 4.6's shape; 4.7's handlers are thicker by design, while
  the invariant — **no capability reached except by dispatching a registry
  tool** — is unchanged. Worth a CLAUDE.md wording amendment at some point.

### The per-function cycle

Each wired function repeats the same short loop:
1. **Extraction doc** for the function group (the standing convention), Rick-
   reviewed, quirks classified load-bearing vs. candidate-bug. **RDF Entry's is
   already written and applied** — `EXTRACTION_record_group.md` pinned the closed
   sets, made qrcode derived, required the image, and tightened the vocabulary
   gate. The record group starts the cycle with its semantics already settled.
2. **Wire the form**: serve that part of `function.html`, reproduce the Groovy
   handler's per-field behaviour (defaults, derived values, option lists,
   validation) in Python over registry tools.
3. **Dev-test with Rick** on the real shadow, end to end including the
   Distribute Data + Server refresh tail.
4. **Record the session as a scenario episode**, with its depends-on edges.

### Order — RDF Entry first, and the chain the workflow edit revealed

RDF Entry (workflow A1) is first, unchanged. **Workflows.txt now records a
dependency chain that lengthens the queue:** workflow **B (BlenderComposition)
depends on E (Create a Series) → F (Create a Collection of Backgrounds) → G
(Create HDR Entry)**, and none of those three entry forms exists in the registry
today (`record.new_work`, `record.new_digital`, `record.new_entity` are all
there is). So B is gated behind three new forms, and the wiring queue is A →
{G, F, E} → B → the rest. Sequencing the digital path before those three would
stall mid-cycle.

### AI competency instrumentation

The competency metric is a **Phase 5 scoring concern built on a 4.7
instrumentation duty**, split so 4.7 does not grow an evaluation framework:

- **4.7 records the evidence.** Every human-driven session becomes a scenario
  episode, tagged by function area (RDF entry, digital entry, annotate, series
  creation, …). The audit log already captures every tool call; the scenario
  harness already records replayable steps. This is the watching channel.
- **Phase 5 scores it.** Competency per function area = the agent driving the
  *same* recorded episodes and the end states comparing equal — the harness is
  driver-agnostic by construction precisely so this comparison falls out. This
  is the same mechanism as "admission by scenario" (Phase 5 Stage B); a function
  area's competency is the pass rate over its episodes.
- **⚠ Do not gate on the model's self-reported confidence.** A stated "99%
  confident" is not calibrated and is the wrong signal to admit an agent on.
  The threshold must be an **observed** pass rate over a named episode set, with
  the set and N recorded alongside the number — otherwise the metric measures
  fluency at claiming success. What "fully completes the function" means is
  itself per-area and must be written down before it is scored: for RDF entry,
  populate the form → gates pass → TTL correct → distribute → refresh, with the
  end state isomorphic to the human's.
- **Law 3 still applies to learning:** recorded sessions and file contents are
  data to learn *from*, never instructions to follow. An episode is not a
  privileged channel into the agent's intent.

### Phase 4.7 exit gate

- B1, B2, A0 cleared; metacontent live in QA and the affordance inputs
  addressable (the activation checkpoint, Phase 4.6 §5, recorded).
- `function.html` is the dashboard's surface for every wired function; the
  generic renderer is deleted, not coexisting.
- RDF Entry, then the E/F/G chain, then the digital path, each: extraction doc
  reviewed → wired → Rick-accepted end to end against the shadow → recorded as
  an episode.
- Per-wired-form contract test in place (offered set == enforced set).
- Function areas tagged and their episode sets named, ready for Phase 5 scoring.
- Known partials carried, not discharged: pHash against real originals, orphan
  heuristic at corpus scale, binary promotion at real image sizes, and the
  unexercised `migrate_to_pointer_management` first run.

## Phase 5 — AI coverage, then agnosticism  [priority 4, restructured]

Stage A — AI coverage (Anthropic-first):
- [ ] `ai_service/` seam from the first line of code: handlers never touch an
      SDK; everything goes through `ai_service.call(task_profile, inputs)`.
      One adapter (Anthropic) initially.
- [ ] Build AI coverage against every registry function (coverage is automatic
      where Phase 4.5's law held — the agent calls the same tools the buttons
      call; verify no orphaned functions).
- [ ] Replay the Phase 4.5 scenario corpus through the agent: same scenarios,
      two drivers (human UX vs agent), compared end states.
- [ ] **Function classification**: from scenario runs, classify every
      AI-involved task into a capability tier; write task profiles from this
      empirical record (defines what API compliance means).

Stage B — agnosticism and routing (CE_DESIGN §9.1):
- [ ] Second adapter (OpenAI-compatible / OpenRouter) — or LiteLLM if the
      Stage A surface argues for it. Recorded doubles are provider-neutral,
      keyed by task profile; CI runs the suite against both wire formats
      offline; opt-in live smoke lane.
- [ ] **Three-layer routing**: profiles → capability floors (stable); provider
      catalog → tier/model/price (volatile config, refreshable); router →
      cheapest model satisfying the floor.
- [ ] **Admission by scenario**: a model enters a tier only by passing that
      tier's scenario suite (Phase 4.5/5 corpus).
- [ ] **Escalation ladder**: floor tier first; validated failure (schema repair
      exhausted, gate rejection) escalates one tier, capped N. Escalation-rate
      metric per model → demotion signal.
- [ ] **Metering**: model identity + token usage + computed cost on every
      response (shared plumbing with prov: attribution); audit-logged by
      profile/tier/model; per-episode cost report.
- [ ] Schema validation with retry/repair on every structured output;
      malformed-output + budget-enforcement tests; profile-swap invariance
      test (same task, both adapters, schema-identical results from doubles).
- [ ] Secrets in environment only; ai_profiles.rson and the provider catalog
      never contain keys.

## Phase 6 — Agent orchestration core  [reserved slot]

- [ ] Chat loop (FastAPI + simple UI); voice input via speech-to-text
      feeding the same channel (can trail).
- [ ] Workflow-state file on disk: agent reconstructable from disk state at
      any time; single-user, single-workflow enforcement.
- [ ] Agent wiring: tool registry (Phase 2) + ai_service (Phase 5) +
      audit/provenance on every action (prov: with model identity).
- [ ] First conversational capability: narrate sandbox/queue state and run
      Phase 2 tools under instruction.

## Phase 7 — QA store + data browser  [reserved slot]

The user's window; completes the promotion review gate.

- [ ] QA RDF instance (Fuseki or in-process RDFLib per config) over the
      sandbox stage tree; loaded by refresh (Phase 4).
- [ ] Reuse cwvaServer-py data browser against the QA endpoint: enter an
      artwork instance, view all fields, follow links (criticisms etc.)
      as in prod CE.
- [ ] Upgrade promotion review gate: change preview + affected-instance
      links into the browser; agent records that review occurred.

## Phase 8 — Concept pipeline as agent workflows  [reserved slot]

- [ ] Port derive → promote → distribute → tag → annotate as agent-managed
      workflows over the queue state machine (concept_agent capabilities
      surfaced as tools; batch API pathway from Phase 5).
- [ ] Each workflow terminates in a promotion unit (Phase 3).
- [ ] End-to-end test per workflow: fixture stage tree, mocked AI, fixture
      SOT transport, promotion, QA git history verified, revert→converge
      round-trip.

## Phase 9 — Optimistic publication + merge/demote  [priorities 9–14]

- [ ] **Optimistic concept publication** [9]: no mandatory curation gate;
      derivation output promotes after conformance gates only.
- [ ] **Merge/demote workflow** [9]: retire concept → attach label to
      survivor as skos:altLabel → rewrite all tag/annotation references →
      one promotion unit; referential-integrity gate proves completeness.
- [ ] **Dup matcher** [11–13]: rapidfuzz, score = max(ratio,
      token_sort_ratio) after normalization (lowercase, strip hyphens/
      possessives); threshold **> 0.9 default, user-overridable** [12];
      label set = skos:prefLabel ∪ skos:altLabel ∪ rdfs:label [13].
      Lemmatized third signal deferred until practice demands it.
- [ ] **Derivation-time reporting**: near-matches in agent output,
      non-blocking ("publish anyway / use existing?").
- [ ] **Hygiene ledger** [10]: unresolved near-matches persisted in a TTL
      file in the sandbox; "show me pending concept dups" supported.
- [ ] **Annotation-time remedy** [14]: concept picker runs the matcher over
      current candidates; near-synonym pairs get an inline merge offer that
      launches merge/demote; annotation proceeds with the survivor.

## Phase 10+ — AI feature backlog (CE_DESIGN.md §10, interleave from Phase 6 on)

NL→SPARQL console → form drafting → tag-curation UI → SHACL translation →
diff/report narration → keep-notes sniffing and the rest. Each feature:
task profile, schema tests, provider-neutral double, both-provider CI.

## Phase 11 — CE onboarding

- [ ] Agent-led first-run wizard: config, sandbox/stage creation, SOT
      transport setup, one full record → validate → promote →
      view-in-browser cycle.
- [ ] **Identity decision** (CE_DESIGN §13.2): wizard presents own-domain /
      communal / defer, writes `domain` to config, scaffolds the local
      extension scheme (§13.5). `work:` is sovereign; `vad:`/`the:` are commons
      (never renamed). Namespace rebase (§13.6) is post-v1.
- [ ] Windows install script (Layer-2 user + ACLs); Linux Landlock check.
- [ ] SANDBOX_SPEC.md + OPERATIONS.md; release gate = Phase 1 exit gate
      re-run on release artifacts, both OSes.

---

## Standing rules

1. The four CLAUDE.md non-negotiables most likely to erode under iteration:
   single gated exit, no exec tool, conformance-not-intent gates,
   optimistic publication. Re-read them at each phase boundary.
2. Every phase ends with its tests in CI and the harness/dashboard usable.
3. Decisions that change CE_DESIGN.md get recorded there in the same
   session they're made.

## Suggested first three Claude Code sessions

1. **Phase 1 core**: scaffolding + paths.py + fileops + adversarial corpus
   (Linux first; Windows corpus entries included, ACL script deferred).
2. **Phase 1 close + Phase 2**: Landlock broker, Layer-2 fault-injection
   test, tool registry + harness.
3. **Phase 3 start**: promotion unit + parse/SHACL gates against fixture
   git SOT repos.
