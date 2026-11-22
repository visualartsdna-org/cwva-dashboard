"""Ported utility tools: rdf.sparql/validate/diff, image.scale/convert,
doc.md_to_html — dispatched through the registry against a FileOps."""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN


@pytest.fixture
def env(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    reg = build_default_registry(domain=TEST_DOMAIN)
    return reg, ops, sb


def _ok(reg, ops, name, **args):
    dr = reg.dispatch(name, args, ops)
    assert dr.ok, dr.error
    return dr.result


DATA_TTL = """
@prefix ex: <http://example.org/> .
ex:w1 a ex:Work ; ex:title "Sunrise" .
ex:w2 a ex:Work .
"""

SHAPES_TTL = """
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
ex:WorkShape a sh:NodeShape ; sh:targetClass ex:Work ;
  sh:property [ sh:path ex:title ; sh:minCount 1 ] .
"""


def test_all_ported_tools_registered(env):
    reg, _, _ = env
    names = set(reg.names())
    assert {"rdf.sparql", "rdf.validate", "rdf.diff", "image.scale", "image.convert", "doc.md_to_html"} <= names


def test_rdf_sparql_select_and_ask(env):
    reg, ops, _ = env
    ops.write_text("d.ttl", DATA_TTL)
    sel = _ok(reg, ops, "rdf.sparql",
              query="PREFIX ex: <http://example.org/> SELECT ?w WHERE { ?w a ex:Work }",
              paths=["d.ttl"])
    assert sel["type"] == "select" and len(sel["rows"]) == 2
    ask = _ok(reg, ops, "rdf.sparql",
              query="PREFIX ex: <http://example.org/> ASK { ?w ex:title 'Sunrise' }",
              paths=["d.ttl"])
    assert ask == {"type": "ask", "boolean": True}


def test_rdf_validate_conformance(env):
    reg, ops, _ = env
    ops.write_text("d.ttl", DATA_TTL)
    ops.write_text("s.ttl", SHAPES_TTL)
    res = reg.dispatch("rdf.validate", {"data_paths": ["d.ttl"], "shapes_paths": ["s.ttl"]}, ops)
    # w2 lacks a title -> non-conformant.
    assert res.ok and res.result["ok"] is False and res.result["stage"] == "shacl"


def test_rdf_diff_is_isomorphic(env):
    reg, ops, _ = env
    ops.write_text("a.ttl", "@prefix ex: <http://example.org/> .\nex:x ex:p [ ex:q 1 ] .\n")
    ops.write_text("b.ttl", "@prefix ex: <http://example.org/> .\nex:x ex:p [ ex:q 1 ] .\n")
    d = _ok(reg, ops, "rdf.diff", path_a="a.ttl", path_b="b.ttl")
    assert d["only_in_a"] == 0 and d["only_in_b"] == 0  # bnode relabel is not a change


def test_image_scale_updates_pointer(env):
    reg, ops, sb = env
    buf = BytesIO()
    Image.new("RGB", (100, 60), (255, 0, 0)).save(buf, format="PNG")
    ops.write_bytes("pic.png", buf.getvalue())

    r = _ok(reg, ops, "image.scale", path="pic.png", factor=0.5)
    assert r["size"] == [50, 30]
    # The written image is real; its .ptr sidecar tracks the new content.
    assert (sb.root / "pic.png.ptr").exists()
    assert Image.open(sb.root / "pic.png").size == (50, 30)


def test_image_convert_png_to_jpeg(env):
    reg, ops, sb = env
    buf = BytesIO()
    Image.new("RGBA", (20, 20), (0, 255, 0, 128)).save(buf, format="PNG")
    ops.write_bytes("pic.png", buf.getvalue())

    r = _ok(reg, ops, "image.convert", path="pic.png", format="JPEG")
    assert r["path"] == "pic.jpg" and r["format"] == "JPEG"
    assert Image.open(sb.root / "pic.jpg").format == "JPEG"


def test_doc_md_to_html(env):
    reg, ops, _ = env
    ops.write_text("n.md", "# Title\n\nSome **bold** text.")
    html = _ok(reg, ops, "doc.md_to_html", path="n.md")["html"]
    assert "<h1>" in html and "<strong>bold</strong>" in html


# Every SPARQL mutation shape. The guard is structural: rdf.sparql uses
# Graph.query(), whose parser accepts only SELECT/ASK/CONSTRUCT/DESCRIBE, so an
# update form cannot parse as a query — regardless of leading comments/PREFIX.
_MUTATIONS = [
    "INSERT DATA { <x:a> <x:b> <x:c> }",
    "DELETE DATA { <x:a> <x:b> <x:c> }",
    "DELETE WHERE { ?s ?p ?o }",
    "DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
    "WITH <http://x/g> DELETE { ?s ?p ?o } WHERE { ?s ?p ?o }",
    "LOAD <http://example.org/g>",
    "CLEAR ALL",
    "DROP GRAPH <http://example.org/g>",
    "CREATE GRAPH <http://example.org/g>",
    "# leading comment\nINSERT DATA { <x:a> <x:b> <x:c> }",
    "PREFIX ex: <http://example.org/>\nINSERT DATA { ex:a ex:b ex:c }",
]


@pytest.mark.parametrize("mutation", _MUTATIONS)
def test_sparql_rejects_every_mutation_shape(env, mutation):
    reg, ops, sb = env
    ops.write_text("d.ttl", DATA_TTL)
    before = (sb.root / "d.ttl").read_text()
    dr = reg.dispatch("rdf.sparql", {"query": mutation, "paths": ["d.ttl"]}, ops)
    assert not dr.ok, f"mutation slipped through: {mutation!r}"
    assert (sb.root / "d.ttl").read_text() == before  # nothing written


def test_sparql_reads_with_leading_comment_and_prefix(env):
    # Control: legitimate read queries with comments/PREFIX still work, proving
    # the rejection above is structural (update forms), not keyword-sniffing.
    reg, ops, _ = env
    ops.write_text("d.ttl", DATA_TTL)
    q = "# a comment\nPREFIX ex: <http://example.org/>\nASK { ?w a ex:Work }"
    assert _ok(reg, ops, "rdf.sparql", query=q, paths=["d.ttl"]) == {"type": "ask", "boolean": True}
