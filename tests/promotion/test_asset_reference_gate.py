"""Asset-reference gate: image-family references resolve to a managed asset.

The forward complement of the orphan report (referenced-but-absent, vs the
orphan report's present-but-unreferenced). Two properties this pins:

1. **"Present" is the pointer layer's notion, not the filesystem's.** A managed
   image is gitignored; its `.ptr` sidecar is what git tracks. So a reference
   resolves if the real file OR the sidecar is present. A naive
   `os.path.exists(image)` passes a fixture (real file staged) and fails on real
   pointer-managed content (only sidecar) — the seam to the binary work.
2. **Malformed vs. absent are separate classes.** A well-formed
   `{image_base}<name>` whose asset is absent is a dangling reference (the
   image-less shadow produces ~200 of these on first sync, an expected
   known-partial). A value that is not a well-formed image-base reference — a
   bare filename, the qrcode base-join bug — is a data-shape defect that must
   stay visible and never be drowned by the absent class.
"""

from __future__ import annotations

import shutil

import pytest
from rdflib import Graph, Namespace, URIRef
from rdflib.namespace import RDF

from cwva_dashboard.promotion.gates import asset_reference_gate
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.transports import FilesTransport
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.sandbox.pointers import pointer_path_of
from cwva_dashboard.workflows.promote import run_promotion

VAD = Namespace("http://visualartsdna.org/model/")
SCHEMA = Namespace("https://schema.org/")
WORK = Namespace("http://visualartsdna.org/work/")
IMG_BASE = "http://visualartsdna.org/images/"
IMG_DIR = "content/images"


def _graph(*triples) -> Graph:
    g = Graph()
    for t in triples:
        g.add(t)
    return g


def _work(g, guid="w1"):
    s = WORK[guid]
    g.add((s, RDF.type, VAD.Watercolor))
    return s


# -- "present" = managed asset (file OR sidecar), not os.path.exists ---------


def test_resolves_when_the_real_file_is_present(tmp_path):
    (tmp_path / IMG_DIR).mkdir(parents=True)
    (tmp_path / IMG_DIR / "a.jpg").write_bytes(b"JPEG")
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "a.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.ok and r.details["resolved"] == 1


def test_resolves_when_only_the_sidecar_is_present(tmp_path):
    """The real content case: the binary is gitignored, the sidecar is tracked.
    A file-exists check would wrongly fail here."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    # no a.jpg on disk — only its .ptr, as after a git tree restore / clean tree
    pointer_path_of(tmp_path / IMG_DIR / "a.jpg").write_text(
        '{"sha256": "abc", "size": 4, "created": ""}'
    )
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "a.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.ok and r.details["resolved"] == 1


# -- absent (well-formed, asset missing) -------------------------------------


def test_absent_reference_fails_when_present_required(tmp_path):
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "missing.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert not r.ok
    assert r.details["absent"] == ["image → missing.jpg"]
    assert r.details["malformed"] == []


def test_absent_is_reported_not_fatal_when_not_required(tmp_path):
    """The shadow first-sync mode: ~200 absent image refs are the expected
    known-partial class, not a wall of failures."""
    g = Graph(); s = _work(g)
    g.add((s, SCHEMA.image, URIRef(IMG_BASE + "one.jpg")))
    g.add((s, VAD.qrcode, URIRef(IMG_BASE + "qrc_two.jpg")))

    r = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR, require_present=False
    )
    assert r.ok  # not fatal
    assert set(r.details["absent"]) == {"image → one.jpg", "qrcode → qrc_two.jpg"}


# -- malformed (the qrcode base-join bug) ------------------------------------


def test_bare_filename_qrcode_is_malformed_not_absent(tmp_path):
    """The base-join bug: `URIRef("qrc_x.jpg")` with no image-base join. It must
    land in `malformed`, not `absent`, so it stays visible among expected
    danglers and reads as the data-shape defect it is."""
    g = Graph(); s = _work(g)
    g.add((s, VAD.qrcode, URIRef("qrc_x.jpg")))  # bare — the bug

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert not r.ok
    assert r.details["malformed"] == ["qrcode → qrc_x.jpg"]
    assert r.details["absent"] == []


def test_malformed_stays_visible_amid_many_absent(tmp_path):
    """The discriminator's whole point: one malformed must not drown in absents."""
    g = Graph(); s = _work(g)
    for i in range(50):
        g.add((s, SCHEMA.image, URIRef(IMG_BASE + f"img{i}.jpg")))  # absent
    g.add((s, VAD.qrcode, URIRef("qrc_bug.jpg")))  # the one malformed

    r = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR, require_present=False
    )
    # absents are non-fatal in this mode, but the malformed still fails the gate
    assert not r.ok
    assert r.details["malformed"] == ["qrcode → qrc_bug.jpg"]
    assert len(r.details["absent"]) == 50


def test_wrong_host_is_malformed(tmp_path):
    g = Graph(); s = _work(g)
    g.add((s, SCHEMA.image, URIRef("http://evil.example/images/a.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert not r.ok and r.details["malformed"] == ["image → http://evil.example/images/a.jpg"]


def test_background_is_not_treated_as_an_asset_reference(tmp_path):
    """vad:background points at a work:, not an image — it must be ignored here
    (its referential integrity is a work-cross-reference concern, not this gate)."""
    g = Graph(); s = _work(g)
    g.add((s, VAD.background, WORK["other-work-guid"]))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    # Full-dict equality on purpose: the claim is that NOTHING was recorded in
    # any class, so a new class has to appear here too (`empty`, 2026-10-29).
    assert r.ok and r.details == {
        "malformed": [], "absent": [], "empty": [], "external": [], "resolved": 0
    }


# -- armed in run_promotion (end-to-end + mutation discipline) ---------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_dangling_reference_blocks_promotion_when_armed(tmp_path):
    root = tmp_path / "qa"; root.mkdir()
    qa = QAGit.init(root); ops = FileOps(Sandbox.open(root))
    base = qa.head()
    ops.write_text(
        "content/ttl/data/w1.ttl",
        f"@prefix vad: <{VAD}> .\n@prefix schema: <{SCHEMA}> .\n"
        f"<{WORK}w1> a vad:Watercolor ; schema:image <{IMG_BASE}missing.jpg> .\n",
        make_parents=True,
    )
    sot = FilesTransport(tmp_path / "sot")

    # Armed (image_base + image_dir supplied): the dangling ref fails the gate.
    res = run_promotion(
        qa, sot, workflow="entry", base_commit=base, description="dangling image",
        expected_stamp=sot.current_stamp(), image_base=IMG_BASE, image_dir=IMG_DIR,
    )
    assert not res.ok and res.status == "gates_failed"
    ar = [g for g in res.unit.gates if g.name == "asset_reference"]
    assert ar and ar[0].details["absent"] == ["image → missing.jpg"]
    assert not (sot.target / "content/ttl/data/w1.ttl").exists()  # nothing converged


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_not_armed_lets_the_dangling_reference_through(tmp_path):
    """Mutation-discipline mirror of the arming: WITHOUT image_base/image_dir the
    gate never runs and the same dangling reference promotes. This is the
    'authored but never armed' state made explicit as the failure it would be."""
    root = tmp_path / "qa"; root.mkdir()
    qa = QAGit.init(root); ops = FileOps(Sandbox.open(root))
    base = qa.head()
    ops.write_text(
        "content/ttl/data/w1.ttl",
        f"@prefix vad: <{VAD}> .\n@prefix schema: <{SCHEMA}> .\n"
        f"<{WORK}w1> a vad:Watercolor ; schema:image <{IMG_BASE}missing.jpg> .\n",
        make_parents=True,
    )
    sot = FilesTransport(tmp_path / "sot")

    res = run_promotion(
        qa, sot, workflow="entry", base_commit=base, description="dangling image",
        expected_stamp=sot.current_stamp(),  # image_base/image_dir omitted -> not armed
    )
    assert res.ok and res.status == "converged"
    assert [g for g in res.unit.gates if g.name == "asset_reference"] == []
    assert (sot.target / "content/ttl/data/w1.ttl").exists()  # it went through


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_resolving_reference_promotes_when_armed(tmp_path):
    root = tmp_path / "qa"; root.mkdir()
    qa = QAGit.init(root); ops = FileOps(Sandbox.open(root))
    base = qa.head()
    ops.write_bytes("content/images/a.jpg", b"JPEGBYTES", make_parents=True)  # staged -> sidecar
    ops.write_text(
        "content/ttl/data/w1.ttl",
        f"@prefix vad: <{VAD}> .\n@prefix schema: <{SCHEMA}> .\n"
        f"<{WORK}w1> a vad:Watercolor ; schema:image <{IMG_BASE}a.jpg> .\n",
        make_parents=True,
    )
    sot = FilesTransport(tmp_path / "sot")

    res = run_promotion(
        qa, sot, workflow="entry", base_commit=base, description="resolving image",
        expected_stamp=sot.current_stamp(), image_base=IMG_BASE, image_dir=IMG_DIR,
    )
    assert res.ok and res.status == "converged"
    ar = [g for g in res.unit.gates if g.name == "asset_reference"]
    assert ar and ar[0].ok and ar[0].details["resolved"] == 1


# -- schema:video: contentUrl IS gated, thumbnailUrl deliberately is NOT ------


def test_video_content_url_is_gated(tmp_path):
    """The MP4 is really ingested by the dashboard, so a dangling schema:
    contentUrl is the same defect as a dangling schema:image."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    g = Graph(); s = _work(g)
    bn = URIRef("urn:video")
    g.add((s, SCHEMA.video, bn))
    g.add((bn, RDF.type, SCHEMA.VideoObject))
    g.add((bn, SCHEMA.contentUrl, URIRef(IMG_BASE + "Orbit.mp4")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert not r.ok
    assert any("Orbit.mp4" in d for d in r.details["absent"])

    pointer_path_of(tmp_path / IMG_DIR / "Orbit.mp4").write_text("{}")
    r2 = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r2.ok and r2.details["resolved"] == 1


def test_content_url_on_a_WORK_is_not_an_asset_reference(tmp_path):
    """Found against the real store: seven records use schema:contentUrl on the
    work itself to name the site page it appears on. That is not a file
    reference, and gating the property unconditionally — as this gate did when
    contentUrl was first added — would have failed all seven on promotion.

    The property does not carry the meaning; the SUBJECT does. Inside a
    VideoObject it is the MP4; on a work it is a URL to a website.
    """
    (tmp_path / IMG_DIR).mkdir(parents=True)
    g = Graph(); s_ = _work(g)
    g.add((s_, SCHEMA.contentUrl, URIRef("https://www.art.visualartsdna.org/")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.ok, "a site link on a work must not be treated as a missing file"
    assert not r.details["malformed"] and not r.details["absent"]


def test_video_thumbnail_url_is_deliberately_not_gated(tmp_path):
    """A DECIDED omission, pinned so nobody 'fixes' it into a gate.

    The video thumbnail is named by convention but rendered by cwva-py on demand
    when the video first loads. Nothing in this system creates it, so at
    promotion time it correctly does not exist — gating it would fail every
    video entry forever, and the only ways out would be weakening the gate or
    having the dashboard fabricate a file that is not its to make.
    """
    (tmp_path / IMG_DIR).mkdir(parents=True)
    g = Graph(); s = _work(g)
    bn = URIRef("urn:video")
    g.add((s, SCHEMA.video, bn))
    g.add((bn, SCHEMA.thumbnailUrl, URIRef(IMG_BASE + "Orbit_thumbnail.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.ok, "thumbnailUrl must not be gated — cwva-py renders it on demand"
    assert r.details["resolved"] == 0
    assert not r.details["absent"] and not r.details["malformed"]


# -- the document family (entity form, 2026-09-07) ---------------------------

DOC_BASE = "http://visualartsdna.org/documents/"
DOC_DIR = "content/documents"


def _entity_with_doc(prop, name):
    g = Graph()
    s = WORK["e1"]
    g.add((s, THE_MD if prop == "md" else THE_PDF, URIRef(DOC_BASE + name)))
    return g


THE_MD = URIRef("http://visualartsdna.org/thesaurus/mdDocument")
THE_PDF = URIRef("http://visualartsdna.org/thesaurus/pdfDocument")


def test_a_markdown_reference_resolves_as_ORDINARY_GIT_CONTENT(tmp_path):
    """`.md` is in git_content_extensions, so it is present as a REAL FILE with
    no sidecar. Requiring a managed binary — as the image family does — would
    report every markdown reference as malformed."""
    (tmp_path / DOC_DIR).mkdir(parents=True)
    (tmp_path / DOC_DIR / "Analysis.md").write_text("# notes")
    g = _entity_with_doc("md", "Analysis.md")

    r = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR,
        document_base=DOC_BASE, document_dir=DOC_DIR,
    )
    assert r.ok and r.details["resolved"] == 1


def test_a_pdf_reference_resolves_by_its_SIDECAR(tmp_path):
    """`.pdf` is not git content, so it is pointer-managed and the sidecar is
    what git tracks — the same rule as an image."""
    (tmp_path / DOC_DIR).mkdir(parents=True)
    pointer_path_of(tmp_path / DOC_DIR / "Analysis.pdf").write_text("{}")
    g = _entity_with_doc("pdf", "Analysis.pdf")

    r = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR,
        document_base=DOC_BASE, document_dir=DOC_DIR,
    )
    assert r.ok and r.details["resolved"] == 1


def test_a_document_that_never_arrived_is_ABSENT(tmp_path):
    (tmp_path / DOC_DIR).mkdir(parents=True)
    g = _entity_with_doc("md", "Missing.md")

    r = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR,
        document_base=DOC_BASE, document_dir=DOC_DIR,
    )
    assert not r.ok
    assert any("Missing.md" in d for d in r.details["absent"])


def test_documents_are_UNCHECKED_when_the_gate_is_not_armed(tmp_path):
    """Deliberate: a caller that supplies no documents base has no way to
    resolve them, and reporting every document as dangling would be noise. The
    app arms it; a fixture that forgets gets no document checking, which is why
    the entity form's own test asserts a missing document fails there."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    g = _entity_with_doc("md", "Missing.md")

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.ok and r.details["resolved"] == 0


# -- zero-byte: the reference resolves, the asset is unusable ---------------
#
# `documents/CupsStudyCriticism.pdf` sat in production at 0 bytes, cited by
# `work:552759c6...`, while the baseline read "504 resolved, 0 absent, 0
# malformed". An empty file exists, so "resolves" said yes.


def test_a_zero_byte_real_file_is_REPORTED_as_empty(tmp_path):
    (tmp_path / IMG_DIR).mkdir(parents=True)
    (tmp_path / IMG_DIR / "a.jpg").write_bytes(b"")
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "a.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.details["resolved"] == 1, "it still resolves — the file is there"
    assert r.details["empty"] == ["image → a.jpg"]


def test_empty_is_NOT_FATAL_even_when_presence_is_required(tmp_path):
    """Deliberate. The one known instance is in current content, so failing on
    it would stop every promotion until that record is fixed. Flipping this is
    one line in `gates.py` once it is."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    (tmp_path / IMG_DIR / "a.jpg").write_bytes(b"")
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "a.jpg")))

    r = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR, require_present=True
    )
    assert r.ok, "a zero-byte asset reports, it does not block"
    assert "a.jpg" not in " ".join(r.messages)
    assert "ZERO-BYTE" in r.summary, "a finding nobody reads is not a finding"


def test_size_comes_from_the_SIDECAR_when_the_bytes_are_absent(tmp_path):
    """A pointer-managed binary is gitignored, so `stat()` on the asset path
    sees nothing. The sidecar records the size, and that is the only artifact a
    clean tree carries."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    pointer_path_of(tmp_path / IMG_DIR / "a.jpg").write_text(
        '{"sha256": "abc", "size": 0, "created": ""}'
    )
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "a.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.details["empty"] == ["image → a.jpg"]


def test_a_sidecar_recording_real_bytes_is_not_empty(tmp_path):
    (tmp_path / IMG_DIR).mkdir(parents=True)
    pointer_path_of(tmp_path / IMG_DIR / "a.jpg").write_text(
        '{"sha256": "abc", "size": 4, "created": ""}'
    )
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "a.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.ok and r.details["empty"] == []


def test_an_UNREADABLE_sidecar_is_not_reported_as_empty(tmp_path):
    """A broken sidecar is the parse/pointer gate's business. Reporting it here
    as a zero-byte asset would be a wrong answer dressed as a finding."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    pointer_path_of(tmp_path / IMG_DIR / "a.jpg").write_text("{not json")
    g = Graph(); s = _work(g); g.add((s, SCHEMA.image, URIRef(IMG_BASE + "a.jpg")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.details["empty"] == []


def test_the_DOCUMENT_family_is_gated_only_when_ARMED(tmp_path):
    """`scripts/gate_baseline.py` passed no document base or dir, so
    `the:mdDocument` and `the:pdfDocument` were never checked and "baseline
    clean" covered none of them -- 155 references, found when the family was
    armed on 2026-10-29. Same shape as the fixtures CLAUDE.md records: a gate
    built without its arguments silently runs nothing.
    """
    THE = Namespace("http://visualartsdna.org/thesaurus/")
    DOC_BASE, DOC_DIR = "http://visualartsdna.org/documents/", "content/documents"
    (tmp_path / DOC_DIR).mkdir(parents=True)
    (tmp_path / DOC_DIR / "d.pdf").write_bytes(b"")
    g = Graph(); s = _work(g); g.add((s, THE.pdfDocument, URIRef(DOC_BASE + "d.pdf")))

    unarmed = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert unarmed.details["resolved"] == 0 and unarmed.details["empty"] == []

    armed = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR,
        document_base=DOC_BASE, document_dir=DOC_DIR,
    )
    assert armed.details["resolved"] == 1
    assert armed.details["empty"] == ["pdfDocument → d.pdf"]


def test_gate_baseline_ARMS_BOTH_FAMILIES():
    """The operator script is where "baseline clean" gets read, and it armed
    only the image family for months. Checked on the source, because the script
    talks to a real store and cannot be called from here."""
    import ast
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "scripts" / "gate_baseline.py").read_text()
    call = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call)
        and (getattr(n.func, "attr", None) or getattr(n.func, "id", None))
        == "asset_reference_gate"
    )
    passed = {k.arg for k in call.keywords}
    assert {"image_base", "image_dir", "document_base", "document_dir"} <= passed, (
        f"gate_baseline.py arms only {sorted(passed)}; an unarmed family is a "
        "gate that silently checks nothing"
    )


import pathlib  # noqa: E402  (used by the arming test above)


# -- vad:asset: the file a proof anchored ----------------------------------


def test_vad_asset_is_gated(tmp_path):
    """Added 2026-10-31. Twenty-four `vad:ProofEvent` records pointed at real
    .jpg and .glb files and no gate looked at any of them, because this set is
    a hand-kept list and nothing announces a file-valued property missing from
    it. It is the asset reference that matters most: a proof's whole claim is
    about those exact bytes, so a dangling one means the record attests to a
    file the system no longer has."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    (tmp_path / IMG_DIR / "a.glb").write_bytes(b"GLB")
    g = Graph(); s = _work(g)
    g.add((s, VAD.asset, URIRef(IMG_BASE + "a.glb")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.ok and r.details["resolved"] == 1


def test_a_dangling_vad_asset_FAILS(tmp_path):
    (tmp_path / IMG_DIR).mkdir(parents=True)
    g = Graph(); s = _work(g)
    g.add((s, VAD.asset, URIRef(IMG_BASE + "gone.glb")))

    r = asset_reference_gate(
        g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR, require_present=True
    )
    assert not r.ok and r.details["absent"] == ["asset → gone.glb"]


def test_a_zero_byte_vad_asset_is_reported(tmp_path):
    """The combination that found this gap in the first place: the zero-byte
    class was added, reported nothing, and the reason was that `vad:asset` was
    not being looked at."""
    (tmp_path / IMG_DIR).mkdir(parents=True)
    (tmp_path / IMG_DIR / "a.glb").write_bytes(b"")
    g = Graph(); s = _work(g)
    g.add((s, VAD.asset, URIRef(IMG_BASE + "a.glb")))

    r = asset_reference_gate(g, tmp_path, image_base=IMG_BASE, image_dir=IMG_DIR)
    assert r.details["empty"] == ["asset → a.glb"]


def test_a_commons_terms_image_is_reported_never_required(tmp_path):
    """The reference thesaurus cites a swatch per paint, hosted by whoever
    publishes the commons; a new collection holds none of them (2026-11-21)."""
    from rdflib import Graph

    from cwva_dashboard.promotion.gates import asset_reference_gate

    g = Graph()
    g.parse(data="""
        @prefix the: <http://visualartsdna.org/thesaurus/> .
        @prefix schema: <https://schema.org/> .
        the:AzureBlueLCS schema:image <http://visualartsdna.org/images/AzureBlueLCS.jpg> .
        the:Other schema:image <http://elsewhere.example/x.jpg> .
    """, format="turtle")
    r = asset_reference_gate(g, tmp_path, image_base="http://mine.example/images/",
                             image_dir="images")
    assert r.ok
    assert len(r.details["external"]) == 2 and not r.details["malformed"]
    assert "shared model or thesaurus" in r.summary


def test_a_records_own_image_is_still_required(tmp_path):
    from rdflib import Graph

    from cwva_dashboard.promotion.gates import asset_reference_gate

    g = Graph()
    g.parse(data="""
        @prefix work: <http://mine.example/work/> .
        @prefix schema: <https://schema.org/> .
        work:w1 schema:image <http://mine.example/images/Missing.jpg> .
    """, format="turtle")
    r = asset_reference_gate(g, tmp_path, image_base="http://mine.example/images/",
                             image_dir="images")
    assert not r.ok and r.details["absent"]
