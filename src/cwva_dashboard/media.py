"""Reading facts out of media files — trusted-orchestrator only.

``schema:duration`` is a fact about the file, not something a person should have
to remember, so it is read from the video itself with ``ffprobe``.

**This cannot be a registry tool.** It shells out, and the confined worker has
no exec (law 2) — so like ingest and the promotion tail it lives in the trusted
layer, and the route passes the answer to the record tool as an ordinary
argument. The tool stays pure and the agent gains no exec by the back door.

**ffprobe is optional, never required.** A CE install without ffmpeg simply gets
the manual field, so absence degrades to typing rather than to failure. Every
error path returns ``None`` for the same reason: a probe that cannot answer must
not block an entry.
"""

from __future__ import annotations

import json
import shutil
import subprocess

__all__ = ["ffprobe_available", "probe_duration", "iso8601_duration"]

_TIMEOUT_S = 20


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def iso8601_duration(seconds: float) -> str:
    """Seconds -> an ``xsd:duration`` literal such as ``PT1H2M34S``.

    Whole seconds: the existing record uses ``PT34S``, and sub-second precision
    on a gallery video is noise. Rounds rather than truncates so a 33.7s clip
    does not become 33.
    """
    total = max(0, int(round(seconds)))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    out = "PT"
    if hours:
        out += f"{hours}H"
    if minutes:
        out += f"{minutes}M"
    if secs or out == "PT":
        out += f"{secs}S"
    return out


def probe_duration(path) -> str | None:
    """The clip's duration as an ``xsd:duration`` literal, or ``None``.

    ``None`` covers every "cannot answer" case — ffprobe absent, unreadable
    file, unparseable output, a container that does not carry a duration — so
    the caller has exactly one thing to check and the form falls back to the
    manual field.
    """
    if not ffprobe_available():
        return None
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
        )
        if proc.returncode != 0:
            return None
        raw = json.loads(proc.stdout).get("format", {}).get("duration")
        if raw in (None, "", "N/A"):
            return None
        return iso8601_duration(float(raw))
    except (OSError, ValueError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
