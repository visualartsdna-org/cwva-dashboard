# Requirements

## Operating system

**Linux, or Windows 11 through WSL2.** The dashboard confines everything that works in the sandbox using Landlock, a feature of the Linux kernel (5.13 or later; every current distribution has it, and so does WSL2). It will not run its confined parts where Landlock is missing rather than run them unconfined. macOS and native Windows are planned for later releases.

On Windows, WSL2 is installed with `wsl --install` from an administrator terminal, then a restart; after that, the commands on these pages are typed into the Ubuntu terminal it adds.

## Software

- **Python 3.11 or later.**
- **cwva-py**, the VisualArtsDNA server, version 5.1.4 or later, checked out beside the dashboard. It is what shows your collection; the dashboard can run it over your work in progress.
- **git**, which keeps the sandbox's history (and, if you choose, your collection's).
- **ffmpeg** (optional): with it, a video's duration is read from the file; without it, you type it in.

The Python packages the dashboard needs (RDFLib, pySHACL, FastAPI, Pillow and a few others) are installed with it.

## Where your collection lives

The dashboard publishes to a **source of truth**, and you choose which kind:

- **A folder** (the usual choice): the folder cwva-py serves on your computer, laid out as cwva-py's README describes (`content/data`, `content/images`, `metacontent/model` and so on). Nothing else is needed.
- **A git repository**: the same, kept in git, so every change you publish becomes a commit, and a pushed copy can live elsewhere.
- **A Google Cloud Storage bucket** (advanced): for a collection served from the cloud, as visualartsdna.org is. This needs a Google Cloud account and credentials.

A new collection can start empty: the ontology and thesaurus are fetched from the reference VisualArtsDNA server the first time.

## For the AI-assisted steps

Concept derivation, tagging and summarising call an AI model, by default Anthropic's Claude, and need an API key for it (see [Configuration](configuration.md)). Everything else works without one.

## Disk

The sandbox holds a full copy of the collection, images included, so allow about twice the size of the collection's folder.

Next: [Installing](installing.md).
