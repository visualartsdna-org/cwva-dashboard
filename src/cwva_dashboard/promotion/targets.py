"""Build the transport a configuration's source of truth names.

One place, so the app (which distributes to it) and the sync script (which
reads it into a sandbox) cannot disagree about what the target is. Four kinds:

    {"transport": "files",      "path": "~/cwva-py"}
    {"transport": "git_local",  "path": "~/cwva-py/content"}
    {"transport": "git_remote", "path": "~/cwva-py/content", "remote": "origin",
                                "branch": "main"}
    {"transport": "gcp_bucket", "bucket_env": "GCP_BUCKET", "prefix": ""}

A folder or git target is somebody's own directory, so it is SCOPED to the
folders the placement map names; anything else there is left alone and never
counted as drift. A bucket target is scoped by its prefix instead.

Trusted-orchestrator machinery: the writable transport is built here and only
reaches the promotion tail (law 1). ``read_only=True`` wraps it in a
:class:`ReadOnlySource`, which has no ``converge`` at all.
"""

from __future__ import annotations

import os
from pathlib import Path

from .transports import (FilesTransport, GcpBucketTransport, GitLocalTransport,
                         GitRemoteTransport, ReadOnlySource, Transport)

__all__ = ["build_transport", "managed_dirs", "TargetError", "KINDS", "describe"]

KINDS = ("files", "git_local", "git_remote", "gcp_bucket")

#: Placement-map kinds the dashboard never writes to the target: thumbnails
#: are the published server's own cache, made on demand.
_NOT_MANAGED = {"thumbnail"}


class TargetError(ValueError):
    """The configuration names a target that cannot be built; the message says
    what to fix."""


def managed_dirs(layout) -> list[str]:
    """The target's folders the dashboard manages, from the placement map."""
    dirs = {layout.dir(k).strip("/") for k in layout.kinds if k not in _NOT_MANAGED}
    # a folder inside another managed folder is already covered
    return sorted(d for d in dirs if d and not any(
        d != o and d.startswith(o + "/") for o in dirs))


def _path(target: dict) -> Path:
    p = target.get("path")
    if not p:
        raise TargetError(f"a {target.get('transport')} target needs a 'path'")
    return Path(os.path.expanduser(str(p)))


def describe(target: dict) -> str:
    kind = target.get("transport", "?")
    if kind == "gcp_bucket":
        return f"gcp bucket ${target.get('bucket_env')}/{target.get('prefix', '')}"
    if kind == "git_remote":
        return f"git {target.get('path')} -> {target.get('remote', 'origin')}/{target.get('branch', 'main')}"
    return f"{kind} {target.get('path')}"


def build_transport(target: dict, layout, *, read_only: bool = False,
                    client=None) -> Transport | ReadOnlySource:
    kind = (target or {}).get("transport")
    include = managed_dirs(layout)
    if kind == "files":
        root = _path(target)
        if read_only and not root.is_dir():
            raise TargetError(f"the source folder {root} does not exist")
        t = FilesTransport(root, include=include)
    elif kind in ("git_local", "git_remote"):
        root = _path(target)
        if read_only and not (root / ".git").exists():
            raise TargetError(f"{root} is not a git checkout")
        if kind == "git_local":
            t = GitLocalTransport(root, include=include, ensure=not read_only)
        else:
            t = GitRemoteTransport(root, remote=target.get("remote", "origin"),
                                   branch=target.get("branch", "main"),
                                   include=include, ensure=not read_only)
    elif kind == "gcp_bucket":
        env = target.get("bucket_env", "")
        bucket = os.environ.get(env, "")
        if not bucket:
            raise TargetError(f"{env or 'bucket_env'} is not set: bucket names come "
                              "from the environment")
        if client is None:
            from google.cloud import storage  # optional: pip install -e ".[gcp]"

            client = storage.Client()
        t = GcpBucketTransport(client.bucket(bucket), prefix=target.get("prefix", ""))
    else:
        raise TargetError(f"unknown transport {kind!r}; use one of {', '.join(KINDS)}")
    return ReadOnlySource(t, label=describe(target)) if read_only else t
