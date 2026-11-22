"""Transport adapters — state convergence to SOT (CE_DESIGN §3.3).

SOT deployment varies per CE user, so "apply" is not a single write but
transport-specific **state convergence**: SOT is made to match QA's committed
content for the paths in the change manifest. Pushes are idempotent and
full-state — re-running a converge is a no-op — computed from the QA git diff
(adds / modifies / **deletes**). There is no uniform transactional undo across
these transports; that is exactly why rollback restores a known-good state in
QA and converges *that*, rather than undoing SOT in place (§3.4).

Four transports:

- :class:`FilesTransport`   — plain files on disk (write changed, delete removed)
- :class:`GitLocalTransport`— commit in the SOT git repo
- :class:`GitRemoteTransport` — commit + push to the user's remote
- :class:`GcpBucketTransport` — upload changed objects, delete removed ones

Each exposes ``current_stamp()`` (a per-transport fingerprint of SOT state,
for drift detection) and ``converge()``. Drift detection is uniform at the
apply layer: capture the stamp, and abort if SOT changed under us (§4).
"""

from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from .unit import ChangeManifest

__all__ = [
    "Transport",
    "ConvergeResult",
    "TransportError",
    "FilesTransport",
    "GitLocalTransport",
    "GitRemoteTransport",
    "GcpBucketTransport",
    "ReadOnlySource",
]

_GIT_NAME = "cwva-dashboard"
_GIT_EMAIL = "dashboard@localhost"


class TransportError(RuntimeError):
    pass


@dataclass
class ConvergeResult:
    stamp: str
    applied: ChangeManifest
    detail: dict = field(default_factory=dict)


class Transport(ABC):
    """A convergence target. ``converge`` reads the changed files from
    ``content_root`` (the QA content tree) and makes SOT match them."""

    name: str = "transport"

    @abstractmethod
    def current_stamp(self) -> str:
        """A fingerprint of SOT's CONTENT, for drift detection.

        Operational state (`operational/`, the QA history backup) is excluded.
        A promotion writes that backup, which changes the target — so if the
        stamp covered it, the very next promotion would compare against a stamp
        the previous one invalidated and abort with DriftError. Drift means
        "someone else changed the CONTENT", and a backup is neither.
        """

    @abstractmethod
    def converge(
        self, content_root: str | Path, manifest: ChangeManifest, *, message: str | None = None
    ) -> ConvergeResult:
        """Apply the manifest to SOT: copy adds/modifies from ``content_root``,
        delete removals. Idempotent and full-state for the manifest paths."""

    # -- SOT -> QA (sync direction, Phase 4) --------------------------------

    @abstractmethod
    def snapshot(self) -> dict[str, str]:
        """Current SOT content as ``{relpath: fingerprint}``. The fingerprint is
        sha256 where the transport can compute it (files/git); for buckets it is
        whatever the store exposes — sync stays correct regardless, re-fetching
        when fingerprints are not directly comparable."""

    @abstractmethod
    def fetch(self, path: str) -> bytes:
        """Return the bytes of one SOT file."""

    def put_operational(self, rel: str, data: bytes) -> None:
        """Write OPERATIONAL state (not content) to the target.

        Used only by the QA backup, which cannot go through `converge`: a
        repository cannot back itself up into itself, so the bundle is built
        outside the tree and has no manifest to belong to. Deliberately a
        separate method from `converge` so a reader can see at a glance that
        nothing in the content path calls it, and so a transport that should not
        accept operational writes can simply not implement it.
        """
        raise NotImplementedError(f"{self.name} cannot store operational state")

    def local_fingerprint(self, path: "Path") -> str:
        """This transport's fingerprint for a LOCAL file, so sync can compare
        like with like.

        Sync decides what to pull by comparing its snapshot of SOT against the
        QA tree. Both sides must speak the same hash or every object looks
        changed and the whole store is re-fetched every time — correct, but
        O(everything). The default is sha256, matching the file and git
        transports; a store that reports something else overrides this.
        """
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def pull_remote(self) -> None:
        """Refresh the local SOT view from a remote, if any. No-op by default;
        the git-remote transport pulls."""
        return None


# -- shared helpers ---------------------------------------------------------


def _digest(items: list[str]) -> str:
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest()


def _tree_digest(root: Path) -> str:
    """Content fingerprint of a directory tree (path + file hash), ignoring
    the repo's own .git."""
    if not root.exists():
        return _digest([])
    items: list[str] = []
    for dirpath, dirs, files in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        for f in files:
            fp = Path(dirpath) / f
            rel = fp.relative_to(root).as_posix()
            try:
                h = hashlib.sha256(fp.read_bytes()).hexdigest()
            except OSError:
                h = "?"
            items.append(f"{rel}:{h}")
    return _digest(sorted(items))


def _is_operational(rel: str) -> bool:
    """Is this path operational state rather than content?

    Kept here rather than imported, so the transport layer has no dependency on
    the backup module it serves.
    """
    return rel == "operational" or rel.startswith("operational/")


def _tree_snapshot(root: Path) -> dict[str, str]:
    """{relpath: sha256} for every file under ``root``, ignoring .git."""
    out: dict[str, str] = {}
    if not root.exists():
        return out
    for dirpath, dirs, files in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        for f in files:
            fp = Path(dirpath) / f
            rel = fp.relative_to(root).as_posix()
            out[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()
    return out


def _in_scope(rel: str, include) -> bool:
    """Is ``rel`` under one of the managed folders? ``include`` None = all.

    A folder or git source of truth is somebody's own directory, and it holds
    more than the dashboard manages: cwva-py writes thumbnails there, a git
    checkout has a README. Counting those would make every thumbnail look like
    someone else changing the published data (drift), and syncing them would
    copy them into the sandbox as content (2026-11-21).
    """
    if include is None:
        return True
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in include)


def _scoped_snapshot(root: Path, include) -> dict[str, str]:
    if include is None:
        return _tree_snapshot(root)
    out: dict[str, str] = {}
    for p in include:
        sub = root / p
        if sub.is_dir():
            for rel, fp in _tree_snapshot(sub).items():
                out[f"{p.strip('/')}/{rel}"] = fp
        elif sub.is_file():
            out[p] = hashlib.sha256(sub.read_bytes()).hexdigest()
    return out


def _apply_manifest_to_tree(content_root: Path, target: Path, manifest: ChangeManifest) -> None:
    for rel in [*manifest.adds, *manifest.modifies]:
        src = content_root / rel
        dst = target / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    for rel in manifest.deletes:
        dst = target / rel
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        _prune_empty_dirs(dst.parent, stop=target)


def _prune_empty_dirs(start: Path, *, stop: Path) -> None:
    cur = start
    while cur != stop and stop in cur.parents:
        try:
            next(cur.iterdir())
            return  # not empty
        except StopIteration:
            cur.rmdir()
            cur = cur.parent
        except OSError:
            return


def _is_folder_placeholder(name: str) -> bool:
    """True for the ``dir/`` objects the GCS console creates to fake a folder.
    GCS has no directories; these are real objects that name no content.

    They must never enter a snapshot: the relpath would be ``documents/``, and
    sync would try to write a *file* where a *directory* has to go — a
    file/directory collision, plus permanent phantom drift (converge never
    creates them, so they are always "extra"). The production CWVA bucket
    contains ten of these, so this is observed behavior, not a hypothetical.
    Console use is ordinary user behavior, so this belongs here rather than in
    the clone: every bucket SOT can grow one at any time.

    **The predicate is the trailing slash, deliberately NOT the zero length.**
    A trailing slash cannot occur in a real filename, so it is exact; size is
    incidental. Filtering on emptiness would drop legitimately empty files (a
    .gitkeep-style marker, a truncated write) out of the snapshot and cause the
    mirror-image bug: phantom *absence* — sync deleting a file that is really
    there, and converge re-uploading it forever.
    """
    return name.endswith("/")


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    cp = subprocess.run(
        ["git", "-C", str(root), "-c", f"user.name={_GIT_NAME}", "-c", f"user.email={_GIT_EMAIL}", *args],
        capture_output=True,
        text=True,
    )
    if check and cp.returncode != 0:
        raise TransportError(f"git {' '.join(args)} failed ({cp.returncode}): {cp.stderr.strip()}")
    return cp


def _git_commit(root: Path, message: str) -> str:
    cp = _git(root, "commit", "-q", "-m", message, check=False)
    if cp.returncode != 0 and "nothing to commit" not in (cp.stdout + cp.stderr):
        raise TransportError(f"git commit failed ({cp.returncode}): {cp.stderr.strip()}")
    return _git(root, "rev-parse", "HEAD").stdout.strip()


# -- plain files ------------------------------------------------------------


class FilesTransport(Transport):
    name = "files"

    def __init__(self, target_root: str | Path, *, include=None):
        """``include``: the folders under ``target_root`` the dashboard manages
        (from the placement map); everything else there is left alone."""
        self.target = Path(target_root)
        self.target.mkdir(parents=True, exist_ok=True)
        self.include = tuple(include) if include else None

    def current_stamp(self) -> str:
        return _digest(sorted(
            f"{rel}:{fp}" for rel, fp in self.snapshot().items()
            if not _is_operational(rel)
        ))

    def converge(self, content_root, manifest, *, message=None) -> ConvergeResult:
        _apply_manifest_to_tree(Path(content_root), self.target, manifest)
        return ConvergeResult(
            stamp=self.current_stamp(), applied=manifest, detail={"target": str(self.target)}
        )

    def snapshot(self) -> dict[str, str]:
        return _scoped_snapshot(self.target, self.include)

    def fetch(self, path: str) -> bytes:
        return (self.target / path).read_bytes()

    def put_operational(self, rel: str, data: bytes) -> None:
        dest = self.target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)


# -- local git --------------------------------------------------------------


class GitLocalTransport(Transport):
    name = "git_local"

    def __init__(self, target_root: str | Path, *, ensure: bool = True, include=None):
        self.target = Path(target_root)
        self.include = tuple(include) if include else None
        if ensure:
            self._ensure_repo()

    def _ensure_repo(self) -> None:
        self.target.mkdir(parents=True, exist_ok=True)
        if not (self.target / ".git").exists():
            _git(self.target, "init", "-q", "-b", "main")
            _git(self.target, "commit", "--allow-empty", "-q", "-m", "sot: initial")

    def current_stamp(self) -> str:
        """The commit AND the working tree. The commit alone would miss an
        edit made by hand and not yet committed, which is the likeliest kind
        for someone who keeps their collection in git; it would not be drift,
        and the next distribution would commit it along with its own changes."""
        cp = _git(self.target, "rev-parse", "HEAD", check=False)
        head = cp.stdout.strip() if cp.returncode == 0 else ""
        tree = _digest(sorted(f"{rel}:{fp}" for rel, fp in self.snapshot().items()
                              if not _is_operational(rel)))
        return f"{head}:{tree}"

    def converge(self, content_root, manifest, *, message=None) -> ConvergeResult:
        _apply_manifest_to_tree(Path(content_root), self.target, manifest)
        # Only what this distribution changed: anything else in the checkout
        # is the owner's, committed or not, and stays out of this commit.
        if self.include:
            changed = [*manifest.adds, *manifest.modifies]
            # A path the checkout ignores (cwva-py's sample ignores images/,
            # too large for git) is copied into place and left uncommitted,
            # which is the repository owner's choice; `git add` would refuse it.
            ignored = set()
            if changed:
                cp = subprocess.run(["git", "-C", str(self.target), "check-ignore", "--stdin"],
                                    input="\n".join(changed), capture_output=True, text=True)
                ignored = set(cp.stdout.split())
            changed = [c for c in changed if c not in ignored]
            if changed:
                _git(self.target, "add", "--", *changed)
            if manifest.deletes:
                _git(self.target, "rm", "-q", "--cached", "--ignore-unmatch", "--",
                     *manifest.deletes)
        else:
            _git(self.target, "add", "-A")
        sha = _git_commit(self.target, message or "promote")
        return ConvergeResult(stamp=self.current_stamp(), applied=manifest,
                              detail={"commit": sha})

    def snapshot(self) -> dict[str, str]:
        return _scoped_snapshot(self.target, self.include)  # skips .git

    def put_operational(self, rel: str, data: bytes) -> None:
        """Backups beside the checkout, never in its history: a bundle per
        distribution committed to the repository would grow it without end,
        and the repository's own history is already a history. Kept out by
        the clone's local exclude file, which is never pushed."""
        exclude = self.target / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        lines = exclude.read_text().splitlines() if exclude.exists() else []
        if "/operational/" not in lines:
            exclude.write_text("\n".join([*lines, "/operational/"]) + "\n")
        dest = self.target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def fetch(self, path: str) -> bytes:
        return (self.target / path).read_bytes()


# -- git remote -------------------------------------------------------------


class GitRemoteTransport(GitLocalTransport):
    name = "git_remote"

    def __init__(self, target_root, *, remote: str = "origin", branch: str = "main",
                 ensure: bool = True, include=None):
        super().__init__(target_root, ensure=ensure, include=include)
        self.remote = remote
        self.branch = branch

    def converge(self, content_root, manifest, *, message=None) -> ConvergeResult:
        res = super().converge(content_root, manifest, message=message)
        _git(self.target, "push", "-q", self.remote, f"HEAD:{self.branch}")
        res.detail["pushed"] = f"{self.remote}/{self.branch}"
        return res

    def pull_remote(self) -> None:
        _git(self.target, "pull", "-q", self.remote, self.branch, check=False)


# -- gcp bucket -------------------------------------------------------------


class GcpBucketTransport(Transport):
    name = "gcp_bucket"

    def __init__(self, bucket, *, prefix: str = ""):
        """``bucket`` is a ``google.cloud.storage.Bucket`` (or any object with
        the same ``blob()`` / ``list_blobs()`` surface — injectable for tests)."""
        self._bucket = bucket
        self._prefix = prefix.strip("/")

    @classmethod
    def connect(cls, bucket_name: str, *, prefix: str = "", client=None) -> "GcpBucketTransport":
        if client is None:
            from google.cloud import storage  # optional dep, lazy

            client = storage.Client()
        return cls(client.bucket(bucket_name), prefix=prefix)

    def _key(self, rel: str) -> str:
        return f"{self._prefix}/{rel}" if self._prefix else rel

    def current_stamp(self) -> str:
        items = []
        for b in self._bucket.list_blobs(prefix=self._prefix or None):
            if _is_folder_placeholder(b.name) or _is_operational(self._rel_of(b.name)):
                continue
            fingerprint = getattr(b, "md5_hash", None) or str(getattr(b, "generation", ""))
            items.append(f"{b.name}:{fingerprint}")
        return _digest(sorted(items))

    def converge(self, content_root, manifest, *, message=None) -> ConvergeResult:
        content_root = Path(content_root)
        for rel in [*manifest.adds, *manifest.modifies]:
            self._bucket.blob(self._key(rel)).upload_from_filename(str(content_root / rel))
        for rel in manifest.deletes:
            blob = self._bucket.blob(self._key(rel))
            try:
                blob.delete()
            except Exception:  # already absent — convergence is idempotent
                pass
        return ConvergeResult(stamp=self.current_stamp(), applied=manifest, detail={})

    def _rel_of(self, name: str) -> str:
        if self._prefix and name.startswith(self._prefix + "/"):
            return name[len(self._prefix) + 1 :]
        return name

    def snapshot(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for b in self._bucket.list_blobs(prefix=self._prefix or None):
            if _is_folder_placeholder(b.name):
                continue
            fp = getattr(b, "md5_hash", None) or str(getattr(b, "generation", ""))
            out[self._rel_of(b.name)] = fp
        return out

    def fetch(self, path: str) -> bytes:
        return self._bucket.blob(self._key(path)).download_as_bytes()

    def put_operational(self, rel: str, data: bytes) -> None:
        self._bucket.blob(self._key(rel)).upload_from_string(data)

    def local_fingerprint(self, path: Path) -> str:
        """Base64 MD5, which is what GCS reports in `md5_hash`.

        Without this the comparison was sha256-hex against base64-MD5 — never
        equal, so every sync re-downloaded the entire bucket. Invisible while
        the shadow held ~50 MB of TTL; after seeding 1093 production images it
        meant 3.7 GB per sync, and an Approve does two (the pre-push check and
        the post-promotion refresh). That is the "seems hung" of 2026-09-11.
        """
        return base64.b64encode(hashlib.md5(path.read_bytes()).digest()).decode()


# -- read-only source -------------------------------------------------------


class ReadOnlySource:
    """A SOT one may **read** and can never write.

    Deliberately NOT a :class:`Transport` subclass. The safety property is
    structural rather than enforced: there is no ``converge`` method to call and
    no name to validate, so "push to production" is not a mistake this codebase
    can express — ``apply``/``rollback`` take a Transport and would fail at
    construction, not at some runtime check that a future edit could weaken
    (security in code, never in prompts — CLAUDE.md law 3).

    Its purpose is seeding a disposable shadow SOT from live production content:
    production is wrapped here, the shadow is an ordinary Transport, and the
    asymmetry is enforced by the type.
    """

    def __init__(self, inner: Transport, *, label: str = ""):
        self._inner = inner
        self.label = label or getattr(inner, "name", "source")

    @property
    def name(self) -> str:
        return f"readonly:{self.label}"

    def snapshot(self) -> dict[str, str]:
        return self._inner.snapshot()

    def fetch(self, path: str) -> bytes:
        return self._inner.fetch(path)

    def pull_remote(self) -> None:
        self._inner.pull_remote()

    def current_stamp(self) -> str:
        return self._inner.current_stamp()

    def __repr__(self) -> str:  # pragma: no cover - diagnostics
        return f"<ReadOnlySource {self.name}>"
