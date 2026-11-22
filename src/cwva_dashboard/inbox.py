"""The user's drop folder — the one way content enters the system.

**The user never touches the sandbox.** The sandbox is the system's private
working area: a QA git repo whose contents are managed by sync, the record
tools, and promotion. A human placing a file in it by hand produces exactly the
failure found on 2026-08-25 — a binary with no ``.ptr`` sidecar, invisible to
the git-derived manifest, referenced by a record that reaches SOT while the
image itself never converges. So instead the user drops files into a configured
folder *outside* the sandbox, and the dashboard copies them in.

**This is the INGRESS counterpart to promotion, and it is trusted-orchestrator
machinery — never a registry tool.** The confined worker is Landlock-restricted
to the sandbox, so reading the inbox is not merely disallowed but structurally
impossible from it; an ``fs.*`` tool could never serve this. The architecture is
symmetric: promotion is the single gated *exit*, this is the single gated
*entry*, and both live in the trusted layer where the agent cannot hold them.
An agent that needs a file ingested asks the orchestrator, exactly as it must
for promotion.

**Everything here treats the inbox as hostile** (law 3). The folder is outside
every containment boundary the project owns, its contents arrive by means the
dashboard does not control, and a submitted filename is untrusted input about to
be joined to a path. So:

- **Names are validated, never joined blindly.** A selection must be a bare
  filename — no separators, no ``..``, no absolute path, no NUL — and the
  resolved path's parent must be the inbox itself. This is the Layer-1 rule
  applied at the second boundary, because "the form only ever sends names we
  listed" is a property of the *renderer*, and the renderer is not a guard.
- **Symlinks are refused**, matching the sandbox's prohibition: a link in the
  inbox would otherwise read a file the user never placed there.
- **Extensions are an allowlist**, per kind, from config.
- **Bytes land through FileOps**, so the pointer sidecar is minted on arrival
  and the file is immediately visible to promotion.

Nothing here ever writes to the inbox or deletes from it: the user's folder is
theirs. Ingested files stay where they are, so re-running an entry works.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "open_folder", "Inbox", "InboxError", "DEFAULT_EXTENSIONS",
           "normalize_filename", "filename_from_label"]


# Characters a filename may keep. The RFC 3986 *unreserved* set — every one of
# these is safe unescaped in a URI path — because a filename here is not just a
# filename: it is joined to the image or documents base and becomes the IRI a
# record points at. A space in an IRI is not merely awkward, it is invalid, and
# `#`, `?` and `%` change what the IRI MEANS.
_KEEP = re.compile(r"[^A-Za-z0-9._~-]")
_SPACE_THEN_ALNUM = re.compile(r"\s+([A-Za-z0-9])")

# Mojibake and typographic characters that reach filenames via copy-paste, with
# ASCII stand-ins. Mirrors the Groovy's `Text.toGuaranteedAscii`, which existed
# for the same reason.
_TYPOGRAPHIC = str.maketrans({
    "\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"',
    "\u2013": "-", "\u2014": "-", "\u2026": "", "\u00a0": " ",
})


def normalize_filename(name: str) -> str:
    """The name a file gets INSIDE the system: ``Unmoored Swing.jpg`` ->
    ``UnmooredSwing.jpg``.

    Spaces are the reason this exists. They work on Linux and mostly work on
    Windows, but the filename does not stay a filename — it is joined to the
    image or documents base to form the IRI a record points at, and a space in
    an IRI is invalid, not just ugly. Rick has been collapsing names by hand
    before every entry; that convention cannot be asked of other users, so the
    dashboard applies it.

    The rule is the Groovy's own `Text.camelCase` — drop the space, capitalise
    the character after it — plus its `toGuaranteedAscii` folding, so the result
    matches the names already in the store rather than inventing a new style.
    Accents fold (``Café`` -> ``Cafe``) rather than vanish. Anything still
    outside the URI-unreserved set is dropped.

    The EXTENSION is LOWERCASED. It carries no information — `.JPG` and `.jpg`
    name the same format — and a single convention is one fewer way for
    `Sunset.jpg` and `sunset.JPG` to end up as two records pointing at what a
    case-insensitive filesystem considers one file. Existing content is
    untouched: normalization runs only on names entering through the drop
    folder, so the store's 13 `.JPG` references stay exactly as they are and
    nothing re-processes them.

    Only the FINAL extension: `thing.TAR.gz` keeps its `.TAR`, which is part of
    the stem by this function's splitting rule, and the stem's case is
    deliberately preserved (that is what camelCase names are made of).

    A name needing nothing comes back unchanged, which is the common case.
    """
    import unicodedata

    raw = str(name)
    stem, dot, ext = raw.rpartition(".")
    if not dot:
        stem, ext = raw, ""

    stem = stem.translate(_TYPOGRAPHIC)
    # NFKD then drop combining marks: é -> e, not é -> "".
    stem = "".join(
        ch for ch in unicodedata.normalize("NFKD", stem)
        if not unicodedata.combining(ch)
    )
    stem = _SPACE_THEN_ALNUM.sub(lambda m: m.group(1).upper(), stem.strip())
    stem = _KEEP.sub("", stem)
    stem = stem.strip("._-") or "file"
    return f"{stem}.{ext.lower()}" if dot else stem

# Kind -> the extensions a user may drop for it. Deliberately narrow: these are
# the types the wired functions consume, and an unknown type in the folder is
# ignored rather than offered.
DEFAULT_EXTENSIONS: dict[str, tuple[str, ...]] = {
    # `.hdr` is a Radiance HDR environment map, not a photograph — but it is
    # what a Background entity's `schema:image` points at, and a Blender
    # composition is lit by one (Rick, 2026-09-27). It rides with the image kind
    # rather than getting its own because the EDITOR derives predicate -> kind
    # from these, and two kinds claiming `schema:image` would collide there.
    # The cost is that an HDRI appears in a work's image picker too; picking one
    # for a painting is a deliberate act, and branding it would fail and say so.
    "image": (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp", ".heic", ".hdr"),
    # 3D objects for vad:image3d — glTF in both flavours, the JSON .gltf and the
    # self-contained binary .glb. A separate KIND rather than more image
    # extensions: a picker for a 3D object must not offer a photograph, and one
    # for a photograph must not offer a mesh.
    "model3d": (".glb", ".gltf"),
    # Video for schema:video — the formats the Chrome player handles natively.
    "video": (".mp4", ".webm", ".ogg", ".ogv"),
    # Markdown and PDF are separate KINDS, not one "document" kind with two
    # extensions — the entity form has a field for each, and a picker that
    # offered both would let the .md field name a .pdf. Same rule that keeps
    # photographs out of the 3D-object picker.
    "markdown": (".md",),
    "pdf": (".pdf",),
}


class InboxError(Exception):
    """A selection that is not a legitimate file in the inbox."""


@dataclass(frozen=True)
class InboxFile:
    name: str
    size: int
    kind: str

    def to_dict(self) -> dict:
        return {"value": self.name, "label": f"{self.name} ({self.size // 1024} KB)"}


class Inbox:
    """Read-only view of the user's drop folder, plus copy-in to the sandbox."""

    def __init__(self, path, *, extensions: dict[str, tuple[str, ...]] | None = None):
        self.root = Path(os.path.expanduser(str(path))).resolve()
        self.extensions = extensions or DEFAULT_EXTENSIONS

    # -- listing ------------------------------------------------------------
    def exists(self) -> bool:
        return self.root.is_dir()

    def list(self, kind: str = "image") -> list[InboxFile]:
        """Files of ``kind`` currently in the folder, sorted by name.

        Missing folder -> ``[]``, not an error: a fresh CE install has not made
        it yet, and the form must still render (with an empty picker that says
        where to put files).
        """
        allowed = tuple(e.lower() for e in self.extensions.get(kind, ()))
        if not self.root.is_dir() or not allowed:
            return []
        out: list[InboxFile] = []
        for entry in self.root.iterdir():
            # is_file() follows symlinks; check the link itself first so a link
            # to something outside the folder is never offered.
            if entry.is_symlink() or not entry.is_file():
                continue
            if entry.name.startswith("."):
                continue
            if not entry.suffix.lower() in allowed:
                continue
            try:
                out.append(InboxFile(entry.name, entry.stat().st_size, kind))
            except OSError:
                continue
        return sorted(out, key=lambda f: f.name.lower())

    # -- resolution (the untrusted-input boundary) ---------------------------
    def resolve(self, name: str, kind: str = "image") -> Path:
        """The real path of ``name`` in the inbox, or raise.

        Validation order matters: reject the *name* on its own terms first, so a
        traversal attempt never reaches the filesystem, then confirm containment
        of the resolved path as the structural backstop.
        """
        if not name or name in (".", ".."):
            raise InboxError("no file selected")
        if "\x00" in name:
            raise InboxError("invalid filename")
        # A bare filename only: no separators of either flavour, no drive/UNC.
        if os.sep in name or (os.altsep and os.altsep in name) or "/" in name or "\\" in name:
            raise InboxError(f"{name!r} is not a bare filename")
        if Path(name).is_absolute() or ":" in name:
            raise InboxError(f"{name!r} is not a bare filename")

        allowed = tuple(e.lower() for e in self.extensions.get(kind, ()))
        if Path(name).suffix.lower() not in allowed:
            raise InboxError(f"{name!r} is not an accepted {kind} type")

        target = (self.root / name).resolve()
        # Structural containment: the resolved parent must BE the inbox. Also
        # catches a symlink that resolved elsewhere.
        if target.parent != self.root:
            raise InboxError(f"{name!r} is not in the drop folder")
        if not target.is_file() or (self.root / name).is_symlink():
            raise InboxError(f"{name!r} is not a file in the drop folder")
        return target

    # -- ingest --------------------------------------------------------------
    def copy_into(self, name: str, fileops, dest_dir: str, *, kind: str = "image",
                  dest_name: str | None = None) -> dict:
        """Copy one inbox file into the sandbox **through FileOps**.

        Going through FileOps rather than `shutil` is the point: it enforces the
        path chokepoint and quotas, and it mints the ``.ptr`` sidecar, so the
        arriving binary is visible to promotion from the moment it lands. A
        plain filesystem copy is precisely the bug this whole folder exists to
        prevent.

        Idempotent: an unchanged file already in the sandbox is left alone, so
        re-running an entry does not needlessly attic the previous copy.
        """
        src = self.resolve(name, kind)
        # The file lands under its NORMALIZED name; the drop folder keeps its
        # own. The user's folder is theirs — renaming a file they can see, out
        # from under them, is not this component's business, and leaving the
        # original in place means re-running the entry still works.
        rel = f"{dest_dir.rstrip('/')}/{dest_name or name}"
        data = src.read_bytes()

        try:
            if fileops.read_bytes(rel) == data:
                return {"path": rel, "copied": False, "bytes": len(data)}
        except Exception:
            pass  # absent or unreadable -> write it

        res = fileops.write_bytes(rel, data, make_parents=True)
        return {"path": res.path, "copied": True, "bytes": res.bytes_written}


def filename_from_label(label: str, source: str, *, ordinal: int = 1) -> str:
    """The name an IMAGE gets from the WORK it belongs to.

    `IMG_2104.JPG` + "Covered Bridge" -> `CoveredBridge.jpg`.

    **Restoring the Groovy's rule**, `support/ImageMgt.groovy:179`:
    ``def fname = "${util.Text.camelCase(title)}.jpg"``. There it lived inside
    `makeStampedFile`, so naming and branding were a single act; the port split
    them — ingest stays a verbatim copy, which is what makes the unbranded
    original recoverable from `.qa/attic` — and the naming did not survive the
    split (Rick, 2026-10-05: "I didn't like seeing the google photos name
    IMG_2104 when I pulled it up in the browser, I was about to grab a copy to
    post on my site").

    **The cost of not doing it is published.** The filename is the last segment
    of the IRI the record cites AND of the URL on the artist's site, so a camera
    name is what a visitor sees and what a search engine indexes.

    It reuses `normalize_filename` rather than inventing a second rule: that
    function already applies the Groovy's own `Text.camelCase` and ASCII
    folding, so a label and a drop-folder name are shaped by one convention.

    The EXTENSION comes from the source, lowercased — not forced to `.jpg` the
    way the Groovy forced it, because this port also carries `.png`, `.webp`
    and `.hdr`, and renaming a PNG to `.jpg` would be a lie about its bytes.

    ``ordinal`` suffixes the second and later images OF ONE RECORD
    (`CoveredBridge-2.jpg`). A field may legitimately hold two images of one
    work (CE_DESIGN §14); two DIFFERENT records wanting one name is a clash the
    caller refuses, because the answer there is to change a label, not to
    invent a number.

    Returns "" when the label yields no usable stem — an empty or
    punctuation-only label — so the caller can fall back to the drop folder's
    own name rather than minting `.jpg` with nothing in front of it.
    """
    _stem, dot, ext = str(source).rpartition(".")
    suffix = f".{ext.lower()}" if dot and ext else ""
    named = normalize_filename(f"{label}{suffix}")
    stem = named[: -len(suffix)] if suffix and named.endswith(suffix) else named
    # `normalize_filename` substitutes `file` for a stem that reduces to
    # nothing, which is right for a dropped file and wrong here: `file.jpg` is
    # no better than `IMG_2104.jpg` and is a worse lie, since it looks derived.
    # An unusable label means fall back to the drop folder's own name.
    if not stem or stem == "file":
        return ""
    return f"{stem}-{ordinal}{suffix}" if ordinal > 1 else f"{stem}{suffix}"


# ---------------------------------------------------------------------------
# Opening the drop folder in the desktop's own file manager.
#
# A browser cannot do this: navigation from an http page to a `file://` URL is
# blocked, silently, in every current browser. So it is done server-side — which
# is honest about what it is, a local convenience for a dashboard that binds to
# localhost, and is why the path comes from CONFIG and never from the request.
#
# The path is not a parameter for the same reason the instance targets are not
# (law 11): a caller who could name a directory could name any directory, and
# "open this in a file manager" is a fine way to find out what is on a disk.
# ---------------------------------------------------------------------------

#: platform -> the command that shows a folder, given an OS-native path.
_OPENERS = {
    "wsl": ("explorer.exe",),      # WSL2 -> Windows Explorer
    "linux": ("xdg-open",),
    "darwin": ("open",),
    "win32": ("explorer",),
}


def _platform() -> str:
    import sys

    if sys.platform.startswith("linux"):
        try:
            if "microsoft" in Path("/proc/version").read_text().lower():
                return "wsl"
        except OSError:
            pass
        return "linux"
    return "darwin" if sys.platform == "darwin" else (
        "win32" if sys.platform.startswith("win") else "linux")


def _native_path(path: Path, platform: str) -> str:
    r"""The path as the FILE MANAGER understands it.

    Under WSL the manager is Windows Explorer, which cannot read
    `/home/you/...`; `wslpath -w` turns it into the `\\wsl.localhost\...`
    form that it can.
    """
    if platform != "wsl":
        return str(path)
    import subprocess

    try:
        out = subprocess.run(["wslpath", "-w", str(path)], capture_output=True,
                             text=True, timeout=10)
        return out.stdout.strip() or str(path)
    except (OSError, subprocess.SubprocessError):
        return str(path)


def open_folder(path) -> dict:
    """Show `path` in the desktop file manager. Never raises.

    Returns what happened, including the path, so a caller that cannot open
    anything — a headless host, a dashboard reached from another machine — can
    still tell the user where the folder is. That is the fallback that matters:
    the point is to get the user to their folder, and naming it does that even
    when launching fails.
    """
    import subprocess

    folder = Path(str(path)).expanduser()
    result = {"ok": False, "path": str(folder), "opener": ""}
    if not folder.is_dir():
        result["error"] = f"{folder} is not a folder on this machine"
        return result

    platform = _platform()
    result["opener"] = _OPENERS.get(platform, ("xdg-open",))[0]
    try:
        subprocess.Popen(
            [result["opener"], _native_path(folder, platform)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    # Launched, not verified. `explorer.exe` returns 1 on success often enough
    # that its exit code says nothing, and waiting on a file manager would hold
    # the request open for as long as the window is. Whether a window appeared
    # is something the user can see and this process cannot.
    result["ok"] = True
    return result
