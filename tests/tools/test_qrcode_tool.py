"""`image.qrcode` — the submit-time side effect the Groovy entry performed.

Found by driving the wired form for real: the record derives `vad:qrcode` for
every work, nothing generated the file, so **every** entry failed the
asset-reference gate with a dangling qrcode. These tests pin the two things that
make the reference resolve: the filename the record derives, and the fact that
the gate then passes.
"""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion import gates
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.image_tools import build_image_tools, qrcode_filename
from cwva_dashboard.tools.record_tools import image_base, qrcode_url

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

FLAT = Layout.from_map({"image": "images", "work_ttl": "ttl/data"})
DOMAIN = "http://visualartsdna.org"


def _tool(name="image.qrcode", layout=FLAT):
    return next(t for t in build_image_tools(DOMAIN, layout=layout) if t.name == name)


def _ops(tmp_path):
    return FileOps(Sandbox.open(tmp_path))


def test_generates_the_filename_the_record_references(tmp_path):
    """The two must agree by construction — the record derives `vad:qrcode`
    from the guid, and this writes that exact name."""
    ops = _ops(tmp_path)
    out = _tool().handler(ops, guid="abc-123")

    assert out["path"] == "images/qrc_abc-123.jpg"
    assert qrcode_filename("abc-123") in qrcode_url("abc-123", image_base(DOMAIN))
    assert (tmp_path / "images" / "qrc_abc-123.jpg").is_file()


def test_encodes_the_work_uri_at_the_groovy_size(tmp_path):
    from io import BytesIO

    from PIL import Image

    ops = _ops(tmp_path)
    out = _tool().handler(ops, guid="abc-123")

    assert out["uri"] == f"{DOMAIN}/work/abc-123"  # ImageMgt.qrcode ns + guid
    img = Image.open(BytesIO((tmp_path / "images" / "qrc_abc-123.jpg").read_bytes()))
    assert img.size == (125, 125)  # ImageMgt default
    assert img.format == "JPEG"


def test_existing_file_is_left_alone(tmp_path):
    """Groovy skipped generation when the file existed; regenerating would
    rewrite a managed binary and attic the old one for nothing."""
    ops = _ops(tmp_path)
    first = _tool().handler(ops, guid="abc-123")
    again = _tool().handler(ops, guid="abc-123")

    assert first["generated"] is True
    assert again["generated"] is False


def test_overwrite_regenerates_when_asked(tmp_path):
    ops = _ops(tmp_path)
    _tool().handler(ops, guid="abc-123")
    again = _tool().handler(ops, guid="abc-123", overwrite=True)
    assert again["generated"] is True


def test_dest_dir_follows_the_active_layout(tmp_path):
    """Flat target -> images/; default target -> content/images/ (B1)."""
    assert _tool().handler(_ops(tmp_path), guid="g")["path"].startswith("images/")
    other = tmp_path / "b"
    other.mkdir()
    out = _tool(layout=Layout.default()).handler(_ops(other), guid="g")
    assert out["path"].startswith("content/images/")


def test_the_asset_gate_passes_once_the_qr_exists(tmp_path):
    """The end-to-end claim: this is what turns the failing gate green, without
    weakening the gate."""
    from rdflib import Graph, URIRef

    from cwva_dashboard.tools.record_tools import SCHEMA, VAD

    ops = _ops(tmp_path)
    (tmp_path / "images").mkdir(exist_ok=True)
    (tmp_path / "images" / "pic.jpg").write_bytes(b"\xff\xd8jpeg")

    g = Graph()
    subj = URIRef(f"{DOMAIN}/work/abc-123")
    g.add((subj, SCHEMA.image, URIRef(image_base(DOMAIN) + "pic.jpg")))
    g.add((subj, VAD.qrcode, URIRef(qrcode_url("abc-123", image_base(DOMAIN)))))

    before = gates.asset_reference_gate(
        g, tmp_path, image_base=image_base(DOMAIN), image_dir="images"
    )
    assert not before.ok and before.details["absent"] == ["qrcode → qrc_abc-123.jpg"]

    _tool().handler(ops, guid="abc-123")

    after = gates.asset_reference_gate(
        g, tmp_path, image_base=image_base(DOMAIN), image_dir="images"
    )
    assert after.ok, after.details
