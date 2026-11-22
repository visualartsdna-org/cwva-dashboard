"""The workflow board page (/workflows) and its hub card.

One row per work, one column per step: a subway map turned sideways. A row can
have more than one step ready at once — Annotate and Criticism both depend only
on Entry — which is why this is a grid and not a kanban board, where a card can
sit in one column only.

The page renders the ``workflow.board`` tool's result; it computes nothing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlencode

from .forms import _STYLE, _esc

__all__ = ["render_board_page", "render_board_card", "board_summary"]

_CSS = """
main{max-width:1400px}
.wf-tabs{display:flex;gap:.4rem;flex-wrap:wrap;align-items:center;margin-bottom:1rem}
.wf-tabs .tab{padding:.25rem .7rem;border:1px solid var(--line);border-radius:999px;
font-size:.85rem;color:var(--muted)}
.wf-tabs .tab.on{color:var(--ink);border-color:var(--accent);background:var(--card)}
.wf-tabs .fin{margin-left:auto;font-size:.85rem;color:var(--muted)}
table.board{width:100%;border-collapse:collapse;font-size:.85rem}
table.board th{text-align:center;font-weight:500;color:var(--muted);padding:.3rem .4rem;
border-bottom:1px solid var(--line);white-space:nowrap}
table.board th.work{text-align:left}
table.board td{padding:.45rem .4rem;border-bottom:1px solid var(--line);
text-align:center;vertical-align:top}
table.board td.work{text-align:left;min-width:15rem}
.work .name{font-weight:600}
.work .meta{color:var(--muted);font-size:.78rem}
.work .route{font-size:.78rem;margin-top:.15rem}
.work .route b{font-weight:500;color:var(--ink)}
.cell .g{font-size:1.05rem;line-height:1}
.cell .d{display:block;font-size:.72rem;color:var(--muted);white-space:nowrap}
.cell.done .g{color:var(--ok)}
.cell.done.implied .g{color:var(--ok);opacity:.45}
.cell.started .g{color:var(--warn)}
.cell.ready .g{color:var(--accent)}
.cell.blocked .g{color:var(--line)}
.cell.skipped .g{color:var(--muted)}
.cell.skipped .d{text-decoration:line-through}
.cell.staged .g{text-shadow:0 0 0 var(--warn);outline:2px dashed var(--warn);
outline-offset:2px;border-radius:50%}
.cell button{font-size:.7rem;padding:.1rem .4rem;margin-top:.2rem;background:#0d121c;
color:var(--ink);border:1px solid var(--line);border-radius:6px;cursor:pointer}
.cell button:hover{border-color:var(--accent)}
.cell .undo{font-size:.7rem;color:var(--muted);cursor:pointer;background:none;border:none}
.age{display:inline-block;padding:0 .4rem;border-radius:999px;font-size:.72rem;
border:1px solid var(--line);color:var(--muted);margin-left:.3rem}
.age.stalled{border-color:var(--warn);color:var(--warn)}
.badge{display:inline-block;padding:0 .4rem;border-radius:999px;font-size:.72rem;
border:1px solid var(--warn);color:var(--warn);margin-left:.3rem}
.legend{color:var(--muted);font-size:.8rem;margin:.6rem 0 0}
.legend span{margin-right:1rem}
.empty{color:var(--muted)}
h2.wf{font-size:1rem;margin:0 0 .6rem}
h2.wf .sub{color:var(--muted);font-weight:400;font-size:.85rem;margin-left:.5rem}
"""

_GLYPH = {"done": "&#9679;", "started": "&#9673;", "ready": "&#9675;", "blocked": "&middot;",
          "skipped": "&ndash;"}


def _short(iso: str | None) -> str:
    """``11-04``: the year is this year's almost always, and width is scarce."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    return dt.strftime("%m-%d")


def _age(days: float | None) -> str:
    if days is None:
        return ""
    if days < 1:
        return f"{max(1, round(days * 24))}h"
    return f"{int(days)}d"


def _guid(iri: str) -> str:
    return iri.rstrip("/").rsplit("/", 1)[-1]


def _cell(wf: Mapping, step: Mapping, row: Mapping, drafts: Mapping[str, bool]) -> str:
    c = row["cells"][step["id"]]
    state = c["state"]
    classes = ["cell", state]
    title = [step["label"], step.get("description", "")]
    detail = ""
    if state == "done":
        src = c.get("source")
        if src == "implied":
            classes.append("implied")
            title.append("done: a later step that depends on it is done")
        elif src == "manual":
            title.append(f"ticked {_short(c.get('at'))}")
        else:
            title.append("done" + (f" {_short(c.get('at'))}" if c.get("at") else ""))
        detail = _short(c.get("at")) or ("ticked" if src == "manual" else "")
        staged = [r for r in c.get("records") or []
                  if _guid(r) in drafts and (_guid(r) != _guid(row["work"])
                                             or drafts[_guid(r)])]
        if staged:
            classes.append("staged")
            title.append("written here, not yet distributed")
    elif state == "started":
        detail = _esc(c.get("note") or "under way")
        if c.get("age_days") is not None:
            detail += f" {_age(c['age_days'])}"
        title.append(f"under way: {c.get('note') or ''}")
    elif state == "skipped":
        detail = "not needed"
        title.append(f"dismissed as not needed {_short(c.get('at'))}")
    elif state == "ready":
        detail = "ready" + (f" {_age(c['age_days'])}" if c.get("age_days") is not None else "")
        title.append("ready: nothing is blocking it")
    else:
        waiting = [next((s["label"] for s in wf["steps"] if s["id"] == w), w)
                   for w in c.get("waiting_on") or []]
        title.append("needs " + ", ".join(waiting))
    glyph = _GLYPH[state]
    if state in ("ready", "started") and step.get("action"):
        glyph = f'<a href="{_esc(step["action"])}" class="g">{glyph}</a>'
    else:
        glyph = f'<span class="g">{glyph}</span>'
    extra = ""
    data = (f'data-wf="{_esc(wf["id"])}" data-step="{_esc(step["id"])}" '
            f'data-work="{_esc(row["work"])}" data-label="{_esc(step["label"])}" '
            f'data-name="{_esc(row["label"])}"')
    if step.get("manual"):
        if state == "ready":
            extra = f'<br><button class="tick" {data} data-done="1">mark done</button>'
        elif state == "done" and c.get("source") == "manual":
            extra = f'<br><button class="undo tick" {data} data-done="0">undo</button>'
    if state in ("ready", "started"):
        extra += (f'<br><button class="undo skip" {data} data-skip="1" '
                  'title="dismiss this step for this work">not needed</button>')
    elif state == "skipped":
        extra = f'<br><button class="undo skip" {data} data-skip="0">restore</button>'
    return (f'<td class="{" ".join(classes)}" title="{_esc(" — ".join(t for t in title if t))}">'
            f'{glyph}<span class="d">{detail}</span>{extra}</td>')


def _row(wf: Mapping, row: Mapping, drafts: Mapping[str, bool], edit_link=None) -> str:
    labels = {s["id"]: s["label"] for s in wf["steps"]}
    meta = [x for x in (row.get("disposition"), _short(row.get("created"))
                        and f"entered {_short(row['created'])}") if x]
    last = row.get("last")
    last_txt = ""
    if last:
        at = _short(row["cells"][last].get("at"))
        last_txt = f"last <b>{_esc(labels[last])}</b>{' ' + at if at else ''}"
    nxt = ", ".join(labels[n] for n in row.get("next") or [])
    route = " &rarr; ".join(x for x in (last_txt, f"next <b>{_esc(nxt)}</b>" if nxt else
                                         ("<b>finished</b>" if row["finished"] else "")) if x)
    age = ""
    if row.get("age_days") is not None and not row["finished"]:
        age = (f'<span class="age{" stalled" if row.get("stalled") else ""}" '
               f'title="since the last completed step">{_age(row["age_days"])}</span>')
    work_guid = _guid(row["work"])
    badge = ""
    if work_guid in drafts:
        badge = ('<span class="badge" title="the work record is written here and not '
                 'yet distributed">staged</span>')
    name = (f'<a class="name" href="{_esc(edit_link(work_guid))}">{_esc(row["label"])}</a>'
            if edit_link else f'<span class="name">{_esc(row["label"])}</span>')
    return (f'<tr><td class="work">{name}'
            f'{age}{badge}<div class="meta">{_esc(" · ".join(meta))}</div>'
            f'<div class="route">{route}</div></td>'
            + "".join(_cell(wf, s, row, drafts) for s in wf["steps"]) + "</tr>")


def _table(wf: Mapping, drafts: Mapping[str, bool], edit_link=None) -> str:
    head = "".join(f'<th title="{_esc(s.get("description", ""))}">{_esc(s["label"])}</th>'
                   for s in wf["steps"])
    rows = "".join(_row(wf, r, drafts, edit_link) for r in wf["rows"])
    if not rows:
        rows = (f'<tr><td class="empty work" colspan="{len(wf["steps"]) + 1}">'
                "Nothing in flight.</td></tr>")
    n = len(wf["rows"])
    return (f'<section class="card"><h2 class="wf">{_esc(wf["id"])} &middot; '
            f'{_esc(wf["label"])}<span class="sub">{n} work{"s" if n != 1 else ""}'
            f'</span></h2><table class="board"><thead><tr><th class="work">Work</th>'
            f"{head}</tr></thead><tbody>{rows}</tbody></table></section>")


_SCRIPT = """
<script>
document.querySelectorAll('button.tick').forEach(function (b) {
  b.addEventListener('click', function () {
    b.disabled = true;
    fetch('/api/workflows/mark', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({workflow: b.dataset.wf, step: b.dataset.step,
                            work: b.dataset.work, done: b.dataset.done === '1'})})
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.ok) { location.reload(); return; }
        b.disabled = false;
        alert((j.error && j.error.message) || 'could not record it');
      });
  });
});
document.querySelectorAll('button.skip').forEach(function (b) {
  b.addEventListener('click', function () {
    var skip = b.dataset.skip === '1', reason = '';
    if (skip) {
      reason = prompt(b.dataset.label + ' is not needed for ' + b.dataset.name +
                      '. Why? (optional)', '');
      if (reason === null) { return; }
    }
    b.disabled = true;
    fetch('/api/workflows/skip', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({workflow: b.dataset.wf, step: b.dataset.step,
                            work: b.dataset.work, skip: skip, reason: reason})})
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (j.ok) { location.reload(); return; }
        b.disabled = false;
        alert((j.error && j.error.message) || 'could not record it');
      });
  });
});
</script>
"""


def render_board_page(board: Mapping[str, Any] | None, *, selected: str = "",
                      drafts: Mapping[str, bool] | None = None,
                      error: str = "", edit_link=None) -> str:
    """``drafts``: ``{guid: is_new}`` for what is written and not distributed.
    ``edit_link(guid)``: where the work's name links (its record in Edit)."""
    drafts = drafts or {}
    wfs = list((board or {}).get("workflows") or [])
    finished = bool((board or {}).get("include_finished"))

    def link(wf_id: str, fin: bool) -> str:
        q = {k: v for k, v in (("wf", wf_id), ("finished", "1" if fin else "")) if v}
        return "/workflows" + (f"?{urlencode(q)}" if q else "")

    tabs = [f'<a class="tab{" on" if not selected else ""}" href="{link("", finished)}">all</a>']
    for wf in wfs:
        tabs.append(f'<a class="tab{" on" if wf["id"] == selected else ""}" '
                    f'href="{link(wf["id"], finished)}">{_esc(wf["id"])} {_esc(wf["label"])} '
                    f'{len(wf["rows"])}</a>')
    tabs.append(f'<a class="fin" href="{link(selected, not finished)}">'
                f'{"hide" if finished else "show"} finished</a>')
    shown = [w for w in wfs if not selected or w["id"] == selected]
    body = (f'<div class="card err">{_esc(error)}</div>' if error else
            "".join(_table(w, drafts, edit_link) for w in shown) or
            '<p class="empty">No workflows are configured (config/workflows.rson).</p>')
    since = (board or {}).get("track_since")
    horizon = f"works entered since {_esc(since)}" if since else "all works"
    legend = ('<p class="legend"><span>&#9679; done (date)</span>'
              '<span style="opacity:.6">&#9679; done by implication</span>'
              '<span>&#9673; under way</span><span>&#9675; ready</span>'
              '<span>&middot; waiting on an earlier step</span>'
              '<span>&ndash; not needed for this work</span>'
              '<span>dashed ring: not yet distributed</span></p>')
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Workflows</title>
<style>{_STYLE}{_CSS}</style></head>
<body>
<header><h1>Workflows</h1>
<span class="sub">where each work is, read from the records &middot; {horizon}</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main><nav class="wf-tabs">{"".join(tabs)}</nav>
{body}
{legend}
</main>{_SCRIPT}</body></html>"""


def board_summary(board: Mapping[str, Any] | None) -> tuple[int, int]:
    """(works in flight, of which stalled)."""
    rows = [r for w in (board or {}).get("workflows") or [] for r in w["rows"]
            if not r["finished"]]
    return len(rows), sum(1 for r in rows if r.get("stalled"))


def render_board_card(board: Mapping[str, Any] | None, stall_days: int = 7) -> str:
    if board is None:
        return ('<a href="workflows" class="card">'
                '<div class="card-title">Workflows</div>'
                '<div class="card-desc">Where each work is in its workflow</div></a>')
    n, stalled = board_summary(board)
    desc = f"{n} work{'s' if n != 1 else ''} in flight"
    if stalled:
        desc += f" &middot; {stalled} idle over {stall_days} days"
    return (f'<a href="workflows" class="card{" yellow" if stalled else ""}">'
            f'<div class="card-title">Workflows</div>'
            f'<div class="card-desc">{desc}</div></a>')
