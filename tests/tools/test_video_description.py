"""A VideoObject gets a description even when nobody types one.

Rick, 2026-09-16: "Can you do a reasonable summary for the video from context
and no sampling, something relatively generic, I'm more concerned about the
video object metadata being missing than not being specific enough."

So the sentence says what the RECORD knows — which work, what class, how long —
and claims nothing about what the footage shows. Describing content needs the
file (AI backlog §10.7) and the user's correction (§14.7); a sentence that is
merely unspecific can be improved later, while one that is confidently wrong
about a work's own video has to be noticed first.
"""

from __future__ import annotations

import pytest

from cwva_dashboard.tools.record_tools import video_description


@pytest.mark.parametrize("label,cls,duration,expected", [
    ("Last Supper", "BlenderComposition", "PT34S",
     'Video of the Blender Composition "Last Supper". Running time 34 seconds.'),
    ("Fairy Pool", "Watercolor", "",
     'Video of the Watercolor "Fairy Pool".'),
    ("Orbit", "LindenmayerSystemImage", "PT1M5S",
     'Video of the Lindenmayer System Image "Orbit". Running time 1 minute, 5 seconds.'),
])
def test_it_says_what_the_record_knows(label, cls, duration, expected):
    assert video_description(label, cls, duration) == expected


def test_a_class_keeps_the_ONTOLOGYS_capitalisation():
    """`Blender` is a proper noun. Lowercasing a class name to make it read like
    prose turns a product into a word, and the ontology's own casing is the
    closest thing to an authority here."""
    assert "Blender Composition" in video_description("x", "BlenderComposition")
    assert "blender" not in video_description("x", "BlenderComposition")


def test_nothing_to_say_says_NOTHING():
    """An empty property beats a sentence with a hole in it."""
    assert video_description() == ""
    assert video_description("", "Watercolor") == ""


def test_a_work_with_no_class_is_still_describable():
    assert video_description("Untitled", "", "PT2S") == \
        'Video of "Untitled". Running time 2 seconds.'


@pytest.mark.parametrize("duration,expected", [
    ("PT34S", "Running time 34 seconds."),
    ("PT1S", "Running time 1 second."),
    ("PT2M", "Running time 2 minutes."),
    ("PT1H2M3S", "Running time 1 hour, 2 minutes, 3 seconds."),
    ("PT4.5S", "Running time 4.5 seconds."),
])
def test_the_running_time_reads_as_prose(duration, expected):
    assert video_description("W", "", duration).endswith(expected)


@pytest.mark.parametrize("duration", ["", "34", "PT", "eleventy", None, "P1D"])
def test_a_duration_it_cannot_read_is_LEFT_OUT(duration):
    """Only the shapes the ffprobe path actually emits are parsed. A description
    is not the place to discover that a duration was malformed."""
    out = video_description("W", "", duration)

    assert out == 'Video of "W".'


def test_a_TYPED_description_always_wins(tmp_path):
    """Derivation fills a hole; it never argues with the user."""
    from rdflib import Graph, Namespace, URIRef
    from cwva_dashboard.tools.record_tools import _add_video

    SCHEMA = Namespace("https://schema.org/")
    g = Graph()
    subj = URIRef("http://test.example/work/w1")
    _add_video(g, subj, "http://test.example/images/", "Clip.mp4",
               description="A turntable, lit from the left.",
               work_label="Last Supper", type_local="BlenderComposition")

    bn = g.value(subj, SCHEMA.video)
    assert str(g.value(bn, SCHEMA.description)) == "A turntable, lit from the left."
