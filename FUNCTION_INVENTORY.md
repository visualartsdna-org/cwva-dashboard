# Dashboard UX — Function Inventory

Every function in the current UX (function.html / function2.html), categorized.
Disposition column: decisions already made are filled in; blank = for Rick to
annotate. Workflow column left open for the implied-workflow documentation.

Scoping decisions applied throughout:
- Single environment (dashboard no longer spans QA + prod targets).
- Single prod server (two-server Groovy deployment retired).
- All multi-target parameters (tgt=, target=) collapse to the one configured
  prod instance.

---

## 1. Record entry & authoring (create/edit content in QA)

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 1 | RDF Entry | /rdf/entry | Non-digital work record form | Information registering an artwork is input on this form including connecting an image of the work.  This will continue to exist but an alternative AI-agent dialog to collect the information will be available.  This task begins a workflow concluded with a push to SOT and a server refresh  |
| 2 | RDF Digital | /rdf/digital | Digital work record form | Same as RDF Entry but for digital works, collecting a few different fields of data and two image files|
| 3 | Entity | /entity_page | New entity record form | Registration of criticism instances and other types of data.  Introducing documents (any file) requires camelCased name.  For concept derivation, line inserted in doc after title [id=work:{URI}]. Needs a workflow of push to SOT and refresh |
| 4 | Interpretation | /interpretation | Interpretation for a work | This function is DISCONTINUED!! (replaced by Entity)|
| 5 | Proof | /proof | Load proof information | Uses OriginStamp (https://originstamp.com/solutions/timestamp/en) to encode image files on a blockchain for proof.  Two-step process: submit to OriginStamp (place incipient proof ttl record in proof folder), wait 24 hours, collect proof, finish populating proof data ttl, push to SOT and refresh. **Design notes for CC:** (a) OriginStamp submission is an outbound network *action* (POST) — add it to the sanctioned network effect class in CLAUDE.md alongside post-promotion refresh and the read-only site scrape. (b) Do NOT build this as one long-lived workflow: the 24h wait would block the v1 single-active-workflow rule. Build as **two workflows + a standing query**: workflow 1 ends at submission (incipient ttl in proof folder); "incipient proofs older than 24h awaiting collection" is a standing query / open obligation in the workflow panel; its resolving action is workflow 2 (collect, populate, promote, refresh). The proof folder is a stage-tree citizen — include it in the fixture tree. |
| 6 | Annotate Work | /annotateWork.html | Concept picker for work annotation; future home of the annotation-time merge remedy | Concepts relevant to the artwork chosen for work-instance decoration.  Collect condepts, decorate work, push to SOT, refresh.  |**Note for CC:** this is the first item requiring extraction of Groovy logic (everything else is rebuild/replace/reuse). Scope it explicitly: locate the decoration algorithm, document it, port with tests.  single ported module, shared by #6 and #15.
| 7 | Brand Image | *(no page — the ingest path)* | Brand an image file | Somtimes it is necessary to update an image related to an artwork instance.  This task stamps and image with correct website brand and changes file name to match the artwork title (camelCased), then push to SOT and refresh. **DONE 2026-09-14, as a property of ingest rather than a page** (Rick: "we don't need brand image anymore because edit record does everything needed"). `ImageMgt2` is ported to `image.brand`; RDF Entry and Edit Record each offer **Brand arriving images**, and the camelCase rename is already what `normalize_filename` does on every ingest. The QR/`rsart.jpg` overlay (`ImageMgt`, sig=left|right) is NOT ported: its own caller disabled it (`if (false)`) and every work already carries `vad:qrcode`.|
| 8 | RDF Graph Editor | /html/rdf-graph-editor.html | Vocabulary hierarchy editor (client-side JS) | This is a graphing tool that accepts an ontology or thesaurus file and displays it for editing in different formats.  No ai-agent corollary.  Tool remains in UX. |
| 9 | Update workOnSite | /updateWorkOnSite | Sync workOnSite data with websites — effect pattern to confirm (network read + QA write?) | Scrape configured websites for available artworks, then update work-on-site TTL data in one ttl file per site. |

## 2. Publication (writes toward SOT)

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 10 | Distribute Data | /distributeData | Legacy push-to-prod script | **Replaced by promotion unit** (card stays, handler = promote) |
| 11 | Distribute Metadata | /distributeMetadata | Legacy push-to-prod script | **Replaced by promotion unit**: model and vocabulary changes leave through Preview Staged like any staged file. Card removed 2026-11-19 (it linked to a route that never existed) |

## 3. Concept / document pipeline (workflow steps)

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 12 | Derive Concepts from Documents | /conceptImport | Derivation over conceptQueue markdowns | Possibly multiple documents.  From Entity doc instances already in SOT, derive new concepts via concept agent, curate|
| 13 | Concept Promote | /conceptPromote | Consolidate curated derived concepts to single file | Push to SOT vocab and refresh. **Superseded by DTS** (one vocabulary file per run, `dts/session.py`, distributed through the review stop). Card removed 2026-11-19 |
| 14 | Tag Markdowns | /tagMarkdowns | Tag documents, then curate | Call concept agent to identify known concepts in document, then curate
| 15 | Annotate Document Instances | /promoteMarkdownTags | Promote tag TTL to instances | These tags decorate Entity instances by algorithm found in groovy code.  Results in Entity instances are pushed to SOT data, refresh. **Note for CC:** this is the second item requiring extraction of Groovy logic (everything else is rebuild/replace/reuse). Scope it explicitly: locate the decoration algorithm, document it, port with tests. single ported module, shared by #6 and #15.
| 16 | Summarize Documents | /summarizeNewDocs | Update document instances with summaries | Using markdowns as source, update Entity instances with summaries.  Then pushed to SOT data, refresh|
| — | Workflow notes card | (informational) | Setup / Derivation / Maintenance / Tagging / Summarization prose = Phase 8 workflow spec; manual archival steps likely retired (QA git preserves history) | Yes, manual archival steps retired!!|

## 4. Query & browse

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 17 | SPARQL | /sparql | Console against the store | Update disabled, read-only |
| 18 | Query TTL | /queryTtl?pathname= | Convenience feed for outboard SPARQL browser; absolute-path parameter | **Removed** |

## 5. Reports & documents

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 19 | Print Registry | /registry | → /temp/html/registry.html | Prints an HTML listing of all works w/in a given category, e.g., watercolors.  No workflow. **Wired 2026-11-19** as `GET /report/registry` (`report.registry`): per artist profile, the artist read from the data instead of hard-wired. |
| 20 | Certificate of Authenticity | /certificate?guid= | → /temp/html/ca.html | Prints a single HTML artwork certificat of authenticity, essentially data from the catalog entry. **Wired 2026-11-19** as `GET /certificate` (`report.certificate`): concepts by name, dimensions by label, the art form as the type. |
| 21 | Author Page | /author_page?selectAccount= | Account dropdown (5 hardcoded accounts → config) | Deferred to a future release!! |
| 22 | Stats Report | /statsReport?tgt= | Was ×4 targets | Single target from config |
| 23 | Metric Charts | /statsChart?tgt= | One active button, one commented card | Single target from config |

## 6. Instance control

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 24 | Status | /status?target= | Was per-instance ×3–4 | Single server |
| 25 | Reload (Refresh) | /reload?target= | Was per-instance | **Retained, repositioned**: workflow-fired step after SOT update operations (button survives; primary invocation is in-workflow) |
| 26 | Stop | /stop?target= | Was per-instance | **Removed from dashboard** — remains at cmd line, coordinated with git pulls |

## 7. File utilities (sandbox scratch, /stage/tmp)

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 27 | Load TTL File | /loadTtlBlob (POST multipart) | This is simply a ttl validation, no upload! The dashboard will take responsibility for TTL validation and correction upon file presentation |DISCONTINUED as a UX card — capability **absorbed**: parse validation runs implicitly wherever files enter the dashboard (gate behavior), not deleted. **Restored 2026-11-19 as "Syntax Check RDF/JSON"** for the public release, one check for #27 and #28: `POST /check`, tool `check.syntax`, the parser chosen by extension (Turtle, RDF/XML, N-Triples, N3, TriG, N-Quads, JSON-LD, JSON); the first error and its line; stores nothing. |
| 28 | Load JSON File | /loadJsonBlob (POST multipart) | Like TTL file load but for JSON | DISCONTINUED as a UX card — same absorption as #27 (implicit validation on file presentation). **Restored 2026-11-19**, merged into #27's "Syntax Check RDF/JSON" (`.json` checks plain JSON, `.jsonld` JSON-LD). |
| 29 | Markdown to HTML | /md2htmlBlob (POST multipart) | Convert .md | Still useful in the UX.  No workflow implications. **Wired 2026-11-19**: `POST /md2html` opens the rendered page in a new tab; nothing saved (`doc.render_markdown`). |
| 30 | Difference | /diffBlobs (POST, modelFile1/2) | Two-model diff → maps to isomorphic preview machinery | This is better handled under AI agent control.  DISCONTINUED as a UX card — the isomorphic diff (preview.py) **must be registered as an agent tool** so the agent has something to control. Capability retained. |
| 31 | Validate File (SHACL) | /validateFile (fileupload + shaclupload, directory=/stage/tmp) | → maps to gates.py | Let's let the agent manage SHACL development and validation.  DISCONTINUED as a UX card — SHACL validation (gates.py) **must be registered as an agent tool** (and continues to run automatically in promotion gates). Capability retained. |

## 8. Image processing (sandbox scratch)

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 32 | Scale Image | /fileScale (fileupload, scale, overwrite) | Pillow | Still needed in UX.  Often upload images to google Keep which has a image size limit.  No workflow, resized in same folder. **Wired 2026-11-19** as `POST /image/scale`: the result DOWNLOADS rather than landing beside the original, because the dashboard writes outside the sandbox only by promotion (law 1). |
| 33 | Convert Image | /fileConvert (fileupload, format) | Formats: JPG/MPEG/PDF/PICT/PNG/RGB/RGBA/SGI/SVG/TIFF | Occasionally useful to change PNG to JPG, etc.  Type change in same folder w/rename extension.  No workflow. **Wired 2026-11-19** as `POST /image/convert`, downloading; the format list is what Pillow can write (MPEG, PICT, SVG, RGB, RGBA dropped). |

## 9. External-location synchronization

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 34 | Check Synchronization | /file/synch?<location> | gcp://images, file://~/images, c:/temp, G:/My Drive | **Removed** — discrepancy reporting need covered later by the binary↔TTL orphan report (deferred; not critical path; Phase 4 orphan report is the seed) |
| 35 | Compare Folders | /file/compare?<loc1>&<loc2> | GCP vs Home / Temp / Drive | **Removed** (same note) |

## 10. Utilities

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 36 | Generate GUID | /guid | | All the need for this is handled by the dashboard.  It will be too confusing for end users.  Let's remove it.  DISCONTINUED!! |

## 11. Commented out in current UX (decide: dead or deferred)

| # | Function | Endpoint | Notes | Disposition |
|---|----------|----------|-------|-------------|
| 37 | Related Concepts | /related | Concept-relation assertion picker | superseded by annotate work|
| 38 | Concepts | /vocab | Concept create/manage (RDF Graph Editor may have superseded) | DISCONTINUED!!|
| 39 | Metric Charts (grid card) | /statsChart | Duplicate of #23, commented in Metrics grid | This was to regen the metric charts.  No longer needed.  DISCONTINUED!! |


## 12. Missed One

| 40 | Keep Notes Import | /loadKeepData | Import google keep notes as concepts | deferred for consideration in a later release|

---

Cross-cutting notes (apply during port, not functions themselves):
- Config needed for 4.5: the **site list** for updateWorkOnSite
  (visualartsdna.org, art.visualartsdna.org) and the **single instance URL**; HTML
  templated from config. (The five-account dropdown is vestigial for 4.5 —
  its only consumers, Author Page #21 and Keep Notes #40, are deferred;
  account config arrives with them in a later release.)
- Multi-target instance grid collapses to a single instance card.
- All SOT-writing functions terminate in promotion units; all functions
  dispatch through the tool registry (UX handlers = thin bindings).
- Sanctioned network effect class now enumerates three members:
  post-promotion refresh (#25), read-only site scrape (#9), OriginStamp
  submission POST (#5). Amend CLAUDE.md law accordingly.
- Sync-before-workflow-start is load-bearing for the pipeline: derivation
  (#12) sources Entity documents already in SOT via the QA mirror — a
  stale mirror derives from stale documents. (Existing rule covers it;
  noted so nobody relaxes it.)
- The proof folder joins the stage tree and the test fixture tree.
