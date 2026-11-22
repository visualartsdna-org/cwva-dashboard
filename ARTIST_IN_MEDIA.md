# ARTIST_IN_MEDIA.md — the `vad:ArtistProfile` rename, and why it is postponed

**Status: POSTPONED, 2026-10-28. Nothing is renamed. The dashboard code change was made and then reverted.** This document exists because the rename was analysed in detail, found to be right, costed, attempted, and stopped for a reason that has nothing to do with whether it is right. Everything learned is here so the next attempt starts from the findings rather than from the beginning.

The decision is Rick's and the reason is in §1. **Two sessions wrote this**, each from the repository it could measure: the dashboard analysis and the mutation testing (§4, §6) from `~/cwva-py/dashboard`, and §5 from the cwva-py side, checked against its code and content tree on 2026-10-28 (cwva-py at `712bacb`). Where one side verified the other's claim, it says so.

**One side is unmeasured.** The Groovy breakages are the *reason* for the postponement (§1) and are not inventoried anywhere here — neither session could reach that code with confidence. Before the next attempt, that gap has to be closed the way §5 closed cwva-py's, or the precondition in §8 will be met without anyone knowing what it released.

## 1. Why it is postponed

**The old Groovy server is still load-bearing, and the rename breaks it in several places.** Until the new dashboard is complete, that server is how real work gets published, so a change that silently empties the gallery home page is not a change that can be absorbed now. The rename also turned out to require a production server upgrade, which was not the expectation when it was brought forward — it was understood to be a mechanical data migration that merely touched many instances.

**Revisit when the dashboard has replaced the Groovy server.** At that point the Groovy breakages stop mattering. What remains is the ontology, the data, the dashboard **and cwva-py**, which is the cheaper version of this change but not a free one. cwva-py's breakages (§5) have nothing to do with Groovy and don't go away when Groovy retires. They are part of the change whenever it is made. The Groovy breakages themselves are not listed in this document.

**Nothing about the model argument has changed.** §2 and §3 stand. This is a scheduling decision.

## 2. What the rename is

| from | to |
|---|---|
| `vad:ArtistProfile` (class) | `vad:ArtistInMedia` |
| `vad:hasArtistProfile` (property) | `vad:artistInMedia` |

`vad:measurementSystem`'s and `ops:template`'s `rdfs:domain` follow, and `vad:hasArtistProfile`'s `rdfs:range` follows. Every other property on the class — notably the operations properties — is retained.

### Why those names, specifically

**`ArtistInMedia` is the only correct half of its pair.** The model uses *Medium* (singular) for physical additives — `GelMedium`, `PouringMedium`, `RetarderMedium`, `GranulationMedium`, all under `AcrylicAdditive`/`TextureModifier` — and *Media* for artistic media, as `MixedMediaForm` ("Combines different artistic media and materials") does. That is the APO medium/media disambiguation this model version exists to carry, so `ArtistInMedium` would read as "artist in gel medium".

**The property drops the `has` prefix.** The house convention is otherwise `has<Range>`: of 45 `vad:` object properties, 33 are named `has*` and **21 are exactly `has<Range>`**, including `hasArtistProfile → ArtistProfile`. The bare form was chosen because it reads better and has a direct precedent — **`vad:artist`** is already an object property (domain `vad:Art`, range `vad:VisualArtist`, 40 triples in use), one of only 12 non-`has*` object properties, naming exactly this kind of relationship. The two then read as a matched pair on a work:

```turtle
work:1234
    vad:artist        work:{person} ;      # who
    vad:artistInMedia work:{practice} .    # who, working how
```

The cost accepted is one more exception to a 21-strong convention, and the loss of a property name mechanically derivable from its range.

**Keep the broad `rdfs:domain rdfs:Resource`.** Do not narrow it to `vad:Art` or `vad:VisualArts` in imitation of `vad:artist`. `rdfs:domain` entails, and this property's subjects are not all works: of the 225 carrying it, **two are not** — `the:DigitalSculptureProcesses`, a `skos:ConceptScheme` deliberately attributed to the Blender practice, and the record formerly typed `vad:PaintApplicationImage`. A narrow domain would entail that a concept scheme is a work of art.

**Give the class and the property visibly different `rdfs:label`s.** `ArtistInMedia` and `artistInMedia` differ only in capitalisation. RDF and the routes are case-sensitive so this is correct, but identical labels would make them indistinguishable in tooltips, on the Explore graph and in `query_labels()` output. (Raised by the cwva-py review.)

## 3. Why the rename is right

`vad:ArtistProfile rdfs:subClassOf vad:ArtsPersonRole` currently says that a *document about a role* **is** a role. An `ArtistInMedia` — the artist as practitioner in a given medium — genuinely is a person-role, so the subsumption becomes true rather than conventional.

This is the same correction made on 2026-10-28 to `vad:Provenance`, which had been a subclass of `vad:ContextualAnalysis` and therefore of `vad:VisualAnalysis`, entailing that a record of who owns a painting is a visual analysis of it. `vad:ArtEvent` fixed that one. This section is the other half of the same is-a/is-about cleanup, and it is the only part of it left undone.

## 4. Dashboard blast radius, measured

**Data (QA store):** 225 `vad:hasArtistProfile` triples, 14 triples naming the class, 5 `vad:measurementSystem`.

**Ontology:** `vad:measurementSystem` and `ops:template` both declare `rdfs:domain vad:ArtistProfile`, and `vad:hasArtistProfile` declares it as `rdfs:range` — so `operations.ttl` moves with `cwva.ttl`.

**Code and config, by spelling:** `ArtistProfile` 52 occurrences across 20 files; `hasArtistProfile` 27 across 11; `artist_profile` 101 across 25. Plus 36 occurrences across the documents.

**What the attempt actually changed: 49 occurrences across 20 files, IRIs only** — six modules plus the shape file in `src/`/`config/`, the rest test fixtures.

### What must NOT be renamed with it

The RDF terms and the Python/tool names are independent, and keeping them separate is what makes this change affordable.

- **The tool argument `has_artist_profile`.** It is in the tool schema, and **four recorded scenarios pass it** — `entry_promote.rson`, `entry_promote_rollback.rson`, `binary_replace_rollback.rson`, `drift_adoption.rson`. Renaming an argument invalidates every recording that used it, and the recorder exists to measure agent competency by replay (Phase 5). That cost did not exist before the recorder was built and grows with every session recorded.
- **The six `record.*artist*` tool names**, for the same reason.
- **`config/shapes/artist_profile.ttl` as a filename**, and every `artist_profile` Python identifier.

The consequence is that the form field and the property it writes have different names. `WORK_FIELD_PROPERTIES` in `record_tools.py` is the one table that maps between them, which is exactly what it is for.

## 5. cwva-py blast radius

Written from the cwva-py side and checked against its code and content tree on 2026-10-28 (cwva-py at `712bacb`). Line numbers refer to that state of the code.

**These breakages have nothing to do with the Groovy server.** cwva-py is the Python server, not the Groovy one. Retiring Groovy removes Groovy's breakages, not these. Every item below belongs in the change whenever it is made (§8).

**Nothing breaks loudly.** Every reference is a hardcoded IRI inside a SPARQL or SHACL string, so a mismatch returns no rows instead of raising an error.

### Code (`main/`)

| location | what it does | if missed |
|---|---|---|
| `services/browse_works.py:46` | `?uri vad:hasArtistProfile ?_profile` is a REQUIRED pattern in both the count and page queries | **the gallery shows 0 works**, with no pages and nothing logged. This is the main risk |
| `res/Policy.upd:17` | `vad:hasArtistProfile/vad:artist/rdfs:label` builds `schema:copyrightNotice` | no copyright notices are generated, so the line silently disappears from every work page |
| `services/model_viewer.py:50` | same path, used to find the artist's homepage | the "Visit …" link silently disappears from the 3D viewer |
| `res/works.shacl:101` | `sh:path vad:hasArtistProfile ; sh:minCount 1` | every `CreativeWork` fails validation at load. Validation is log-only, so this floods the log but breaks nothing |

Those four are the only references in the code. Nothing else refers to either term: not `html/`, `dist/` or `static/`, and not the other `res/` files (`servletPolicy.rson`, `*.sparql`, the other shapes, `res/checks/`).

`services/rdf2html.py` needs no change **provided** the new property is declared `owl:ObjectProperty` in `cwva.ttl`. Its discrete-anchor rule finds object properties with a batched lookup (`query_object_properties()`), not by name. If the data moves before the model declares the property, work pages show the CURIE instead of the profile's label.

**cwva-py has no test suite, so none of the four sites is guarded.** Confirmed from the dashboard side 2026-10-28, because the claim invites doubt: `~/cwva-py/main/test` exists, but it holds only `err.log` and `out.log`, and there is no `import pytest`, `import unittest` or `def test_` anywhere in `test/`, `services/` or `rdf/`. It is a log directory with a misleading name. This is the cwva-py counterpart of §6. When the change is made, add a load-time check that calls `log_err` when no `vad:CreativeWork` carries the artist property. That is the condition that empties the gallery. Verify the check by mutation, as §6 does.

### Ontology (`metacontent/model/`)

- `cwva.ttl:2932`: the class. `:3128`: the property, whose `rdfs:range` is at `:3131`. `:3401`: `vad:measurementSystem`'s `rdfs:domain`.
- `operations.ttl:65`: `ops:template`'s `rdfs:domain`. **If this is missed, RDFS inference adds `vad:ArtistProfile` back** to every subject that uses `ops:template`. That brings an undeclared, unlabelled class back into the `rdfs` store, and it shows up on detail pages. cwva-py loads every file in `model/`, so `operations.ttl` is in the inference closure.

### Vocabulary (`metacontent/vocab/`)

- `digitalProcess.ttl:116`: one triple, on `the:DigitalSculptureProcesses`. This is the `skos:ConceptScheme` that §2 says is not a work.

### Data (`content/ttl/data/`)

Measured by parsing each file with rdflib, not by grep:

- **222 `vad:hasArtistProfile` triples on 222 subjects**, in 178 files. 175 of those are single-work files. The other three hold several works each: `art.ttl` (33), `archivo.ttl` (9), `digitalRspates.ttl` (5).
- **4 profile instances typed `vad:ArtistProfile`**: `6d5746c7…`, `b3d3c314…`, `ebab5e0c…`, `f91cad0b…`.
- **4 more references to the property, one in each profile's form template**: `ops:property vad:hasArtistProfile` (e.g. `6d5746c7…ttl:45`). The property appears there as an IRI in object position, not as a triple that uses it, so a triple count misses it and only a text search finds it. **It must be renamed with the rest**, or the generated profile form keeps writing the old property. This is why a text search finds 226 occurrences in 182 files: 222 triples plus 4 template references.
- `content/ttl/archive/cwva-20210716.ttl` uses the old `cwva:` prefix and is not under `cfg.data`, so it is never loaded. Leave it alone.

Migrate with a bulk replace over all 226 occurrences, not file by file. A multi-work file like `art.ttl` is easy to convert only partly.

**The 223-vs-225 difference is resolved**, checked from the dashboard side 2026-10-28. cwva-py has **223** (222 in data, 1 in vocab) and the dashboard QA store has **225**. The two extra are **`Top VR` and `junk`**, both of which carry the property and both of which Rick identified on 2026-10-27 as QA-only test records that production does not have. 225 − 2 = 223, and the single vocab triple is `the:DigitalSculptureProcesses`, present in both. The stores agree; nothing is missing from either.

### Outside `main/`, `metacontent/` and `content/`

- `ops/workflow.ttl` lines 196, 248 and 379 (two `rdfs:range`/`rdfs:domain` declarations, plus a typed instance). cwva-py does not load this file, but it should move with the ontology.
- `stage/dev/` holds staged copies of `cwva.ttl`, `operations.ttl` and the four profile files, all with the old names. Either update them or confirm they are superseded before anything is distributed from there.

### Production deployment

With `referenceModel` null, the production config, `model/` and `vocab/` are **deleted and re-synced from the bucket on every start**. They are also re-synced on every `/cmd?cmd=refresh`, because the refresh builds a new `DBMgr` and its constructor runs the same sync (`rdf/db_mgr.py`, around line 267). Local edits there are lost. The ontology, vocab and data changes have to go to `gs://$GCP_BUCKET/ttl/…` (and the ontology to `cwvaMetacontent`).

Since the bridge was rejected (§7), no deployment order avoids an empty gallery. Code without data, and data without code, both match nothing. The cheapest safe order is to upload the bucket content first, deploy the cwva-py code, then do **one restart**. Startup re-syncs the bucket and loads the new code together. **Between the upload and the restart, don't run `/cmd?cmd=refresh`.** It would pull the renamed data into the running old code and empty the gallery. A refresh reloads data, never code, so it can't take the place of the restart.

### Inbound links

`/model/ArtistProfile` appears under about 30 IP-day entries per metrics snapshot (165 across 14 snapshots), and `/model/hasArtistProfile` under 6 in total. After a hard rename both return 404. The `skos:historyNote` in §7 doesn't help, because it sits on the new term.

To keep the old URLs working without the drawbacks §7 rejects, keep each old term as a **bare deprecated declaration**: an `rdfs:label`, `owl:deprecated true`, and `rdfs:seeAlso` pointing to the new term, with **no** `rdfs:subClassOf` or `rdfs:subPropertyOf`. Nothing is inferred from it, so work pages get no duplicate rows. The old URL still opens a page that says where the term went.

### Documentation in cwva-py

`main/CLAUDE.md` lines 548, 615 and 617; `main/DBTESTPLAN.md:165`; `metacontent/README.md:38`; `VISION.md:112`. `main/V5.1PLAN.md:254` is a historical plan and can stay as it is.

There is also unrelated doc drift: cwva-py's CLAUDE.md says `res/Policy.upd` is gitignored, but the file is tracked. That makes the `Policy.upd` change an ordinary commit.

## 6. Four sites that fail SILENTLY — the reusable finding

The dangerous part of this rename is not the IRIs inside a triple; a wrong one of those breaks loudly. It is the places that compare a term as a **string** and go quiet when it stops matching. Each was found, changed, and then **verified by mutation** — the old value reintroduced and the suite re-run to see whether anything objected.

| site | what it does | breaking it |
|---|---|---|
| `config/shapes/artist_profile.ttl` `sh:targetClass` | which class the artist-profile shape validates | **caught.** A shape targeting a class with no instances validates everything, and `tests/promotion/test_shacl_armed.py` notices |
| `tools/edit_tools.py` `_PROFILE` | a hardcoded IRI, string-compared | **caught** |
| `profiles.py` cheap skip, `"ArtistProfile" not in head` | avoids parsing every file in the records dir | **caught**, and it would have been total: stale, it matches no profile file, `list_profiles` returns empty, and every profile card and generated form disappears |
| `main.py` `_bootstrap_in`, `local == "ArtistProfile"` | whether a promotion rebuilds the registry | **NOT caught** |

The last one is the worst failure mode of the four and had no test: the promotion succeeds, the card appears because it is read from disk, and only the **tool** behind it is stale — a profile form serving the shape it had before. The negative test existed (`test_an_ORDINARY_record_does_not_rebuild_the_registry`, so a plain work does not pay for a re-parse of the ontology) and its positive counterpart did not.

**`tests/ux/test_profile_cards.py::test_a_PROFILE_record_DOES_rebuild_the_registry` was kept when the rename was reverted**, written against the old term. The gap it closes was never contingent on the rename, and it is mutation-verified in place.

## 7. Three ways to do it, and what each is worth

### Hard rename — chosen, then postponed

Everything moves at once: model, vocabulary, data, cwva-py code, dashboard code. Cleanest model, least code, and a window during which the gallery is empty if the deployments are not simultaneous. §5 "Production deployment" gives the order that shrinks that window to one cwva-py restart. Postponed per §1 rather than rejected.

### Deprecation with `owl:equivalentClass` / `owl:equivalentProperty` — rejected

Originally recommended here and **the recommendation was wrong.** Rick's reason: without a reasoner the equivalence helps nobody, since a consumer querying `vad:ArtistProfile` against a plain SPARQL endpoint gets nothing back whether or not the equivalence triple exists. It breaks the same people while looking considerate.

What replaces it is documentation, which is the honest form of the same courtesy — a `skos:historyNote` on the class recording the former name. SKOS has the exact term, and the model already carries SKOS notes on classes (`skos:scopeNote` on `vad:ContextualAnalysis`, `skos:altLabel` on `vad:ArtForm`), so it is also more findable than prose inside an `rdfs:comment`:

```turtle
vad:ArtistInMedia
  skos:historyNote "Formerly vad:ArtistProfile, renamed <date>. The property vad:hasArtistProfile became vad:artistInMedia." ;
.
```

The note sits on the new term, so it does nothing for anyone who follows an old link: `/model/ArtistProfile` still returns 404. §5 "Inbound links" covers that with a bare deprecated declaration of the old terms. That declaration has no subsumption, so it entails nothing and avoids both objections in this section.

### An RDFS bridge — elegant, and rejected for two concrete reasons

Proposed by the cwva-py review:

```turtle
vad:hasArtistProfile rdfs:subPropertyOf vad:artistInMedia .
vad:ArtistProfile    rdfs:subClassOf    vad:ArtistInMedia .
```

**It works, and for the reason that makes the deprecation idea salvageable in principle: `rdfs:subPropertyOf` IS honoured by RDFS semantics, where `owl:equivalentProperty` is not.** owlrl runs RDFS only, so old triples entail new ones and new-name queries find unmigrated data. That is the right mechanism; the earlier deprecation proposal simply named the wrong one.

Two reasons not to use it:

1. **Rick's, and it is decisive:** while the bridge is in place, an unmigrated work displays **both** rows on its detail page — `hasArtistProfile x` and `artistInMedia x`. And the bridge buys a staged rollout that is not needed, because the data and metadata changes were already staged in full. Paying an ugly intermediate state for a window that does not exist.
2. **Mine, and it is the asymmetry worth remembering:** the bridge covers cwva-py and **not the dashboard.** cwva-py runs an inference model, so entailment makes old data readable under new names. The dashboard reads files directly with no reasoner and sees exactly the triples on disk. So a bridge would tempt a deploy-code-now-migrate-later order that leaves the dashboard blind — no profile cards, no generated forms. **A dashboard refresh must follow the data migration whether or not a bridge exists.**

## 8. When it is revisited

Precondition: the dashboard has replaced the Groovy server, so the Groovy breakages (§1) no longer apply. **§5's cwva-py breakages still apply.** They are steps 6–9 below, not something the precondition removes.

Then, in one change:

1. `cwva.ttl` — rename the class and the property; move `vad:measurementSystem`'s domain and `vad:hasArtistProfile`'s range; keep `rdfs:domain rdfs:Resource` on the property; add the `skos:historyNote`; give the class and property distinct `rdfs:label`s.
2. `operations.ttl` — move `ops:template`'s `rdfs:domain`. Missing this re-entails the old class on every subject.
3. Vocabulary — `metacontent/vocab/digitalProcess.ttl`.
4. Data — the work records and the profile instances, in both the dashboard's store and cwva-py's content tree. In cwva-py that is 222 triples plus the 4 `ops:property` template references inside the profile files (§5). The two stores are reconciled (§5): the dashboard's extra two are `Top VR` and `junk`, QA-only test records, so no third source is missing.
5. Dashboard code — the 49 IRI occurrences across 20 files. Leave `has_artist_profile`, the tool names and the `artist_profile` identifiers alone (§4).
6. cwva-py code — `services/browse_works.py`, `res/Policy.upd`, `services/model_viewer.py`, `res/works.shacl` (§5). Add the load-time `log_err` guard against an empty gallery, mutation-verified.
7. Old-term declarations — the bare deprecated `vad:ArtistProfile` and `vad:hasArtistProfile` (§5 "Inbound links"), if keeping old URLs working is wanted.
8. Peripheral TTL — `ops/workflow.ttl`; update `stage/dev/` or confirm it is superseded.
9. Deploy — upload ontology, vocab and data to `gs://$GCP_BUCKET/ttl/…` and the ontology to `cwvaMetacontent`. Then deploy the cwva-py code and do **one** restart (§5 "Production deployment"). Editing `metacontent/` locally is not enough: it is overwritten on start.
10. Confirm the four silent sites in §6 individually. Three have tests; `main.py`'s has one now. Then check cwva-py's four (§5) by hand: gallery count, a copyright line, the 3D viewer's artist link, and a SHACL log with no `works.shacl` violations.
11. Documentation — dashboard: CLAUDE.md, `CE_DESIGN.md` §14, `PROJECT_PLAN.md`, `ONTOLOGY_PLAN.md` §8, and this file. cwva-py: the files listed in §5 "Documentation in cwva-py".
12. Refresh the dashboard **after** the data migration, never before.

The reverted commit is the **dashboard** code half, ready to re-apply: **`5daa34f`**, reverted by the commit that added this document. `git show 5daa34f` is the diff to redo. cwva-py has no equivalent commit, because its four code changes were never made.
