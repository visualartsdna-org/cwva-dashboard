"""Image utility tools (Phase 4.5 port of inventory #32 / #33).

``image.scale`` and ``image.convert`` over Pillow. Both read and write through
``FileOps``, so a written image is confined *and* its pointer sidecar stays
consistent automatically (managed binaries update their ``.ptr`` on write, and
an overwrite attics the superseded content — CE_DESIGN §3.4). No workflow /
promotion; these are scratch operations in the sandbox.
"""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import PurePosixPath

from PIL import Image, UnidentifiedImageError

from .base import Tool, ToolError

__all__ = ["IMAGE_TOOLS", "build_image_tools", "qrcode_filename",
           "transform_image", "CONVERT_FORMATS", "MAX_TRANSFORM_BYTES",
           "brand_bytes", "BrandError", "FONT_CANDIDATES",
           "signature_options"]

# QR fidelity, from support/ImageMgt.groovy qrcode(guid, dir, ns, size):
# the encoded payload is the WORK URI (`{domain}/work/{guid}`), the file is
# `qrc_<guid>.jpg`, and the square is 125px. Existing files are left alone
# there, and here too -- regenerating would rewrite a managed binary and attic
# the old one for no reason.
_QR_SIZE = 125

_EXT_FOR_FORMAT = {"JPEG": ".jpg", "JPG": ".jpg", "TIFF": ".tiff", "PNG": ".png"}


def _scale(fileops, path, factor, overwrite=True):
    img = Image.open(BytesIO(fileops.read_bytes(path)))
    fmt = img.format or "PNG"
    w, h = img.size
    nw, nh = max(1, round(w * factor)), max(1, round(h * factor))
    resized = img.resize((nw, nh))
    buf = BytesIO()
    resized.save(buf, format=fmt)
    dst = path if overwrite else _suffixed(path, f"-{nw}x{nh}")
    res = fileops.write_bytes(dst, buf.getvalue())
    return {"path": res.path, "size": [nw, nh], "bytes": res.bytes_written}


def _convert(fileops, path, format):
    fmt = format.upper()
    if fmt == "JPG":
        fmt = "JPEG"
    img = Image.open(BytesIO(fileops.read_bytes(path)))
    if fmt == "JPEG" and img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = BytesIO()
    img.save(buf, format=fmt)
    ext = _EXT_FOR_FORMAT.get(fmt, "." + fmt.lower())
    dst = str(PurePosixPath(path).with_suffix(ext))
    res = fileops.write_bytes(dst, buf.getvalue())
    return {"path": res.path, "format": fmt, "bytes": res.bytes_written}


# -- on a file the user hands over, not one in the sandbox ---------------------
#
# The hub's Scale Image / Convert Image (2026-11-19). Groovy wrote the result
# beside the original in the user's own folder (to get under Google Keep's
# image-size limit, say), and the dashboard may not write outside the sandbox
# except by promotion (law 1). So the bytes come in as an argument and go back
# as the result, for the browser to download; nothing is stored.

#: What Convert Image offers, which is what Pillow can actually write. The old
#: form also listed MPEG, PICT, SVG, RGB and RGBA, none of which it can.
CONVERT_FORMATS = ["JPG", "PNG", "TIFF", "WEBP", "GIF", "BMP", "PDF"]
MAX_TRANSFORM_BYTES = 40_000_000


def transform_image(data: bytes, op: str, *, factor: float = 1.0,
                    format: str = "") -> dict:
    """``{"bytes", "format", "size", "ext"}`` for a scaled or converted image."""
    if len(data) > MAX_TRANSFORM_BYTES:
        raise ToolError("too_large", f"more than {MAX_TRANSFORM_BYTES // 1_000_000} MB")
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ToolError("not_an_image", f"not an image Pillow can read: {exc}") from None
    if op == "scale":
        if not 0 < factor <= 10:
            raise ToolError("bad_args", "the scale factor must be above 0 and at most 10")
        fmt = img.format or "PNG"
        w, h = img.size
        img = img.resize((max(1, round(w * factor)), max(1, round(h * factor))),
                         Image.LANCZOS)
    elif op == "convert":
        fmt = "JPEG" if format.upper() == "JPG" else format.upper()
        if format.upper() not in CONVERT_FORMATS:
            raise ToolError("bad_args", f"cannot write {format!r}")
        if fmt in ("JPEG", "PDF", "BMP") and img.mode not in ("RGB", "L"):
            img = img.convert("RGB")  # no alpha channel in these
    else:
        raise ToolError("bad_args", f"unknown operation {op!r}")
    buf = BytesIO()
    img.save(buf, format=fmt)
    return {"bytes": buf.getvalue(), "format": fmt, "size": list(img.size),
            "ext": _EXT_FOR_FORMAT.get(fmt, "." + fmt.lower())}


def _transform(fileops, data_b64, op, factor=1.0, format=""):
    try:
        data = base64.b64decode(data_b64, validate=True)
    except ValueError:
        raise ToolError("bad_args", "data_b64 is not base64") from None
    out = transform_image(data, op, factor=float(factor), format=str(format))
    return {"data_b64": base64.b64encode(out.pop("bytes")).decode("ascii"), **out}


def qrcode_filename(guid: str) -> str:
    """`qrc_<guid>.jpg` — the name the record tool derives its `vad:qrcode`
    reference from, so the two must agree by construction (D1)."""
    return f"qrc_{guid}.jpg"


def _qrcode(fileops, guid, work_uri, dest_dir, size=_QR_SIZE, overwrite=False):
    """Generate the work's QR-code JPEG into the images dir.

    **Why this tool exists:** the Groovy entry generated this JPEG on submit
    (`ImageMgt.qrcode`), and the dashboard decomposed the side effect out of the
    record tool -- correctly -- but never built the piece that replaces it. The
    record still derives `vad:qrcode` for every work, so with nothing generating
    the file, *every* entry failed the asset-reference gate with a dangling
    qrcode. Found on the first real run of the wired form, which is exactly what
    driving it was for.
    """
    import qrcode as _qr

    path = f"{dest_dir.rstrip('/')}/{qrcode_filename(guid)}"
    if not overwrite:
        try:
            fileops.read_bytes(path)
            return {"path": path, "generated": False, "uri": work_uri}
        except Exception:
            pass  # absent -> generate

    img = _qr.make(work_uri).convert("RGB").resize((size, size))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    res = fileops.write_bytes(path, buf.getvalue(), make_parents=True)
    return {"path": res.path, "generated": True, "uri": work_uri,
            "bytes": res.bytes_written}


# ---------------------------------------------------------------------------
# Branding — the port of support/ImageMgt2 (inventory #7, Brand Image).
#
# The published convention is that every image carries the artist's domain in
# its lower-right corner. Until now the only thing that could draw it was the
# legacy Groovy server, so a CE user had no way to brand at all; Rick's images
# arrive pre-branded from that server, which is why the dashboard looked like it
# was doing this already (2026-09-14: the ingested file was byte-identical to
# the one dropped, signature and all).
#
# Every constant below is the Groovy's, kept because the stamp must land where
# it lands on 1,600 existing images, not where a fresh eye would put it.
_SIG_X = 0.9        # wproportion — left edge of the text
_SIG_Y = 0.98       # hproportion — the BASELINE, not the top (Java drawString)
_SIG_DIVISOR = 1028  # size = max(h, w) / 1028 * 8 …
_SIG_SCALE = 8
_SIG_MIN, _SIG_MAX = 10, 35  # … clamped
_LIGHT = (192, 192, 192)  # java.awt.Color.lightGray
_DARK = (64, 64, 64)      # java.awt.Color.darkGray

# Arial is the Groovy's font and is present on Windows, which CE also targets.
# Elsewhere it is not: this machine has DejaVu and Ubuntu only. Metric-compatible
# substitutes come first so the stamp keeps its width where one is installed.
FONT_CANDIDATES = (
    "arial.ttf",  # found by name on Windows
    # A dashboard in WSL2 can read the Windows font directory, which is where
    # the real Arial is on this machine — the stamp then matches the existing
    # images exactly instead of merely landing in the same place.
    "/mnt/c/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf",
    "/Library/Fonts/Arial.ttf",
)


class BrandError(Exception):
    """Branding could not be done — no usable font, unreadable image. Raised
    rather than degraded: Pillow's built-in bitmap font does not scale, so the
    fallback would be an illegible speck burned into a published image."""


def _load_font(size: int, candidates=FONT_CANDIDATES):
    from PIL import ImageFont

    for cand in candidates:
        try:
            return ImageFont.truetype(cand, size), cand
        except OSError:
            continue
    raise BrandError(
        "no usable TrueType font found for the signature; tried "
        + ", ".join(candidates)
    )


def _corner_is_dark(img, hprop: float = _SIG_Y, wprop: float = _SIG_X) -> bool:
    """ImageMgt2.detectPixValue, faithfully.

    It votes over the corner the signature sits in: +1 for each pixel whose
    packed RGB is below 0x800000, -1 otherwise, dark wins on a positive sum.
    That threshold is really "is the RED channel under 128" — a crude test, but
    it is the one that chose the colour on every image already published, so
    reproducing it matters more than improving it.
    """
    w, h = img.size
    x0, y0 = int(w * wprop), int(h * hprop)
    votes = 0
    px = img.load()
    for x in range(x0, w):
        for y in range(y0, h):
            r, g, b = px[x, y][:3]
            votes += 1 if ((r << 16) | (g << 8) | b) < 0x800000 else -1
    return votes > 0


def brand_bytes(data: bytes, signature: str, *, candidates=FONT_CANDIDATES) -> tuple:
    """Draw `signature` into the image's lower-right corner. Returns (jpeg, meta).

    JPEG out regardless of what came in, as the Groovy did — the branded image
    is the published one, and `schema:image` on 1,600 records names a .jpg.
    """
    from PIL import Image, ImageDraw

    if not signature.strip():
        raise BrandError("no signature to draw")
    try:
        img = Image.open(BytesIO(data))
        img_format = img.format
        img = img.convert("RGB")
    except Exception as exc:
        raise BrandError(f"cannot read the image ({exc})") from None

    w, h = img.size
    size = max(_SIG_MIN, min(_SIG_MAX, int(max(h, w) / _SIG_DIVISOR * _SIG_SCALE)))
    font, font_path = _load_font(size, candidates)
    dark = _corner_is_dark(img)

    draw = ImageDraw.Draw(img)
    # anchor="ls": left edge, BASELINE — Java's drawString(x, y) places the
    # baseline at y, and Pillow's default anchor is the top of the ascender, so
    # without this the text sits a line lower than every existing stamp.
    draw.text((w * _SIG_X, h * _SIG_Y), signature, font=font,
              fill=_LIGHT if dark else _DARK, anchor="ls")

    # The Groovy always wrote JPEG because it also renamed the file to
    # `camelCase(title).jpg`. Here the name already exists and a record already
    # cites it, so the FORMAT IS PRESERVED — branding a .png must not leave a
    # JPEG sitting at a .png path that the asset gate then vouches for.
    fmt = (img_format or "JPEG").upper()
    if fmt not in ("JPEG", "PNG", "TIFF", "WEBP"):
        fmt = "JPEG"
    buf = BytesIO()
    img.save(buf, format=fmt, **({"quality": 95} if fmt == "JPEG" else {}))
    return buf.getvalue(), {
        "signature": signature, "font_size": size, "font": font_path,
        "colour": "light" if dark else "dark", "size": [w, h], "format": fmt,
    }


def signature_options(sites, brands=()) -> list[str]:
    """The signatures a deployment may stamp.

    Two sources, both data the deployment owns: its configured `sites`, and the
    `vad:brand` each ARTIST declares. The second is what actually drives
    branding now (CE_DESIGN §14.5) — a profile form stamps its artist's brand
    without asking — so a tool whose enum came only from `sites` would refuse
    the very value the dashboard was about to send. Offered and enforced have to
    be the same set, and the set grew when the artists did.

    `https://visualartsdna.org` -> `visualartsdna.org`, which is exactly what the
    Groovy's radio buttons held — but as DATA now, so a deployment that is not
    Rick's gets its own and no code changes. Derived rather than listed: a
    second enumeration of the same set is how the offered set and the enforced
    set come apart.
    """
    out = []
    for value in [*(sites or []), *(brands or [])]:
        host = str(value).split("://", 1)[-1].strip("/").strip()
        if host and host not in out:
            out.append(host)
    return out


def _brand(fileops, path, signature):
    """Stamp an image ALREADY IN THE SANDBOX, in place.

    Deliberately separate from the ingest, which stays a verbatim copy: the
    stamp is destructive and NOT idempotent — branding twice writes the
    signature over itself, which is invisible when the fonts match and a smear
    when they do not. Overwriting through FileOps attics the unbranded original,
    so this is recoverable (CE_DESIGN §3.4).
    """
    data = fileops.read_bytes(path)
    out, meta = brand_bytes(data, signature)
    res = fileops.write_bytes(path, out)
    return {"path": res.path, "bytes": res.bytes_written, **meta}


def _suffixed(path: str, suffix: str) -> str:
    p = PurePosixPath(path)
    return str(p.with_name(p.stem + suffix + p.suffix))


IMAGE_TOOLS: list[Tool] = [
    Tool(
        name="image.transform",
        description=("Scale or convert an image handed over as base64 (not a "
                     "sandbox file) and return the result as base64. Writes nothing."),
        input_schema={
            "type": "object",
            "properties": {
                "data_b64": {"type": "string", "description": "The image, base64."},
                "op": {"type": "string", "enum": ["scale", "convert"]},
                "factor": {"type": "number", "default": 1.0,
                           "description": "scale: e.g. 0.25 for a quarter size."},
                "format": {"type": "string", "enum": [*CONVERT_FORMATS, ""],
                           "default": "", "description": "convert: the target format."},
            },
            "required": ["data_b64", "op"],
            "additionalProperties": False,
        },
        handler=_transform,
        redact=frozenset({"data_b64"}),
    ),
    Tool(
        name="image.scale",
        description="Scale an image by a factor (e.g. 0.5), preserving format.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Sandbox-relative image path."},
                "factor": {"type": "number", "description": "Scale factor (>0)."},
                "overwrite": {
                    "type": "boolean",
                    "description": "Overwrite in place; else write a -WxH sibling.",
                    "default": True,
                },
            },
            "required": ["path", "factor"],
            "additionalProperties": False,
        },
        handler=_scale,
    ),
    Tool(
        name="image.convert",
        description="Convert an image to another format (PNG/JPEG/TIFF/…), writing a sibling.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Sandbox-relative image path."},
                "format": {"type": "string", "description": "Target format, e.g. JPEG."},
            },
            "required": ["path", "format"],
            "additionalProperties": False,
        },
        handler=_convert,
    ),
]


def build_image_tools(domain: str, *, layout=None, sites=None,
                      brands=()) -> list[Tool]:
    """Image tools, plus `image.qrcode` bound to the deployer's domain (the work
    URI it encodes) and the active target's images dir (where it writes)."""
    from functools import partial

    from ..promotion.layout import Layout
    from .record_tools import work_namespace

    lay = layout or Layout.default()
    images_dir = lay.dir("image")
    work_ns = work_namespace(domain)

    def _handler(fileops, guid, dest_dir=images_dir, size=_QR_SIZE, overwrite=False):
        return _qrcode(fileops, guid, str(work_ns[guid]), dest_dir, size, overwrite)

    # Offered only where a deployment has said who it is. With no configured
    # site there is no signature to draw, and registering the tool with an empty
    # enum would advertise a capability that refuses every argument.
    signatures = signature_options(sites, brands)
    brand = [
        Tool(
            name="image.brand",
            description=(
                "Stamp an image in the sandbox with a site signature in its lower-right "
                "corner (inventory #7, the port of ImageMgt2). Overwrites in place; the "
                "unbranded original goes to the attic. NOT idempotent — branding twice "
                "draws the signature over itself."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Sandbox-relative image path."},
                    "signature": {
                        "type": "string",
                        "description": "The site to stamp, from the configured sites.",
                        "enum": signatures,
                    },
                },
                "required": ["path", "signature"],
                "additionalProperties": False,
            },
            handler=_brand,
        ),
    ] if signatures else []

    return [
        *IMAGE_TOOLS, *brand,
        Tool(
            name="image.qrcode",
            description=(
                "Generate a work's QR-code JPEG (qrc_<guid>.jpg) encoding the work URI, "
                "into the images dir — the side effect the Groovy entry performed on submit."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "guid": {"type": "string", "description": "Work guid."},
                    "dest_dir": {"type": "string", "description": "Images dir.", "default": images_dir},
                    "size": {"type": "number", "description": "Square side in px.", "default": _QR_SIZE},
                    "overwrite": {
                        "type": "boolean",
                        "description": "Regenerate if present (default: leave existing).",
                        "default": False,
                    },
                },
                "required": ["guid"],
                "additionalProperties": False,
            },
            handler=_handler,
        ),
    ]
