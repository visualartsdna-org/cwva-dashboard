"""An image is named after the WORK, not after the camera.

Rick, 2026-10-05: "I forgot dashboard is not renaming files uniquely after the
work's label the way the old dashboard did. I didn't like seeing the google
photos name IMG_2104 when I pulled it up in the browser, I was about to grab a
copy to post on my site."

Restoring `support/ImageMgt.groovy:179` — `camelCase(title).jpg` — which the
port lost when it split naming from branding. The cost of not doing it is
published: the filename is the last segment of the IRI the record cites AND of
the URL on the artist's site.
"""

from __future__ import annotations

import pytest

from cwva_dashboard import config as cfgmod
from cwva_dashboard.inbox import filename_from_label, normalize_filename


# -- the rule ----------------------------------------------------------------


def test_the_camera_name_is_replaced_by_the_work():
    assert filename_from_label("Covered Bridge", "IMG_2104.JPG") == "CoveredBridge.jpg"


def test_it_is_the_SAME_rule_normalize_filename_applies():
    """Not a second naming convention — `normalize_filename` already applies the
    Groovy's own `Text.camelCase` and ASCII folding, so a label and a dropped
    name are shaped by one rule."""
    assert filename_from_label("Covered Bridge", "x.jpg") == \
        normalize_filename("Covered Bridge.jpg")


def test_the_EXTENSION_comes_from_the_file_not_the_Groovy():
    """The Groovy forced `.jpg`. This port also carries `.png`, `.webp` and
    `.hdr`, and renaming a PNG to `.jpg` would be a lie about its bytes."""
    assert filename_from_label("Pillars", "p.HDR") == "Pillars.hdr"
    assert filename_from_label("Study", "s.PNG") == "Study.png"


def test_accents_FOLD_rather_than_vanish():
    assert filename_from_label("Café Study", "x.webp") == "CafeStudy.webp"


def test_the_SECOND_image_of_one_record_is_ORDINAL():
    """A field may legitimately hold two images of one work (CE_DESIGN §14), and
    that is not a collision."""
    assert filename_from_label("Covered Bridge", "a.jpg", ordinal=1) == "CoveredBridge.jpg"
    assert filename_from_label("Covered Bridge", "b.jpg", ordinal=2) == "CoveredBridge-2.jpg"


# -- what it refuses to do ---------------------------------------------------


def test_an_UNUSABLE_label_falls_back_rather_than_minting_a_lie():
    """`normalize_filename` substitutes `file` for a stem that reduces to
    nothing, which is right for a dropped file and wrong here: `file.jpg` is no
    better than `IMG_2104.jpg` and is a worse lie, because it looks derived.
    Returning "" lets the caller keep the drop folder's own name."""
    for label in ("", "   ", "!!!", "---"):
        assert filename_from_label(label, "IMG_1.jpg") == "", repr(label)


def test_a_file_with_NO_extension_keeps_having_none():
    assert filename_from_label("Covered Bridge", "README") == "CoveredBridge"


# -- the config that governs it ----------------------------------------------


def test_the_DEFAULT_is_images_only():
    """A camera's `IMG_2104.JPG` carries no information. An export's
    `ChatGPT-ArtCriticism…-20261005-1348.md` says which assistant and when, so
    renaming it would DESTROY information — documents, meshes and videos keep
    their names."""
    assert cfgmod.name_from_label_kinds({}) == ("image",)


def test_the_SHIPPED_config_agrees_with_the_default():
    """The same trap `tests/test_inbox_config_agrees.py` stands against: the
    config REPLACES the code default rather than merging with it, so a default
    nobody ships is a default nobody gets."""
    cfg = cfgmod.load_config("config/base.rson")

    assert cfgmod.name_from_label_kinds(cfg) == cfgmod.DEFAULT_NAME_FROM_LABEL


@pytest.mark.parametrize("example", ["folder", "git", "gcp", "sample"])
def test_every_example_inherits_it(example):
    cfg = cfgmod.load_config(f"config/examples/{example}.rson")

    assert cfgmod.name_from_label_kinds(cfg) == ("image",)


def test_an_EXPLICIT_empty_list_turns_it_off():
    """A deployment that wants the drop folder's names keeps them — this is the
    pre-2026-10-07 behaviour, reachable by configuration rather than by code."""
    assert cfgmod.name_from_label_kinds({"entry_forms": {"name_from_label": []}}) == ()


# -- which FORMS rename, and which do not (Rick, 2026-10-07) -----------------
#
# "On entity forms, the image is not renamed … this applies only to the work
# entry/edit. Entity has its own rules." Which the entity spec had already half
# said for a neighbouring act: an entity's images "are references — a
# background plate, a document scan, a reference photograph — and are left
# exactly as they arrive". A work's image IS the work; an entity's image is a
# reference to something that already has a name.


def _forms():
    """The form specs, read from a built app rather than restated here."""
    from conftest import TEST_DOMAIN
    from cwva_dashboard.main import create_app
    app = create_app(domain=TEST_DOMAIN, enforce_landlock=False)
    return app


def test_the_WORK_forms_rename_and_the_ENTITY_form_does_not():
    import re
    from pathlib import Path

    src = Path("src/cwva_dashboard/main.py").read_text()
    block = src[src.index("    _FORMS = {"):src.index("    # A profile becomes an entry")]
    for form, expected in (("entry", "True"), ("digital", "True"), ("entity", "False")):
        seg = block[block.index(f'"{form}": {{'):]
        seg = seg[: seg.index("},")]
        m = re.search(r'"name_from_label":\s*(True|False)', seg)
        assert m, f"{form} does not say whether it renames"
        assert m.group(1) == expected, f"{form} says {m.group(1)}, expected {expected}"


def test_a_PROFILE_form_renames_because_it_makes_works():
    from pathlib import Path

    src = Path("src/cwva_dashboard/main.py").read_text()
    seg = src[src.index('"workflow": "rdf_profile",'):][:400]

    assert '"name_from_label": True' in seg
