"""QA git wrapper: init + non-nesting guards, commit/HEAD, change manifest
(adds/modifies/deletes), and restore-to (rollback tree)."""

from __future__ import annotations

import shutil

import pytest

from cwva_dashboard.promotion.qa_git import NestingError, QAGit

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _qa(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    return QAGit.init(root)


def test_init_creates_repo_with_base_commit(tmp_path):
    qa = _qa(tmp_path)
    assert (qa.root / ".git").is_dir()
    assert qa.head()  # initial empty commit exists
    assert qa.is_clean()


def test_init_is_idempotent(tmp_path):
    qa = _qa(tmp_path)
    head1 = qa.head()
    qa2 = QAGit.init(qa.root)  # open existing, do not re-init
    assert qa2.head() == head1


def test_refuses_to_nest_inside_existing_repo(tmp_path):
    outer = tmp_path / "outer"
    outer.mkdir()
    QAGit.init(outer)  # outer is now a git repo
    inner = outer / "nested" / "qa"
    inner.mkdir(parents=True)
    with pytest.raises(NestingError):
        QAGit.init(inner)


def test_refuses_overlap_with_project_root(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    qa_inside = project / "sandbox"
    qa_inside.mkdir()
    with pytest.raises(NestingError):
        QAGit.init(qa_inside, project_root=project)


def test_manifest_since_detects_add_modify_delete(tmp_path):
    qa = _qa(tmp_path)
    # unit 1: two files added
    (qa.root / "a.ttl").write_text("A1")
    (qa.root / "b.ttl").write_text("B1")
    base = qa.head()
    m1 = qa.manifest_since(base)
    assert m1.adds == ["a.ttl", "b.ttl"] and not m1.modifies and not m1.deletes
    qa.commit("unit1")

    # unit 2: modify a, delete b, add c
    (qa.root / "a.ttl").write_text("A2")
    (qa.root / "b.ttl").unlink()
    (qa.root / "c.ttl").write_text("C1")
    base2 = qa.head()
    m2 = qa.manifest_since(base2)
    assert m2.adds == ["c.ttl"]
    assert m2.modifies == ["a.ttl"]
    assert m2.deletes == ["b.ttl"]


def test_commit_returns_sha_and_advances_head(tmp_path):
    qa = _qa(tmp_path)
    h0 = qa.head()
    (qa.root / "a.ttl").write_text("x")
    h1 = qa.commit("add a")
    assert h1 != h0
    assert qa.head() == h1


def test_empty_commit_refused(tmp_path):
    qa = _qa(tmp_path)
    with pytest.raises(Exception):
        qa.commit("nothing changed")


def test_restore_to_reverts_tree(tmp_path):
    qa = _qa(tmp_path)
    (qa.root / "a.ttl").write_text("1")
    c1 = qa.commit("state1")

    (qa.root / "a.ttl").write_text("2")
    (qa.root / "b.ttl").write_text("new")
    qa.commit("state2")

    qa.restore_to(c1)
    assert (qa.root / "a.ttl").read_text() == "1"
    assert not (qa.root / "b.ttl").exists()  # file added after c1 is gone
