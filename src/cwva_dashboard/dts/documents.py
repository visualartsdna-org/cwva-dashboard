"""Reading a criticism document: the prompt that produced it, and grounding.

Two pure-text jobs that both belong on the dashboard side (the DTS design review
§9.6), because both are things a model should not be trusted with and neither
needs one.

**The first human turn** becomes the entity's `skos:definition`, which is what
every criticism record in the store already carries there — "Write an art
criticism of this digital sculpture…". Rick's instruction named `## Prompt:`,
which is the ChatGPT export's heading; the Claude export writes `## User:` and
puts a `>` metadata block (timestamps, attached filenames) before the prose.
Keying on one of them would have silently produced an empty definition for the
other, so the reader takes the first human turn under EITHER heading and drops
the quoted metadata.

**Grounding verification** is a string check, not a judgement: is the phrase
the model quoted actually in the document it read? A model that invents its
evidence is the failure this catches, and catching it mechanically is the
whole reason the agent is asked for a phrase at all. The check is deliberately
forgiving about whitespace and quote characters — an export wraps lines and
turns `'` into `’` — and deliberately strict about everything else.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = ["first_prompt", "verify_phrase", "context_around", "Grounded",
           "turns", "speaker_of", "USER", "CRITIC", "clean_text",
           "STRIPPED", "sentences_around", "split_on_phrase"]

USER = "user"
CRITIC = "critic"

#: Headings that introduce the CRITIC's turn. The counterpart of `_HUMAN_HEADING`
#: below, and together they cut a transcript into whose words are whose.
_CRITIC_HEADING = re.compile(r"^#{1,6}\s*(assistant|response|chatgpt|claude)\s*:?\s*$", re.I)

#: Headings that introduce something a PERSON said. ChatGPT exports write
#: `## Prompt:`; Claude exports write `## User:`. Matched case-insensitively
#: with the trailing colon optional, because exporters disagree about both.
_HUMAN_HEADING = re.compile(r"^#{1,6}\s*(prompt|user|human)\s*:?\s*$", re.I)
_ANY_HEADING = re.compile(r"^#{1,6}\s+")

#: Lines an export adds that are not the prompt: the `>` blockquote carrying
#: timestamps and attachment names, and the bracketed attachment markers
#: ChatGPT writes inline.
#: A line that is only an ATTACHMENT, in either syntax an export uses. The
#: bracketed forms are what ChatGPT wrote until it started embedding the
#: attachment as markdown instead: `![IMG_2103.JPG](https://chatgpt.com/…)`.
#: Same thing, so it is read the same way (2026-10-05).
_METADATA = re.compile(r"^\s*(>|\[Attachment:|\[File:|!\[[^\]]*\]\()", re.I)

#: A markdown image embed anywhere in a line. Stripped from every literal DTS
#: writes, not just from a prompt: the URL inside one is a signed, expiring
#: link carrying a 64-character `sig=` token, and these records converge to a
#: published catalogue. It is also 230 of the 315 characters of the definition
#: it landed in — and `match_work` and `detect_material` read a LIMITED window
#: of the first prompt, so a second attachment would push the work's name out
#: of it and the criticism would be tagged onto nothing, silently.
_IMAGE_EMBED = re.compile(r"!\[[^\]]*\]\([^)]*\)")


def first_prompt(text: str, *, limit: int = 0) -> str:
    """The first thing the human asked, as prose.

    Returns "" when the document has no human turn at all, which the caller
    should treat as a document it cannot describe rather than as an empty
    description — an entity whose `skos:definition` is blank is worse than one
    that failed loudly.
    """
    lines = str(text).splitlines()
    for i, line in enumerate(lines):
        if not _HUMAN_HEADING.match(line):
            continue
        block: list[str] = []
        for following in lines[i + 1:]:
            if _ANY_HEADING.match(following):
                break
            if _METADATA.match(following):
                # Metadata BEFORE the prose is skipped; metadata after it ends
                # the prompt, because ChatGPT puts its attachment markers last.
                # "Before" means before any PROSE — blank lines do not count,
                # and counting them read the Claude export as prompt-less.
                if any(b.strip() for b in block):
                    break
                continue
            block.append(following)
        prose = clean_text(" ".join(p.strip() for p in block if p.strip()))
        if prose:
            return prose[:limit].rstrip() if limit and len(prose) > limit else prose
    return ""


def _flatten(s: str) -> str:
    """Normalise the characters an export changes, WITHOUT changing lengths
    beyond whitespace runs. Used to build the search pattern, never to display.
    """
    s = unicodedata.normalize("NFKD", str(s))
    return (s.replace("\u2019", "'").replace("\u2018", "'")
             .replace("\u201c", '"').replace("\u201d", '"')
             .replace("\u2014", "-").replace("\u2013", "-"))


def _pattern(phrase: str):
    """A phrase as it may appear in the SOURCE: wrapped, re-spaced, re-quoted.

    Matching against the original text rather than against a flattened copy is
    what makes the offset real — a flattened search gives a position in a
    string nobody has, and mapping it back proportionally lands in the wrong
    paragraph (measured: a phrase in the middle of a 23 KB document reported
    context from its opening prompt).

    Typographic substitutions are handled by matching either form, so an
    apostrophe the export curled still matches the straight one the model
    quoted.
    """
    pieces = []
    for token in _flatten(phrase).split():
        chars = []
        for ch in token:
            if ch in "'\"":
                # ANY quote mark matches any other. The model quoting a
                # document that itself contains quotation marks routinely
                # swaps the style \u2014 it wrote `reading 'Prestress' as naming a
                # resolved equilibrium` where the critic wrote it with double
                # quotes, and that was reported as evidence the critic never
                # gave. Quote style is typography, which is what this function
                # already normalises; the WORDS still have to match.
                chars.append("['\u2018\u2019\"\u201c\u201d]")
            elif ch == "-":
                chars.append("[-\u2013\u2014]")
            else:
                chars.append(re.escape(ch))
        pieces.append("".join(chars))
    if not pieces:
        return None
    return re.compile(r"\s+".join(pieces), re.I)


@dataclass(frozen=True)
class Grounded:
    """Whether a quoted phrase is really in the source, and where."""

    phrase: str
    verified: bool
    offset: int = -1
    context: str = ""


def verify_phrase(text: str, phrase: str, *, context_chars: int = 240) -> Grounded:
    """Is this phrase in this document?

    The answer the curation screen shows beside every proposal, and the reason
    the agent is asked to quote at all. `[NOT FOUND]` in the agent's own output
    proves the case is real — one of the tagging examples in the plan carries
    exactly that.
    """
    pattern = _pattern(phrase)
    if pattern is None:
        return Grounded(phrase=str(phrase), verified=False)
    found = pattern.search(str(text))
    if found is None:
        return Grounded(phrase=str(phrase), verified=False)
    return Grounded(
        phrase=str(phrase), verified=True, offset=found.start(),
        context=_window(str(text), found.start(), found.end(), context_chars),
    )


def context_around(text: str, phrase: str, *, chars: int = 240) -> str:
    """The text around a grounding phrase, for the curator to read."""
    return verify_phrase(text, phrase, context_chars=chars).context


def _window(text: str, start: int, end: int, chars: int) -> str:
    """The phrase plus its surroundings, snapped outward to word boundaries and
    collapsed to one line — a curator is reading it in a table cell."""
    half = max(chars // 2, 40)
    left, right = max(0, start - half), min(len(text), end + half)
    if left:
        space = text.find(" ", left)
        left = space + 1 if 0 <= space < start else left
    if right < len(text):
        space = text.rfind(" ", end, right)
        right = space if space > end else right
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return prefix + " ".join(text[left:right].split()) + suffix


def turns(text: str) -> list:
    """The document cut into `(speaker, text)`, speaker being user or critic.

    A criticism export is a conversation, and **the two sides are not
    interchangeable evidence**. Rick, 2026-09-30: "I was the one to say
    'reminiscent of Raphael's golden apples', which is the grounding phrase,
    not the agent writing the criticism. The agent then picked up the
    association. Concepts originating from my text contributions I tend to
    leave out."

    That is a rule the dashboard can apply mechanically, and it is the same
    class of check as grounding itself: not whether the words are in the
    document, but WHOSE they are. Anything before the first heading belongs to
    neither — it is the export's own front matter.
    """
    out, speaker, buffer = [], "", []
    for line in str(text).splitlines():
        if _HUMAN_HEADING.match(line) or _CRITIC_HEADING.match(line):
            if speaker and buffer:
                out.append((speaker, "\n".join(buffer)))
            speaker = USER if _HUMAN_HEADING.match(line) else CRITIC
            buffer = []
            continue
        if speaker:
            buffer.append(line)
    if speaker and buffer:
        out.append((speaker, "\n".join(buffer)))
    return out


def speaker_of(text: str, phrase: str) -> str:
    """Whose turn a phrase comes from, or "" if it is in neither.

    The CRITIC wins a tie. A phrase appearing in both turns is one the critic
    also wrote — quoting the artist back at them is still the critic using the
    words, and the association it grounds is theirs to have made.
    """
    pattern = _pattern(phrase)
    if pattern is None:
        return ""
    found = ""
    for speaker, body in turns(text):
        if pattern.search(body):
            if speaker == CRITIC:
                return CRITIC
            found = speaker
    return found


#: Characters dropped from any text DTS takes out of a document or a model
#: reply. **Dropped, not escaped** (Rick, 2026-09-30): "the difference between
#: <modelviewer> and modelviewer in a text field in ttl to an end user is
#: nothing."
#:
#: `<` and `>` are the known issue. `services/rdf2html.py` in cwva-py passes
#: RDF literals through UNESCAPED on the stated assumption that they "come
#: from controlled TTL files" — so `viewed in <modelviewer>` reaches a browser
#: as an unknown tag and the words vanish from the page. DTS imports the
#: widest variety of text of anything in the system, so this is where the
#: hygiene stands rather than at every consumer.
STRIPPED = "<>"


def clean_text(value: str) -> str:
    """Text fit to put in a literal, from a source nobody controls.

    Four things go, and nothing else — the aim is hygiene, not rewriting what
    a critic said:

    - the angle brackets, per above;
    - MARKDOWN IMAGE EMBEDS, whole. An export writes the artist's attachment
      as `![IMG_2103.JPG](https://chatgpt.com/backend-api/…&sig=…)`, which is
      not prose, is not durable, and carries a 64-character signed token into a
      record that converges to a published catalogue. The alt text goes with
      it: it is a camera filename, not a description (2026-10-05);
    - C0 control characters other than tab and newline, which have no visible
      form and break a Turtle literal or a terminal depending on which one;
    - leading and trailing whitespace, and any run of spaces a removal left
      behind, so dropping a character does not leave a gap where it was.

    **A markdown LINK is left alone.** `[text](url)` in a criticism is prose
    with a citation attached, and dropping either half would change what the
    critic said — which is the line this function does not cross.
    """
    value = _IMAGE_EMBED.sub(" ", str(value))
    text = "".join(c for c in str(value)
                   if c not in STRIPPED
                   and (c in "\t\n" or ord(c) >= 32)
                   and ord(c) != 127)
    # `viewed in <modelviewer>.` would otherwise become `viewed in .`
    text = re.sub(r"[ \t]{2,}", " ", text)
    return re.sub(r"\s+([.,;:!?])", r"\1", text).strip()


#: Where a sentence ends, for the purpose of showing a curator what surrounds a
#: grounding phrase. Deliberately simple: a period, question or exclamation
#: mark followed by whitespace and something that starts a new sentence. It
#: over-splits on an abbreviation and that costs a curator nothing — a short
#: fragment beside the real sentence is still the right paragraph.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\s\u201d\"']+(?=[A-Z\u201c\"'(\[])")

#: Markdown furniture that is not prose: a heading, a blockquote marker, a list
#: bullet. Stripped from the display so the context reads as the critic wrote
#: it rather than as the export formatted it.
_FURNITURE = re.compile(r"^\s*(?:#{1,6}\s*|>\s?|[-*+]\s+|\d+\.\s+)", re.M)


def sentences_around(text: str, phrase: str, *, before: int = 1,
                     after: int = 1) -> str:
    """The phrase in its own sentence, plus its neighbours in that PARAGRAPH.

    **A character window is not enough, and the case that proves it is a
    negation.** `Color symbolism` was proposed on the phrase "simple symbolic
    diagram", which is in the document — inside "Yet the effect avoids becoming
    a simple symbolic diagram". The prompt's rule 9 forbids deriving a concept
    from what the critic says the work is NOT, and the grounding check cannot
    see it: the words are there. Only a reader can catch it, and only if the
    screen shows them the sentence (Rick, 2026-10-01).

    Bounded by the paragraph on purpose. A window that spilled across a blank
    line would reach into another speaker's turn or the next section, and
    attribute to the critic a sentence they wrote about something else.
    """
    pattern = _pattern(phrase)
    if pattern is None:
        return ""
    source = str(text)
    found = pattern.search(source)
    if found is None:
        return ""

    # The paragraph: back to a blank line, forward to the next one.
    start = source.rfind("\n\n", 0, found.start())
    start = 0 if start < 0 else start + 2
    end = source.find("\n\n", found.end())
    end = len(source) if end < 0 else end
    paragraph = _FURNITURE.sub("", source[start:end])

    # Where the phrase sits inside the cleaned paragraph — re-found rather than
    # offset-mapped, because stripping furniture changes the length.
    inside = pattern.search(paragraph)
    if inside is None:
        return " ".join(paragraph.split())

    pieces, cursor = [], 0
    for split in _SENTENCE_END.finditer(paragraph):
        pieces.append((cursor, split.start()))
        cursor = split.end()
    pieces.append((cursor, len(paragraph)))
    here = next((i for i, (a, b) in enumerate(pieces)
                 if a <= inside.start() < b), 0)
    lo = max(0, here - max(before, 0))
    hi = min(len(pieces), here + max(after, 0) + 1)
    return " ".join(" ".join(paragraph[a:b].split())
                    for a, b in pieces[lo:hi] if paragraph[a:b].strip())


def split_on_phrase(context: str, phrase: str) -> tuple:
    """`(before, the phrase as it appears, after)` so a renderer can mark it.

    The split is done on the RAW text and handed over in three pieces, because
    the alternative — escaping the context and then searching for an escaped
    phrase inside it — breaks on exactly the typography this module exists to
    tolerate. The caller escapes each piece.
    """
    pattern = _pattern(phrase)
    if pattern is None:
        return (str(context), "", "")
    found = pattern.search(str(context))
    if found is None:
        return (str(context), "", "")
    return (context[:found.start()], context[found.start():found.end()],
            context[found.end():])
