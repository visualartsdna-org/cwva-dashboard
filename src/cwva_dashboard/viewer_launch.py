"""Run cwva-py over a sandbox, confined READ-ONLY to it. A standalone script.

Started by :mod:`cwva_dashboard.viewer` with **cwva-py's own interpreter**, so
it imports nothing from this package: the one thing it needs, the Landlock
primitive, is loaded from its file (``sandbox/broker.py`` is stdlib-only).

Why the confinement, when cwva-py "is read-only": it is read-only towards its
SOURCE, not towards its folders. Started with a ``cloud`` block and
``GCP_BUCKET`` in its environment, its loader DELETES the data and tags folders
and re-downloads them from the bucket (``rdf/db_mgr.py: _clear_gcp_folders``).
Pointed at a sandbox, that is every draft gone and production's records in
their place, with nothing in git to say so. The generated config never sets
``cloud`` and the environment is scrubbed, but a config is a promise; Landlock
makes it a fact: after this runs, the process cannot write anywhere but its
scratch folder, whatever any later code tries.

    python viewer_launch.py --cwva DIR --config CFG --scratch DIR \
        --sandbox DIR [--ro DIR ...]
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import runpy
import sys
from pathlib import Path


def _load(rel: str, name: str):
    """A module of this package by FILE: this script runs under cwva-py's
    interpreter, where the package is not installed."""
    path = Path(__file__).resolve().parent / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses resolve the module by name
    spec.loader.exec_module(mod)
    return mod


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cwva", required=True, help="cwva-py checkout (holds main.py)")
    ap.add_argument("--config", required=True, help="generated cwva-py config")
    ap.add_argument("--scratch", required=True, help="the ONLY writable folder")
    ap.add_argument("--sandbox", required=True, help="read-only: the sandbox")
    ap.add_argument("--ro", action="append", default=[], help="more read-only paths")
    ap.add_argument("--banner", default="", help="strip shown on every HTML page")
    ap.add_argument("--banner-colour", default="")
    a = ap.parse_args(argv)

    cwva = Path(a.cwva).resolve()
    broker = _load("sandbox/broker.py", "_cwva_viewer_broker")
    # The dashboard's own banner, loaded BEFORE confinement like everything
    # from this package (it needs only starlette, which cwva-py has).
    banner = (_load("ux/banner.py", "_cwva_viewer_banner") if a.banner else None)
    ro = [a.sandbox, str(cwva), "/etc", *a.ro]
    result = broker.restrict_process(a.scratch, extra_ro_paths=tuple(ro))
    print(f"[viewer] confined: write {a.scratch} only; read-only {ro} "
          f"(landlock abi {result.abi})", flush=True)

    # Loopback only. cwva-py's main.py binds 0.0.0.0, which would serve
    # undistributed drafts to the network; the viewer is for this machine.
    # And a banner on every page, because otherwise this looks exactly like
    # the published site (Rick, 2026-11-19): added around cwva-py's app here,
    # so the site itself never carries it.
    try:
        import uvicorn

        _run = uvicorn.run

        def _local(app, *args, **kw):
            kw["host"] = "127.0.0.1"
            if banner is not None:
                app = banner.EnvironmentBanner(app, label=a.banner,
                                               colour=a.banner_colour)
            return _run(app, *args, **kw)

        uvicorn.run = _local
    except ImportError:
        pass

    os.chdir(a.scratch)  # cwva-py's load lock lives in its `dir`, the scratch
    sys.path.insert(0, str(cwva))
    sys.argv = [str(cwva / "main.py"), "-cfg", a.config, "--test"]
    runpy.run_path(str(cwva / "main.py"), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
