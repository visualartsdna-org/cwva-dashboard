"""QA-side git — system of record for history and rollback (CE_DESIGN §3.4).

A private git repo over the QA content tree inside the sandbox. Invisible to
the user, zero setup, no requirement that their SOT be git-able. Each promotion
is a commit here; rollback is a revert here; the file-level change manifest and
drift detection come from git here. After a successful transport push, QA HEAD
≡ SOT state.

**This is dashboard machinery, never an agent tool** (CLAUDE.md law 6). It runs
in the orchestrator, drives the `git` binary via subprocess with a fixed
identity, and refuses to operate anywhere it would nest with another repo —
in particular the project repo (§3.4): the QA repo and the project repo have
separate histories and must never overlap.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from ..sandbox.pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, POINTER_SUFFIX
from .unit import ChangeManifest, is_local_only

__all__ = ["QAGit", "QAGitError", "NestingError"]

_AUTHOR_NAME = "cwva-dashboard"
_AUTHOR_EMAIL = "dashboard@localhost"

# Defense in depth for the QA repo, whose working tree IS the agent's sandbox.
# Layer 1 refuses to resolve .git/** at all, so a hook cannot be planted through
# the tool surface; these flags mean a hook that somehow exists still never runs.
# That second layer matters more here than elsewhere: hooks execute in the
# *orchestrator*, which is not Landlock-confined, so unlike a path escape this
# class has no OS-level backstop.
#
# hooksPath is pointed at a path that is not a directory containing hooks on
# either target: on Linux /dev/null exists but is not a directory, on Windows it
# does not exist. Either way git finds no hooks. These apply to the QA repo only
# — a user's own SOT repo (git_local/git_remote transports) keeps its hooks,
# since those are the user's machinery, not ours.
_HARDENING = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")


class QAGitError(RuntimeError):
    """A git invocation failed."""


class NestingError(QAGitError):
    """The QA repo root would nest with another git repo (e.g. the project
    repo). Refused per CE_DESIGN §3.4."""


@dataclass(frozen=True)
class QAGit:
    root: Path

    # -- construction / guards ---------------------------------------------

    @classmethod
    def init(
        cls,
        root: str | Path,
        *,
        project_root: str | Path | None = None,
        git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
    ) -> "QAGit":
        """Initialize (or open) the QA repo at ``root``, asserting it does not
        nest with any other git repo. If ``project_root`` is given, also assert
        the two trees are disjoint. The initial commit lays down a ``.gitignore``
        that ignores QA-internal state (``/.qa/``) and pointer-managed binaries,
        so ``git add -A`` tracks the ``.ptr`` sidecars but never the binaries
        themselves (CE_DESIGN §3.4)."""
        root = Path(root).resolve()
        if not root.is_dir():
            raise QAGitError(f"QA repo root is not a directory: {root}")

        _assert_not_nested(root, project_root)

        repo = cls(root=root)
        if not (root / ".git").exists():
            repo._run("init", "-q")
            (root / ".gitignore").write_text(_gitignore(git_content_extensions))
            repo._run("add", ".gitignore")
            repo._run("commit", "-q", "-m", "qa: initial")
        else:
            repo.reconcile_gitignore(git_content_extensions)
        return repo

    def reconcile_gitignore(self, git_content_extensions: frozenset[str]) -> bool:
        """Rewrite ``.gitignore`` if the managed-extension set has changed.

        Without this, ``pointer_git_content_extensions`` is effectively write-once:
        the file was laid down at init and never revisited, so extending the
        config did not merely fail to backfill old files — it silently
        double-tracked NEW ones, committing both the binary and its ``.ptr``
        and defeating the whole point of §3.4's pointer scheme.

        Returns True if the file changed. Callers that care about already-
        tracked binaries should follow with :meth:`unmanaged_binaries_tracked`;
        this method deliberately does not untrack anything by itself, because
        that is a content decision the operator should see, not a side effect of
        opening a repo.
        """
        path = self.root / ".gitignore"
        want = _gitignore(git_content_extensions)
        if path.exists() and path.read_text() == want:
            return False
        path.write_text(want)
        return True

    def tracked_managed_binaries(self, git_content_extensions: frozenset[str]) -> list[str]:
        """Paths git still tracks as ordinary content despite now being
        pointer-managed by extension.

        These are the files a `.gitignore` change cannot fix retroactively: git
        keeps tracking what it already tracks. They must be untracked
        deliberately (``git rm --cached``, which preserves history and simply
        stops future tracking) — and their existing blobs stay in history
        regardless, since removing those would require the history rewriting
        that rollback's guarantees depend on never happening (law 6).
        """
        from ..sandbox.pointers import is_managed_binary

        return [
            p
            for p in self._run("ls-files").split("\n")
            if p and is_managed_binary(p, git_content_extensions)
        ]

    def untrack(self, paths: list[str]) -> int:
        """Stop tracking ``paths`` without deleting them from disk. History is
        untouched; the blobs remain reachable from older commits."""
        if not paths:
            return 0
        self._run("rm", "--cached", "-q", "--", *paths)
        return len(paths)

    def migrate_to_pointer_management(
        self,
        git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
        *,
        attic_dir: str = ".qa/attic",
    ) -> dict:
        """Move files that are now pointer-managed out of git tracking, minting
        their sidecars and seeding the attic **in the same operation**.

        Ordering is the whole point. A file that is managed-by-extension but has
        no ``.ptr`` is owned by *neither* rollback mechanism: git no longer
        tracks its content, and the attic has nothing to restore. So this mints
        the sidecar and seeds the attic BEFORE untracking, and never leaves a
        file in the gap even if it stops partway.

        Idempotent: files already carrying a sidecar and already untracked are
        not touched. Returns a report; the caller commits.
        """
        from ..sandbox.pointers import PointerManager, pointer_path_of

        stale = self.tracked_managed_binaries(git_content_extensions)
        manager = PointerManager(
            self.root, git_content=git_content_extensions, attic_dir=attic_dir
        )
        minted: list[str] = []
        atticked: list[str] = []
        missing: list[str] = []

        for rel in stale:
            binary = self.root / rel
            if not binary.exists():
                # Tracked but absent from the working tree: nothing to mint from.
                missing.append(rel)
                continue
            # 1. attic first — the rollback reserve exists before anything moves
            if manager.attic_store(binary) is not None:
                atticked.append(rel)
            # 2. then the sidecar, so the file is pointer-owned...
            if not pointer_path_of(binary).exists():
                manager.write_sidecar(binary)
                minted.append(rel)

        # 3. ...and only then drop git's claim on the content.
        untracked = self.untrack([r for r in stale if r not in missing])

        return {
            "untracked": untracked,
            "sidecars_minted": sorted(minted),
            "attic_seeded": sorted(atticked),
            "missing_from_worktree": sorted(missing),
        }

    # -- low-level ----------------------------------------------------------

    def _argv(self, *args: str) -> list[str]:
        return [
            "git",
            "-C",
            str(self.root),
            "-c",
            f"user.name={_AUTHOR_NAME}",
            "-c",
            f"user.email={_AUTHOR_EMAIL}",
            *_HARDENING,
            *args,
        ]

    def _run(self, *args: str, check: bool = True) -> str:
        cp = subprocess.run(
            self._argv(*args),
            capture_output=True,
            text=True,
        )
        if check and cp.returncode != 0:
            raise QAGitError(
                f"git {' '.join(args)} failed ({cp.returncode}): {cp.stderr.strip()}"
            )
        return cp.stdout

    # -- state --------------------------------------------------------------

    def head(self) -> str:
        return self._run("rev-parse", "HEAD").strip()

    def status_porcelain(self) -> str:
        return self._run("status", "--porcelain")

    def file_at(self, commit: str, path: str) -> str | None:
        """Return a file's text content at ``commit``, or None if it did not
        exist there. Used by the change preview to load the pre-work graph."""
        cp = subprocess.run(
            self._argv("show", f"{commit}:{path}"),
            capture_output=True,
            text=True,
        )
        return cp.stdout if cp.returncode == 0 else None

    def uncommitted_paths(self) -> list[str]:
        """Every path git has not committed, FILE BY FILE.

        `--porcelain` alone collapses an untracked directory to `content/`, so a
        caller asking "is this record distributed yet?" about a file inside one
        got no answer at all. `-uall` is the difference between a summary and a
        list.
        """
        out = []
        for line in self._run("status", "--porcelain", "-uall").splitlines():
            path = line[3:].strip().strip('"')
            if path:
                # A rename reads `old -> new`; what exists now is the new one.
                out.append(path.split(" -> ")[-1])
        return out

    def is_clean(self) -> bool:
        return self.status_porcelain().strip() == ""

    # -- writing ------------------------------------------------------------

    def stage_all(self) -> None:
        self._run("add", "-A")

    def commit(self, message: str, *, allow_empty: bool = False) -> str:
        """Stage everything and commit. Returns the new commit sha. Raises if
        there is nothing to commit and ``allow_empty`` is false."""
        self.stage_all()
        args = ["commit", "-q", "-m", message]
        if allow_empty:
            args.insert(1, "--allow-empty")
        cp = subprocess.run(
            self._argv(*args),
            capture_output=True,
            text=True,
        )
        if cp.returncode != 0:
            if not allow_empty and "nothing to commit" in (cp.stdout + cp.stderr):
                raise QAGitError("nothing to commit (empty promotion unit)")
            raise QAGitError(f"git commit failed ({cp.returncode}): {cp.stderr.strip()}")
        return self.head()

    # -- diff / manifest ----------------------------------------------------

    def manifest_since(self, base: str) -> ChangeManifest:
        """Change manifest from ``base`` to the current working tree (staging
        everything first so new files count). Renames are decomposed into
        delete+add so convergence stays a pure add/modify/delete set."""
        self.stage_all()
        out = self._run(
            "diff", "--cached", "--no-renames", "--name-status", base
        )
        return _parse_name_status(out)

    def manifest_between(self, base: str, target: str) -> ChangeManifest:
        out = self._run("diff", "--no-renames", "--name-status", base, target)
        return _parse_name_status(out)

    # -- rollback -----------------------------------------------------------

    def reset_hard(self, ref: str = "HEAD") -> None:
        """Discard tracked-file changes back to ``ref`` (WIP reset)."""
        self._run("reset", "--hard", "-q", ref)

    def clean_untracked(self) -> None:
        """Remove untracked files, keeping gitignored ones (binaries, /.qa/)."""
        self._run("clean", "-fdq")

    def untracked_paths(self) -> list[str]:
        """Files present in the tree that git does not track, gitignored ones
        excluded. What an episode CREATED is the difference between this taken
        at its start and taken now."""
        return [p for p in self._run(
            "ls-files", "--others", "--exclude-standard").splitlines() if p]

    def snapshot(self, ref: str) -> str:
        """Record the working tree as a commit object under ``ref``, changing
        nothing on disk. Returns its sha.

        `git stash create` is the usual way to do this and is the wrong one
        here: it captures tracked modifications only, so a record staged
        yesterday and edited today — untracked, uncommitted, entirely real —
        would have no pre-edit state to go back to. Staging everything and
        writing the tree captures it, and the index is put straight back.

        The commit is anchored to a ref so it survives `gc`, and it is on no
        branch: history stays the rollback authority it has to be (law 6), and
        this leaves no mark on it.
        """
        self._run("add", "-A")
        tree = self._run("write-tree").strip()
        sha = self._run("commit-tree", tree, "-p", self.head(),
                        "-m", "episode snapshot").strip()
        self._run("update-ref", ref, sha)
        self._run("reset", "-q")  # index back to HEAD; the tree is untouched
        return sha

    def restore_tree_from(self, commit: str) -> None:
        """Put every path that ``commit`` holds back to its content there.

        Deliberately NOT `read-tree --reset`: that would also delete paths the
        commit does not know about, and the whole point of a scoped restore is
        that other uncommitted work in the sandbox is none of its business.
        What this episode created is removed by its own bookkeeping instead.
        """
        self._run("checkout", commit, "--", ".")
        self._run("reset", "-q")

    def diff_names(self, commit: str) -> list[str]:
        """Paths where the working tree differs from ``commit``. Asked BEFORE a
        restore, so the restore can say what it changed."""
        return [p for p in self._run("diff", "--name-only", commit).splitlines() if p]

    def restore_path(self, commit: str, path: str) -> None:
        """Put ONE path back to its content at ``commit``. What "discard this
        draft" means for a record that has been distributed before."""
        self._run("checkout", commit, "--", path)
        self._run("reset", "-q", "--", path)

    def drop_ref(self, ref: str) -> None:
        cp = subprocess.run(self._argv("update-ref", "-d", ref),
                            capture_output=True, text=True)
        return None if cp.returncode == 0 else None

    def restore_to(self, commit: str) -> None:
        """Make the index and working tree exactly match ``commit`` (removing
        files added since). Rollback then commits this restored state and
        converges it to SOT (CE_DESIGN §3.4) — never an in-place SOT undo.
        Only tracked files are touched; gitignored binaries are re-materialized
        by the binary-asset layer."""
        self._run("read-tree", "-u", "--reset", commit)


def _gitignore(git_content_extensions: frozenset[str]) -> str:
    """Generate `.gitignore` for the INVERTED policy (2026-07-21).

    The pointer-managed set is now the open complement of the diffable list, so
    this can no longer enumerate binaries — it ignores everything with an
    extension and then re-admits the authored types. Pattern order matters:
    later rules win in gitignore, so the deny comes first, the negations after,
    and `/.qa/` goes LAST so QA-internal state stays ignored regardless.

    `*.*` matches only names containing a dot, which leaves extensionless files
    (README, LICENSE) tracked — matching `is_managed_binary`, which treats them
    as text. `!*/` re-admits directories so git still descends into a folder
    whose name contains a dot.
    """
    lines = [
        "# Pointer-managed binaries live at real paths but are tracked via their",
        "# .ptr sidecars (CE_DESIGN §3.4). The policy is INVERTED: ignore every",
        "# extension by default, then re-admit the types a user authors and diffs.",
        "*.*",
        "",
        "# ...but keep descending into directories (a dir name may contain a dot).",
        "!*/",
        "",
        "# Authored, diffable content (config: git_content_extensions).",
    ]
    lines += [f"!*{ext}" for ext in sorted(git_content_extensions)]
    lines += [
        "",
        "# Machinery that shares the content path space and must stay tracked.",
        f"!*{POINTER_SUFFIX}",
        "",
        "# Dotfiles: `*.*` DOES match a single-dot name — `*` matches the empty",
        "# string, so the leading dot satisfies the pattern's dot. Without this",
        "# line .env/.npmrc/.dockerignore/.editorconfig are ignored by git while",
        "# is_managed_binary() calls them text: tracked nowhere, sidecarred never.",
        "# (.gitignore itself was only safe because it was re-admitted by name.)",
        "!.*",
        "",
        "# QA-internal state — never promoted to SOT. Last, so it always wins",
        "# over the dotfile negation above.",
        "/.qa/",
    ]
    return "\n".join(lines) + "\n"


def _assert_not_nested(root: Path, project_root: str | Path | None) -> None:
    # Refuse if any strict ancestor of root is itself a git repo — initializing
    # here would nest the QA repo inside it.
    for ancestor in root.parents:
        if (ancestor / ".git").exists():
            raise NestingError(
                f"{root} lies inside an existing git repo at {ancestor}; the QA "
                f"content repo must not nest (CE_DESIGN §3.4)"
            )
    if project_root is not None:
        proj = Path(project_root).resolve()
        if proj == root or _is_relative_to(root, proj) or _is_relative_to(proj, root):
            raise NestingError(
                f"QA repo root {root} and project root {proj} overlap; they must "
                f"be disjoint trees (CE_DESIGN §3.4)"
            )


def _is_relative_to(p: Path, other: Path) -> bool:
    try:
        p.relative_to(other)
        return True
    except ValueError:
        return False


def _parse_name_status(out: str) -> ChangeManifest:
    """Git's name-status output as a manifest, minus what never converges.

    The filter belongs here because EVERY manifest comes through this function
    — preview, apply and rollback alike — so a path excluded here cannot reach
    the SOT by any route. The QA commit is `git add -A` and does not consult
    the manifest, which is exactly the split `evidence/` needs: full history in
    the QA git, nothing in the published catalogue.
    """
    m = ChangeManifest()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        status = parts[0]
        path = parts[-1]
        if is_local_only(path):
            continue
        code = status[0]
        if code == "A":
            m.adds.append(path)
        elif code == "D":
            m.deletes.append(path)
        elif code in ("M", "T"):
            m.modifies.append(path)
        else:  # C (copy) or anything unexpected -> treat as an add
            m.adds.append(path)
    m.adds.sort()
    m.modifies.sort()
    m.deletes.sort()
    return m
