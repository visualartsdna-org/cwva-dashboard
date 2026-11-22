"""A new collection's model and vocabulary from the reference server, into
EMPTY folders only (reference_model.py)."""

from __future__ import annotations

import io

from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.reference_model import MODEL_FILE, VOCAB_FILE, fetch_reference_model
from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox

LAYOUT = Layout.from_map({"model_ttl": "metacontent/model", "vocab_ttl": "metacontent/vocab"})
TTL = "@prefix x: <http://x/> .\nx:a x:b x:c .\n"


class _Reply(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(replies, seen):
    def open_(req, timeout=0):
        seen.append((req.full_url, req.get_header("Accept")))
        body = replies[req.full_url]
        if isinstance(body, Exception):
            raise body
        return _Reply(body.encode())
    return open_


def _fo(tmp_path):
    return FileOps(Sandbox.open(tmp_path))


def test_an_empty_collection_gets_both_as_drafts(tmp_path):
    seen = []
    res = fetch_reference_model("https://ref.example/", _fo(tmp_path), LAYOUT, opener=_opener({
        "https://ref.example/schema?format=ttl": TTL, "https://ref.example/vocab": TTL}, seen))
    assert res.ok and len(res.written) == 2
    assert (tmp_path / "metacontent/model" / MODEL_FILE).read_text() == TTL
    assert (tmp_path / "metacontent/vocab" / VOCAB_FILE).read_text() == TTL
    assert all(accept == "text/turtle" for _url, accept in seen)


def test_a_collection_with_a_model_keeps_it(tmp_path):
    (tmp_path / "metacontent/model").mkdir(parents=True)
    (tmp_path / "metacontent/model/mine.ttl").write_text(TTL)
    seen = []
    res = fetch_reference_model("https://ref.example", _fo(tmp_path), LAYOUT, opener=_opener({
        "https://ref.example/vocab": TTL}, seen))
    assert res.skipped == ["metacontent/model"]
    assert [u for u, _ in seen] == ["https://ref.example/vocab"]
    assert not (tmp_path / "metacontent/model" / MODEL_FILE).exists()


def test_a_reply_that_is_not_turtle_writes_nothing(tmp_path):
    res = fetch_reference_model("https://ref.example", _fo(tmp_path), LAYOUT, opener=_opener({
        "https://ref.example/schema?format=ttl": "<html>not found</html>",
        "https://ref.example/vocab": OSError("no network")}, []))
    assert not res.ok and len(res.errors) == 2
    assert not (tmp_path / "metacontent").exists() or not any((tmp_path / "metacontent").rglob("*.ttl"))
