"""cwva_dashboard.media: reading schema:duration out of the file itself.

Two properties matter more than exact numbers. First, **every failure path
returns None** — the probe is a convenience, and a deployment without ffmpeg
must degrade to typing the value rather than to a broken form. Second, it is
**trusted-side only**: it execs, and the confined worker has no exec (law 2), so
it must never appear in the tool registry.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from cwva_dashboard.media import ffprobe_available, iso8601_duration, probe_duration

from conftest import TEST_DOMAIN


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (34, "PT34S"),
        (0, "PT0S"),          # a zero-length clip still needs a legal literal
        (0.4, "PT0S"),
        (33.7, "PT34S"),      # rounds, so a 33.7s clip is not reported as 33
        (62, "PT1M2S"),
        (3600, "PT1H"),
        (3725, "PT1H2M5S"),
    ],
)
def test_iso8601_duration(seconds, expected):
    assert iso8601_duration(seconds) == expected


def test_iso8601_durations_are_accepted_by_dispatch():
    """What the probe PRODUCES must be what dispatch ACCEPTS — otherwise the
    automatic path fails validation the manual path passes."""
    from cwva_dashboard.tools.base import _is_duration

    for s in (0, 0.4, 34, 62, 3600, 3725, 86399):
        assert _is_duration(iso8601_duration(s)), s


def test_probe_returns_none_for_missing_file(tmp_path):
    assert probe_duration(tmp_path / "nope.mp4") is None


def test_probe_returns_none_for_a_non_video(tmp_path):
    junk = tmp_path / "notavideo.mp4"
    junk.write_bytes(b"this is not a video" * 100)
    assert probe_duration(junk) is None


def test_probe_returns_none_when_ffprobe_is_absent(tmp_path, monkeypatch):
    """The CE-without-ffmpeg case: no probe, no crash, manual field takes over."""
    monkeypatch.setattr("cwva_dashboard.media.shutil.which", lambda _: None)
    assert not ffprobe_available()
    assert probe_duration(tmp_path / "anything.mp4") is None


def test_probe_returns_none_when_ffprobe_hangs(tmp_path, monkeypatch):
    def _timeout(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffprobe", timeout=1)

    monkeypatch.setattr("cwva_dashboard.media.shutil.which", lambda _: "/usr/bin/ffprobe")
    monkeypatch.setattr("cwva_dashboard.media.subprocess.run", _timeout)
    assert probe_duration(tmp_path / "slow.mp4") is None


@pytest.mark.skipif(
    not (shutil.which("ffprobe") and shutil.which("ffmpeg")),
    reason="ffmpeg/ffprobe not installed",
)
@pytest.mark.parametrize(
    "name,codec",
    [("clip.mp4", []), ("clip.webm", ["-c:v", "libvpx"]), ("clip.ogv", ["-c:v", "libtheora"])],
)
def test_probe_reads_real_files_in_every_offered_container(tmp_path, name, codec):
    """All three offered kinds really probe — the picker must not offer a format
    the duration step then silently gives up on."""
    out = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi",
         "-i", "testsrc=duration=3:size=64x64:rate=10", *codec, str(out)],
        check=True, capture_output=True,
    )
    assert probe_duration(out) == "PT3S"


def test_probe_is_not_a_registry_tool():
    """Law 2: no exec in the agent's vocabulary. The probe shells out, so it
    lives in the trusted layer and the route passes its answer to the tool as an
    ordinary argument."""
    from cwva_dashboard.tools.fileops_tools import build_default_registry

    names = build_default_registry(domain=TEST_DOMAIN).names()
    assert not any("duration" in n or "probe" in n or "media" in n for n in names)
