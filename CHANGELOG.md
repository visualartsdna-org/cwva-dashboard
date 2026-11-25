# Changelog

What each version changes, and anything to do when upgrading. How to upgrade: the end of [Troubleshooting and upgrading](docs/about/troubleshooting.md#upgrading).

## 1.0.2 (2026-11-25)

If the dashboard now refuses to start because of `domain`, the message says what to write. If you already made records under that domain, ask for help before changing it.

**Fixed**

- **Installing.** The step that installed cwva-py with `pip` failed and was never needed; it is gone. cwva-py gets a `.venv` of its own, which the cwva-py view uses. If you have none, see [Installing](docs/about/installing.md#1-get-the-code).
- **The sample collection** is now unpacked from the zip cwva-py ships; the old command copied a folder that is not there. It needs cwva-py 5.1.6 for its works to show in the gallery.
- **An unusable `domain` is refused** when the dashboard starts: no `http://`, a path, capital letters, and the like. Records made under one are very hard to correct.
- **A shared background picked under your own domain** was recorded as one of your own records, which does not exist. The picker now names the record it shows.

**Known limit**

- cwva-py before 5.2.0 shows records under your own domain with most of their page missing. The records themselves are correct.

**Documentation**

- Hand-written works need `vad:CreativeWork` beside their own type to appear in cwva-py's gallery.

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
