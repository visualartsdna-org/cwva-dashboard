"""The Files tab's utilities: syntax checks and Markdown to HTML. A file
handed to them is never stored (2026-11-19)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import TEST_DOMAIN
from cwva_dashboard.main import create_app
from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.tools.check_tools import check_syntax

GOOD_TTL = "@prefix x: <http://x/> .\nx:a x:b x:c ; x:d [ x:e 1 ] .\n"
BAD_TTL = '@prefix x: <http://x/> .\nx:a x:b x:c .\nx:d x:e "open .\nx:f x:g x:h .\n'


@pytest.fixture
def env(tmp_path):
    root = tmp_path / "qa"
    (root / Layout.default().dir("work_ttl")).mkdir(parents=True)
    app = create_app(domain=TEST_DOMAIN, sandbox_root=root, enforce_landlock=False,
                     audit_path=tmp_path / "audit.jsonl")
    with TestClient(app) as c:
        yield c, root


def _files(root):
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def test_well_formed_turtle_is_counted():
    r = check_syntax(GOOD_TTL, "turtle")
    assert r["ok"] and r["triples"] == 3 and r["subjects"] == 1 and r["prefixes"] == ["x"]


def test_a_turtle_error_names_its_line_and_shows_it():
    r = check_syntax(BAD_TTL, "turtle")
    assert not r["ok"]
    assert r["error"]["line"] == 3
    assert "string literal" in r["error"]["message"]
    assert [c["n"] for c in r["error"]["context"] if c["here"]] == [3]


def test_an_error_at_the_end_points_at_a_real_line():
    r = check_syntax("@prefix x: <http://x/> .\nx:a x:b\n", "turtle")
    assert not r["ok"] and 1 <= r["error"]["line"] <= 3


def test_a_json_error_names_line_and_column():
    r = check_syntax('{\n  "a": 1,\n  "b": \n}', "json")
    assert not r["ok"] and r["error"]["line"] == 4 and r["error"]["column"] == 1
    ok = check_syntax('[1, 2, 3]', "json")
    assert ok["ok"] and ok["top"] == "list" and ok["size"] == 3


def test_the_check_page_reports_and_stores_nothing(env):
    c, root = env
    before = _files(root)
    page = c.post("/check", files={"fileupload": ("bad.ttl", BAD_TTL)}).text
    assert "Not well-formed Turtle" in page and "line 3" in page and "bad.ttl" in page
    page = c.post("/check", files={"fileupload": ("good.ttl", GOOD_TTL)}).text
    assert "Well-formed Turtle" in page and "3 triples" in page
    page = c.post("/check", files={"fileupload": ("a.json", '{"a": [1,2]}')}).text
    assert "Well-formed JSON" in page and "an object of 1 item" in page
    assert _files(root) == before


XML_BAD = ('<?xml version="1.0"?>\n<rdf:RDF xmlns:rdf="http://www.w3.org/1999/'
           '02/22-rdf-syntax-ns#">\n<rdf:Description rdf:about="http://x/a">\n<bad\n</rdf:RDF>')


@pytest.mark.parametrize("name,text,verdict,line", [
    ("m.owl", XML_BAD, "Not well-formed RDF/XML", 5),
    ("m.rdf", XML_BAD, "Not well-formed RDF/XML", 5),
    ("d.nt", "<http://x/a> <http://x/b> <http://x/c> .\n<http://x/a> <http://x/b> .\n",
     "Not well-formed N-Triples", 2),
    ("d.jsonld", '{"@id": "http://x/a",\n "http://x/b": [{"@value": 1}]',
     "Not well-formed JSON-LD", 2),
    ("g.trig", "@prefix x: <http://x/> .\nx:g { x:a x:b x:c . }\n",
     "Well-formed TriG", None),
    ("q.nq", "<http://x/a> <http://x/b> <http://x/c> <http://x/g> .\n",
     "Well-formed N-Quads", None),
])
def test_the_extension_picks_the_parser(env, name, text, verdict, line):
    c, _root = env
    page = c.post("/check", files={"fileupload": (name, text)}).text
    assert verdict in page
    if line:
        assert f"line {line}" in page


def test_an_unknown_extension_names_the_ones_it_takes(env):
    c, _root = env
    page = c.post("/check", files={"fileupload": ("a.csv", "x,y")}).text
    assert "cannot tell the format" in page and ".ttl" in page and ".jsonld" in page


def test_a_binary_file_is_refused_politely(env):
    c, _root = env
    page = c.post("/check", files={"fileupload": ("x.json", b"\xff\xfe\x00")}).text
    assert "not UTF-8" in page


def test_the_drop_zone_accepts_exactly_the_extensions_the_route_knows(env):
    """Offered == enforced."""
    import re

    from cwva_dashboard.tools.check_tools import EXTENSIONS

    c, _root = env
    form = re.search(r'<form id="checkSyntax".*?</form>', c.get("/").text, re.S).group(0)
    for attr in ("data-accept", "accept"):
        offered = re.search(rf' {attr}="([^"]+)"', form).group(1).split(",")
        assert sorted(offered) == sorted(EXTENSIONS), attr


def test_markdown_is_displayed_not_downloaded(env):
    c, root = env
    before = _files(root)
    r = c.post("/md2html", files={"fileupload": ("Lepers Notes.md", "# Lepers\n\nA *hearth*.")})
    assert r.status_code == 200
    assert "content-disposition" not in r.headers  # shown in the tab, no file
    assert "<title>Lepers</title>" in r.text and "<em>hearth</em>" in r.text
    assert r.headers.get("x-cwva-no-banner") == "1"  # a document, not a page
    assert _files(root) == before


def test_the_markdown_form_opens_a_new_tab(env):
    import re

    c, _root = env
    form = re.search(r'<form id="cvtForm"[^>]*>', c.get("/").text).group(0)
    assert 'target="_blank"' in form


def test_the_hub_forms_point_at_the_routes(env):
    c, _root = env
    hub = c.get("/").text
    for action, title in (("/check", "Syntax Check RDF/JSON"),
                          ("/md2html", "Markdown to HTML")):
        assert f'action="{action}"' in hub and title in hub


def test_an_awkward_filename_still_makes_a_valid_header(env):
    c, _root = env
    r = c.post("/image/convert", data={"format": "PNG"},
               files={"fileupload": ('Café "draft".png', _png())})
    cd = r.headers["content-disposition"]
    value = cd.removeprefix('attachment; filename="').removesuffix('"')
    assert cd.isascii() and '"' not in value
    assert value.startswith("Caf_") and value.endswith(".png")


# -- Scale Image / Convert Image ------------------------------------------------

def _png(w=40, h=20, mode="RGBA"):
    from io import BytesIO

    from PIL import Image

    buf = BytesIO()
    Image.new(mode, (w, h), (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(
        buf, format="PNG")
    return buf.getvalue()


def _open(data):
    from io import BytesIO

    from PIL import Image

    return Image.open(BytesIO(data))


def test_scale_downloads_the_resized_image_named_with_its_size(env):
    c, root = env
    before = _files(root)
    r = c.post("/image/scale", data={"scale": "0.5"},
               files={"fileupload": ("Hearth.png", _png())})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="Hearth-20x10.png"'
    assert _open(r.content).size == (20, 10) and _open(r.content).format == "PNG"
    assert _files(root) == before


def test_convert_downloads_the_new_format_and_drops_alpha_for_jpeg(env):
    c, _root = env
    r = c.post("/image/convert", data={"format": "JPG"},
               files={"fileupload": ("Hearth.png", _png())})
    assert r.headers["content-disposition"] == 'attachment; filename="Hearth.jpg"'
    img = _open(r.content)
    assert img.format == "JPEG" and img.mode == "RGB"


@pytest.mark.parametrize("data,files,why", [
    ({"scale": "abc"}, ("a.png", None), "must be a number"),
    ({"scale": "0"}, ("a.png", None), "above 0"),
    ({"scale": "0.5"}, ("a.png", b"not an image"), "not an image"),
])
def test_scale_refusals_explain_themselves(env, data, files, why):
    c, _root = env
    name, body = files
    r = c.post("/image/scale", data=data, files={"fileupload": (name, body or _png())})
    assert r.status_code == 400 and why in r.text


def test_convert_refuses_a_format_it_cannot_write(env):
    c, _root = env
    r = c.post("/image/convert", data={"format": "SVG"},
               files={"fileupload": ("a.png", _png())})
    assert r.status_code == 400


def test_the_convert_form_offers_exactly_what_the_tool_accepts(env):
    """Offered == enforced (CLAUDE.md testing rule)."""
    import re

    from cwva_dashboard.tools.image_tools import CONVERT_FORMATS

    c, _root = env
    hub = c.get("/").text
    form = re.search(r'<form id="convertForm".*?</form>', hub, re.S).group(0)
    assert re.findall(r'<option value="([^"]+)"', form) == CONVERT_FORMATS
    assert 'action="/image/scale"' in hub and 'action="/image/convert"' in hub
