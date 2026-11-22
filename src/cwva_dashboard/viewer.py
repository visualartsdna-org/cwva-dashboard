"""The cwva-py VIEWER: the published site's own server, run over THIS sandbox.

So a change can be seen in cwva-py before it is distributed (Rick,
2026-11-19: "whereas now I must distribute and refresh an environment in order
to see the changes"). Each dashboard runs its own viewer over its own sandbox:
QA's over QA's drafts, production's over production's. Drafts included, since
those are the point.

**Trusted-orchestrator machinery, never a registry tool**, like Instance
Control (CLAUDE.md law 11): it starts a process, and nothing the agent holds
may do that (law 2). The process is cwva-py itself, confined by
``viewer_launch.py``:

* **read-only to the sandbox, by Landlock.** cwva-py's loader deletes its data
  folders and re-downloads them from the bucket when started with a ``cloud``
  block — over a sandbox, every draft gone. The config below never sets one and
  the environment carries no bucket or credentials, but the OS is what
  guarantees it: the process can write only its scratch folder.
* **loopback only**, because it serves undistributed drafts.
* **no outbound effect**: no ``cloud``, no ``referenceModel``, no ``agentUrl``,
  no ``GCP_BUCKET``, ``--test`` (no metrics upload on shutdown). It cannot read
  the cloud credentials either: they are outside every path it may read.

The scratch folder sits beside the sandbox, like the audit log, never in it.
"""

from __future__ import annotations

import json
import os
import platform
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

__all__ = ["ViewerSettings", "Viewer", "ViewerError"]

_LAUNCHER = Path(__file__).resolve().parent / "viewer_launch.py"
#: cwva-py finds html/, static/, dist/ and res/ under its `dir`, which must be
#: the writable scratch (its load lock lives there too), so these are linked in.
_LINKED = ("html", "static", "dist", "res")
_ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TZ")


class ViewerError(RuntimeError):
    pass


@dataclass(frozen=True)
class ViewerSettings:
    cwva_py: str = "~/cwva-py/main"
    python: str = ""           # default: <cwva_py>/.venv/bin/python
    port: int = 8091
    start_timeout_s: int = 120

    @classmethod
    def from_config(cls, cfg: dict | None) -> "ViewerSettings | None":
        """None when the config names no viewer: the card then says so."""
        v = (cfg or {}).get("viewer")
        if not v:
            return None
        return cls(cwva_py=str(v.get("cwva_py", cls.cwva_py)),
                   python=str(v.get("python", "")),
                   port=int(v.get("port", cls.port)),
                   start_timeout_s=int(v.get("start_timeout_s", cls.start_timeout_s)))

    @property
    def cwva_dir(self) -> Path:
        return Path(os.path.expanduser(self.cwva_py))

    @property
    def interpreter(self) -> Path:
        if self.python:
            return Path(os.path.expanduser(self.python))
        return self.cwva_dir / ".venv" / "bin" / "python"


class Viewer:
    def __init__(self, settings: ViewerSettings, *, sandbox_root, layout, domain: str,
                 scratch: Path, label: str = "", colour: str = ""):
        self.settings = settings
        self.sandbox = Path(sandbox_root).resolve()
        self.layout = layout
        self.domain = domain
        self.scratch = Path(scratch)
        if self.scratch.resolve().is_relative_to(self.sandbox):
            raise ViewerError("the viewer's scratch folder must be outside the sandbox")
        self.label = label
        self.colour = colour
        self._proc: subprocess.Popen | None = None
        self._started_at: float | None = None

    # -- paths ---------------------------------------------------------------
    @property
    def url(self) -> str:
        return f"http://localhost:{self.settings.port}"

    @property
    def log_path(self) -> Path:
        return self.scratch / "viewer.log"

    @property
    def _pid_path(self) -> Path:
        return self.scratch / "viewer.pid"

    @property
    def banner(self) -> str:
        """On every page the viewer serves: it is not the published site."""
        who = f"{self.label} · " if self.label else ""
        return f"{who}DASHBOARD VIEW — this sandbox, drafts included; not published"

    def _dir(self, kind: str) -> str:
        return str(self.sandbox / self.layout.dir(kind).strip("/"))

    def cwva_config(self) -> dict:
        """The cwva-py config, generated every start and never edited by hand,
        because the safety of the run depends on what it leaves out."""
        port = self.settings.port
        return {
            "port": port,
            "host": f"http://localhost:{port}",
            "dir": str(self.scratch),
            "cloud": None,
            "referenceModel": None,
            "agentUrl": None,
            "data": self._dir("work_ttl"),
            "tags": self._dir("tags_ttl"),
            "model": self._dir("model_ttl"),
            "vocab": self._dir("vocab_ttl"),
            "images": self._dir("image"),
            "documents": self._dir("document"),
            "thumbnails": str(self.scratch / "thumbnails"),
            "domain": self.domain,
            "verbose": True,
            "clobber": False,
            "multithreaded": False,
            "primaryHost": True,
            "sparql": True,
        }

    def _env(self) -> dict:
        env = {k: os.environ[k] for k in _ENV_KEEP if k in os.environ}
        env["TMPDIR"] = str(self.scratch / "tmp")
        env["PYTHONUNBUFFERED"] = "1"
        return env  # no GCP_BUCKET, no credentials, no API keys

    # -- lifecycle -----------------------------------------------------------
    def _port_busy(self) -> bool:
        with socket.socket() as s:
            s.settimeout(0.5)
            return s.connect_ex(("127.0.0.1", self.settings.port)) == 0

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _reap_orphan(self) -> None:
        """A viewer left by a dashboard that died without stopping it."""
        try:
            pid = int(self._pid_path.read_text().strip())
        except (OSError, ValueError):
            return
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
        except OSError:
            cmd = b""
        if b"viewer_launch.py" in cmd and str(self.scratch).encode() in cmd:
            try:
                os.killpg(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            for _ in range(50):
                if not Path(f"/proc/{pid}").exists():
                    break
                time.sleep(0.1)
        self._pid_path.unlink(missing_ok=True)

    def start(self) -> dict:
        if self._alive():
            return self.status()
        if platform.system() != "Linux":
            raise ViewerError("the viewer needs Landlock (Linux) to run cwva-py "
                              "read-only; it will not run unconfined")
        s = self.settings
        if not (s.cwva_dir / "main.py").is_file():
            raise ViewerError(f"no cwva-py at {s.cwva_dir} (config viewer.cwva_py)")
        if not s.interpreter.is_file():
            raise ViewerError(f"no Python at {s.interpreter} (config viewer.python)")
        self.scratch.mkdir(parents=True, exist_ok=True)
        self._reap_orphan()
        if self._port_busy():
            raise ViewerError(f"port {s.port} is already in use: is another cwva-py "
                              "running there? (config viewer.port)")
        for sub in ("thumbnails", "tmp"):
            (self.scratch / sub).mkdir(exist_ok=True)
        for name in _LINKED:
            link, target = self.scratch / name, s.cwva_dir / name
            if link.is_symlink() or link.exists():
                if link.is_symlink() and link.resolve() == target.resolve():
                    continue
                link.unlink()
            if target.exists():
                link.symlink_to(target)
        cfg_path = self.scratch / "cwva-view.rson"
        cfg_path.write_text(json.dumps(self.cwva_config(), indent=2))
        if self.log_path.exists():
            self.log_path.replace(self.scratch / "viewer.previous.log")
        log = open(self.log_path, "wb")
        try:
            self._proc = subprocess.Popen(
                [str(s.interpreter), str(_LAUNCHER), "--cwva", str(s.cwva_dir),
                 "--config", str(cfg_path), "--scratch", str(self.scratch),
                 "--sandbox", str(self.sandbox),
                 "--banner", self.banner, "--banner-colour", self.colour],
                cwd=str(self.scratch), env=self._env(), stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        finally:
            log.close()
        self._pid_path.write_text(str(self._proc.pid))
        self._started_at = time.time()
        return self.status()

    def stop(self) -> dict:
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
            except ProcessLookupError:
                pass
        self._pid_path.unlink(missing_ok=True)
        self._started_at = None
        return self.status()

    def reload(self) -> dict:
        """cwva-py's own refresh is token-gated and would also look to a
        bucket; restarting re-reads the sandbox and nothing else."""
        self.stop()
        return self.start()

    def _ready(self) -> bool:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.settings.port}/status", timeout=1) as r:
                return r.status == 200
        except Exception:
            return False

    def status(self) -> dict:
        alive = self._alive()
        exited = None if self._proc is None or alive else self._proc.returncode
        if alive:
            state = "running" if self._ready() else "loading"
        else:
            state = "stopped" if exited in (None, 0, -15) else "failed"
        return {
            "state": state,
            "url": self.url,
            "port": self.settings.port,
            "pid": self._proc.pid if alive else None,
            "started_at": self._started_at,
            "exit_code": exited,
            "sandbox": str(self.sandbox),
        }

    def log_tail(self, lines: int = 40) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        return "\n".join(text.splitlines()[-lines:])
