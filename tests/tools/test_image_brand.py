"""Branding — the port of support/ImageMgt2 (inventory #7, Brand Image).

The published convention is that every image carries the artist's domain in its
lower-right corner, and until now the only thing that could draw it was the
legacy Groovy server. Rick's images arrive pre-branded from that server, which
is why the dashboard looked like it was already doing this: the file it ingested
on 2026-09-14 was byte-identical to the one he dropped, signature and all.

The geometry here is the Groovy's, not a fresh judgement — it has to land where
it lands on 1,600 published images.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from cwva_dashboard.tools.image_tools import (
    BrandError,
    brand_bytes,
    build_image_tools,
    signature_options,
)

SITES = ["https://visualartsdna.org", "https://art.visualartsdna.org"]


def _jpeg(w=1028, h=1028, colour=(255, 255, 255)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="JPEG")
    return buf.getvalue()


def _png(w=1028, h=1028, colour=(255, 255, 255)) -> bytes:
    """Lossless, for the tests that measure WHERE the ink is: JPEG ringing
    spreads non-white pixels across the whole 8x8 block, which moved the
    measured left edge five pixels and is an artifact of the fixture, not the
    stamp."""
    buf = BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


def _pixels(data: bytes):
    return Image.open(BytesIO(data)).convert("RGB")


def test_the_signature_lands_where_the_groovy_put_it():
    """x = 0.9w, and y = 0.98h is the BASELINE — Java's drawString anchors
    there, Pillow's default anchors at the top of the ascender, so a text drawn
    without `anchor="ls"` sits a whole line below every existing stamp."""
    plain = _png()
    out, meta = brand_bytes(plain, "visualartsdna.org")
    img = _pixels(out)

    ink = [(x, y) for x in range(img.width) for y in range(img.height)
           if img.getpixel((x, y)) != (255, 255, 255)]
    assert ink, "nothing was drawn"
    left = min(x for x, _ in ink)
    bottom = max(y for _, y in ink)
    assert left == pytest.approx(int(1028 * 0.9), abs=2)
    # the baseline is at 0.98h; descenders reach a little below it
    assert bottom == pytest.approx(int(1028 * 0.98), abs=5)


def test_the_font_size_is_the_groovy_formula():
    """max(h, w) / 1028 * 8, clamped to 10..35 — so the divisor's own size
    lands on the floor, not on 8."""
    assert brand_bytes(_jpeg(1028, 1028), "x.art")[1]["font_size"] == 10
    assert brand_bytes(_jpeg(4000, 4000), "x.art")[1]["font_size"] == 31
    assert brand_bytes(_jpeg(200, 200), "x.art")[1]["font_size"] == 10
    assert brand_bytes(_jpeg(9000, 9000), "x.art")[1]["font_size"] == 35
    # and the real one: Rick's 2806x3886 watercolour brands at 30, which is what
    # the legacy server drew on it.
    assert brand_bytes(_jpeg(2806, 3886), "x.art")[1]["font_size"] == 30


def test_the_colour_is_chosen_by_LOOKING_at_that_corner():
    """ImageMgt2.detectPixValue votes over the pixels the text will cover:
    light gray on a dark corner, dark gray on a light one. A signature the same
    colour as the paint is a signature nobody sees."""
    on_dark = _pixels(brand_bytes(_png(colour=(10, 10, 10)), "x.art")[0])
    on_light = _pixels(brand_bytes(_png(colour=(250, 250, 250)), "x.art")[0])

    def ink(img, ground):
        return [img.getpixel((x, y)) for x in range(img.width) for y in range(img.height)
                if abs(img.getpixel((x, y))[0] - ground) > 20]

    assert max(p[0] for p in ink(on_dark, 10)) > 120, "light ink on a dark corner"
    assert min(p[0] for p in ink(on_light, 250)) < 120, "dark ink on a light one"


def test_the_format_is_PRESERVED_not_forced_to_jpeg():
    """The Groovy always wrote .jpg because it also renamed the file. Here the
    name already exists and a record already cites it — leaving JPEG bytes at a
    .png path would be a lie the asset gate then vouches for."""
    buf = BytesIO()
    Image.new("RGB", (500, 500), (128, 128, 128)).save(buf, format="PNG")

    out, meta = brand_bytes(buf.getvalue(), "x.art")

    assert meta["format"] == "PNG"
    assert Image.open(BytesIO(out)).format == "PNG"


def test_branding_TWICE_is_not_the_same_as_branding_once():
    """Not a bug to fix — a property to respect. The second stamp lands on the
    first, which is invisible when the fonts match and a smear when they do not,
    and it is why branding is a deliberate act rather than part of the ingest."""
    once = brand_bytes(_jpeg(), "visualartsdna.org")[0]
    twice = brand_bytes(once, "art.visualartsdna.org")[0]

    assert once != twice
    a, b = _pixels(once), _pixels(twice)
    differing = sum(1 for x in range(a.width) for y in range(a.height)
                    if a.getpixel((x, y)) != b.getpixel((x, y)))
    assert differing > 100, "the second signature is really there, over the first"


def test_an_empty_signature_is_refused():
    with pytest.raises(BrandError, match="no signature"):
        brand_bytes(_jpeg(), "   ")


def test_something_that_is_not_an_image_is_refused():
    with pytest.raises(BrandError, match="cannot read"):
        brand_bytes(b"this is not a jpeg", "x.art")


def test_no_font_is_an_ERROR_not_a_silent_speck():
    """Pillow's built-in bitmap font does not scale, so falling back to it would
    burn an illegible mark into a published image."""
    with pytest.raises(BrandError, match="no usable TrueType font"):
        brand_bytes(_jpeg(), "x.art", candidates=("/nonexistent/nope.ttf",))


# ---------------------------------------------------------------------------
# What may be stamped is DATA, derived from the deployment's own sites.
# ---------------------------------------------------------------------------

def test_the_signatures_are_derived_from_the_configured_sites():
    """`https://visualartsdna.org` -> `visualartsdna.org`, which is exactly what the
    Groovy's radio button held — as config now, so a CE deployment that is not
    Rick's gets its own with no code change."""
    assert signature_options(SITES) == ["visualartsdna.org", "art.visualartsdna.org"]
    assert signature_options(["http://x.art/", "http://x.art"]) == ["x.art"]
    assert signature_options([]) == []


def test_the_tool_ENFORCES_exactly_what_the_form_offers():
    tool = next(t for t in build_image_tools("example.org", sites=SITES)
                if t.name == "image.brand")

    offered = tool.input_schema["properties"]["signature"]["enum"]
    assert offered == signature_options(SITES)


def test_a_deployment_with_no_sites_is_offered_no_branding():
    """Rather than a tool that advertises a capability and refuses every
    argument."""
    names = [t.name for t in build_image_tools("example.org")]

    assert "image.brand" not in names
