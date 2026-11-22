"""The hardened worker process — Layer 1 + Layer 2 + tools, composed.

This is the "least-privilege executor process" of CE_DESIGN §2.2: a separate
process that (1) confines itself to the sandbox with Landlock, then (2) serves
tool calls against a :class:`FileOps` through the registry. The parent
(orchestrator) side, :class:`WorkerClient`, is unconfined; it sends tool-call
requests and persists the audit trail **outside** the sandbox — which the
confined worker could not do itself. That split is deliberate: it is what lets
the audit log resist a compromised worker (CE_DESIGN §2.3, audit.py).

Wire protocol: newline-delimited JSON over an ``AF_UNIX`` socketpair. Requests
and responses are plain JSON (tool results are already JSON-safe), so nothing
is unpickled from the worker — the boundary carries data, not code.

    parent -> worker : {"cmd":"call","id":N,"tool":str,"args":{...}}
                       {"cmd":"shutdown"}
    worker -> parent : {"cmd":"hello","landlock_abi":int,"enforced":bool}
                       {"id":N,"ok":bool,"result":obj|null,
                        "error":obj|null,"audit":[{op,args,outcome},...]}

On Linux with Landlock the worker is kernel-confined. Without Landlock (older
kernel, or Windows, where Layer 2 is instead an install-time low-privilege
user + NTFS ACLs) it still runs, reporting ``enforced=False``; the caller can
decide whether that is acceptable.
"""

from __future__ import annotations

import json
import os
import socket
from typing import Any

from ..tools.registry import ToolRegistry
from .broker import LandlockError, landlock_abi, restrict_process
from .fileops import FileOps
from .paths import Sandbox

__all__ = ["WorkerClient", "serve_worker"]


def _send(sock: socket.socket, obj: dict) -> None:
    sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))


def serve_worker(
    sock: socket.socket,
    sandbox_root: str,
    registry: ToolRegistry,
    *,
    enforce_landlock: bool = True,
    rebuild=None,
) -> None:
    """Worker-side loop (runs in the child). Confines the process, announces
    itself, then serves requests until shutdown or EOF.

    ``rebuild`` is an optional zero-argument callable that returns a fresh
    registry, inherited across the fork. It backs the ``reload`` command, which
    exists so a refresh can make dispatch-time enforcement current — the `type`
    enum is resolved from the ontology, and a worker still holding the old one
    would reject a class the form now offers.

    **Rebuilding in place rather than re-forking is deliberate.** Forking a new
    worker from the running server would mean `os.fork()` in a process that by
    then has a threadpool, which risks a child deadlocked on a lock another
    thread held at fork time — the hazard `create_app` forks early to avoid.
    A reload message keeps the single early fork and changes only what the
    already-confined child holds.
    """
    rfile = sock.makefile("rb")
    sandbox = Sandbox.open(sandbox_root, create=True)
    fileops = FileOps(sandbox)

    abi = landlock_abi()
    enforced = False
    if enforce_landlock and abi >= 1:
        try:
            restrict_process(sandbox_root)
            enforced = True
        except LandlockError:
            enforced = False  # ran, but could not confine
    _send(sock, {"cmd": "hello", "landlock_abi": abi, "enforced": enforced})

    for line in rfile:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        cmd = req.get("cmd")
        if cmd == "shutdown":
            break
        if cmd == "reload":
            ok, detail = True, ""
            if rebuild is None:
                ok, detail = False, "worker has no rebuild hook"
            else:
                try:
                    registry = rebuild()
                except Exception as exc:  # a bad ontology must not kill the worker
                    ok, detail = False, f"{type(exc).__name__}: {exc}"
            _send(sock, {"id": req.get("id"), "ok": ok, "error": detail,
                         "tools": registry.names()})
            continue
        if cmd != "call":
            continue

        events: list[dict] = []

        def audit(op: str, args: dict, outcome: str) -> None:
            events.append({"op": op, "args": args, "outcome": outcome})

        dr = registry.dispatch(req.get("tool"), req.get("args") or {}, fileops, audit=audit)
        _send(
            sock,
            {
                "id": req.get("id"),
                "ok": dr.ok,
                "result": dr.result,
                "error": dr.error,
                "audit": events,
            },
        )


class WorkerClient:
    """Parent-side handle to a hardened worker. Forks the worker at
    construction, then routes tool calls to it and persists returned audit
    events to an out-of-sandbox :class:`~cwva_dashboard.audit.AuditLog`.
    """

    def __init__(
        self,
        sandbox_root: str | os.PathLike[str],
        registry: ToolRegistry,
        *,
        actor: str = "agent",
        audit: Any | None = None,
        enforce_landlock: bool = True,
        rebuild=None,
    ):
        self._registry = registry
        self._audit = audit
        self._actor = actor
        self._next_id = 0
        self._closed = False

        parent_sock, child_sock = socket.socketpair()
        pid = os.fork()
        if pid == 0:  # child
            parent_sock.close()
            try:
                serve_worker(
                    child_sock, str(sandbox_root), registry,
                    enforce_landlock=enforce_landlock, rebuild=rebuild,
                )
            except BaseException:
                pass
            finally:
                os._exit(0)

        # parent
        child_sock.close()
        self._pid = pid
        self._sock = parent_sock
        self._rfile = parent_sock.makefile("rb")

        hello = json.loads(self._rfile.readline())
        self.landlock_abi: int = hello.get("landlock_abi", 0)
        self.landlock_enforced: bool = hello.get("enforced", False)

    def reload(self) -> dict:
        """Ask the worker to rebuild its registry from the ontology on disk.

        This is what makes a refresh reach *enforcement*: the form's `type`
        options and `validate_args`' accepted set are resolved from the same
        model, so they must move together or the form offers what dispatch
        rejects.
        """
        if self._closed:
            raise RuntimeError("worker client is closed")
        self._next_id += 1
        _send(self._sock, {"cmd": "reload", "id": self._next_id})
        return json.loads(self._rfile.readline())

    def call(self, tool: str, **args: Any) -> dict:
        """Invoke a tool in the worker and return the response dict
        (``ok``/``result``/``error``). Audit events are persisted here, in the
        unconfined parent."""
        if self._closed:
            raise RuntimeError("worker client is closed")
        self._next_id += 1
        _send(self._sock, {"cmd": "call", "id": self._next_id, "tool": tool, "args": args})
        resp = json.loads(self._rfile.readline())
        if self._audit is not None:
            for ev in resp.get("audit", []):
                self._audit.record(
                    ev["op"], ev.get("args", {}), ev.get("outcome", "ok"), actor=self._actor
                )
        return resp

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            _send(self._sock, {"cmd": "shutdown"})
        except OSError:
            pass
        try:
            os.waitpid(self._pid, 0)
        except ChildProcessError:
            pass
        try:
            self._rfile.close()
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "WorkerClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
