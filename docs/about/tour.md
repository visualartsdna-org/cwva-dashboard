# A tour of the dashboard

The hub is the page the dashboard opens on. Across the top are the logo, which always brings you back here, the version number, and five destinations: **Content**, **Monitoring**, **Tools**, **Files** and **About**.

## Content

Where the collection is made. Its first section, **Content Management**, holds the cards you use most. Each card has a small handle in its corner: drag it to arrange the cards the way you work, and the arrangement is kept.

- **One card per artist profile**, such as a watercolour profile or a Blender profile. A profile is what an artist makes in one medium, and its card opens the entry form for a new work in it, with the fields that medium needs. A red card is a profile with no form yet: open it to choose its fields.
- **Edit Record** opens any existing work or entity and lets you change its fields, including replacing its image or document under the same name.
- **Update workOnSite** reads the artist's websites and records which works appear on them.
- **Annotate Work** attaches concepts from the thesaurus to a work: the paints, papers and techniques used.
- **Entity** creates a supporting record, such as a written criticism of a work with its markdown document.
- **Proof** loads a proof of existence for an image, from its OriginStamp certificate.
- **DTS** is concept derivation, tagging and summarising: from a criticism's text, it proposes concepts, places them, and drafts a summary, each step reviewed by you.
- **Drafts** counts what is written and not yet distributed.
- **Workflows** shows each work in progress against the steps of its workflow (entry, annotation, criticism, concepts, proof) with what is done, what is next, and how long it has waited.
- **cwva-py view** starts the published site's own server over your sandbox, so you can see a change before distributing it.
- **New artist**, **Edit artist** and **New artist profile** set up who makes the work and in what medium; the profile cards come from these.

Below them, **Immediate Actions**:

- **Preview Staged** reviews and distributes everything waiting in the sandbox.
- **Refresh** pulls the published data into the sandbox, after asking, because it discards anything not distributed. Use it after changing the collection's files by hand.

## Monitoring

The servers that publish the collection, each on its own card, with **Status**, **Refresh** and **Metrics**. Refresh tells a server to reload the published data, which is the last step after distributing. Each card shows when that server was last refreshed. For a collection on your own computer that is usually one server, your cwva-py.

## Tools

- **SPARQL** queries everything in the sandbox, drafts and provenance included, without changing anything.
- **Print Registry** lists one artist profile's works, with image, QR code, year and description, ready to print.
- **Storage Report** lists the works in a storage arrangement by their storage number (Disposition Identifier), with a thumbnail of each: the list to take to the boxes.
- **Generate Certificate** makes a printable Certificate of Authenticity for a work from its record.

## Files

Utilities for a file of your own. None of them stores anything.

- **Syntax Check RDF/JSON** says whether a Turtle, RDF/XML, N-Triples, N3, TriG, N-Quads, JSON-LD or JSON file is well formed, and if not, where the first error is.
- **Markdown to HTML** shows a markdown file as a web page, in a new tab.
- **Scale Image** and **Convert Image** resize an image or change its format, and give the result back as a download.

## About

These pages.

Next: [Requirements](requirements.md), the start of *Installing and running*.
