"""The DTS surface: every queue, and the curation stop at each one.

**All the information first, then the design** (Rick, 10.8: "Show all the
queue information prominently first, then work on UX design. Real estate is
accepted."). So this page lists every queue and every entity in it, rather
than summarising into badges that would have to be clicked through. A
dashboard hosting workflows in myriad states is unusable without seeing them,
and a count you cannot expand is a count you learn to ignore.

**Curation is include / exclude per item, never an editor** (decision E). The
curator says "not this concept", "not this tag" — and the proposal survives
the decision, which is what makes the evidence record worth keeping. Nothing
here edits a label, a definition or a summary.

**There is a third answer, and it is not a fourth kind of screen.** A
proposal is sometimes neither kept nor rejected but DEMOTED: it is an
`skos:altLabel` of something the store already has (Rick, 2026-09-30, of
`the:SelfStressState` against `the:Prestress`). Asserting that is a radio
beside the other two; acting on it is vocabulary management, which is a
different workflow and a different day.
"""

from __future__ import annotations

from typing import Any, Mapping

from .forms import _STYLE, _esc

__all__ = ["render_dts_card", "render_queues_page", "render_curation_page",
           "render_summary_page", "KEEP", "REJECT", "DEMOTE"]

KEEP = "keep"
REJECT = "reject"
DEMOTE = "demote"

#: What each finding means, in the words a curator needs rather than the
#: status name. Shown beside the proposal it is about, because a status with
#: no explanation is a status people learn to click past.
_WHY = {
    "duplicate": ("duplicate", "the store already has this concept. Reject it "
                               "here — this document's USE of it belongs in "
                               "tagging, where it gets its own grounding"),
    "ungrounded": ("not grounded", "the phrase the model quoted is not in the "
                                   "document"),
    "user_sourced": ("your words", "grounded in your own turn, not the "
                                   "critic's — they picked the association up"),
    "orphan": ("no parent", "its broader term does not resolve, so TCAP cannot "
                            "place it"),
    "unknown": ("not in the store", "tagging chooses from concepts that exist"),
    "derived_here": ("derived here", "derived from this very document, so "
                                     "discussed in it by construction"),
    "proposed": ("", ""),
}


def _shell(title: str, sub: str, body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_esc(title)}</title>
<style>{_STYLE}{_DTS_STYLE}</style></head><body>
<header><h1>{_esc(title)}</h1>
<span class="sub">{_esc(sub)}</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


_DTS_STYLE = """
.queue{border:1px solid var(--line);border-radius:10px;margin-bottom:.9rem;
background:var(--card)}
.queue>summary{padding:.7rem 1rem;cursor:pointer;display:flex;gap:.7rem;
align-items:center;font-size:.95rem}
.queue>summary::-webkit-details-marker{display:none}
.queue .n{font-weight:700;min-width:2.2rem;text-align:right}
.queue.has>summary{color:var(--ink)}
.queue.empty>summary{color:var(--muted)}
.queue .rule{color:var(--muted);font-size:.8rem;margin-left:auto}
.queue ul{list-style:none;margin:0;padding:0 1rem 1rem}
.queue li{display:flex;gap:.7rem;align-items:baseline;padding:.3rem 0;
border-top:1px solid var(--line)}
.queue li .doc{color:var(--muted);font-size:.8rem}
.prop{border:1px solid var(--line);border-radius:8px;padding:.7rem .9rem;
margin-bottom:.6rem}
.prop.flagged{border-color:var(--warn)}
.prop h3{margin:0 0 .3rem;font-size:.95rem;font-weight:600}
.prop .def{color:var(--muted);font-size:.85rem;margin-bottom:.35rem}
.prop .meta{font-size:.8rem;color:var(--muted)}
.prop .phrase{font-style:italic}
.prop .why{color:var(--warn);font-size:.8rem;margin-top:.3rem}
.choices{display:flex;gap:1rem;margin-top:.45rem;flex-wrap:wrap}
.choices label{display:flex;align-items:center;gap:.3rem;margin:0;
text-transform:none;font-size:.85rem;color:var(--ink);letter-spacing:0}
.choices input[type=radio]{width:auto;flex:none;margin:0}
/* The sentences around a grounding phrase. Set apart from the metadata and
   given room to be read: it is prose, and the decision depends on reading it. */
.context{background:var(--bg);border-left:2px solid var(--line);
padding:.45rem .7rem;margin-top:.4rem;font-size:.85rem;line-height:1.5;
color:var(--ink)}
.context mark{background:rgba(255,180,84,.25);color:var(--ink);
padding:0 .1rem;border-radius:2px}
.summary-text{background:var(--bg);border:1px solid var(--line);
border-radius:8px;padding:1rem;line-height:1.55}
"""


def render_dts_card(pending: int, documents: int = 0) -> str:
    """The hub card. A number, because a queue nobody can see is a queue
    nobody works."""
    if pending or documents:
        bits = []
        if pending:
            bits.append(f"{pending} awaiting a step")
        if documents:
            bits.append(f"{documents} new document{'s' if documents != 1 else ''}")
        return ('<a href="dts" class="card yellow">'
                f'<div class="card-title">DTS &mdash; {pending + documents}</div>'
                f'<div class="card-desc">{_esc("; ".join(bits))}</div></a>')
    return ('<a href="dts" class="card">'
            '<div class="card-title">DTS</div>'
            '<div class="card-desc">Nothing waiting</div></a>')


def render_queues_page(*, queues, documents=(), notice: str = "",
                       error: str = "", works=None,
                       unavailable: Mapping[str, Any] | None = None
                       ) -> str:
    """Every queue, open, with every entity in it.

    Empty queues are rendered too, collapsed. A queue that disappears when it
    empties teaches you that the list is a list of problems rather than a
    model of the workflow, and then its absence means nothing.
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    note = f'<div class="notice">{_esc(notice)}</div>' if notice else ""
    held = ""
    if unavailable and not unavailable.get("available", True):
        held = ('<div class="err">The model is unavailable until '
                f'{_esc(str(unavailable.get("until", "")))} &mdash; '
                f'{_esc(str(unavailable.get("why", "")))}. '
                "Steps that call it will refuse rather than wait.</div>")

    blocks = []
    if documents or True:
        # GENERATE, then review. The entity a criticism document implies is
        # derivable from the document — its material from what the artist
        # asked for, its source from the export's own headings, the work from
        # the headings that name it — so the step is a button rather than a
        # form to retype (Rick, 2026-10-01). It lands in Edit Record, which
        # opens entities, so "review and edit as needed" is one click on.
        items = "".join(
            '<li><span>' + _esc(d) + '</span>'
            '<span style="margin-left:auto" class="pick-row">'
            '<form method="post" action="/dts/entity/new" style="display:inline">'
            f'<input type="hidden" name="doc" value="{_esc(d)}">'
            f'{_work_options(works)}'
            '<button type="submit">Generate entity</button></form></span></li>'
            for d in documents)
        blocks.append(_queue_block(
            "Documents to process", len(documents),
            "a file in the drop folder with no entity",
            items or '<li class="doc">nothing new</li>',
            note=("Generating derives the label, topics, definition and the "
                  "work it criticises from the document, and opens the record "
                  "for review. Nothing is guessed silently — the editor shows "
                  "what was derived, and the Entity form is still there for a "
                  "document this cannot read. Name the work here if you know "
                  "it: the editor renders one field per predicate the record "
                  "already has, so an entity created without a work reference "
                  "has no field in which to add one.")))

    for q in queues:
        rows = []
        for e in q["entities"]:
            action = (f'<a class="button" href="/dts/entity?guid={_esc(e["guid"])}">'
                      f'{_esc(q["action"])}</a>' if q.get("action") else "")
            rows.append(
                f'<li><span>{_esc(e["label"])}</span>'
                f'<span class="doc">{_esc(e.get("document", ""))}</span>'
                f'<span style="margin-left:auto">{action}</span></li>')
        blocks.append(_queue_block(q["title"], len(q["entities"]), q["rule"],
                                   "".join(rows) or '<li class="doc">empty</li>'))

    return _shell(
        "DTS", "derive / tag / summarize — every queue and what is in it",
        f"{err}{held}{note}" + "".join(blocks) +
        '<div class="card"><div class="note">Every stage writes into QA and '
        'nothing reaches the SOT until you approve it at '
        '<a href="/staged/preview">Preview Staged</a>. A stage cannot be left '
        'until it is curated, which is why each one appears here twice.</div>'
        '<a href="/">&larr; dashboard</a></div>')


def _work_options(works) -> str:
    """The work this criticism is about, offered rather than only derived.

    **Because the editor cannot add a predicate a record does not have.** The
    generator matches the work from the document's headings and leaves
    `the:tag` off when nothing clears the threshold — then told the user to
    "set `the:tag` in the editor", which Edit Record has no way to do: it
    renders one field per predicate IN THE FILE, so an absent property is an
    absent field (Rick, 2026-10-01: "there is no the:tag property field").
    Adding a predicate from the type's domain is a deferred Edit Record item,
    so the place to answer is here, before the record exists.

    The derived match stays the default — it is right when the document names
    its subject in a heading — and this is the override and the fallback. The
    options are the same set `match_work` searches, so what the page offers is
    what the matcher could have found.

    **Newest first** (Rick, 2026-10-01), ordered by the caller on the same key
    the Edit Record picker uses, and the date is shown beside each label for
    the same reason it is shown there: an order you cannot see is one you have
    to trust.
    """
    if not works:
        return ""
    opts = "".join(
        f'<option value="{_esc(r["value"])}">{_esc(r["label"])}'
        + (f' &mdash; {_esc(r["published"])}' if r.get("published") else "")
        + "</option>"
        for r in works)
    return ('<select name="work" style="width:auto;margin-right:.4rem">'
            '<option value="">&mdash; derive the work from the document '
            "&mdash;</option>"
            f"{opts}</select>")


def _queue_block(title: str, count: int, rule: str, items: str,
                 note: str = "") -> str:
    state = "has" if count else "empty"
    extra = f'<div class="note" style="padding:0 1rem 1rem">{_esc(note)}</div>' if note else ""
    return (f'<details class="queue {state}"{" open" if count else ""}>'
            f'<summary><span class="n">{count}</span>'
            f'<span>{_esc(title)}</span>'
            f'<span class="rule">{_esc(rule)}</span></summary>'
            f"<ul>{items}</ul>{extra}</details>")


def render_curation_page(*, entity, stage: str, items, action: str,
                         error: str = "", counts=None) -> str:
    """Include / exclude per item, with every finding said out loud.

    Each item carries the dashboard's findings — duplicate, not grounded, your
    words, no parent — because the whole value of this screen is that the
    curator sees what the machine noticed before deciding. A proposal arrives
    pre-set to what the findings imply, and every one of those defaults is
    overridable: they are a reading, not a ruling.
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    tally = ""
    if counts:
        tally = ('<div class="note">'
                 + " &middot; ".join(f"{v} {_esc(k.replace('_', ' '))}"
                                     for k, v in counts.items() if v)
                 + "</div>")

    rows = []
    for item in items:
        rows.append(_proposal(item))

    return _shell(
        f"Curate {stage}", f"{entity['label']} — {entity.get('document', '')}",
        f"""{err}
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">{_esc(entity['label'])}</h2>
  <div class="note mono">{_esc(entity['uri'])}</div>
  {tally}
</div>
<form method="post" action="{_esc(action)}">
<input type="hidden" name="guid" value="{_esc(entity['guid'])}">
<div class="card">{''.join(rows)}</div>
<div class="card">
  <button type="submit" class="primary">Record these decisions</button>
  <a href="/dts" style="margin-left:1rem">&larr; DTS</a>
  <div class="note" style="margin-top:.6rem">What you keep is written into QA
  and what you reject is recorded as rejected — both, because a rejection that
  leaves nothing behind cannot be reconstructed and the next run would propose
  it again. Nothing reaches the SOT until you approve it at Preview Staged.</div>
</div></form>""")


def _proposal(item: Mapping[str, Any]) -> str:
    """One proposal, its findings, and the three answers."""
    status = str(item.get("status") or "proposed")
    label, why = _WHY.get(status, (status, ""))
    flagged = " flagged" if status not in ("proposed", "derived_here") else ""
    name = f"choice:{item['key']}"
    default = str(item.get("default") or KEEP)

    bits = []
    if item.get("definition"):
        bits.append(f'<div class="def">{_esc(item["definition"])}</div>')
    meta = []
    if item.get("broader"):
        meta.append(f'broader: {_esc(item["broader"])}')
    if item.get("scheme"):
        meta.append(f'scheme: {_esc(item["scheme"])}')
    if item.get("reference"):
        meta.append(f'ref: {_esc(item["reference"])}')
    if item.get("confidence"):
        meta.append(f'confidence: {_esc(item["confidence"])}')
    if meta:
        bits.append(f'<div class="meta">{" &middot; ".join(meta)}</div>')
    if item.get("phrase"):
        bits.append('<div class="meta">grounded in '
                    f'<span class="phrase">&ldquo;{_esc(item["phrase"])}&rdquo;</span>'
                    f'{" &mdash; " + _esc(item["speaker"]) if item.get("speaker") else ""}'
                    "</div>")
    # THE SENTENCES AROUND IT, which is what catches what the phrase cannot.
    # `Color symbolism` was proposed on "simple symbolic diagram" — present in
    # the document, inside "Yet the effect AVOIDS becoming a simple symbolic
    # diagram". The prompt forbids deriving from a negation and the grounding
    # check cannot see one, because the words are there. Only a reader can,
    # and only if the screen shows them the sentence (Rick, 2026-10-01).
    if item.get("context"):
        before, match, after = item["context"]
        bits.append('<div class="context">' + _esc(before)
                    + (f"<mark>{_esc(match)}</mark>" if match else "")
                    + _esc(after) + "</div>")
    if item.get("near"):
        bits.append('<div class="meta">near: '
                    + ", ".join(_esc(n) for n in item["near"]) + "</div>")
    notes = [n for n in (item.get("notes") or [])]
    if why:
        notes.insert(0, why)
    if notes:
        bits.append(f'<div class="why">{_esc("; ".join(notes))}</div>')

    choices = [
        (KEEP, "Keep"),
        (REJECT, "Reject"),
    ]
    # THE THIRD ANSWER, offered only where there is something to demote ONTO.
    # A demotion with no target is a wish rather than a decision.
    if item.get("demote_to"):
        choices.append((DEMOTE, f"altLabel of {item['demote_to_label']}"))
    radios = "".join(
        f'<label><input type="radio" name="{_esc(name)}" value="{value}"'
        + (" checked" if value == default else "") + f"> {_esc(text)}</label>"
        for value, text in choices)

    return (f'<div class="prop{flagged}">'
            f'<h3>{_esc(item["label"])}'
            + (f' <span class="meta">({_esc(label)})</span>' if label else "")
            + "</h3>" + "".join(bits)
            + f'<div class="choices">{radios}</div></div>')


def render_summary_page(*, entity, summary: str, notes=(), words: int = 0,
                        action: str, error: str = "") -> str:
    """Accept or send back — the one stage whose curation is a verdict.

    There is nothing to include or exclude in a single paragraph, so the
    screen is a different shape from the other two even though the stamp is
    the same (Rick, 2.1a: he reads summaries before release, though not to
    edit them).
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    flags = "".join(f'<div class="why">{_esc(n)}</div>' for n in notes)
    return _shell(
        "Curate summary", f"{entity['label']} — {entity.get('document', '')}",
        f"""{err}
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">{_esc(entity['label'])}</h2>
  <div class="note">{words} words</div>{flags}
</div>
<div class="card"><div class="summary-text">{_esc(summary)}</div></div>
<form method="post" action="{_esc(action)}">
<input type="hidden" name="guid" value="{_esc(entity['guid'])}">
<div class="card">
  <button type="submit" name="verdict" value="accept" class="primary">Accept</button>
  <a href="/dts" style="margin-left:1rem">&larr; DTS</a>
  <div class="note" style="margin-top:.6rem">Accepting writes this onto the
  record. There is no "send back": DTS runs once per entity, so the way to a
  different summary is to reset this entity's DTS state and start again &mdash;
  which is deliberate, because a second summary beside the first is two answers
  to one question with nothing saying which is current.</div>
</div></form>""")
