"""One builder for every kind of source of truth (promotion/targets.py)."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.layout import Layout
from cwva_dashboard.promotion.targets import TargetError, build_transport, managed_dirs
from cwva_dashboard.promotion.transports import (FilesTransport, GitLocalTransport,
                                                 GitRemoteTransport, ReadOnlySource)

FOLDER = Layout.from_map({
    "work_ttl": "content/data", "entity_ttl": "content/data", "digital_ttl": "content/data",
    "proof_ttl": "content/data", "provenance_ttl": "content/provenance",
    "tags_ttl": "content/tags", "model_ttl": "metacontent/model",
    "vocab_ttl": "metacontent/vocab", "image": "content/images",
    "thumbnail": "thumbnails", "document": "content/documents"})


def test_managed_dirs_leave_out_thumbnails_and_nested_dirs():
    assert managed_dirs(FOLDER) == ["content/data", "content/documents", "content/images",
                                    "content/provenance", "content/tags",
                                    "metacontent/model", "metacontent/vocab"]
    nested = Layout.from_map({"work_ttl": "ttl", "tags_ttl": "ttl/tags"})
    assert "ttl/tags" not in managed_dirs(nested)


def test_a_folder_target(tmp_path):
    t = build_transport({"transport": "files", "path": str(tmp_path)}, FOLDER)
    assert isinstance(t, FilesTransport) and t.include == tuple(managed_dirs(FOLDER))


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_git_targets(tmp_path):
    t = build_transport({"transport": "git_local", "path": str(tmp_path / "a")}, FOLDER)
    assert isinstance(t, GitLocalTransport) and (tmp_path / "a" / ".git").exists()
    r = build_transport({"transport": "git_remote", "path": str(tmp_path / "b"),
                         "remote": "up", "branch": "trunk"}, FOLDER)
    assert isinstance(r, GitRemoteTransport) and (r.remote, r.branch) == ("up", "trunk")


def test_read_only_has_no_converge_and_wants_the_source_to_exist(tmp_path):
    src = build_transport({"transport": "files", "path": str(tmp_path)}, FOLDER, read_only=True)
    assert isinstance(src, ReadOnlySource) and not hasattr(src, "converge")
    with pytest.raises(TargetError, match="does not exist"):
        build_transport({"transport": "files", "path": str(tmp_path / "nope")}, FOLDER,
                        read_only=True)
    with pytest.raises(TargetError, match="not a git checkout"):
        build_transport({"transport": "git_local", "path": str(tmp_path)}, FOLDER,
                        read_only=True)


@pytest.mark.parametrize("target,why", [
    ({"transport": "ftp"}, "unknown transport"),
    ({"transport": "files"}, "needs a 'path'"),
    ({"transport": "gcp_bucket", "bucket_env": "NO_SUCH_BUCKET_VAR"}, "not set"),
])
def test_a_bad_target_says_what_to_fix(target, why, monkeypatch):
    monkeypatch.delenv("NO_SUCH_BUCKET_VAR", raising=False)
    with pytest.raises(TargetError, match=why):
        build_transport(target, FOLDER)
