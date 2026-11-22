"""File operations — the single filesystem chokepoint (CE_DESIGN §2.1).

Every path an operation touches is first run through :meth:`Sandbox.resolve`
(Layer 1). This module is the *only* place in the dashboard permitted to read
or mutate the filesystem for the agent; the agent's whole file vocabulary is
the small, deny-by-default set of methods here (list, read, write, mkdir,
move, copy, trash). There is no exec/shell tool, by law.

Beyond Layer-1 confinement, opens use ``O_NOFOLLOW`` so a symlink swapped in
after resolution (TOCTOU) still cannot be followed on the final component.
The real OS boundary is Layer 2 (broker + Landlock/ACLs, added later); this
module is the portable first line.

Results carry logical (sandbox-relative, POSIX) paths only — host-absolute
paths are never handed back to the agent.
"""

from __future__ import annotations

import os
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .paths import Sandbox
from .pointers import DEFAULT_GIT_CONTENT_EXTENSIONS, PointerManager, pointer_path_of
from .quotas import Quotas, RateLimiter

__all__ = ["FileOps", "DirEntry", "WriteResult", "AuditHook"]

# open() flags, guarded for non-POSIX platforms (Windows lacks O_NOFOLLOW).
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_CLOEXEC = getattr(os, "O_CLOEXEC", 0)

# op name, arguments, outcome ("ok" or "error:<reason>"). The full append-only
# audit log (CE_DESIGN §2.3) is a separate module; fileops emits through this
# hook so it is ready to receive one.
AuditHook = Callable[[str, dict, str], None]


@dataclass(frozen=True)
class DirEntry:
    name: str
    path: str  # sandbox-relative, POSIX
    is_dir: bool
    is_file: bool
    is_symlink: bool
    size: int
    # Nanosecond mtime, from the stat list_dir already performs. Carried so a
    # caller can tell whether a directory changed without re-reading every file
    # in it — size alone misses a same-length edit.
    mtime_ns: int = 0


@dataclass(frozen=True)
class WriteResult:
    path: str  # sandbox-relative, POSIX
    bytes_written: int
    created: bool  # True if the file did not exist before this write


class FileOps:
    """The confined filesystem interface. Construct with a :class:`Sandbox`;
    quotas and an audit hook are optional but recommended."""

    def __init__(
        self,
        sandbox: Sandbox,
        quotas: Quotas | None = None,
        *,
        trash_dir: str = ".qa/trash",
        audit: AuditHook | None = None,
        git_content_extensions: frozenset[str] = DEFAULT_GIT_CONTENT_EXTENSIONS,
        attic_dir: str = ".qa/attic",
    ):
        self._sb = sandbox
        self._quotas = quotas or Quotas()
        self._trash_dir = trash_dir
        self._audit = audit
        self._rate = RateLimiter(self._quotas.max_ops_per_minute)
        # Binary-asset pointer/attic policy (CE_DESIGN §3.4). fileops is the
        # consistency chokepoint: managed binaries always carry a synced .ptr.
        self._pointers = PointerManager(
            sandbox.root, git_content=git_content_extensions, attic_dir=attic_dir
        )

    # -- helpers ------------------------------------------------------------

    def _rel(self, resolved: Path) -> str:
        if resolved == self._sb.root:
            return "."
        return resolved.relative_to(self._sb.root).as_posix()

    def _begin(self, op: str, args: dict) -> None:
        # Rate limit is charged before the work; the audit outcome is emitted
        # by the caller via _done/_fail.
        try:
            self._rate.tick()
        except Exception as exc:
            self._emit(op, args, f"error:{type(exc).__name__}")
            raise

    def _emit(self, op: str, args: dict, outcome: str) -> None:
        if self._audit is not None:
            self._audit(op, args, outcome)

    def _count_files(self) -> int:
        n = 0
        for _root, _dirs, files in os.walk(self._sb.root):
            n += len(files)
        return n

    # -- read side ----------------------------------------------------------

    def list_dir(self, userpath: str = ".") -> list[DirEntry]:
        self._begin("list_dir", {"path": userpath})
        target = self._sb.resolve(userpath)
        if not target.is_dir():
            self._emit("list_dir", {"path": userpath}, "error:NotADirectoryError")
            raise NotADirectoryError(self._rel(target))
        entries: list[DirEntry] = []
        with os.scandir(target) as it:
            for e in it:
                try:
                    st = e.stat(follow_symlinks=False)
                    size, mtime_ns = st.st_size, st.st_mtime_ns
                except OSError:
                    size, mtime_ns = 0, 0
                entries.append(
                    DirEntry(
                        name=e.name,
                        path=self._rel(Path(e.path)),
                        is_dir=e.is_dir(follow_symlinks=False),
                        is_file=e.is_file(follow_symlinks=False),
                        is_symlink=e.is_symlink(),
                        size=size,
                        mtime_ns=mtime_ns,
                    )
                )
        entries.sort(key=lambda x: x.name)
        self._emit("list_dir", {"path": userpath}, "ok")
        return entries

    def read_bytes(self, userpath: str) -> bytes:
        self._begin("read_bytes", {"path": userpath})
        target = self._sb.resolve(userpath)
        try:
            fd = os.open(target, os.O_RDONLY | _O_NOFOLLOW | _O_CLOEXEC)
        except OSError as exc:
            self._emit("read_bytes", {"path": userpath}, f"error:{type(exc).__name__}")
            raise
        try:
            with os.fdopen(fd, "rb") as fh:
                data = fh.read()
        except OSError:
            os.close(fd)
            raise
        self._emit("read_bytes", {"path": userpath, "bytes": len(data)}, "ok")
        return data

    def read_text(self, userpath: str, encoding: str = "utf-8") -> str:
        return self.read_bytes(userpath).decode(encoding)

    # -- write side ---------------------------------------------------------

    def write_bytes(
        self, userpath: str, data: bytes, *, make_parents: bool = False
    ) -> WriteResult:
        args = {"path": userpath, "bytes": len(data)}
        self._begin("write_bytes", args)
        self._quotas.check_write_size(len(data))
        target = self._sb.resolve(userpath)

        existed = target.exists()
        if not existed:
            # Only a genuinely new file grows the count.
            self._quotas.check_file_count(self._count_files(), adding=1)
        if make_parents and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)

        managed = self._pointers.is_managed(userpath)
        if managed and existed:
            # Replacement: preserve the superseded content in the attic before
            # overwriting, so rollback can re-materialize it (CE_DESIGN §3.4).
            self._pointers.attic_store(target)

        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _O_NOFOLLOW | _O_CLOEXEC
        try:
            fd = os.open(target, flags, 0o644)
        except OSError as exc:
            self._emit("write_bytes", args, f"error:{type(exc).__name__}")
            raise
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
        except OSError:
            os.close(fd)
            raise

        if managed:
            # Keep the .ptr sidecar consistent with the new content.
            self._pointers.write_sidecar(target)
        self._emit("write_bytes", args, "ok")
        return WriteResult(path=self._rel(target), bytes_written=len(data), created=not existed)

    def write_text(
        self, userpath: str, text: str, *, encoding: str = "utf-8", make_parents: bool = False
    ) -> WriteResult:
        return self.write_bytes(userpath, text.encode(encoding), make_parents=make_parents)

    def mkdir(self, userpath: str, *, parents: bool = False, exist_ok: bool = False) -> str:
        self._begin("mkdir", {"path": userpath})
        target = self._sb.resolve(userpath)
        try:
            target.mkdir(parents=parents, exist_ok=exist_ok)
        except OSError as exc:
            self._emit("mkdir", {"path": userpath}, f"error:{type(exc).__name__}")
            raise
        self._emit("mkdir", {"path": userpath}, "ok")
        return self._rel(target)

    # -- structural ops -----------------------------------------------------

    def move(self, src: str, dst: str, *, overwrite: bool = False) -> str:
        self._begin("move", {"src": src, "dst": dst})
        s = self._sb.resolve(src)
        d = self._sb.resolve(dst)
        if d.exists() and not overwrite:
            self._emit("move", {"src": src, "dst": dst}, "error:FileExistsError")
            raise FileExistsError(self._rel(d))
        os.replace(s, d)  # atomic within the one sandbox filesystem
        # Keep the .ptr sidecar paired with a managed binary as it moves.
        if self._pointers.is_managed(src):
            self._move_sidecar(s, d, dst_managed=self._pointers.is_managed(dst))
        self._emit("move", {"src": src, "dst": dst}, "ok")
        return self._rel(d)

    def copy(self, src: str, dst: str, *, overwrite: bool = False) -> str:
        self._begin("copy", {"src": src, "dst": dst})
        s = self._sb.resolve(src)
        d = self._sb.resolve(dst)
        if d.exists() and not overwrite:
            self._emit("copy", {"src": src, "dst": dst}, "error:FileExistsError")
            raise FileExistsError(self._rel(d))
        if s.is_dir():
            self._quotas.check_file_count(self._count_files(), adding=_count_tree(s))
            shutil.copytree(s, d, symlinks=True, dirs_exist_ok=overwrite)
        else:
            if not d.exists():
                self._quotas.check_file_count(self._count_files(), adding=1)
            shutil.copy2(s, d)
            # A copied managed binary gets its own fresh sidecar.
            if self._pointers.is_managed(dst):
                self._pointers.write_sidecar(d)
        self._emit("copy", {"src": src, "dst": dst}, "ok")
        return self._rel(d)

    def trash(self, userpath: str) -> str:
        """Soft delete: move the target into the in-sandbox trash. Nothing is
        ever hard-deleted by an agent op (CE_DESIGN §2.3)."""
        self._begin("trash", {"path": userpath})
        target = self._sb.resolve(userpath)
        if not target.exists():
            self._emit("trash", {"path": userpath}, "error:FileNotFoundError")
            raise FileNotFoundError(self._rel(target))

        trash_root = self._sb.resolve(self._trash_dir)
        trash_root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%dT%H%M%S")
        unique = f"{stamp}-{uuid.uuid4().hex[:8]}-{target.name}"
        dest = trash_root / unique
        os.replace(target, dest)
        # Trash the .ptr sidecar alongside a managed binary so the pair stays
        # together and the content tree no longer references it.
        if self._pointers.is_managed(userpath):
            side = pointer_path_of(target)
            if side.exists():
                os.replace(side, pointer_path_of(dest))
        self._emit("trash", {"path": userpath, "trash": self._rel(dest)}, "ok")
        return self._rel(dest)

    def _move_sidecar(self, src_binary: Path, dst_binary: Path, *, dst_managed: bool) -> None:
        side = pointer_path_of(src_binary)
        if not side.exists():
            return
        if dst_managed:
            os.replace(side, pointer_path_of(dst_binary))
        else:
            # Destination is no longer pointer-managed; drop the stale sidecar.
            side.unlink()


def _count_tree(path: Path) -> int:
    n = 0
    for _root, _dirs, files in os.walk(path):
        n += len(files)
    return n
