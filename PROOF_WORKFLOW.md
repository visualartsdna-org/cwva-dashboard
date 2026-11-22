# PROOF_WORKFLOW.md — creating a `vad:ProofEvent` without transcribing anything

**Status: specification, 2026-11-01. Not built.** Function #5 (proof) has been deferred since the port began; this is what it should be when it is written. `ONTOLOGY_PLAN.md` §14 holds the model changes, `PROOF_VERIFICATION.md` holds how to check a finished proof, and this document holds how one gets made.

## 1. Why this exists

Twenty-four proof records were made by reading values off a web page and typing them into RDF. Every defect found in them came from that step and none from the data:

- **all 24 timestamps were twelve hours early** — the certificate renders a 12-hour clock and the PM was lost
- **three carried an impossible or wrong UTC offset**, one of them `-21:00`, which is outside XSD's legal range and which `rdflib` accepts without complaint
- **one record borrowed its sibling's transaction and root hash** for a proof that was never created
- **three `vad:sha256` values matched no file**, while the platform's own `vad:dataHash` matched all 24

Rick, 2026-10-31: *"This situation points out the frailty of human data interpretation."* The remedy is not more care. It is to stop a human being in the path between the platform's answer and the record.

## 2. The pipeline

1. **At entry**, a work whose artist profile asks for proofs gets an **incipient** `vad:ProofEvent` carrying the file's SHA-256 and nothing else.
2. **A standing query** lists incipient proofs, which is the queue of assets to submit to OriginStamp and, a day later, collect.
3. **An input adapter** turns the platform's answer into the missing properties, matching it to its incipient record by hash.
4. **Three gates** decide whether that answer is accepted, and the completed proof then goes through the ordinary review and distribution.

Steps 1, 2 and 4 are the same whichever adapter is used in step 3, which is the point of the separation: **the validator is the durable part and the extractor is disposable.**

## 3. Step 1 — incipient at entry

The record is created when the work is, not when the anchor exists:

```turtle
work:{guid} a vad:ProofEvent ;
    rdfs:label    "Proof" ;
    vad:asset     <…/images/TensionT5Clash.jpg> ;
    vad:assetOf   work:{the work} ;
    vad:blockchain "Bitcoin" ;
    vad:service   <https://originstamp.com/solutions/timestamp/en> ;
    vad:dataHash  "0xfb0b5307…" .
```

`vad:timestamp`, `schema:startDate`, `vad:rootHash` and `vad:transaction` are **absent, not blank** — nothing asserts an anchor that does not exist, and completing the record later is purely additive. Two such records exist already, for `UnmooredSwing.jpg` and `PassionT3.jpg`.

**`vad:dataHash` is computed by the dashboard from the file's bytes**, never typed. That is what makes it usable as the join key in step 3: a certificate that matches no incipient record fails loudly instead of being attached to the wrong one — which is exactly the defect `UnmooredSwing.jpg` carries today.

**Which works get a proof is artist-profile configuration**, the same shape as the storage-solution map in `PROVENANCE_PLAN.md`: a property of the practice rather than a flag on each work.

## 4. Step 2 — the pending queue is a standing query

"An incipient `vad:ProofEvent`" is "a `vad:ProofEvent` with no `vad:transaction`". That is a SPARQL file in `config/sparql/` and a row in `config/standing_queries.rson`, and it then appears in the workflow panel beside the other obligations with no new code. The same mechanism as `concepts_extracted_false`.

The queue has two states worth distinguishing, because they need different actions: **never submitted** (no proof requested yet) and **submitted, awaiting the anchor** (OriginStamp batches, and `FUNCTION_INVENTORY` #5 records a 24-hour wait). A submission timestamp would separate them — but note §14's finding that `vad:created` meant two different things across the old records, so if this is wanted it needs its own term and a clear definition, not a revival of that one.

## 5. Step 3 — two input adapters, scraper first

### The scraper is the baseline, and the reason is distribution

OriginStamp has **no self-serve API registration**. Keys are issued by hand after emailing `mail@originstamp.com` with a project description, and a CE user cataloguing their own paintings may simply be declined. **A feature that only works for people who can talk a vendor into an account is not a CE feature.**

It is also the less coupled path. The whole point of storing a Merkle path (§14) is independence from OriginStamp's survival; a pipeline that needs their API even to *populate* a record is more dependent on them than one that reads a document the user already holds.

### Extracting the certificate needs no dependency

Demonstrated end to end against a real certificate on 2026-11-01, in roughly forty lines of standard library. The route matters because three obvious approaches fail first:

- the JSON is **not** in the file as text — searching the raw bytes for `leftSha256` finds nothing
- nor is it in any decompressed stream as ASCII
- the page is **not** an image either, which is the next wrong guess

The text is emitted as **two-byte glyph IDs in hex strings** — `<0035003700340034002B>` is `PROOF` — against **subset fonts carrying ToUnicode CMaps**, and the CMaps are themselves inside compressed object streams. So: decompress every stream, collect the `beginbfchar`/`beginbfrange` mappings into one table, then decode the `<…>` hex strings of the content stream through it. The proof JSON comes out intact and parses.

### Two extraction routes, and the second is the robust one

**Route A parses the JSON.** Exact, and dependent on OriginStamp keeping that format.

**Route B ignores structure entirely.** Pull every 64-character hex string out of the decoded text — 34 occurrences, 20 distinct, in the verified example — and reconstruct the path by search: from `vad:dataHash`, find the sibling that combines to another hash in the set, and repeat. It reached the root in 11 levels. **It does not care about page layout or JSON formatting**, only that the hashes appear as text somewhere.

Use A when the JSON parses and B as the fallback, and run B as a cross-check on A's structure when both are available. A layout change then degrades the scraper rather than corrupting it.

### The API adapter, when a key exists

The API returns the same content as structured JSON — submission metadata, root hash, transaction details and the complete Merkle branch — so it needs no extraction at all, and it collapses both manual visits: submission becomes a POST and collection becomes a poll. It is strictly better **for whoever can get a key**, which is why it is an accelerator rather than the baseline.

## 6. Step 4 — the three gates

An adapter's output is accepted only if all three pass. They are what make either adapter trustworthy, and they are the reason a brittle parser is acceptable here: **a parser that cannot silently lie is a sound foundation; one that can is not.**

1. **The extracted leaf equals the incipient record's `vad:dataHash`.** Binds the document to the record. Catches a certificate attached to the wrong proof.
2. **The path recomputes to the extracted root.** Binds the path to the root. Catches every transcription or extraction error, because a wrong sibling cannot produce the right parent. The combining rule is `sha256(hexLeft + hexRight)` over the ASCII hex strings — **not** the raw 32-byte digests, which is what Bitcoin's own tree uses, and getting it wrong yields nonsense (`PROOF_VERIFICATION.md` §5).
3. **The root appears in the named transaction on-chain.** Binds the root to Bitcoin. This is the only step needing the network.

On any failure: refuse, leave the record incipient, and report. Never write a partial proof.

A fourth check applies across records rather than within one: **proofs sharing a `vad:transaction` must share a `vad:rootHash` and a `vad:timestamp`**, because one anchoring event produced them. That invariant found two of the transcription errors in the existing set and belongs in SHACL.

## 7. What gets stored, and what does not

**Store the Merkle path in the record.** Eleven sibling hashes is about 700 bytes, and it is what makes a proof verifiable without OriginStamp existing — the gap `ONTOLOGY_PLAN.md` §14 records. Obtaining it through their API does not remove the need to keep it; the API is how you get it, storing it is why you are safe without them.

Its shape is an open modelling decision. An ordered list of sibling-plus-side, as an `rdf:List`, or a blank node per level in the style of `ops:template`, or one packed literal. Blank nodes add to the nested-preservation surface that broke Edit Record twice; a packed literal is ugly in RDF but costs nothing to preserve verbatim.

**The certificate itself is transient.** It is read once, validated, distilled, and has no further job. It should not become a managed binary: `the:pdfDocument` names documents that converge and are served, and twenty-four 2.5 MB certificates in the SOT would be 60 MB of artifact for 17 KB of fact. `.pdf` is already an accepted drop-folder kind, so ingress needs no config change — but the file should be consumed at ingest rather than ingested. If a human-readable fallback is ever wanted, `LOCAL_ONLY_DIRS` is the mechanism: committed to the QA git for history, never converging.

**Timestamps are converted once, by code.** `vad:timestamp` is stored as the service reported it, with its offset, because a fact an external system reported stays in that system's terms. `schema:startDate` is the date part **read in that same offset**, never in UTC — `xsd:date` cannot carry a zone, so a UTC reading silently asserts a convention nothing states, and for most of these records the UTC date is the following day.

## 8. Law 11: two network effects, one of them credentialed

Both the API adapter and gate 3 reach outside, so the proof workflow adds to the sanctioned network-effect class and the entry should cover both.

The split is the one the ffprobe duration probe uses: **the fetch happens trusted-side and the pure result is handed to a registry tool** that writes the record. The Landlock-confined worker cannot resolve a hostname at all, so a network tool registered for the agent would silently return nothing — the failure that produced two empty snapshots from `updateWorkOnSite`.

And an API key makes this the **second credentialed member** after Instance Control, which inherits that member's two extra rules: the target is resolved by configured name rather than by a URL supplied in the request, and **the token never enters the audit log.**

## 9. Development plan

Rick, 2026-11-01: fetch the 24 certificates now, build against them, compare with the hand-made records in staging, then distribute `ProofEvent`s complete with Merkle paths.

**The 24 are a better regression corpus than any fixture** — real certificates, real formatting, 10 distinct batches, including the two whose proofs do not exist yet. And the expected values are already established independently: every `vad:dataHash` was verified against the production file on 2026-10-30, and the batch invariant holds across all 10 batches.

**Where scraper and staged record disagree, the scraper wins** — provided it passes the three gates, which the hand-made records never did. The staged values are hard-won but they are still transcription, and three of their `sha256` values were demonstrably wrong. Treat agreement as confirmation and disagreement as a finding about the record, then check it by hand.

Two things that cannot be compared: `UnmooredSwing.jpg` and `PassionT3.jpg` have no certificate yet. They stay incipient and are the first real exercise of the queue.

## 10. What is built

`src/cwva_dashboard/proof/`, 2026-11-01, with the separation §2 argues for:

- **`merkle.py`** — the combining rule, `fold`/`verify`, the packed literal, and `reconstruct` for the structure-free route. Durable; no notion of where a path came from.
- **`certificate.py`** — the PDF reader, standard library only. Disposable.
- **`validate.py`** — the three gates and the timestamp anchoring.

**Verified against the first two certificates**: each extracts via the JSON route with the search route agreeing, each path verifies to the root in the record, and **each yields a timestamp identical to the hand-corrected staged value** — `2026-08-25T20:21:21-04:00` and `2026-02-04T19:12:03-05:00`. The packed paths are 803 and 736 characters.

**Then against all 24 (2026-11-02).** Rick obtained the full set into `/mnt/c/stage/tmp/proof`; all 24 extract, both routes agree on every one, every path verifies to its record's root, and the 24 regenerated records were distributed to production. 18,133 characters of Merkle path is what makes the collection verifiable with no OriginStamp and no network — `PROOF_VERIFICATION.md` is the procedure. The batch invariant holds across the set: proofs sharing a `vad:transaction` share one `vad:rootHash` and one `vad:timestamp`, which `ops:ProofBatchShape` now enforces.

**What the full set proved about the hand-transcribed records** is the argument for the whole exercise: all 24 timestamps were twelve hours early, three offsets were wrong or illegal (a `-21:00` among them), one record had borrowed its sibling's transaction, and three `vad:sha256` values matched no file while `vad:dataHash` matched all 24. None of that was carelessness — the certificate prints a 12-hour clock, and the combining rule is OriginStamp's ASCII-hex concatenation rather than Bitcoin's raw bytes.

44 tests. The gates are tested unconditionally with synthetic certificates; the extractor's tests are opt-in against real ones (`CWVA_PROOF_CERTS`, defaulting to `/mnt/c/stage/tmp/proof`), because certificates are the artist's own documents and far too large to commit. That split follows the design: an API adapter replaces the extractor and leaves every gate test standing.

Not built: the registry tool that writes the record, the standing query, and the trusted-side chain lookup for gate 3 — which is injected, so the gate is exercised without it and **reported as not run rather than passed** when it is absent.

## 11. Open decisions

- ~~The path's RDF shape.~~ **Settled 2026-11-01: a packed literal**, `L:<hash> R:<hash> …`, leaf-first, where the letter says which operand the SIBLING is. Implemented in `proof/merkle.py`.
- **Whether to record a submission time**, to separate "not yet submitted" from "awaiting the anchor" in the queue (§4). It needs its own term; `vad:created` is not it.
- **Which works require a proof**, as artist-profile configuration (§3).
- **Whether the certificate is kept local-only** or discarded after extraction (§7).
- **`vad:dataHash` vs `vad:sha256`** is settled — keep `dataHash`, drop `sha256` — but the third hash, `vad:rootHash`'s relationship to the two, is documented in `ONTOLOGY_PLAN.md` §14 item 2 and still wants the OriginStamp flow to confirm.
