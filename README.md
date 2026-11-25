# CWVA dashboard

A workspace for preparing a VisualArtsDNA art collection before it is published: the companion to [cwva-py](https://github.com/visualartsdna-org/cwvaServer-py), which shows the collection on the web. Enter works with their images and dimensions, annotate them with the paints and techniques used, record where each original is kept, attach and analyse written criticism with an AI model's help, and publish each change only after reviewing exactly what it does.

**New here? Open [START_HERE.md](START_HERE.md)**: read it yourself, or give it to an AI assistant such as Claude and ask it to help you install the dashboard.

Version 1.0.2 ([what changed](CHANGELOG.md)). Runs on Linux, or Windows 11 through WSL2.

## What it is

- [What the dashboard is](docs/about/what-it-is.md)
- [Key ideas](docs/about/key-ideas.md)
- [A tour of the dashboard](docs/about/tour.md)

## Install

- [Requirements](docs/about/requirements.md)
- [Installing](docs/about/installing.md), with a [sample collection](docs/about/installing.md#trying-the-sample-collection-first) to try it on
- [Bringing in an existing collection](docs/about/existing-collection.md)
- [Configuration](docs/about/configuration.md), [Running](docs/about/running.md), [Backups](docs/about/backups.md), [Troubleshooting and upgrading](docs/about/troubleshooting.md)

The same pages are under **About** in the dashboard itself.

## With an AI assistant

[START_HERE.md](START_HERE.md) is one file to give an assistant such as Claude so it can walk you through installing, running and using the dashboard safely.

## Licence

MIT, as cwva-py is: see [LICENSE](LICENSE).

## Developing it

[CLAUDE.md](CLAUDE.md) holds the rules the code is built on, [docs/CE_DESIGN.md](docs/CE_DESIGN.md) the architecture and why, and [docs/OPERATIONS.md](docs/OPERATIONS.md) every page and script with what it touches. [docs/PROOF_VERIFICATION.md](docs/PROOF_VERIFICATION.md) explains how to check a timestamp proof independently. `pip install -e ".[dev]"` and `pytest -q` run the tests.
