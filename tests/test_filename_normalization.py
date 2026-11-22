"""Filenames are normalized on the way in.

A filename here does not stay a filename: it is joined to the image or documents
base and becomes the IRI a record cites. A space in an IRI is invalid, and `#`,
`?` and `%` change what the IRI MEANS — so the convention Rick has been applying
by hand before every entry is applied by the dashboard instead.

The rule is the Groovy's own `Text.camelCase` (drop the space, capitalise what
follows) plus its `toGuaranteedAscii` folding, so results match the names
already in the store rather than inventing a style.
"""

from __future__ import annotations

import pytest

from cwva_dashboard.inbox import normalize_filename as n


@pytest.mark.parametrize(
    "given,expected",
    [
        # the case that motivated this
        ("Unmoored Swing.jpg", "UnmooredSwing.jpg"),
        ("Last Supper Orbit.mp4", "LastSupperOrbit.mp4"),
        ("Watercolor critique of Spirited Tree.md", "WatercolorCritiqueOfSpiritedTree.md"),
        # runs of spaces, and leading/trailing space
        ("  spaced  out  name .md", "spacedOutName.md"),
        # accents FOLD rather than vanish
        ("Café Noir.jpg", "CafeNoir.jpg"),
        ("ÜberBild.png", "UberBild.png"),
        # characters that would change what the IRI means
        ("report#2?.pdf", "report2.pdf"),
        ("50% done.md", "50Done.md"),
        # the extension is lowercased: it carries no information, and one
        # convention is one fewer way for Sunset.jpg / sunset.JPG to happen
        ("IMG_1525.JPG", "IMG_1525.jpg"),
        ("Unmoored Swing.JPG", "UnmooredSwing.jpg"),
        ("Mesh.GLB", "Mesh.glb"),
        ("Analysis.PDF", "Analysis.pdf"),
    ],
)
def test_names_that_need_fixing(given, expected):
    assert n(given) == expected


@pytest.mark.parametrize(
    "already_fine",
    [
        # The common case must be a no-op. Renaming a legal name is churn, not
        # repair — and it would rename half the existing store on re-entry.
        "IMG_1525.jpg",
        "Test-UnmooredSwing.jpg",
        "LastSupperOrbit.mp4",
        "qrc_baabb7e7-da0e-490f-9fee-3d1116706403.jpg",
        "AbstractionMetricsII.md",
        "domOSCommonOntology.jpg",
    ],
)
def test_a_legal_name_is_left_alone(already_fine):
    assert n(already_fine) == already_fine


def test_only_the_FINAL_extension_is_lowercased():
    """The stem keeps its case — camelCase names are made of it — and by this
    function's splitting rule `.TAR` is part of the stem."""
    assert n("Some Photo.JPG") == "SomePhoto.jpg"
    assert n("thing.TAR.GZ") == "thing.TAR.gz"


def test_normalization_never_reaches_existing_content():
    """Normalization applies to names ARRIVING from the drop folder, never to
    what is already stored. Nothing in sync, promotion or convergence renames
    anything, so the store's existing `.JPG` references are never re-processed —
    which is what makes extension-lowercasing a convention rather than a
    migration.

    Pinned by where it is USED rather than by how many times: the editor
    legitimately added call sites (offering drop-folder names, and resolving one
    back to its file on ingest). Wiring it into the sync or promotion path is
    the thing that would turn it into a rewrite of the store.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "cwva_dashboard"
    offenders = [
        p.relative_to(root).as_posix()
        for p in list((root / "sot_sync").rglob("*.py")) + list((root / "promotion").rglob("*.py"))
        if "normalize_filename" in p.read_text()
    ]
    assert not offenders, f"normalization must not run over stored content: {offenders}"


def test_normalization_is_idempotent():
    """It runs on every submission, including re-runs of the same entry."""
    for name in ("Unmoored Swing.jpg", "Café Noir.jpg", "50% done.md"):
        once = n(name)
        assert n(once) == once


def test_a_name_that_normalizes_to_nothing_still_gets_one():
    assert n("...jpg") == "file.jpg" or n("...jpg").endswith(".jpg")
    assert n("###.md") == "file.md"
