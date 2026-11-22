"""Shadow-SOT seeding: read-only source, batched clone, honest report."""

from __future__ import annotations

import pytest

from cwva_dashboard.promotion.transports import (
    FilesTransport,
    GcpBucketTransport,
    ReadOnlySource,
    Transport,
)
from cwva_dashboard.promotion.unit import ChangeManifest
from cwva_dashboard.sot_sync.clone import clone_source_to_target


def _seeded_files_transport(tmp_path, name="prod", files=None):
    t = FilesTransport(tmp_path / name)
    files = files or {
        "ttl/data/w1.ttl": b"<a> <b> <c> .",
        "ttl/model/cwva.ttl": b"model",
        "documents/note.md": b"note",
        "images/a.jpg": b"JPEGBYTES",
    }
    for rel, data in files.items():
        p = t.target / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    return t


# -- ReadOnlySource ---------------------------------------------------------


def test_read_only_source_cannot_be_a_converge_target(tmp_path):
    """The §2e guarantee: structural, not a runtime name check."""
    source = ReadOnlySource(_seeded_files_transport(tmp_path), label="production")

    assert not hasattr(source, "converge")
    assert not isinstance(source, Transport)
    with pytest.raises(AttributeError):
        source.converge(tmp_path, ChangeManifest(adds=["x"]))


def test_read_only_source_passes_reads_through(tmp_path):
    inner = _seeded_files_transport(tmp_path)
    source = ReadOnlySource(inner, label="production")

    assert source.snapshot() == inner.snapshot()
    assert source.fetch("documents/note.md") == b"note"
    assert source.current_stamp() == inner.current_stamp()
    assert source.name == "readonly:production"


def test_clone_refuses_a_writable_source(tmp_path):
    """Passing a live Transport as the source must fail loudly, not silently
    clone from something that could equally be written to."""
    with pytest.raises(TypeError):
        clone_source_to_target(
            _seeded_files_transport(tmp_path),  # a Transport, not a ReadOnlySource
            FilesTransport(tmp_path / "shadow"),
            tmp_path / "staging",
        )


# -- the clone --------------------------------------------------------------


def test_clone_copies_every_object(tmp_path):
    source = ReadOnlySource(_seeded_files_transport(tmp_path))
    shadow = FilesTransport(tmp_path / "shadow")

    report = clone_source_to_target(source, shadow, tmp_path / "staging")

    assert report.objects == 4 and report.source_objects == 4
    assert not report.failures
    assert set(shadow.snapshot()) == {
        "ttl/data/w1.ttl",
        "ttl/model/cwva.ttl",
        "documents/note.md",
        "images/a.jpg",
    }
    assert shadow.fetch("images/a.jpg") == b"JPEGBYTES"
    assert report.bytes_copied == sum(
        len(x) for x in (b"<a> <b> <c> .", b"model", b"note", b"JPEGBYTES")
    )


def test_clone_batches_and_does_not_retain_staging(tmp_path):
    """Peak disk must not scale with the SOT: batches flush and staging goes."""
    files = {f"ttl/data/w{i}.ttl": b"x" * 100 for i in range(25)}
    source = ReadOnlySource(_seeded_files_transport(tmp_path, files=files))
    shadow = FilesTransport(tmp_path / "shadow")

    seen = []
    report = clone_source_to_target(
        source,
        shadow,
        tmp_path / "staging",
        batch_objects=10,
        progress=lambda r: seen.append(r.objects),
    )

    assert report.objects == 25
    assert report.batches == 3  # 10 + 10 + 5
    assert seen == [10, 20, 25]
    assert not (tmp_path / "staging").exists()
    assert len(shadow.snapshot()) == 25


def test_clone_include_filter_records_what_it_skipped(tmp_path):
    """The report describes the shadow's real contents, not an intention."""
    source = ReadOnlySource(_seeded_files_transport(tmp_path))
    shadow = FilesTransport(tmp_path / "shadow")

    report = clone_source_to_target(
        source,
        shadow,
        tmp_path / "staging",
        include=lambda rel: not rel.startswith("images/"),
    )

    assert report.objects == 3
    assert report.skipped == ["images/a.jpg"]
    assert "images/a.jpg" not in shadow.snapshot()


def test_clone_records_a_failure_and_continues(tmp_path):
    """One unreadable blob must not discard everything already transferred."""
    inner = _seeded_files_transport(tmp_path)

    class _Flaky(ReadOnlySource):
        def fetch(self, path):
            if path == "images/a.jpg":
                raise OSError("simulated read failure")
            return super().fetch(path)

    shadow = FilesTransport(tmp_path / "shadow")
    report = clone_source_to_target(_Flaky(inner), shadow, tmp_path / "staging")

    assert report.objects == 3
    assert len(report.failures) == 1 and "images/a.jpg" in report.failures[0]
    assert len(shadow.snapshot()) == 3


# -- bucket-shaped source ---------------------------------------------------


class _FakeBlob:
    def __init__(self, store, name):
        self._store, self.name = store, name

    def upload_from_filename(self, path):
        with open(path, "rb") as fh:
            self._store[self.name] = fh.read()

    def delete(self):
        del self._store[self.name]

    def download_as_bytes(self):
        return self._store[self.name]

    @property
    def md5_hash(self):
        import hashlib

        return hashlib.md5(self._store[self.name]).hexdigest()


class _FakeBucket:
    def __init__(self):
        self.store = {}

    def blob(self, name):
        return _FakeBlob(self.store, name)

    def list_blobs(self, prefix=None):
        for name in list(self.store):
            if prefix is None or name.startswith(prefix):
                yield _FakeBlob(self.store, name)


def test_folder_placeholders_never_enter_a_snapshot():
    """Zero-byte `dir/` objects are console artifacts naming no content. The
    production bucket has ten; a snapshot containing one would make sync write a
    file where a directory belongs, and show phantom drift forever."""
    bucket = _FakeBucket()
    bucket.store.update(
        {
            "ttl/": b"",
            "ttl/data/": b"",
            "ttl/data/w1.ttl": b"real content",
            "documents/": b"",
        }
    )
    t = GcpBucketTransport(bucket)

    assert set(t.snapshot()) == {"ttl/data/w1.ttl"}
    stamp_with_placeholders = t.current_stamp()
    for k in ("ttl/", "ttl/data/", "documents/"):
        del bucket.store[k]
    assert t.current_stamp() == stamp_with_placeholders  # they never counted


def test_clone_into_a_prefixed_bucket_shadow(tmp_path):
    """The real shape: production -> `shadow-sot/` prefix on another bucket."""
    prod = _FakeBucket()
    prod.store.update({"ttl/data/w1.ttl": b"work", "images/a.jpg": b"IMG", "ttl/": b""})
    source = ReadOnlySource(GcpBucketTransport(prod), label="production")

    test_bucket = _FakeBucket()
    shadow = GcpBucketTransport(test_bucket, prefix="shadow-sot")

    report = clone_source_to_target(source, shadow, tmp_path / "staging")

    assert report.objects == 2  # the placeholder was never offered
    assert set(test_bucket.store) == {
        "shadow-sot/ttl/data/w1.ttl",
        "shadow-sot/images/a.jpg",
    }
    # The shadow reads back at SOT-relative paths; the prefix is transport-internal.
    assert set(shadow.snapshot()) == {"ttl/data/w1.ttl", "images/a.jpg"}
    assert shadow.fetch("images/a.jpg") == b"IMG"


def test_legitimately_empty_files_survive_the_placeholder_filter():
    """The predicate is the trailing slash, not the size. An empty file is real
    content; dropping it would cause phantom absence — sync deleting a file that
    exists, converge re-uploading it forever."""
    bucket = _FakeBucket()
    bucket.store.update(
        {
            "ttl/": b"",  # console placeholder: filtered
            "content/.gitkeep": b"",  # legitimately empty file: kept
            "content/truncated.ttl": b"",  # empty by accident: still real
            "content/w1.ttl": b"data",
        }
    )
    t = GcpBucketTransport(bucket)

    assert set(t.snapshot()) == {
        "content/.gitkeep",
        "content/truncated.ttl",
        "content/w1.ttl",
    }
    assert t.fetch("content/truncated.ttl") == b""
