# What the dashboard is

The CWVA dashboard is a workspace for preparing visual-arts data before it is published. It is the companion to **cwva-py**, the server that publishes a VisualArtsDNA collection on the web: cwva-py shows the collection, and the dashboard is where the collection is made and kept in order.

## What it is for

A VisualArtsDNA collection is a set of records, one per artwork and one per supporting thing (an artist, a document, a background, a proof of existence), written in RDF and described with a shared ontology and thesaurus. Keeping such a collection is a lot of small, exacting steps: entering a new work with its images and dimensions, annotating it with the paints and techniques used, recording where the original is kept, attaching a written criticism and deriving concepts from it, proving the image existed on a given date. The dashboard puts each of those steps behind a form, checks the result, and publishes it only when you say so.

## How it fits with cwva-py

There are three parts, and it helps to keep them apart:

- **The source of truth** is where the published data lives. Usually that is a plain **folder**: the one cwva-py serves on your own computer. It can also be a **git repository**, which gives the collection a history and a copy elsewhere, or, for larger installations, a **cloud storage bucket**. cwva-py reads it, and so do the people who browse the collection.
- **cwva-py** serves the source of truth as a website: the gallery, each work's page, the thesaurus, a SPARQL endpoint. It only reads.
- **The dashboard** keeps its own private working copy of the source of truth, called the **sandbox**. Everything you do happens there first. When a change is ready, you **distribute** it, and the dashboard writes it to the source of truth; cwva-py then refreshes and shows it.

So the order of events for a new watercolour is: enter it in the dashboard, check it (in the dashboard, and in cwva-py through the dashboard's own read-only view of the sandbox), distribute it, and refresh the published server.

## What it is not

It is not a website editor and not a general file manager. Files enter through one place (the drop folder), and data leaves through one place (distribution). It does not publish anything you have not reviewed, and it does not change the published data in place: a mistake is undone in the dashboard and the corrected state distributed again.

## Where the AI comes in

Some steps use an AI model: deriving concepts from a written criticism, tagging it, and summarising it. The model proposes and you decide; nothing it writes is distributed without passing the same review as anything else. The model is reached through a configured provider, and it never holds any capability the dashboard has not given it: it cannot read or write outside the sandbox, run commands, or reach the network on its own. An agent that can drive the dashboard's workflows is planned; it will use exactly the operations a person uses.

## One dashboard, one collection

An installation is one dashboard working on one collection, set up by one configuration file. Someone developing the dashboard itself can run a second, practice copy beside the real one (see [Running](running.md#a-second-instance-for-trying-things)), and then every page carries a banner saying which is which; an ordinary installation needs neither.

## Working with an AI assistant

If you would like help from an AI assistant such as Claude to install, run or use the dashboard, give it [the assistant guide](../../START_HERE.md): one file holding these pages, with instructions for the assistant on how to help safely and what to ask you.

Next: [Key ideas](key-ideas.md).
