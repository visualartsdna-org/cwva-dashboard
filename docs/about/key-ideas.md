# Key ideas

A handful of ideas explain almost everything the dashboard does. Once they are familiar, the rest of the interface follows from them.

## The sandbox: everything happens there first

The sandbox is the dashboard's private working copy of the published data. Every form, edit and annotation writes into it, and nothing in it is public until you distribute it. You never put files into the sandbox yourself, and you do not need to know where it is: the dashboard keeps it, records its history, and confines everything that works in it so that nothing can reach outside.

## The drop folder: how files come in

Images, documents and other files enter through the **drop folder**, a folder of your own named in the configuration. Put a file there and the entry forms offer it. When a form uses it, the dashboard copies it into the sandbox; it never moves, renames or deletes anything in your folder. Names are tidied on the way in: spaces are removed and the extension lower-cased (`Lepers Hearth.JPG` becomes `LepersHearth.jpg`), because the name becomes part of the web address the record cites. The review tells you when a name was changed.

## Drafts: what is written but not yet distributed

A record you have saved in the sandbox but not distributed is a **draft**. The Drafts card on the hub counts them, and the Drafts page lists each one by name, with what changed since it was last distributed and a way back into the form that made it. Drafts are normal: several related records are often made one at a time and distributed together.

## The review: the one way out

Every change reaches the published data through the same step. You see a **review** of exactly what will change, record by record, and the dashboard's **checks** have already run. Then you choose one of three:

- **Approve & distribute** writes the change to the source of truth.
- **Leave it staged** keeps it as a draft and lets you carry on; you can distribute it later, with others, from **Preview Staged**.
- **Discard** throws this session's changes away and puts the sandbox back as it was.

Distribution is all of the drafts at once: what is approved is everything waiting in the sandbox, which is why the Drafts card matters.

## Checks: what is verified before anything is published

Before a review is shown, the dashboard checks the change. Every file must parse as RDF. A record of a kind that has a declared shape must fit it: a provenance names exactly one work and its owner, a proof carries a consistent set of hashes, an artist profile has a usable form template (a work's required fields are enforced earlier, by its entry form). Every reference must lead somewhere: an image the record names must exist, a paint or paper must be in the thesaurus, a provenance must point at a real work, and no two works may share a storage number. A failed check stops the review and says what is wrong; it is never bypassed. The checks are about whether the data is well formed and consistent, not about whether you meant it; that judgement is yours, at the review.

## Undoing

Because the sandbox keeps a history of everything distributed, a distribution can be undone: the sandbox is put back to before it, and that earlier state is distributed again. Today that is an operator's task, done with a script rather than from a page. **Refresh** goes the other way: it pulls the published data into the sandbox, replacing anything not yet distributed, and is how the dashboard catches up after the data was changed somewhere else. Refresh asks first, because it can throw work away.

## Seeing it before it is public

The **cwva-py view** runs cwva-py itself over your sandbox, drafts included, on your own machine. It is the published site as it will look after you distribute, and it cannot change anything: the operating system prevents it from writing to the sandbox at all.

## Profiles: what you make, and the form for it

An **artist profile** is what an artist makes in one medium (watercolours on paper, say, or Blender compositions), and it carries the **template** for that medium's entry form: which fields the form shows, in what order, and the units of measure. Each profile becomes a card on the hub. A profile made by cwva-py on its own, before the dashboard, has no template yet; its card says so and opens the profile editor, where you choose the fields once.

## Records describe one thing

Each record is a small file about one thing: one artwork, one artist, one document, one provenance. They point at each other: a work names its artist profile, a criticism names the work it is about, a provenance names the work it records. The dashboard's forms, checks and reports all rely on that, which is why an edit preserves what its form does not show and never rewrites a record wholesale.

Next: [A tour of the dashboard](tour.md).
