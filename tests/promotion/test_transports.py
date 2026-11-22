"""Transport adapters: convergence with adds/modifies/deletes, stamp behavior,
idempotency — across all four fixture targets (files, git_local, git_remote via
a bare repo, gcp via a fake bucket)."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from cwva_dashboard.promotion.transports import (
    FilesTransport,
    GcpBucketTransport,
    GitLocalTransport,
    GitRemoteTransport,
)
from cwva_dashboard.promotion.unit import ChangeManifest

_git_missing = shutil.which("git") is None


@pytest.fixture
def content(tmp_path):
    """A QA content tree with three files."""
    root = tmp_path / "qa"
    root.mkdir()
    (root / "a.ttl").write_text("A1")
    (root / "sub").mkdir()
    (root / "sub" / "b.ttl").write_text("B1")
    (root / "c.ttl").write_text("C1")
    return root


# -- FilesTransport ---------------------------------------------------------

def test_files_converge_adds_and_layout(tmp_path, content):
    t = FilesTransport(tmp_path / "sot")
    m = ChangeManifest(adds=["a.ttl", "sub/b.ttl", "c.ttl"])
    r = t.converge(content, m)
    assert (t.target / "a.ttl").read_text() == "A1"
    assert (t.target / "sub" / "b.ttl").read_text() == "B1"
    assert r.stamp == t.current_stamp()


def test_files_converge_modify_and_delete(tmp_path, content):
    t = FilesTransport(tmp_path / "sot")
    t.converge(content, ChangeManifest(adds=["a.ttl", "sub/b.ttl", "c.ttl"]))
    stamp1 = t.current_stamp()

    (content / "a.ttl").write_text("A2")
    (content / "c.ttl").unlink()
    t.converge(content, ChangeManifest(modifies=["a.ttl"], deletes=["c.ttl"]))

    assert (t.target / "a.ttl").read_text() == "A2"
    assert not (t.target / "c.ttl").exists()
    assert t.current_stamp() != stamp1


def test_files_converge_is_idempotent(tmp_path, content):
    t = FilesTransport(tmp_path / "sot")
    m = ChangeManifest(adds=["a.ttl", "sub/b.ttl", "c.ttl"])
    s1 = t.converge(content, m).stamp
    s2 = t.converge(content, m).stamp  # same manifest again
    assert s1 == s2


def test_files_delete_prunes_empty_dirs(tmp_path, content):
    t = FilesTransport(tmp_path / "sot")
    t.converge(content, ChangeManifest(adds=["sub/b.ttl"]))
    assert (t.target / "sub").is_dir()
    (content / "sub" / "b.ttl").unlink()
    t.converge(content, ChangeManifest(deletes=["sub/b.ttl"]))
    assert not (t.target / "sub").exists()


# -- GitLocalTransport ------------------------------------------------------

@pytest.mark.skipif(_git_missing, reason="git not installed")
def test_git_local_commits_and_stamp_is_head(tmp_path, content):
    t = GitLocalTransport(tmp_path / "sot")
    r = t.converge(content, ChangeManifest(adds=["a.ttl", "sub/b.ttl"]), message="promote 1")
    assert (t.target / "a.ttl").read_text() == "A1"
    assert r.stamp == t.current_stamp()  # stamp == HEAD
    log = subprocess.run(
        ["git", "-C", str(t.target), "log", "--oneline"], capture_output=True, text=True
    ).stdout
    assert "promote 1" in log


@pytest.mark.skipif(_git_missing, reason="git not installed")
def test_git_local_delete_removes_tracked_file(tmp_path, content):
    t = GitLocalTransport(tmp_path / "sot")
    t.converge(content, ChangeManifest(adds=["a.ttl", "c.ttl"]), message="add")
    (content / "c.ttl").unlink()
    t.converge(content, ChangeManifest(deletes=["c.ttl"]), message="del")
    assert not (t.target / "c.ttl").exists()
    tracked = subprocess.run(
        ["git", "-C", str(t.target), "ls-files"], capture_output=True, text=True
    ).stdout
    assert "c.ttl" not in tracked


# -- GitRemoteTransport -----------------------------------------------------

@pytest.mark.skipif(_git_missing, reason="git not installed")
def test_git_remote_pushes_to_bare_repo(tmp_path, content):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    local = tmp_path / "sot"
    t = GitRemoteTransport(local, remote="origin", branch="main")
    subprocess.run(["git", "-C", str(local), "remote", "add", "origin", str(bare)], check=True)

    r = t.converge(content, ChangeManifest(adds=["a.ttl"]), message="promote remote")
    # The bare remote received the commit.
    remote_head = subprocess.run(
        ["git", "-C", str(bare), "rev-parse", "main"], capture_output=True, text=True
    ).stdout.strip()
    # the stamp is the commit AND the working tree (2026-11-21); the commit
    # half is what was pushed
    assert remote_head == r.detail["commit"] == r.stamp.split(":", 1)[0]
    assert r.detail["pushed"] == "origin/main"


# -- GcpBucketTransport (fake bucket) ---------------------------------------

class _FakeBlob:
    def __init__(self, store, name):
        self._store = store
        self.name = name

    def upload_from_filename(self, path):
        with open(path, "rb") as fh:
            self._store[self.name] = fh.read()

    def delete(self):
        if self.name not in self._store:
            raise KeyError(self.name)
        del self._store[self.name]

    @property
    def md5_hash(self):
        import hashlib

        return hashlib.md5(self._store[self.name]).hexdigest()


class _FakeBucket:
    def __init__(self):
        self.store: dict[str, bytes] = {}

    def blob(self, name):
        return _FakeBlob(self.store, name)

    def list_blobs(self, prefix=None):
        for name in list(self.store):
            if prefix is None or name.startswith(prefix):
                yield _FakeBlob(self.store, name)


def test_gcp_bucket_upload_delete_and_stamp(tmp_path, content):
    bucket = _FakeBucket()
    t = GcpBucketTransport(bucket, prefix="site")

    t.converge(content, ChangeManifest(adds=["a.ttl", "sub/b.ttl"]))
    assert bucket.store["site/a.ttl"] == b"A1"
    assert "site/sub/b.ttl" in bucket.store
    s1 = t.current_stamp()

    (content / "a.ttl").unlink()
    t.converge(content, ChangeManifest(deletes=["a.ttl"]))
    assert "site/a.ttl" not in bucket.store
    assert t.current_stamp() != s1


def test_gcp_delete_missing_is_idempotent(tmp_path, content):
    bucket = _FakeBucket()
    t = GcpBucketTransport(bucket)
    # Deleting something never uploaded must not raise.
    t.converge(content, ChangeManifest(deletes=["ghost.ttl"]))


# -- a folder or git SOT is someone's own directory (2026-11-21) -------------

def _files(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def test_a_scoped_folder_sot_sees_only_what_it_manages(tmp_path):
    root = tmp_path / "cwva"
    _files(root, {"content/data/a.ttl": "a", "thumbnails/x.jpg": "t", "README.md": "r",
                  "main/server.py": "code"})
    t = FilesTransport(root, include=["content/data", "content/images"])
    assert set(t.snapshot()) == {"content/data/a.ttl"}
    before = t.current_stamp()
    _files(root, {"thumbnails/y.jpg": "new thumbnail", "README.md": "edited"})
    assert t.current_stamp() == before  # not drift
    _files(root, {"content/data/a.ttl": "hand edit"})
    assert t.current_stamp() != before  # drift


def test_git_drift_includes_an_uncommitted_hand_edit(tmp_path, content):
    t = GitLocalTransport(tmp_path / "sot", include=["a.ttl", "data"])
    t.converge(content, ChangeManifest(adds=["a.ttl"]), message="first")
    before = t.current_stamp()
    (tmp_path / "sot" / "a.ttl").write_text("edited by hand, not committed")
    assert t.current_stamp() != before


def test_git_commits_only_what_the_distribution_changed(tmp_path, content):
    sot = tmp_path / "sot"
    t = GitLocalTransport(sot, include=["a.ttl", "data"])
    _files(sot, {"NOTES.md": "the owner's, uncommitted"})
    t.converge(content, ChangeManifest(adds=["a.ttl"]), message="promote")
    committed = subprocess.run(["git", "-C", str(sot), "show", "--name-only", "--format="],
                               capture_output=True, text=True).stdout.split()
    assert committed == ["a.ttl"]
    status = subprocess.run(["git", "-C", str(sot), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert "NOTES.md" in status  # left exactly as it was


def test_git_leaves_an_ignored_path_in_place_but_uncommitted(tmp_path):
    content = tmp_path / "qa"
    _files(content, {"images/big.jpg": "pixels", "data/w.ttl": "w"})
    sot = tmp_path / "sot"
    t = GitLocalTransport(sot, include=["images", "data"])
    _files(sot, {".gitignore": "images/\n"})
    t.converge(content, ChangeManifest(adds=["images/big.jpg", "data/w.ttl"]), message="p")
    assert (sot / "images/big.jpg").read_text() == "pixels"
    committed = subprocess.run(["git", "-C", str(sot), "show", "--name-only", "--format="],
                               capture_output=True, text=True).stdout.split()
    assert committed == ["data/w.ttl"]


def test_git_backups_sit_beside_the_checkout_never_in_its_history(tmp_path, content):
    sot = tmp_path / "sot"
    t = GitLocalTransport(sot, include=["a.ttl"])
    t.put_operational("operational/qa-ledger.ttl", b"ledger")
    assert (sot / "operational/qa-ledger.ttl").read_bytes() == b"ledger"
    status = subprocess.run(["git", "-C", str(sot), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    assert "operational" not in status
