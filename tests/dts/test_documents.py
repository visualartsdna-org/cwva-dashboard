"""Reading a criticism document: the prompt, and whether a quote is real.

Both are jobs the dashboard does rather than the agent (§9.6) — one because a
model should not be trusted to verify its own evidence, the other because it
is a heading match.
"""

from __future__ import annotations

from cwva_dashboard.dts.documents import (clean_text, context_around, first_prompt,
                                           verify_phrase)

CHATGPT = """# Art criticism sculpture

## Prompt:

Write an art criticism of this digital sculpture viewed in <modelviewer>.

[Attachment: Prestress-TheThreeGraces.pdf]

## Response:

The work presents three faceted figures.

## Prompt:

A second question nobody asked for.
"""

CLAUDE = """# Digital sculpture art criticism

**Created:** 9/26/2026 12:12:49

## User:

> 9/26/2026 12:12:51

> File: Prestress-TheThreeGraces.pdf

Write an art criticism of this digital sculpture viewed in <modelviewer>.

## Assistant:

> Weighing visual weaknesses like merged silhouettes and faint tension cables.
"""


# -- the first human turn ----------------------------------------------------


def test_the_CHATGPT_heading_is_read():
    assert first_prompt(CHATGPT).startswith("Write an art criticism")


def test_the_CLAUDE_heading_is_read_TOO():
    """Rick's instruction named `## Prompt:`, which is ChatGPT's heading. The
    Claude export writes `## User:` — keying on one would have produced a
    silently empty definition for the other."""
    assert first_prompt(CLAUDE).startswith("Write an art criticism")


def test_the_QUOTED_METADATA_is_not_the_prompt():
    """Timestamps and attachment names precede the prose in a Claude export,
    and blank lines between them must not count as content — counting them
    read the real document as prompt-less."""
    prompt = first_prompt(CLAUDE)

    assert "9/26/2026" not in prompt
    assert "Prestress-TheThreeGraces.pdf" not in prompt


def test_the_ATTACHMENT_MARKERS_after_the_prose_end_it():
    assert "[Attachment:" not in first_prompt(CHATGPT)


def test_only_the_FIRST_turn_is_taken():
    assert "second question" not in first_prompt(CHATGPT)


def test_a_document_with_no_human_turn_says_so_by_being_EMPTY():
    """The caller treats this as a document it cannot describe. A blank
    `skos:definition` would be worse than a loud failure."""
    assert first_prompt("# Just a title\n\nSome prose.\n") == ""


def test_a_long_prompt_can_be_capped():
    assert len(first_prompt(CHATGPT, limit=20)) <= 20


# -- grounding verification --------------------------------------------------


def test_a_phrase_that_is_THERE_verifies():
    assert verify_phrase(CLAUDE, "merged silhouettes").verified


def test_a_phrase_that_is_NOT_there_does_not():
    """The case the mechanism exists to catch: a model inventing its evidence.
    The agent's own output already reports it as [NOT FOUND]."""
    assert not verify_phrase(CLAUDE, "a phrase nobody wrote").verified


def test_LINE_WRAPPING_does_not_break_a_quote():
    text = "the eye continually\noscillates between surface\nand depth"

    assert verify_phrase(text, "eye continually oscillates between surface").verified


def test_a_CURLED_APOSTROPHE_still_matches_a_straight_one():
    """An exporter substitutes typography; the model quotes what it read."""
    assert verify_phrase("the painting’s logic", "the painting's logic").verified
    assert verify_phrase("the painting's logic", "the painting’s logic").verified


def test_a_DIFFERENT_WORD_still_fails():
    """Forgiving about whitespace and quotes, strict about everything else."""
    assert not verify_phrase(CLAUDE, "merged shadows").verified


def test_an_empty_phrase_is_not_grounded():
    assert not verify_phrase(CLAUDE, "   ").verified


# -- the context a curator reads ---------------------------------------------


def test_the_context_SURROUNDS_the_phrase():
    """It was taken from a flattened copy and mapped back proportionally,
    which landed in the wrong paragraph — a phrase in the middle of a 23 KB
    document reported context from its opening prompt."""
    ctx = context_around(CLAUDE, "merged silhouettes")

    assert "merged silhouettes" in ctx
    assert "Weighing visual weaknesses" in ctx


def test_the_context_is_ONE_LINE():
    """A curator reads it in a table cell."""
    assert "\n" not in context_around(CLAUDE, "merged silhouettes")


def test_a_truncated_context_SAYS_it_is_truncated():
    long = "x " * 400 + "the phrase here " + "y " * 400

    ctx = context_around(long, "the phrase here")

    assert ctx.startswith("...") and ctx.endswith("...")


def test_an_ungrounded_phrase_has_no_context():
    assert context_around(CLAUDE, "not present") == ""


# -- whose words are these? (Rick, 2026-09-30) -------------------------------
#
# A criticism export is a CONVERSATION, and the two sides are not
# interchangeable evidence: "I was the one to say 'reminiscent of Raphael's
# golden apples', which is the grounding phrase, not the agent writing the
# criticism. The agent then picked up the association. Concepts originating
# from my text contributions I tend to leave out."

TRANSCRIPT = """# An export

Front matter belonging to neither.

## User:

> 9/26/2026 12:12

I think the figures are reminiscent of Raphael's golden apples.

## Assistant:

The faceted metallic bodies read as one mass from several angles.

## User:

And the green cables are the life force.

## Assistant:

The critic agrees the green cables are the life force, and says so too.
"""


def test_a_transcript_cuts_into_turns():
    from cwva_dashboard.dts.documents import turns

    got = turns(TRANSCRIPT)

    assert [s for s, _ in got] == ["user", "critic", "user", "critic"]


def test_FRONT_MATTER_belongs_to_neither():
    from cwva_dashboard.dts.documents import turns

    assert not any("Front matter" in body for _s, body in turns(TRANSCRIPT))


def test_a_phrase_from_the_ARTISTS_turn_is_attributed_to_them():
    from cwva_dashboard.dts.documents import speaker_of

    assert speaker_of(TRANSCRIPT, "reminiscent of Raphael's golden apples") == "user"


def test_a_phrase_from_the_CRITICS_turn_is_attributed_to_them():
    from cwva_dashboard.dts.documents import speaker_of

    assert speaker_of(TRANSCRIPT, "faceted metallic bodies") == "critic"


def test_the_CRITIC_WINS_a_tie():
    """Quoting the artist back at them is still the critic using the words,
    and the association it grounds is theirs to have made."""
    from cwva_dashboard.dts.documents import speaker_of

    assert speaker_of(TRANSCRIPT, "green cables are the life force") == "critic"


def test_a_phrase_in_NEITHER_turn_is_attributed_to_neither():
    from cwva_dashboard.dts.documents import speaker_of

    assert speaker_of(TRANSCRIPT, "a phrase nobody wrote") == ""
    assert speaker_of(TRANSCRIPT, "Front matter belonging") == ""


# -- the sentences around a phrase, which is what a phrase cannot show -------
#
# `Color symbolism` was proposed on the phrase "simple symbolic diagram",
# which IS in the document — inside "Yet the effect avoids becoming a simple
# symbolic diagram". The prompt's rule 9 forbids deriving a concept from what
# the critic says the work is NOT, and the grounding check cannot see it: the
# words are there. Only a reader can, and only if the screen shows them the
# sentence (Rick, 2026-10-01).

PARAGRAPHS = """## Assistant:

The first achievement is its kinetic coherence. Although the sculpture is
static, almost nothing appears at rest. The figures run and twist.

The geometry acquires an almost bodily polarity. Yet the effect avoids becoming
a simple symbolic diagram because the figures cross that reading. A third
sentence follows.

## User:

A later turn that must never appear in the context above.
"""


def test_the_NEGATION_is_visible_in_the_context():
    """The case the whole feature exists for."""
    from cwva_dashboard.dts.documents import sentences_around

    got = sentences_around(PARAGRAPHS, "simple symbolic diagram")

    assert "avoids becoming" in got


def test_it_returns_the_phrase_SENTENCE_plus_its_neighbours():
    from cwva_dashboard.dts.documents import sentences_around

    got = sentences_around(PARAGRAPHS, "kinetic coherence")

    assert "The first achievement" in got
    assert "almost nothing appears at rest" in got


def test_it_STOPS_at_the_paragraph():
    """A window spilling across a blank line would reach into another
    speaker's turn and attribute to the critic a sentence about something
    else."""
    from cwva_dashboard.dts.documents import sentences_around

    got = sentences_around(PARAGRAPHS, "cross that reading")

    assert "must never appear" not in got
    assert "appears at rest" not in got, "nor backwards into the previous one"


def test_MARKDOWN_FURNITURE_is_stripped():
    from cwva_dashboard.dts.documents import sentences_around

    got = sentences_around("## Assistant:\n\n> The work is faceted. It reads as one.",
                           "faceted")

    assert not got.startswith(">") and "##" not in got


def test_it_is_ONE_LINE():
    from cwva_dashboard.dts.documents import sentences_around

    assert "\n" not in sentences_around(PARAGRAPHS, "kinetic coherence")


def test_a_phrase_that_is_not_there_has_no_context():
    from cwva_dashboard.dts.documents import sentences_around

    assert sentences_around(PARAGRAPHS, "words nobody wrote") == ""


def test_the_phrase_is_SPLIT_OUT_so_a_renderer_can_mark_it():
    from cwva_dashboard.dts.documents import sentences_around, split_on_phrase

    context = sentences_around(PARAGRAPHS, "simple symbolic diagram")
    before, match, after = split_on_phrase(context, "simple symbolic diagram")

    assert match == "simple symbolic diagram"
    assert "avoids becoming" in before and after
    assert before + match + after == context, "and nothing is lost in the split"


def test_a_split_that_cannot_find_the_phrase_returns_it_WHOLE():
    """Degrading to unmarked prose beats degrading to nothing."""
    from cwva_dashboard.dts.documents import split_on_phrase

    before, match, after = split_on_phrase("some context", "absent")

    assert (before, match, after) == ("some context", "", "")


# -- an attachment is not prose (2026-10-05) --------------------------------
#
# Rick, doing DTS for a watercolour: the generated criticism entity's
# `skos:definition` opened with
# `![IMG_2103.JPG](https://chatgpt.com/backend-api/estuary/content?…&sig=…)`.
# Newer ChatGPT exports embed the artist's attachment as markdown instead of
# writing `[Attachment: …]`, and only the bracketed forms were recognised.

EMBEDDED = """# Art criticism watercolor

## Prompt:
![IMG_2103.JPG](https://chatgpt.com/backend-api/estuary/content?id=file_00000000c2a&fn=IMG_2103.JPG&cd=attachment&sig=1858bd91d646f4f5d552ec61ab901491246b82185103013a9741d3fd1f0b6e64&v=0)

write an art criticism of this watercolor, Covered Bridge, 15x11 on 300 lb cold press

## Response:

The reflection is nearly the equal of the landscape.
"""


def test_the_definition_is_the_PROMPT_not_the_attachment():
    assert first_prompt(EMBEDDED) == (
        "write an art criticism of this watercolor, Covered Bridge, "
        "15x11 on 300 lb cold press")


def test_the_SIGNED_TOKEN_does_not_reach_the_record():
    """These records converge to a published catalogue, and the URL carries a
    64-character expiring access signature."""
    assert "sig=" not in first_prompt(EMBEDDED)
    assert "chatgpt.com" not in first_prompt(EMBEDDED)


def test_the_work_NAME_survives_the_limited_window():
    """`match_work` reads `first_prompt(limit=400)`. The embed was 230 of the
    315 characters, so a second attachment would push the work's name out of
    the window and the criticism would be tagged onto nothing, silently."""
    two = EMBEDDED.replace("## Prompt:\n", "## Prompt:\n![IMG_2104.JPG](https://chatgpt.com/backend-api/estuary/content?id=file_00000000c2b&fn=IMG_2104.JPG&cd=attachment&sig=2958cd91d646f4f5d552ec61ab901491246b82185103013a9741d3fd1f0b6e65&v=0)\n", 1)

    assert "Covered Bridge" in first_prompt(two, limit=400)


def test_an_INLINE_embed_goes_too():
    """`_METADATA` only sees a line that STARTS with one; `clean_text` is the
    boundary that catches it mid-sentence."""
    assert clean_text("before ![x](http://h/a?sig=deadbeef) after") == "before after"


def test_a_markdown_LINK_is_LEFT_ALONE():
    """`[text](url)` in a criticism is prose with a citation attached. Dropping
    either half would change what the critic said, which is the line this
    function does not cross."""
    said = "see [the Seneca reading](https://en.wikipedia.org/wiki/De_Beneficiis)"

    assert clean_text(said) == said


def test_the_OLD_attachment_syntax_still_works():
    """`[Attachment: …]` is what the export wrote until recently, and the 60
    documents already processed carry it."""
    old = EMBEDDED.replace(
        "![IMG_2103.JPG](https://chatgpt.com/backend-api/estuary/content?id=file_00000000c2a&fn=IMG_2103.JPG&cd=attachment&sig=1858bd91d646f4f5d552ec61ab901491246b82185103013a9741d3fd1f0b6e64&v=0)",
        "[Attachment: IMG_2103.JPG]")

    assert first_prompt(old).startswith("write an art criticism")


def test_a_prompt_that_is_ONLY_an_attachment_describes_nothing():
    """And must not become an entity: `propose_entity` refuses a document with
    no human turn, and an embed alone is not one."""
    only = "# T\n\n## Prompt:\n![x](http://h/a)\n\n## Response:\n\nprose\n"

    assert first_prompt(only) == ""
