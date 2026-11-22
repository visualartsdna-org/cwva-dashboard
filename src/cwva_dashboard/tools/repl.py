"""No-AI test harness: invoke tools directly over a hardened worker.

This is the Phase 2 driver that stands in for the agent until the chat loop
lands (Phase 6). It loads the sandbox root from config, starts a
:class:`WorkerClient`, and reads tool calls from stdin so a developer can
exercise the vocabulary by hand:

    $ python -m cwva_dashboard.tools.repl
    landlock: enforced (ABI 3)
    > fs.write {"path": "notes/a.md", "text": "hello", "make_parents": true}
    {"ok": true, "result": {"path": "notes/a.md", "bytes_written": 5, "created": true}}
    > fs.list notes
    ...
    > tools        # print the tool schemas
    > quit

A line is ``<tool-name>`` optionally followed by a JSON object of arguments.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..audit import AuditLog, default_path
from ..rson import load as rson_load
from ..sandbox.worker import WorkerClient
from .fileops_tools import build_default_registry

_DEFAULT_CONFIG = "config/dashboard.rson"


def _load_sandbox_root(config_path: str) -> Path:
    cfg = rson_load(config_path) or {}
    raw = (cfg.get("sandbox") or {}).get("stage_root")
    if not raw:
        raise SystemExit(f"no sandbox.stage_root in {config_path!r}")
    root = Path(os.path.expanduser(raw))
    root.mkdir(parents=True, exist_ok=True)
    return root





def _print_response(resp: dict) -> None:
    slim = {k: resp[k] for k in ("ok", "result", "error") if resp.get(k) is not None or k == "ok"}
    print(json.dumps(slim, ensure_ascii=False))


def run(config_path: str = _DEFAULT_CONFIG, *, enforce_landlock: bool = True) -> None:
    root = _load_sandbox_root(config_path)
    # Identity comes from config here as everywhere else, and from the SAME
    # config the sandbox came from. `load_config()` with no argument read
    # config/dashboard.rson whatever `--config` said, so a REPL pointed at
    # production minted records into QA's sovereign `work:` namespace — the
    # defect `tests/test_script_config_selection.py` exists to catch, invisible
    # to it because that test derives its scope from `scripts/` and this module
    # lives in `src/` (fixed 2026-10-29).
    from ..config import domain as _domain, load_config

    registry = build_default_registry(domain=_domain(load_config(config_path)))
    # Named after the sandbox, so a REPL and a dashboard on the same deployment
    # share one log and two deployments never do. The fixed path this used
    # before gave a production REPL and a running QA dashboard the same file,
    # which breaks the hash chain for the reason `audit.default_path` explains.
    audit = AuditLog(default_path(root), actor="repl")

    with WorkerClient(root, registry, actor="repl", audit=audit, enforce_landlock=enforce_landlock) as wc:
        status = f"enforced (ABI {wc.landlock_abi})" if wc.landlock_enforced else "NOT enforced"
        print(f"sandbox: {root}", file=sys.stderr)
        print(f"landlock: {status}", file=sys.stderr)
        print("type a tool name + JSON args, or 'tools'/'help'/'quit'.", file=sys.stderr)

        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line in ("quit", "exit"):
                break
            if line == "help":
                print("commands: <tool> [json-args] | tools | help | quit", file=sys.stderr)
                continue
            if line == "tools":
                print(json.dumps(registry.schemas(), indent=2, ensure_ascii=False))
                continue

            name, _, rest = line.partition(" ")
            rest = rest.strip()
            if rest.startswith("{"):
                try:
                    args = json.loads(rest)
                except json.JSONDecodeError as exc:
                    print(f"bad JSON args: {exc}", file=sys.stderr)
                    continue
                if not isinstance(args, dict):
                    print("args must be a JSON object", file=sys.stderr)
                    continue
            elif rest:
                # Shorthand: bind a bare argument to the tool's first parameter
                # (e.g. `fs.read a.txt`). Multi-arg tools still need JSON.
                tool = registry.get(name)
                first = next(iter(tool.input_schema.get("properties", {})), None) if tool else None
                args = {first: rest} if first else {}
            else:
                args = {}
            _print_response(wc.call(name, **args))

    audit.close()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=_DEFAULT_CONFIG, help="path to dashboard.rson")
    ap.add_argument(
        "--no-landlock", action="store_true", help="do not confine the worker (dev only)"
    )
    ns = ap.parse_args(argv)
    run(ns.config, enforce_landlock=not ns.no_landlock)


if __name__ == "__main__":
    main()
