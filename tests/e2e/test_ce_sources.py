"""A CE collection kept in a FOLDER or a GIT repository, end to end (2026-11-21).

The journey a new user takes: a config of the example kind, the first sync
from the source of truth, an entry through the dashboard's own form with an
image from the drop folder, approval, and the result in the source of truth.
Also the two things that make someone's own directory a usable target: what
the dashboard does not manage (cwva-py's thumbnails, the owner's notes) is
neither imported, nor counted as drift, nor committed.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard import config as cfgmod
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.qa_git import QAGit
from cwva_dashboard.promotion.targets import build_transport
from cwva_dashboard.sot_sync.runner import sync_into_qa
from cwva_dashboard.sot_sync.sync import adopt_external

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(shutil.which("git") is None, reason="git not installed"),
]

EXAMPLES = Path(__file__).resolve().parents[2] / "config" / "examples"

MODEL = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
vad:PaintingForm a owl:Class .
vad:Watercolor a owl:Class ; rdfs:subClassOf vad:PaintingForm .
"""
VOCAB = """@prefix vad: <http://visualartsdna.org/model/> .
@prefix the: <http://visualartsdna.org/thesaurus/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
the:TestPaper a vad:WatercolorPaper, skos:Concept ; rdfs:label "Test Paper" .
"""


def _write(root: Path, files: dict):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode())


def _setup(tmp_path, kind: str):
    """A source of truth of `kind` holding a model, a vocabulary, and things the
    dashboard does not manage; a config extending the matching example."""
    if kind == "files":
        sot = tmp_path / "cwva"  # cwva-py's own folder, as folder.rson expects
        model_dir, vocab_dir, unmanaged = "metacontent/model", "metacontent/vocab", {
            "thumbnails/old.jpg": b"thumb", "main/server.py": "code"}
        example = "folder.rson"
    else:
        sot = tmp_path / "content"  # a checkout, as git.rson expects
        model_dir, vocab_dir, unmanaged = "model", "vocab", {"NOTES.md": "mine"}
        example = "git.rson"
    _write(sot, {f"{model_dir}/tiny.ttl": MODEL, f"{vocab_dir}/papers.ttl": VOCAB,
                 **unmanaged})
    if kind == "git":
        _write(sot, {".gitignore": "images/\n"})
        for args in (["init", "-q", "-b", "main"], ["add", "-A"],
                     ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
            subprocess.run(["git", "-C", str(sot), *args], check=True)
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "Morning Light.JPG").write_bytes(b"\xff\xd8morning")
    cfg_path = tmp_path / "config.rson"
    cfg_path.write_text(json.dumps({
        "extends": str(EXAMPLES / example),
        "domain": TEST_DOMAIN, "host": TEST_DOMAIN,
        "reference_model": "",  # the fixture brings its own; no network in tests
        "sandbox": {"stage_root": str(tmp_path / "sandbox")},
        "inbox": {"path": str(drop)},
        "sot": {"path": str(sot)},
    }))
    cfg = cfgmod.load_config(str(cfg_path))
    layout = cfgmod.active_layout(cfg)
    source = build_transport(cfg["sot"], layout, read_only=True)
    qa_root = cfgmod.sandbox_root(cfg)
    report, _ = sync_into_qa(source, qa_root,
                             git_content_extensions=cfgmod.git_content_extensions(cfg))
    adopt_external(QAGit(root=qa_root), message="qa: adopt baseline")
    return sot, cfg_path, cfg, layout, report


@pytest.mark.parametrize("kind", ["files", "git"])
def test_import_brings_in_only_what_the_dashboard_manages(tmp_path, kind):
    sot, _p, cfg, layout, report = _setup(tmp_path, kind)
    qa_root = cfgmod.sandbox_root(cfg)
    imported = {p.relative_to(qa_root).as_posix() for p in qa_root.rglob("*")
                if p.is_file() and ".git" not in p.parts and ".qa" not in p.parts}
    assert any(p.endswith("tiny.ttl") for p in imported)
    assert not any("thumbnails" in p or "server.py" in p or "NOTES" in p
                   for p in imported), imported


@pytest.mark.parametrize("kind", ["files", "git"])
def test_an_entry_reaches_the_source_of_truth(tmp_path, kind):
    sot, cfg_path, cfg, layout, _r = _setup(tmp_path, kind)
    app = create_app(config_path=str(cfg_path), enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        assert app.state.promotion_driver is not None, "the target was not built"
        html = c.get("/rdf/entry").text
        guid = re.search(r'name="guid" value="([^"]+)"', html).group(1)
        r = c.post("/rdf/entry", data={
            "guid": guid, "type": "Watercolor", "label": "Morning Light",
            "description": "d", "height": "10", "width": "8", "units": "inch",
            "recorded_date": "2026-11-21", "completed_date": "2026-11-20",
            "has_paper": "the:TestPaper", "has_artist_profile": "work:abc",
            "image": "Morning Light.JPG"})
        assert "Gates failed" not in r.text, r.text[:2000]
        # cwva-py makes a thumbnail meanwhile: not drift, must not block approval
        (sot / "thumbnails").mkdir(exist_ok=True)
        (sot / "thumbnails" / "new.jpg").write_bytes(b"made by cwva-py")
        token = re.search(r'action="/rdf/entry/approve".*?name="token" value="([^"]+)"',
                          r.text, re.S).group(1)
        a = c.post("/rdf/entry/approve", data={"token": token})
        assert "converged" in a.text, a.text[:2000]

    data_dir, image_dir = layout.dir("work_ttl"), layout.dir("image")
    assert (sot / data_dir / f"{guid}.ttl").is_file()
    assert (sot / image_dir / "MorningLight.jpg").read_bytes() == b"\xff\xd8morning"
    assert (sot / image_dir / f"qrc_{guid}.jpg").is_file()
    assert (sot / "thumbnails" / "new.jpg").is_file()  # left alone
    if kind == "git":
        committed = subprocess.run(["git", "-C", str(sot), "show", "--name-only",
                                    "--format="], capture_output=True, text=True).stdout
        assert f"{data_dir}/{guid}.ttl" in committed
        assert "images/" not in committed  # ignored by the repository: in place, uncommitted
        status = subprocess.run(["git", "-C", str(sot), "status", "--porcelain"],
                                capture_output=True, text=True).stdout
        assert "operational" not in status and "NOTES.md" not in status


def test_the_examples_ship_without_a_domain_so_none_is_assumed():
    for name in ("folder", "git", "gcp"):
        cfg = cfgmod.load_config(str(EXAMPLES / f"{name}.rson"))
        with pytest.raises(ValueError, match="domain"):
            cfgmod.domain(cfg)
