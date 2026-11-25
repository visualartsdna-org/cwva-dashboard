# Changelog

What each version changes, and anything to do when upgrading. How to upgrade: the end of [Troubleshooting and upgrading](docs/about/troubleshooting.md#upgrading).

## 1.0.1 (2026-11-25)

Nothing to do beyond the usual upgrade.

**Fixed**

- **Annotating the wrong work.** The workflow board's Annotate link named no work, and the Annotate page then opened on the first work by title, so saving could rewrite that work's paints and techniques. The board's links now carry their work, and Annotate with no work named asks you to choose one and refuses until you do.
- **A criticism labelled with another work's title.** Naming the right work when generating an entity from a criticism corrected its tag but not its label. The label now follows the work you name.
- **A recording lost on restart.** A recorded session was held only in memory. Each step is now saved as it happens, and the dashboard resumes an open recording when it starts.

**Documentation**

- The assistant guide is now [START_HERE.md](START_HERE.md), at the top of the repository.
- The design and planning notes left the repository; the reference documents that remain are in `docs/`.

## 1.0.0 (2026-11-22)

The first public release.
