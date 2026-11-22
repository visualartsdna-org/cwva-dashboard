"""Server-rendered entry forms — the Groovy generators' behaviour, in Python.

Phase 4.7: `html/function.html` is the hub, used directly. The entry forms it
links to were never *in* that file — Groovy generated them per request
(`support/HtmlForm2Ttl.groovy` for RDF Entry), filling in a fresh guid, today's
dates, and a `hasPaper` dropdown queried live from the vocabulary. This module
reproduces that behaviour.

**What is reproduced (semantics) vs. what is not (defects).** The extraction doc
`EXTRACTION_record_group.md` classified every divergence, and its decisions are
already in the record tool. The form follows the tool, so those decisions hold
here for free:

- ``qrcode`` is **derived and readonly** — displayed, never submitted (D1).
- ``workOnSite`` is **not** written by entry; updateWorkOnSite owns it (Q2).
- ``image`` is **required** (Q3, Groovy `assert m.fileupload`).
- ``units`` defaults to **inch** for work (D6); dates default to today.
- The ``sig`` radios are **absent**: branding is not record scope (D7).

**The form is generated FROM THE TOOL SCHEMA, not from a hand-written field
list.** That is what keeps the human surface and the agent's contract the same
object after the generic renderer goes away: the `enum` that fills a `<select>`
is the `enum` `validate_args` enforces, and the `x-vocabulary` a picker queries
is the vocabulary the gate checks. A hand-typed `<option>` list would bind only
the human and reopen exactly the hole the affordance layer closed. Layout —
which fields sit together, in what order — comes from the Groovy form and is
declared in :data:`RDF_ENTRY_LAYOUT`; *affordances* come from the schema.
"""

from __future__ import annotations

import datetime
import html
import uuid
from typing import Any, Mapping

from cwva_dashboard import instances

__all__ = [
    "RDF_ENTRY_LAYOUT",
    "RDF_DIGITAL_LAYOUT",
    "RDF_ENTITY_LAYOUT",
    "render_entry_form",
    "render_review_page",
    "render_discard_page",
    "render_site_page",
    "render_annotate_page",
    "render_edit_picker",
    "render_edit_form",
    "render_backup_page",
    "render_instances_page",
    "render_profile_cards",
]

# Field order and grouping, from support/HtmlForm2Ttl.groovy's table. Each row is
# a list of field names rendered side by side; layout is the Groovy form's, the
# widgets are the schema's.
RDF_ENTRY_LAYOUT: list[list[str]] = [
    ["type", "image"],
    ["has_artist_profile", "guid"],
    ["qrcode", "location"],
    ["completed_date", "recorded_date"],
    ["has_paper", "units"],
    ["height", "width"],
    ["label", "note"],
    ["description"],
]

# Field order for RDF Digital, from support/HtmlForm2DigitalTtl.groovy. Same
# reading of the Groovy as the work form, and the same extraction decisions
# apply: `workOnSite` is not written (Q2), the `sig` radios are branding not
# record scope (D7), the digital-media checkboxes were commented out of the
# Groovy's own TTL (D8), and the proof checkboxes belong to proof #5, deferred.
# What is genuinely different: a third dimension, a required `note`, an optional
# `image3d` (.glb), a `background` reference, and no paper. `file_format` was
# here too and was dropped on 2026-09-06: cwva-py decides format from the file
# extension and mimetype, never from the property, so the field asked the user
# to maintain a literal nothing reads.
RDF_DIGITAL_LAYOUT: list[list[str]] = [
    ["type", "image"],
    ["has_artist_profile", "guid"],
    ["qrcode", "image3d"],
    ["completed_date", "recorded_date"],
    ["height", "width"],
    ["depth", "units"],
    ["background"],
    ["label", "note"],
    ["description"],
    # schema:video, added 2026-09. Optional throughout: no video means the
    # property is absent, not empty. `video_duration` is normally filled in for
    # the user by probing the file on submit; it is shown so a deployment with
    # no ffmpeg can type it, and so a probed value can be corrected.
    ["video", "video_duration"],
    ["video_description"],
]

# Field order for the Entity form, from support/EntityEntry.groovy's table.
#
# The entity form is the first that is genuinely multi-valued: topics are a
# checkbox grid (the Groovy laid them out five to a row), images and tags take
# lists, and notes repeat with a kind each. It is also the first with NO qrcode
# — the Groovy generated one for works only, and an entity is not a work.
#
# `md_document`/`pdf_document` were fetched from Google Docs by the Groovy and
# are drop-folder pickers here (law 11 forbids the download, law 12 gives the
# replacement); `document` remains the free-text source URL it always was.
RDF_ENTITY_LAYOUT: list[list[str]] = [
    ["type", "recorded_date"],
    ["label", "guid"],
    ["topic"],
    ["definition"],
    ["images", "tags"],
    ["notes"],
    ["md_document", "pdf_document"],
    ["primary_site", "wikipedia"],
]

# Fields shown but NOT submitted: derived values the Groovy form displayed
# readonly. They have no schema entry (D1 removed qrcode from the input surface),
# so the renderer needs them declared here or they silently vanish from a layout
# that names them.
DERIVED_FIELDS = {
    "qrcode": "Derived from guid + image base; the JPEG is generated on submit.",
}

_STYLE = """
:root{--bg:#0f1420;--card:#182030;--line:#2b3648;--ink:#e8eef7;--muted:#9fb0c8;
--accent:#4da3ff;--ok:#3ecf8e;--warn:#ffb454;--bad:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
header{padding:1rem 2rem;border-bottom:1px solid var(--line);display:flex;
align-items:center;gap:1rem}
header h1{font-size:1.1rem;margin:0;font-weight:600}
header .sub{color:var(--muted);font-size:.85rem}
a{color:var(--accent);text-decoration:none}
main{max-width:1000px;margin:1.5rem auto;padding:0 1.5rem}
.check-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(11rem,1fr));
gap:.35rem .9rem}
.check{display:flex;align-items:start;gap:.4rem;font-size:.85rem;color:var(--ink);
margin:0;text-transform:none;line-height:1.3}
/* The global `input{width:100%}` stretches a checkbox to fill its cell, which
   pushes the caption to the far right and leaves the column looking ragged. A
   checkbox has an intrinsic size; it must keep it. */
.check input[type=checkbox]{width:auto;flex:none;margin:.15rem 0 0}
.note-row{display:flex;gap:.5rem;align-items:flex-start;margin-bottom:.4rem}
.note-row select{width:9rem;flex:none}
.note-row textarea{flex:1}
.note-row .link{flex:none}
.ok-dot{color:var(--ok);font-weight:700}
a.button{display:inline-block;padding:.5rem .9rem;border:1px solid var(--line);
border-radius:8px;background:#182030;color:var(--ink);font-size:.9rem;
margin-left:.5rem;text-decoration:none}
a.button:hover{border-color:var(--accent)}
.instance-head{display:flex;align-items:center;gap:.5rem;margin-bottom:.6rem}
.instance-actions{display:flex;flex-wrap:wrap;gap:.5rem;align-items:center}
.instance-result{white-space:pre-wrap;font-family:ui-monospace,monospace;
font-size:.8rem;margin-top:.6rem;max-height:19rem;overflow:auto;
background:#0d121c;border:1px solid var(--line);border-radius:8px;padding:.5rem .6rem}
.instance-result.ok{border-color:var(--ok)}
.instance-result.err{border-color:var(--bad);color:var(--bad)}
.instance-result.warn{border-color:#d9a441}
.tgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(19rem,1fr));gap:.35rem;max-height:22rem;overflow-y:auto;padding:.4rem;border:1px solid var(--line);border-radius:8px}
.tfield{display:flex;align-items:center;gap:.5rem}
.tfield input[type=checkbox]{width:auto;flex:none}
.tf-name{flex:1;font-size:.85rem}
.tf-order{width:4.5rem;flex:none}

.ro{background:#0d121c;border:1px dashed var(--line);border-radius:8px;
padding:.5rem .6rem;color:var(--muted);font-size:.85rem;overflow-x:auto}
.bad-dot{color:var(--warn);font-weight:700}
details.scheme{border:1px solid var(--line);border-radius:8px;padding:.5rem .7rem;
margin:.5rem 0;background:#0d121c}
details.scheme summary{cursor:pointer;font-size:.85rem;color:var(--muted);
text-transform:none;list-style:revert}
details.scheme .check-grid{margin-top:.5rem}
#conceptFilter{margin:.4rem 0 .2rem}
.card.session{display:flex;align-items:center;gap:.8rem;padding:.7rem 1rem;
border-color:var(--warn)}
li.draft{display:flex;align-items:center;gap:.6rem;justify-content:space-between}
li.add{color:var(--ok)}
li.gone{color:var(--bad)}
li.draft .check{flex:1}
/* The work picker: a radio pair over the dropdown. `input{width:100%}` would
   stretch each radio across its label, same trap as the checkboxes above. */
.order{display:flex;align-items:center;gap:.9rem;color:var(--muted);
font-size:.8rem;text-transform:uppercase;letter-spacing:.05em;margin-bottom:.4rem}
.order .radio{display:flex;align-items:center;gap:.3rem;margin:0;
text-transform:none;letter-spacing:0;font-size:.85rem;color:var(--ink)}
.order input[type=radio]{width:auto;flex:none;margin:0}
/* The record GROUP: which list you are looking at, not a value being edited,
   so it reads as navigation — a row of links with the current one lit. */
.tabs{display:flex;gap:.4rem;margin-bottom:.7rem;flex-wrap:wrap}
.tabs .tab{padding:.25rem .7rem;border:1px solid var(--line);border-radius:999px;
font-size:.85rem;text-decoration:none;color:var(--muted)}
.tabs .tab.on{color:var(--ink);border-color:var(--accent);background:var(--card)}
.pick-row{display:flex;gap:.5rem;align-items:center}
.pick-row select{flex:1}
.pick-row button{flex:none}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:1.25rem;margin-bottom:1.25rem}
.row{display:flex;gap:1.25rem;flex-wrap:wrap;margin-bottom:.9rem}
.field{flex:1 1 260px;min-width:220px}
.field.wide{flex-basis:100%}
label{display:block;font-size:.8rem;color:var(--muted);margin-bottom:.3rem;
text-transform:lowercase;letter-spacing:.02em}
/* A field's CAPTION is house style, lower-cased on purpose. The template
   builder's rows are <label> too, but what they carry is the MODEL's words —
   "3D image, a URI reference to a GLB file" — and lower-casing those turned an
   initialism into a word and a dimension into a letter: "3d image, a uri
   reference to a glb file" (Rick, 2026-09-17). Vocabulary is not styling. */
.tfield, .tfield .tf-name{text-transform:none;letter-spacing:normal}
label .req{color:var(--warn)}
input,select,textarea{width:100%;padding:.5rem .6rem;background:#0d121c;
color:var(--ink);border:1px solid var(--line);border-radius:6px;font:inherit}
input[readonly]{color:var(--muted);background:#0a0e16}
textarea{min-height:5.5rem;resize:vertical}
.hint{font-size:.75rem;color:var(--muted);margin-top:.25rem}
.actions{display:flex;gap:.75rem;align-items:center;margin-top:1rem}
button{padding:.55rem 1.1rem;border-radius:6px;border:1px solid var(--line);
background:#233047;color:var(--ink);font:inherit;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#08101c;
font-weight:600}
button.danger{background:#3a2028;border-color:#5a2b36;color:#ffb3b3}
.gate{display:flex;gap:.5rem;align-items:baseline;padding:.35rem 0;
border-bottom:1px solid var(--line);font-size:.9rem}
.gate:last-child{border-bottom:0}
.pill{font-size:.7rem;padding:.1rem .5rem;border-radius:999px;font-weight:600}
.pill.ok{background:rgba(62,207,142,.15);color:var(--ok)}
.pill.bad{background:rgba(255,107,107,.15);color:var(--bad)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.85rem}
.summary{background:#0d121c;border:1px solid var(--line);border-radius:6px;
padding:.75rem;white-space:pre-wrap}
.err{background:rgba(255,107,107,.1);border:1px solid #5a2b36;color:#ffc9c9;
padding:.75rem;border-radius:6px;margin-bottom:1rem}
.note{color:var(--muted);font-size:.85rem}
.notice{background:rgba(255,180,84,.12);border:1px solid #5a4526;color:#ffd9a3;
padding:.75rem;border-radius:6px;margin-bottom:1rem}
.legend{margin-top:1rem;padding-top:.75rem;border-top:1px solid var(--line);
color:var(--muted);font-size:.8rem}
.refresh-row{display:flex;gap:.5rem;align-items:center;margin-top:.3rem}
/* One picker per file a record cites; they stack. */
.slot{margin-bottom:.5rem}
button.link{background:none;border:0;padding:0;color:var(--accent);cursor:pointer;
font-size:.78rem}
button.link:hover{text-decoration:underline}
.src-head{color:var(--muted);margin:.6rem 0 .3rem;font-size:.8rem}
.src{background:#0d121c;border:1px solid var(--line);border-radius:6px;
padding:.75rem;margin:0;max-height:22rem;overflow:auto;font-size:.8rem;
line-height:1.45;white-space:pre;tab-size:2}
"""

# Leaving the edit form loses work that exists nowhere else. Two exits are
# guarded: Reset (wipes the fields) and the dashboard link (navigates away).
# beforeunload covers the rest of the ways out of a page.
# Re-read a file-ref folder and rebuild its <select> in place.
#
# The remedy for a filename collision is "rename it in your drop folder", and
# that is only a remedy if the new name can be picked up WITHOUT reloading —
# a reload discards everything typed. Ships on every render of a form that has a
# file picker, not just in edit state.
#
# Deliberately free of escape sequences: an earlier script here shipped a literal
# newline inside a JS string, which is a SyntaxError that kills the whole block
# silently.
_REFRESH_SCRIPT = """<script>
function refreshFileRef(btn, field, subtree, kind) {
  var sel = document.getElementById(field);
  var msg = btn.parentNode.querySelector('.refresh-msg');
  if (!sel) { return; }
  var chosen = sel.value;
  btn.disabled = true;
  if (msg) { msg.textContent = 'reading...'; }
  var editing = sel.hasAttribute('data-unchanged')
    ? '&edit=1&current=' + encodeURIComponent(sel.getAttribute('data-unchanged'))
    : '';
  fetch('/api/affordance/file-ref?subtree=' + encodeURIComponent(subtree)
        + '&kind=' + encodeURIComponent(kind) + editing)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      var items = (data && data.candidates) || [];
      sel.innerHTML = '';
      var first = document.createElement('option');
      var keep = sel.getAttribute('data-unchanged');
      first.value = keep || '';
      first.textContent = keep ? (keep + ' - unchanged') : '- choose -';
      sel.appendChild(first);
      // On an EDIT form the first option is the file this record already
      // cites, and it is the selected one. A refresh that replaced it with an
      // empty choose-one would make the next save clear the reference, which
      // is the opposite of what pressing Refresh asks for.
      if (keep && !chosen) { first.selected = true; }
      var stillThere = false;
      items.forEach(function (it) {
        var o = document.createElement('option');
        o.value = it.value;
        o.textContent = it.label || it.value;
        if (it.value === chosen) { o.selected = true; stillThere = true; }
        sel.appendChild(o);
      });
      sel.disabled = false;
      if (msg) {
        msg.textContent = items.length + ' file(s)'
          + (chosen && !stillThere ? ' - your previous choice is gone, pick again' : '');
      }
    })
    .catch(function () { if (msg) { msg.textContent = 'could not read the folder'; } })
    .then(function () { btn.disabled = false; });
}
</script>"""


# Fill the date-format hint from the browser itself.
#
# <input type="date"> is rendered by the browser in its own locale and the
# server cannot override that, so the only hint guaranteed to match the field is
# one derived from the same source. formatToParts on a known date gives the
# actual order and separators the browser uses — not a guess from a locale
# table, which is where this kind of feature usually goes wrong.
#
# No escape sequences, for the reason the leave guard exists.
_DATE_FORMAT_SCRIPT = """<script>
(function () {
  var slots = document.querySelectorAll('.date-fmt');
  if (!slots.length || typeof Intl === 'undefined') { return; }
  var pattern;
  try {
    var sample = new Date(2001, 11, 22);
    var parts = new Intl.DateTimeFormat(undefined, {
      year: 'numeric', month: '2-digit', day: '2-digit'
    }).formatToParts(sample);
    pattern = parts.map(function (p) {
      if (p.type === 'year') { return 'YYYY'; }
      if (p.type === 'month') { return 'MM'; }
      if (p.type === 'day') { return 'DD'; }
      return p.value;
    }).join('');
  } catch (e) {
    return;
  }
  if (!pattern) { return; }
  for (var i = 0; i < slots.length; i++) { slots[i].textContent = pattern; }
})();
</script>"""


_LEAVE_GUARD = """<script>
(function () {
  var dirty = true;
  var form = document.getElementById('entryForm');
  if (form) { form.addEventListener('submit', function () { dirty = false; }); }
  window.confirmDiscard = function () {
    if (!dirty) { return true; }
    var ok = window.confirm(
      'Leave without submitting? Your draft is still in QA as it was, and the '
      + 'values you have typed since are only in this form.');
    if (ok) { dirty = false; }
    return ok;
  };
  window.addEventListener('beforeunload', function (e) {
    if (!dirty) { return; }
    e.preventDefault();
    e.returnValue = '';
  });
})();
</script>"""


# Add/remove note rows. Deliberately free of escape sequences, like every other
# script here: a literal newline inside a JS string once killed a whole IIFE
# silently, and two unrelated symptoms were traced back to it. The row markup
# comes from a <template> the server rendered, so the JS never builds HTML and
# the kinds cannot drift from the schema's enum.
_NOTES_SCRIPT = """<script>
(function () {
  var container = document.getElementById('notesContainer');
  var template = document.getElementById('noteRowTemplate');
  window.addNote = function () {
    if (!container || !template) { return; }
    container.appendChild(template.content.cloneNode(true));
  };
  window.removeNote = function (button) {
    var row = button.parentNode;
    if (!row || !row.parentNode) { return; }
    if (row.parentNode.children.length > 1) { row.parentNode.removeChild(row); }
    else {
      var text = row.querySelector('textarea');
      if (text) { text.value = ''; }
    }
  };
})();
</script>"""


def _esc(v: Any) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _today() -> str:
    return datetime.date.today().isoformat()


def _drop_note(drop_folder: str) -> str:
    """Where files come from, stated on the form rather than learned by failing.

    With two ways to get there. **Open folder** asks the server to show it in
    the desktop's file manager — a browser cannot, since navigation from an http
    page to a `file://` URL is blocked silently. **Copy path** is the one that
    always works: on another machine, in a headless install, or when no file
    manager is installed, a path you can paste is the whole answer.
    """
    if not drop_folder:
        return ""
    return (
        '<div class="note" style="margin-top:.9rem">Images and documents come from '
        f'your drop folder <span class="mono" id="dropPath">{_esc(drop_folder)}</span>. '
        "Put a file there and reload; the dashboard copies it in when you submit. "
        "<strong>You never touch the sandbox.</strong>"
        '<span class="dropacts">'
        '<button type="button" id="dropOpen">Open folder</button>'
        '<button type="button" id="dropCopy">Copy path</button>'
        '<span id="dropSaid" class="note"></span></span></div>'
        + _DROP_ACTIONS_SCRIPT
    )


# No escape sequences, like every other script here.
_DROP_ACTIONS_SCRIPT = """<script>
(function () {
  var path = document.getElementById('dropPath');
  var said = document.getElementById('dropSaid');
  var openBtn = document.getElementById('dropOpen');
  var copyBtn = document.getElementById('dropCopy');
  if (!path) { return; }
  function say(msg) { said.textContent = msg; }
  if (copyBtn) {
    copyBtn.addEventListener('click', function () {
      var text = path.textContent;
      if (navigator.clipboard && window.isSecureContext) {
        navigator.clipboard.writeText(text).then(
          function () { say('copied'); },
          function () { say('press ctrl-c to copy'); select(text); });
      } else {
        select(text);
        say('press ctrl-c to copy');
      }
    });
  }
  function select(text) {
    var r = document.createRange();
    r.selectNodeContents(path);
    var s = window.getSelection();
    s.removeAllRanges();
    s.addRange(r);
  }
  if (openBtn) {
    openBtn.addEventListener('click', function () {
      say('opening ...');
      fetch('/api/inbox/open', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function (b) {
          say(b.ok ? 'opened in ' + b.opener
                   : 'could not open it here - use Copy path');
        })
        .catch(function () { say('could not open it here - use Copy path'); });
    });
  }
})();
</script>"""


def _as_values(value) -> list[str]:
    if value in (None, ""):
        return []
    return [str(v) for v in (value if isinstance(value, list) else [value])]


def _checkbox_grid(name: str, options: list, value) -> str:
    """A closed multi-select as checkboxes.

    Each box submits under the SAME field name, so the browser sends one
    repeated key and the route reads them with `getlist` — no index juggling.
    The Groovy numbered them `media0..media30` and reassembled the list on the
    server, which is what a form built by string concatenation has to do; it
    also silently truncated at 31 topics.

    Columns are CSS, not markup: the Groovy emitted a `</tr><tr>` every fifth
    cell, which fixes the column count at whatever the author's window happened
    to be. A grid of auto-filled columns keeps the captions aligned at any
    width, and a long caption wraps inside its own cell instead of shoving the
    next one sideways.
    """
    chosen = set(_as_values(value))
    cells = []
    for i, o in enumerate(options):
        val, lab = (o["value"], o.get("label", o["value"])) if isinstance(o, dict) else (o, o)
        checked = " checked" if str(val) in chosen else ""
        box_id = f"{name}__{i}"
        cells.append(
            f'<label class="check" for="{_esc(box_id)}">'
            f'<input type="checkbox" id="{_esc(box_id)}" name="{_esc(name)}" '
            f'value="{_esc(val)}"{checked}><span>{_esc(lab)}</span></label>'
        )
    if not cells:
        return '<div class="note">— none available —</div>'
    return f'<div class="check-grid">{"".join(cells)}</div>'


def _refresh_row(name: str, subtree: str, kind: str) -> str:
    """The in-place "Refresh list" control for a file picker.

    **Rendered even when the picker is EMPTY**, which is the case that needs it
    most: the remedy for "no files in your drop folder" is to put one there, and
    without this the only way to see it was to reload the page and lose
    everything typed (Rick, 2026-09-27). The script re-enables the select when
    candidates arrive, so an empty picker becomes a usable one in place.
    """
    if not subtree:
        return ""
    return (
        '<div class="refresh-row">'
        f'<button type="button" class="link" '
        f"onclick=\"refreshFileRef(this, '{_esc(name)}', "
        f"'{_esc(subtree)}', '{_esc(kind)}')\">"
        "&#8635; Refresh list</button>"
        '<span class="note refresh-msg"></span></div>'
    )


def _multi_select(name: str, options: list, value, empty_hint: str,
                  refresh_subtree: str, refresh_kind: str) -> str:
    """A file picker that takes several files. Still a `<select>`, so the
    in-place "Refresh list" control works on it exactly as on the single
    pickers."""
    common = f'id="{_esc(name)}" name="{_esc(name)}" multiple size="4"'
    if not options:
        label = empty_hint or "— none available —"
        return (f'<select {common} disabled><option>{_esc(label)}</option></select>'
                + _refresh_row(name, refresh_subtree, refresh_kind))
    chosen = set(_as_values(value))
    opts = []
    for o in options:
        val, lab = (o["value"], o.get("label", o["value"])) if isinstance(o, dict) else (o, o)
        sel = " selected" if str(val) in chosen else ""
        opts.append(f'<option value="{_esc(val)}"{sel}>{_esc(lab)}</option>')
    return (f"<select {common}>{''.join(opts)}</select>"
            + _refresh_row(name, refresh_subtree, refresh_kind))


def _notes_widget(value, kinds: list) -> str:
    """Repeating {kind, text} rows, as the Groovy's `+ Add Note` produced.

    Rows submit as parallel `note_type`/`note_text` lists rather than the
    Groovy's numbered `noteType1..20` keys, so removing a row leaves no gap to
    reassemble and there is no upper bound to silently exceed. The kinds are the
    schema's own enum, which `validate_args` now enforces per element.
    """
    rows = [n for n in (value or []) if isinstance(n, dict) and str(n.get("text", "")).strip()]
    if not rows:
        rows = [{"type": "note", "text": ""}]
    out = ['<div id="notesContainer">']
    for n in rows:
        out.append(_note_row(str(n.get("type") or "note"), str(n.get("text") or ""), kinds))
    out.append("</div>")
    out.append(
        '<button type="button" class="link" onclick="addNote()">+ Add note</button>'
        # The template the JS clones, so "add" and "render" cannot disagree
        # about what a row looks like — and the kinds still come from one place.
        f'<template id="noteRowTemplate">{_note_row(kinds[0], "", kinds)}</template>'
    )
    return "".join(out)


def _note_row(kind: str, text: str, kinds: list) -> str:
    opts = "".join(
        f'<option value="{_esc(k)}"{" selected" if k == kind else ""}>{_esc(k)}</option>'
        for k in kinds
    )
    return (
        '<div class="note-row">'
        f'<select name="note_type">{opts}</select>'
        f'<textarea name="note_text" rows="2">{_esc(text)}</textarea>'
        '<button type="button" class="link" onclick="removeNote(this)">remove</button>'
        "</div>"
    )



def _brand_control(signatures) -> str:
    """One select, offered only where an image can arrive.

    Blank by default and that is deliberate. Branding is destructive and not
    idempotent — a second stamp lands on top of the first, invisible when the
    fonts match and a smear when they do not — and Rick's images already arrive
    branded from the legacy server, so a default of ON would double-stamp his
    current workflow on day one. The review stop reports which images were
    branded and which were not, so the choice is visible either way rather than
    remembered.
    """
    if not signatures:
        return ""
    opts = ['<option value="">&mdash; leave as they are &mdash;</option>']
    opts += [f'<option value="{_esc(s)}">{_esc(s)}</option>' for s in signatures]
    return (
        '<div class="field wide brandbox">'
        '<label for="brand_signature">Brand this image on the way in</label>'
        f'<select id="brand_signature" name="brand_signature">{"".join(opts)}</select>'
        '<div class="hint">Stamps the site signature into the lower-right corner '
        "of every image this save copies in from your drop folder. Images already "
        "in the store are left alone, and branding twice draws the signature over "
        "itself &mdash; so leave this blank for an image that arrives already "
        "branded.</div></div>"
    )



def _template_fields_widget(name: str, options: list, value) -> str:
    """The form builder: every property the dashboard can render, each with a
    tick and a position.

    "Perhaps a simple form builder with a list of the properties available to
    select from to populate the template and a means of ordering" — this is
    that, at its smallest. A tick and a number is exactly the shape of
    `ops:field [ops:property … ; ops:order …]`, so the widget and the record it
    writes have the same structure and there is no translation layer to get
    wrong.

    Some rows are LOCKED ON: without them the works browser cannot display the
    record, so they are ticked and cannot be unticked (Rick, 2026-09-17). Their
    position is still the artist's — the requirement is that the property is
    there, not where it sits.

    Each row posts `"<predicate>:<order>"` when ticked, which is what a grid of
    checkboxes can send without inventing a nested form encoding.
    """
    chosen = {}
    for item in (value or []):
        pred, _, order = str(item).rpartition(":")
        if pred:
            chosen[pred] = order
    rows = []
    for i, opt in enumerate(options, start=1):
        if isinstance(opt, dict):
            pred, label = opt["value"], opt.get("label", opt["value"])
            locked, suggested = opt.get("mandatory", False), opt.get("order", i * 10)
        else:
            pred, label, locked, suggested = str(opt), str(opt), False, i * 10
        order = chosen.get(pred, str(suggested))
        ticked = " checked" if locked or pred in chosen else ""
        # `disabled` is what makes it unclickable, and the browser greys it —
        # the lock is visible rather than a click that mysteriously does
        # nothing. The collector reads `.checked`, which a disabled box still
        # reports, so a locked row is carried like any other.
        lock = " disabled" if locked else ""
        rows.append(
            f'<label class="tfield{" locked" if locked else ""}">'
            f'<input type="checkbox" class="tf-pick" value="{_esc(pred)}"{ticked}{lock}>'
            f'<span class="tf-name">{_esc(label)}</span>'
            f'<input type="number" class="tf-order" value="{_esc(order)}" min="1" '
            'step="1" aria-label="position on the form">'
            "</label>"
        )
    return (
        f'<input type="hidden" id="{_esc(name)}" name="{_esc(name)}" value="">'
        f'<div class="tgrid" data-for="{_esc(name)}">{"".join(rows)}</div>'
        + _TEMPLATE_FIELDS_SCRIPT
    )


# Collapses the grid into the hidden field on submit. No escape sequences, for
# the reason every other script here avoids them.
_TEMPLATE_FIELDS_SCRIPT = """<script>
(function () {
  var grid = document.querySelector('.tgrid');
  if (!grid) { return; }
  var target = document.getElementById(grid.getAttribute('data-for'));
  var form = grid.closest('form');
  function collect() {
    var out = [];
    var rows = grid.querySelectorAll('.tfield');
    for (var i = 0; i < rows.length; i++) {
      var pick = rows[i].querySelector('.tf-pick');
      var order = rows[i].querySelector('.tf-order');
      if (pick.checked) { out.push(pick.value + ':' + (order.value || '0')); }
    }
    // Comma-joined because the submit route already splits array fields
    // on commas. A predicate never contains one, and inventing a
    // separator would mean teaching the route a second encoding.
    target.value = out.join(',');
  }
  grid.addEventListener('change', collect);
  if (form) { form.addEventListener('submit', collect); }
  collect();
})();
</script>"""


def _widget(
    name: str,
    spec: Mapping[str, Any],
    value: Any,
    options: list | None,
    empty_hint: str = "",
    refresh_subtree: str = "",
    refresh_kind: str = "image",
) -> str:
    """One input, chosen by the field's *declared affordance* — the same
    `widgetKind` dispatch the retired generic renderer used, kept because it is
    what makes the offered set and the enforced set the same thing."""
    common = f'id="{_esc(name)}" name="{_esc(name)}"'
    is_array = spec.get("type") == "array"

    # --- multi-valued fields, first needed by the entity form ---------------
    #
    # Three shapes, and the shape follows the SOURCE of the values, not taste:
    #
    #   array + closed vocabulary  -> checkbox grid. The set is small (23
    #     topics) and fully known, so showing all of it is better than hiding it
    #     behind a scroll. This is the Groovy's own layout, five to a row.
    #   array + file picker        -> <select multiple>. It stays a <select>
    #     precisely so "Refresh list" keeps working unchanged — the drop folder
    #     changes under the user, and re-reading it must not cost the form.
    #   array + no options         -> textarea, one value per line or comma
    #     separated. Tags are free URIs (up to 20 on one record in the real
    #     store), so no closed set exists to offer.
    if is_array and name == "notes":
        # Kinds come FROM THE SCHEMA — the same enum validate_args enforces per
        # element. A literal list here would be a second copy of a closed set,
        # which is how the offered set and the enforced set come apart.
        kinds = (
            ((spec.get("items") or {}).get("properties") or {})
            .get("type", {}).get("enum") or ["note"]
        )
        return _notes_widget(value, kinds)
    if is_array and spec.get("x-template-fields"):
        return _template_fields_widget(name, options or [], value)
    if is_array and options is not None and "x-vocabulary" in spec:
        return _checkbox_grid(name, options, value)
    if is_array and options is not None:
        return _multi_select(name, options, value, empty_hint,
                             refresh_subtree, refresh_kind)
    if is_array:
        joined = "\n".join(str(v) for v in (value or []) if str(v).strip())
        return f"<textarea {common} rows=\"3\">{_esc(joined)}</textarea>"

    # The SCHEMA's word comes first. A generated form hides `guid`; a
    # hand-written one shows it read-only, and the name-based branches below are
    # what the hand-written forms have always used.
    if spec.get("x-hidden"):
        shown = value if str(value).strip() else spec.get("default", "")
        return f'<input type="hidden" {common} value="{_esc(shown)}">'
    if name == "qrcode":  # derived, never submitted (D1)
        return f'<input {common} value="{_esc(value)}" readonly disabled>'
    if name == "guid":
        return f'<input {common} value="{_esc(value)}" readonly>'
    # Declared read-only by the SCHEMA rather than by name. A profile form is
    # entered from its own card, so `has_artist_profile` is already known and
    # offering it as a picker invites a wrong answer to a question nobody asked
    # (Rick, 2026-09-14). Readonly still submits, so the value is unchanged.
    if spec.get("x-readonly"):
        shown = value if str(value).strip() else spec.get("default", "")
        return f'<input {common} value="{_esc(shown)}" readonly>'

    enum = spec.get("enum")
    if enum and not spec.get("x-options"):
        # `x-options` wins when both are present: the enum is what
        # `validate_args` enforces (artist URIs), the options are how a person
        # reads it (their names). Rendering the enum here showed the picker as
        # a list of URIs — the enforced set displayed instead of the offered
        # one, which is the same set said unhelpfully.
        opts = "".join(
            f'<option value="{_esc(o)}"{" selected" if str(o) == str(value) else ""}>{_esc(o)}</option>'
            for o in enum
        )
        return f"<select {common}>{opts}</select>"

    suggested = spec.get("x-enum-suggested")
    if suggested:
        # Unenforced by design: real data exceeds the form's set (EXTRACTION F1),
        # so this suggests without constraining. Never render it as a closed
        # <select> — that would imply a guard `validate_args` does not apply.
        opts = "".join(f'<option value="{_esc(o)}">' for o in suggested)
        return (
            f'<input type="text" {common} value="{_esc(value)}" list="{_esc(name)}__sug">'
            f'<datalist id="{_esc(name)}__sug">{opts}</datalist>'
        )

    if options is not None:  # x-vocabulary / x-file-ref, resolved server-side
        if not options:
            # An empty picker must say what to DO about it. For a file field
            # that means naming the drop folder — the user never opens the
            # sandbox, so a bare "none available" would be a dead end — AND
            # offering the refresh, since putting a file there is the remedy.
            label = empty_hint or "— none available —"
            return (f'<select {common} disabled><option>{_esc(label)}</option></select>'
                    + _refresh_row(name, refresh_subtree, refresh_kind))
        opts = ['<option value="">— choose —</option>']
        for o in options:
            val, lab = (o["value"], o.get("label", o["value"])) if isinstance(o, dict) else (o, o)
            sel = " selected" if str(val) == str(value) else ""
            opts.append(f'<option value="{_esc(val)}"{sel}>{_esc(lab)}</option>')
        # A filename collision is fixed by renaming in the drop folder, and the
        # fix has to be usable WITHOUT reloading: a reload discards everything
        # typed, which is the opposite of a remedy. This re-reads the folder in
        # place and keeps the rest of the form untouched.
        return (f"<select {common}>{''.join(opts)}</select>"
                + _refresh_row(name, refresh_subtree, refresh_kind))

    if spec.get("x-multiline"):
        return f"<textarea {common}>{_esc(value)}</textarea>"
    if spec.get("format") == "date":
        return f'<input type="date" {common} value="{_esc(value)}">'
    if spec.get("type") == "number":
        return f'<input type="number" step="any" {common} value="{_esc(value)}">'
    return f'<input type="text" {common} value="{_esc(value)}">'


def _file_location_row(spec: Mapping[str, Any] | None) -> str:
    """Where the definitive file of a digital work lives (PROVENANCE_PLAN §3).

    Not a field of the work: it goes on the provenance record the submit writes.
    Offered only when this form's kind of work is stored as a file.
    """
    if not spec:
        return ""
    return (
        '<div class="row"><div class="field wide">'
        '<label for="file_location">Original file</label>'
        f'<input type="text" id="file_location" name="file_location" '
        f'value="{_esc(spec.get("value", ""))}" placeholder="G:\\My Drive\\...\\work.blend">'
        '<div class="note">The definitive file this work IS, for its provenance '
        f'record ({_esc(spec.get("storage_class", ""))} storage). Paste the path; '
        "spaces and backslashes are converted. Optional, but nothing else in the "
        "dashboard can add it later.</div></div></div>"
    )


def render_entry_form(
    schema: Mapping[str, Any],
    *,
    guid: str | None = None,
    vocabularies: Mapping[str, list] | None = None,
    file_refs: Mapping[str, list] | None = None,
    values: Mapping[str, Any] | None = None,
    qrcode_url: str = "",
    drop_folder: str = "",
    field_layout: list[list[str]] | None = None,
    terms: Mapping[str, Mapping[str, str]] | None = None,
    date_format: str = "",
    editing: bool = False,
    notice: str = "",
    error: str = "",
    action: str = "/rdf/entry",
    title: str = "VADNA RDF Entry",
    signatures: list | None = None,
    episode: dict | None = None,
    picker: str = "",
    file_location: Mapping[str, Any] | None = None,
) -> str:
    """Render the RDF Entry form for one fresh work.

    ``vocabularies`` / ``file_refs`` are resolved trusted-side and keyed by the
    annotation value, so the picker offers exactly what the gate accepts.
    """
    # An EDIT form (one with a record chooser above it) gets the unsaved-changes
    # guard, so switching records challenges first. A create form has nothing to
    # go back to and nothing to challenge about.
    chooser_script = (_WORK_ORDER_SCRIPT + _DIRTY_GUARD_SCRIPT) if picker else ""
    guard_attr = (
        ' data-guard="This record has unsaved edits. Leave without saving them?"'
        if picker else ""
    )
    props: Mapping[str, Any] = schema["inputSchema"]["properties"]
    required = set(schema["inputSchema"].get("required", []))
    vocabularies = vocabularies or {}
    file_refs = file_refs or {}
    values = dict(values or {})
    guid = guid or str(uuid.uuid4())
    empty_file_hint = (
        f"— no files in {drop_folder} —" if drop_folder else "— none available —"
    )

    values.setdefault("guid", guid)
    values.setdefault("recorded_date", _today())
    values.setdefault("completed_date", _today())
    for name, spec in props.items():
        if "default" in spec:
            values.setdefault(name, spec["default"])

    # Offered only where an image can actually arrive, AND where the caller has
    # not said this form does not brand. The comment here used to claim the
    # entity form has no image field; it has one (`images`), so the control was
    # appearing on a form whose images are references and are never stamped.
    # Whether a form brands is the caller's to state, not this function's to
    # infer from the shape of the schema.
    brand_row = _brand_control(signatures) if any(
        "x-file-ref" in s and s.get("x-file-kind", "image") == "image"
        for s in props.values()
    ) else ""

    rows = []
    hidden: list[str] = []
    for group in (field_layout or RDF_ENTRY_LAYOUT):
        cells = []
        for name in group:
            spec = props.get(name)
            if spec is None and name in DERIVED_FIELDS:
                spec = {"type": "string", "description": DERIVED_FIELDS[name]}
            if spec is None:
                continue
            options = None
            if "x-options" in spec:
                # Options carried BY THE SCHEMA, for a closed set the schema
                # already enforces as an `enum` — the artists a profile may
                # belong to. The labels are here only so the picker reads as
                # names rather than URIs.
                options = spec["x-options"]
            elif "x-vocabulary" in spec:
                options = vocabularies.get(spec["x-vocabulary"], [])
            elif "x-entity-ref" in spec:
                # A closed set like a vocabulary field; it differs only in which
                # store the candidates came from, which the renderer neither
                # knows nor needs to.
                options = vocabularies.get(spec["x-entity-ref"], [])
            elif "x-file-ref" in spec:
                # (subtree, kind): `image` and `image3d` share images/ but must
                # not offer each other's files. Falls back to the bare subtree
                # so a caller that passed a flat dict still works.
                fk = (spec["x-file-ref"], spec.get("x-file-kind", "image"))
                options = file_refs.get(fk)
                if options is None:
                    options = file_refs.get(spec["x-file-ref"], [])
            value = qrcode_url if name == "qrcode" else values.get(name, "")
            star = ' <span class="req">*</span>' if name in required else ""
            wide = " wide" if len(group) == 1 else ""
            empty_hint = empty_file_hint if "x-file-ref" in spec else ""
            subtree = spec.get("x-file-ref", "")
            file_kind = spec.get("x-file-kind", "image")
            # Wording comes from the ONTOLOGY: rdfs:label above the field,
            # rdfs:comment below it. Editing the model changes what the form
            # says, with no code change here. Falls back to the field name and
            # the schema description when the model has no term for it, so a
            # field is never unlabelled.
            term = (terms or {}).get(name) or {}
            caption = term.get("label") or name
            hint = _esc(term.get("comment") or "")
            if not hint and not term:
                hint = _esc(spec.get("description", ""))
            # A field that names no ontology property has nothing to defer to —
            # `fields` is the form builder itself, not a statement about a work
            # — so the schema is allowed to say what it is called. Fields that DO
            # name a property keep taking their words from the model, including
            # where the model reads oddly: that is a fix for the model.
            if spec.get("x-caption"):
                caption = spec["x-caption"]
            # How to enter SEVERAL values. This is input mechanics, not
            # meaning, so it is appended to the ontology's comment rather than
            # replacing it — the model describes what the property is, and it
            # cannot know that this particular widget wants commas.
            if spec.get("type") == "array":
                if options is None:
                    hint += (" " if hint else "") + "Separate several with commas."
                elif "x-vocabulary" not in spec and not spec.get("x-template-fields"):
                    # Only a <select multiple> is driven that way. The template
                    # builder is a grid of checkboxes, where the instruction is
                    # not merely unnecessary but false — Rick tried it and got
                    # one row (2026-09-17).
                    hint += (" " if hint else "") + (
                        "Choose several with ctrl-click (cmd-click on a Mac)."
                    )
            # The UNIT this profile measures in. Appended, not substituted:
            # `schema:height` is the height of a thing whatever the unit, and
            # the profile's measurement system is what makes it inches here
            # (Rick, 2026-09-16 — "The height of the work in inches").
            if spec.get("x-unit"):
                unit = _esc(spec["x-unit"])
                hint = f"{hint.rstrip('.')} in {unit}." if hint else f"In {unit}."

            # Date fields say which order the parts go in. DISPLAY ONLY: the
            # value is submitted and stored as ISO (xs:date is ISO 8601 by
            # definition), so this annotates the field without touching what
            # reaches the graph.
            if spec.get("format") == "date" and date_format:
                if date_format == "auto":
                    # Filled in by the browser from the same Intl data that
                    # renders <input type="date">, so the hint and the picker
                    # cannot disagree. The server has no say in how that field
                    # displays, so guessing here — from Accept-Language, say —
                    # would reintroduce exactly the mismatch this removes.
                    # ISO shows until the script runs and if scripting is off:
                    # it is what the field submits, so it is never a lie.
                    shown = '<span class="date-fmt">YYYY-MM-DD</span>'
                else:
                    shown = _esc(date_format)
                hint = f"{hint} ({shown})" if hint else f"({shown})"
            # `hint` may carry the date-format span, so escape its parts as
            # they are built rather than the assembled string.
            hint_html = f'<div class="hint">{hint}</div>' if hint else ""
            widget = _widget(name, spec, value, options, empty_hint, subtree,
                             file_kind)
            # A hidden field is carried, not laid out. Wrapping one in a labelled
            # cell leaves a caption above an empty slot, which reads as a field
            # that failed to render.
            #
            # Asked of the SCHEMA, not of the markup. Sniffing for a leading
            # hidden input swallowed the template builder whole — its widget
            # opens with one and continues with the grid — so the form showed a
            # column of numbers with no caption and no explanation of what they
            # were.
            if spec.get("x-hidden"):
                hidden.append(widget)
                continue
            cells.append(
                f'<div class="field{wide}">'
                f'<label for="{_esc(name)}">{_esc(caption)}{star}</label>'
                f"{widget}{hint_html}</div>"
            )
        if cells:
            rows.append(f'<div class="row">{"".join(cells)}</div>')
            # Immediately under the image field, because that is where the
            # decision is made. Parked at the foot of the form it was below
            # every other predicate and read as configuration — Rick changed an
            # image, did not see it, and reached the review with an unbranded
            # file (2026-09-14).
            if brand_row and any(
                "x-file-ref" in (props.get(n) or {})
                and (props.get(n) or {}).get("x-file-kind", "image") == "image"
                for n in group
            ):
                rows.append(brand_row)
                brand_row = ""

    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    note = f'<div class="notice">{_esc(notice)}</div>' if notice else ""
    # The "double dare": in edit state the form holds work that exists NOWHERE
    # else — its draft files were just trashed — so leaving or resetting loses
    # it for real. Guard both exits, and only in edit state, so an empty new
    # form never nags.
    guard = _LEAVE_GUARD if editing else ""
    # Only shipped when the form actually has a notes field, so the two work
    # forms carry no dead script.
    notes_script = _NOTES_SCRIPT if "notes" in props else ""
    home_attr = ' onclick="return confirmDiscard()"' if editing else ""
    # Reset restores a form to its INITIAL values. On a fresh form that clears
    # it, which is useful. In edit state the initial values *are* the
    # repopulated ones, so Reset can only redraw what is already there — it
    # looked broken because it genuinely had nothing to do. Disabled with the
    # reason visible, rather than left as a button that silently no-ops.
    reset_btn = (
        '<button type="button" disabled title="Nothing to reset — these are the '
        'values you submitted. Use Discard on the dashboard to start over.">'
        "Reset</button>"
        if editing
        else '<button type="reset">Reset</button>'
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{_esc(title)}</title><style>{_STYLE}</style></head>
<body>
<header><h1>{_esc(title)}</h1>
<span class="sub">about <span class="mono">work:{_esc(guid)}</span></span>
<span style="margin-left:auto"><a href="/"{home_attr}>&larr; dashboard</a></span></header>
<main>{err}{note}{render_session_bar(episode)}{picker}
<form class="card" id="entryForm" method="post" action="{_esc(action)}"{guard_attr}>
<input type="hidden" name="guid" value="{_esc(guid)}">
{''.join(hidden)}
{''.join(rows)}{_file_location_row(file_location)}
<div class="actions">
  <button type="submit" class="primary">Create record</button>
  {reset_btn}
  <span class="note">Creates the TTL in QA. Distribute is the next step,
  and it stops for your review before anything reaches the SOT.</span>
</div>
{_drop_note(drop_folder)}
<div class="legend"><span class="req">*</span> required.
Field names and help text come from the ontology
(<span class="mono">rdfs:label</span> and <span class="mono">rdfs:comment</span>),
so editing the model changes what this form says.</div>
</form>
</main>{_REFRESH_SCRIPT}{_DATE_FORMAT_SCRIPT}{notes_script}{guard}{chooser_script}</body></html>"""


def render_review_page(
    *,
    preview: Mapping[str, Any],
    created: list[str] | None = None,
    sources: list[Mapping[str, Any]] | None = None,
    warning: str = "",
    error: str = "",
    renamed: list | None = None,
    annotated: list | None = None,
    branded: list | None = None,
    disposition: Mapping[str, Any] | None = None,
    tags: Mapping[str, Any] | None = None,
    annotation: Mapping[str, Any] | None = None,
    back: Mapping[str, str] | None = None,
) -> str:
    """The Distribute Data review stop: gates, preview, approve/reject.

    This page **is** the review gate until the browser lands (Phase 7), which is
    why approving is an explicit act here rather than a step the submit handler
    takes on the operator's behalf — and why ``sources`` shows the generated TTL
    verbatim. Reviewing a change you cannot read is not reviewing it: the file
    list says *what* was written and the graph summary says *how much*, but only
    the text says whether the triples are right.
    """
    status = preview.get("status", "")
    gates = "".join(
        f'<div class="gate"><span class="pill {"ok" if g.get("ok") else "bad"}">'
        f'{"pass" if g.get("ok") else "FAIL"}</span>'
        f'<span class="mono">{_esc(g.get("name"))}</span>'
        f'<span class="note">{_esc(g.get("summary", ""))}</span></div>'
        for g in preview.get("gates", [])
    )
    made = "".join(f'<li class="mono">{_esc(p)}</li>' for p in (created or []))
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    src_blocks = "".join(
        f'<div class="src-head mono">{_esc(f.get("path"))}'
        + (f' <span class="note">({_esc(f.get("note"))})</span>' if f.get("note") else "")
        + "</div>"
        f'<pre class="src">{_esc(f.get("text", ""))}</pre>'
        for f in (sources or [])
    )
    src_card = (
        '<div class="card"><h2 style="margin-top:0;font-size:1rem">Generated RDF</h2>'
        f"{src_blocks}</div>"
        if src_blocks
        else ""
    )
    # Things the dashboard did FOR the user, reported before they approve.
    # Neither is a problem, so neither is a warning — but both changed something
    # the user did not type, and the review stop is where they find that out
    # while Edit form is still one click away.
    did = []
    for field, was, now in (renamed or []):
        did.append(
            f'<li>renamed <span class="mono">{_esc(was)}</span> &rarr; '
            f'<span class="mono">{_esc(now)}</span> '
            f'<span class="note">({_esc(field)})</span></li>'
        )
    if disposition:
        # The one thing here somebody has to act on: this is what goes on the box
        # flap, or, for a digital work, what names its folder.
        location = ""
        if disposition.get("is_file") and not disposition.get("has_location"):
            location = (' <span class="note">The record does not yet name the '
                        "definitive file (vad:fileLocation).</span>")
        elif disposition.get("file_location"):
            location = (' &mdash; original file <span class="mono">'
                        f'{_esc(disposition["file_location"])}</span>')
        did.append(
            f'<li>Disposition ID <strong class="mono">'
            f'{_esc(disposition.get("disposition_id"))}</strong> '
            + ("allocated" if disposition.get("new") else "kept from your earlier submit")
            + f'; provenance record <span class="mono">{_esc(disposition.get("path"))}'
            f"</span>{location}</li>"
        )
    for name, curie in (annotated or []):
        did.append(
            f'<li>stamped <span class="mono">{_esc(name)}</span> with '
            f'<span class="mono">[id={_esc(curie)}]</span></li>'
        )
    # Branding is burned into the published pixels, so it is reported by NAME
    # and signature before approval rather than discovered on the site — and an
    # image that arrived WITHOUT one is reported just as plainly. Rick changed an
    # image, missed the control, and reached this page with no way to tell
    # (2026-09-14). Silence about an unbranded arrival is the failure mode.
    for name, signature in (branded or []):
        if signature:
            did.append(
                f'<li>branded <span class="mono">{_esc(name)}</span> with '
                f'<span class="mono">{_esc(signature)}</span></li>'
            )
        else:
            did.append(
                f'<li><strong>not branded</strong>: '
                f'<span class="mono">{_esc(name)}</span> came in as it was. '
                '<span class="note">Use Back and choose a signature if it '
                "should carry one.</span></li>"
            )
    did_card = (
        '<div class="card"><h2 style="margin-top:0;font-size:1rem">'
        "Applied on entry</h2>"
        f"<ul class=\"files\">{''.join(did)}</ul>"
        '<div class="note">Filenames are normalized because they become part of '
        "the IRI the record cites, where a space is invalid. To choose a "
        "different name, use Edit form and rename the file in your drop "
        "folder.</div></div>"
        if did
        else ""
    )

    # Tag references, resolved to their labels.
    #
    # `work:53bfd31d-…` tells a reviewer nothing about whether the right thing
    # was tagged; "Network-Art Aesthetic" does. Unresolved tags are shown as a
    # question, not a failure: a tag may legitimately run ahead of the record it
    # names — a work tagged into a series collection that is created afterwards
    # — so this reports and lets the user judge.
    #
    # NO tags at all gets its own line, because the commonest tagging mistake is
    # not a wrong tag, it is forgetting to tag.
    tag_card = ""
    if tags is not None:
        rows = tags.get("tags") or []
        if not rows:
            tag_card = (
                '<div class="card"><h2 style="margin-top:0;font-size:1rem">'
                "Tag references</h2>"
                '<div class="notice">No tags on this record. If it belongs to a '
                "collection or series, tag it now with Edit form — nothing later "
                "will remind you.</div></div>"
            )
        else:
            items = []
            for t in rows:
                if t.get("found"):
                    kinds = ", ".join(t.get("types") or [])
                    items.append(
                        f'<li><span class="ok-dot">&check;</span> '
                        f'<strong>{_esc(t.get("label"))}</strong> '
                        f'<span class="mono note">{_esc(t.get("value"))}</span>'
                        + (f' <span class="note">({_esc(kinds)})</span>' if kinds else "")
                        + "</li>"
                    )
                else:
                    items.append(
                        f'<li><span class="bad-dot">?</span> '
                        f'<span class="mono">{_esc(t.get("value"))}</span> '
                        '<span class="note">matches nothing in the store yet</span></li>'
                    )
            missing = tags.get("missing") or []
            foot = (
                f'<div class="notice">{len(missing)} tag(s) point at nothing in the '
                "store. That is allowed — a tag may name a record you have not "
                "created yet — but a typo looks exactly the same. Use Edit form "
                "to correct one.</div>"
                if missing
                else ""
            )
            tag_card = (
                '<div class="card"><h2 style="margin-top:0;font-size:1rem">'
                "Tag references</h2>"
                f'<ul class="files">{"".join(items)}</ul>{foot}</div>'
            )

    # What TCAP decided. The user picked concepts, not properties, so the
    # placement IS the result — showing only "1 file changed" would hide the
    # entire content of the workflow.
    annot_card = ""
    if annotation is not None:
        placed = "".join(
            f'<li><span class="ok-dot">&check;</span> '
            f'<span class="mono">{_esc(str(p_["property"]).rsplit("/", 1)[-1])}</span> '
            f'&larr; <span class="mono">{_esc(str(p_["concept"]).rsplit("/", 1)[-1])}</span></li>'
            for p_ in annotation.get("placed", [])
        )
        ties = "".join(
            f'<li><span class="bad-dot">?</span> '
            f'<span class="mono">{_esc(str(t.get("concept", "")).rsplit("/", 1)[-1])}</span> '
            "— equally specific candidates: "
            + ", ".join(f'<span class="mono">{_esc(str(x).rsplit("/", 1)[-1])}</span>'
                        for x in t.get("candidates", []))
            + "</li>"
            for t in annotation.get("ties", [])
        )
        unmatched = "".join(
            f'<li><span class="bad-dot">?</span> '
            f'<span class="mono">{_esc(str(u).rsplit("/", 1)[-1])}</span></li>'
            for u in annotation.get("unmatched", [])
        )
        # What UNTICKING meant. Annotate Work replaces rather than appends, so a
        # discard is the whole visible effect of removing a concept — invisible
        # in the file list, which just says "1 file changed".
        discarded = "".join(
            f'<li><span class="bad-dot">&minus;</span> '
            f'<span class="mono">{_esc(str(d["property"]).rsplit("/", 1)[-1])}</span> '
            f'&larr; <span class="mono">{_esc(str(d["concept"]).rsplit("/", 1)[-1])}</span></li>'
            for d in annotation.get("discarded", [])
        )
        parts = []
        if placed:
            parts.append(f'<div class="note">placed</div><ul class="files">{placed}</ul>')
        if discarded:
            parts.append(
                '<div class="note">discarded &mdash; these annotated the work '
                "before and were not in your selection</div>"
                f'<ul class="files">{discarded}</ul>'
            )
        if ties:
            parts.append(
                '<div class="notice">TCAP found two equally specific properties for '
                "these and refused to choose. That is a gap in the vocabulary, not "
                "in your selection — it is recorded in the hygiene ledger as an "
                f'open item.</div><ul class="files">{ties}</ul>'
            )
        if unmatched:
            parts.append(
                '<div class="notice">No typed property accepts these concepts, so '
                "nothing was written for them. Either they do not belong on this "
                "kind of work, or the ontology has no property for them yet."
                f'</div><ul class="files">{unmatched}</ul>'
            )
        if not parts:
            parts.append('<div class="notice">Nothing was placed.</div>')
        annot_card = (
            '<div class="card"><h2 style="margin-top:0;font-size:1rem">'
            f"What TCAP placed</h2>{''.join(parts)}</div>"
        )

    # A warning is not a gate failure: the change is promotable, the user is
    # simply being told something worth knowing before they approve it.
    warn = f'<div class="notice">{_esc(warning)}</div>' if warning else ""

    # Binaries the preview ADOPTED — present in the sandbox with no sidecar, so
    # invisible to promotion until one was minted. Building this page created
    # those files; saying so is the difference between a safety net and a
    # surprise.
    adopted = preview.get("adopted") or []
    if adopted:
        listed = "".join(f'<li class="mono">{_esc(p)}</li>' for p in adopted)
        warn += (
            f'<div class="notice">{len(adopted)} binary file(s) had no sidecar '
            "and were adopted while building this preview — they are part of the "
            "change below. A binary with no sidecar is invisible to promotion, so "
            "the record would have converged citing an image that never followed."
            f'<ul class="files">{listed}</ul></div>'
        )

    # The way BACK, and it belongs in every state.
    #
    # `Edit form` posts a promotion token and returns to the record form that
    # minted the draft. A workflow that did not come from a record form needs a
    # different door — annotation returns to its own page with the work and
    # concepts still selected — so the caller supplies one.
    #
    # And it was missing entirely when gates FAILED: that branch rendered the
    # gate list and nothing else, so a failed run was a dead end for every
    # workflow and the only way on was the dashboard and start again. A review
    # stop you cannot leave except by starting over is not a stop, it is a wall.
    # The note under the buttons explains whichever door is actually there.
    # It narrated `Edit form` unconditionally, which on a page reached from the
    # staged tree describes a button that is not on it and a draft nobody minted.
    back_note = (
        "<strong>Edit form</strong> takes you back with these values, and moves "
        "the draft files it minted (the record, its QR, any image it ingested) "
        "to the QA trash — so resubmitting replaces them rather than piling up."
    )
    # LEAVING WITHOUT SAVING, as a button rather than a consequence. A plain
    # POST so it works with scripting off; the header link asks first and then
    # presses this (see `_LEAVE_GUARD_SCRIPT`).
    discard_action = (
        '<form method="post" action="/episode/abandon" id="abandonForm" '
        f'{CONFIRM_ON_ABANDON} style="display:inline;margin-left:.5rem">'
        '<button type="submit">Discard changes</button></form>'
    )
    # THE THIRD ANSWER. Approve distributes, Discard destroys, and until now
    # there was no way to say "keep this and come back to it" — which is what a
    # batch of related records needs, since they are reviewed together and
    # approved once (Rick, 2026-09-27). Leaving by a link did it accidentally;
    # this does it on purpose, and lands on Drafts where the batch is managed.
    stage_action = (
        '<form method="post" action="/episode/stage" '
        'style="display:inline;margin-left:.5rem">'
        '<button type="submit">Leave it staged</button></form>'
    )
    token = _esc(preview.get("token", ""))
    if back:
        # `data-keep`: this link CONTINUES the session. The leave guard asks
        # before a link takes you off an unsaved change, and it was asking here
        # too — so "Back to annotation" put up "Discard it and leave?" and then,
        # on OK, discarded and landed on the Discarded page instead of the
        # annotation page (Rick, 2026-09-19). Going back to the form to make
        # further changes is the opposite of leaving.
        back_action = (
            f'<a class="button" data-keep="1" href="{_esc(back["href"])}">'
            f'&larr; {_esc(back.get("label", "Back"))}</a>'
        )
        back_note = ("Approving distributes everything staged, not only what "
                     "you came here to look at — the preview above is the whole "
                     "of it.")
    elif token:
        back_action = (
            f'<form method="post" action="/rdf/entry/edit" '
            'style="display:inline;margin-left:.5rem">'
            f'<input type="hidden" name="token" value="{token}">'
            "<button type=\"submit\">&larr; Edit form</button></form>"
        )
    else:
        back_action = ""

    if status == "previewed":
        body = f"""
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Change preview</h2>
  <div class="summary mono">{_esc(preview.get('preview', ''))}</div>
  <div class="note" style="margin-top:.6rem">manifest {_esc(preview.get('manifest', {}))}</div>
</div>
<div class="card"><h2 style="margin-top:0;font-size:1rem">Gates</h2>{gates}</div>
<div class="card">
  <form method="post" action="/rdf/entry/approve" style="display:inline">
    <input type="hidden" name="token" value="{token}">
    <button type="submit" class="primary">Approve &amp; distribute</button>
  </form>
  {back_action}
  {stage_action}
  {discard_action}
  <div class="note" style="margin-top:.6rem">Approving converges to the SOT and
  refreshes, and it is the SAVE: nothing here is kept until you press it.
  <strong>Leave it staged</strong> keeps the record as a draft without
  distributing it &mdash; make the rest, review them together on Drafts, and
  approve once.
  {back_note}
  <strong>Discard</strong> puts the record back to where this session started.
  To clear everything uncommitted instead:
  <a href="/wip/discard">discard work in progress</a>.</div>
</div>"""
    elif status == "empty":
        # Reachable from Preview Staged, where it is the ORDINARY answer rather
        # than an edge case: the usual state of a store is that everything in it
        # has been distributed. The other callers write a file before they get
        # here, so they never see it.
        body = f"""<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Nothing is staged</h2>
  <div class="note">The QA tree holds no changes the SOT does not already have,
  so there is nothing to distribute. Records you are part-way through appear
  here as soon as a form writes them.</div>
  {back_action}
</div>"""
    elif status == "gates_failed":
        body = f"""<div class="card"><h2 style="margin-top:0;font-size:1rem">Gates failed —
nothing was distributed</h2>{gates}
<div class="card" style="margin-top:1rem">{back_action}{stage_action}{discard_action}
  <div class="note" style="margin-top:.6rem">Nothing reached the SOT, and what
  was written is still in QA, unsaved. Go back to change it, or
  <strong>Discard</strong> to put the record back to where this session
  started.</div></div></div>"""
    else:
        # After convergence. The backup runs here, and a FAILED one has to be
        # visible: the content reached SOT, so nothing else reports a problem,
        # and a backup nobody notices missing is exactly the one that matters.
        b = preview.get("backup") if isinstance(preview, Mapping) else None
        backed = ""
        if b and b.get("ok"):
            backed = (
                '<div class="note">QA history backed up: '
                f'{b.get("commits", 0)} commit(s), '
                f'{b.get("bundle_bytes", 0) / 1e6:.2f} MB'
                + (f', plus {b.get("attic_files", 0)} attic file(s)'
                   if b.get("attic_files") else "")
                + ' &rarr; <span class="mono">operational/</span></div>'
            )
        elif b:
            backed = (
                '<div class="err">The change was distributed, but backing up the '
                f'QA history FAILED: {_esc(b.get("error", ""))}. Nothing is lost '
                "right now — the history is still on this disk — but rollback "
                "authority is unprotected until a backup succeeds. Try the "
                '<a href="/backup">QA Backup</a> page.</div>'
            )
        body = (f'<div class="card"><div class="summary mono">{_esc(preview)}</div>'
                f"{backed}</div>")

    leaving = _LEAVE_GUARD_SCRIPT if status in ("previewed", "gates_failed") else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Distribute — review</title>
<style>{_STYLE}</style></head><body>
<header><h1>Distribute Data — review</h1>
<span class="sub">nothing is saved until you approve</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{err}{warn}
{did_card}
{annot_card}
{tag_card}
{f'<div class="card"><h2 style="margin-top:0;font-size:1rem">Created in QA</h2><ul>{made}</ul></div>' if made else ''}
{src_card}
{body}
</main>{leaving}</body></html>"""


# Leaving the review asks, but leaving NEVER DESTROYS. The first version
# discarded on OK, which made "go to the dashboard and make the next record" —
# the batch workflow — the one gesture that threw a record away (Rick,
# 2026-09-27). Abandoning is explicit: it is the Discard button, and nothing
# else. The challenge here only makes sure a person knows the record is staged
# rather than distributed, since a change left staged is one the next promotion
# sweeps up (law 4).
# Asked wherever the button is, because discarding deletes files and cannot be
# undone. Rick, 2026-09-19: leaving asked and the button did not, which reads as
# the button being the safer of the two — the reverse of the truth. Inline
# rather than in a script block so it travels with the form to every page that
# renders one.
CONFIRM_ON_ABANDON = (
    "onsubmit=\"return confirm('Discard the changes in this session? "
    "The record goes back to where the session started.')\""
)


_LEAVE_GUARD_SCRIPT = """<script>
(function () {
  var form = document.getElementById('abandonForm');
  if (!form) { return; }
  var links = document.querySelectorAll('a[href]');
  for (var i = 0; i < links.length; i++) {
    links[i].addEventListener('click', function (ev) {
      if (this.getAttribute('href').charAt(0) === '#') { return; }
      if (this.dataset.keep) { return; }  // continues the session, does not leave it
      if (!window.confirm(
            'This is not distributed yet. It stays as a draft on the Drafts '
            + 'page — leave it and carry on?')) {
        ev.preventDefault();
      }
    });
  }
})();
</script>"""


def render_discarded_page(*, result) -> str:
    """What abandoning put back, said out loud.

    An undo that reports nothing is indistinguishable from an undo that did
    nothing, and this one deletes files.
    """
    ok = bool(result.get("abandoned"))
    lines = []
    for key, label in (("reverted", "put back to where the session started"),
                       ("removed", "deleted (this session created it)"),
                       ("restored", "restored from the attic"),
                       ("binaries_removed", "deleted (its sidecar went back)")):
        for p in result.get(key) or []:
            lines.append(f'<li class="mono">{_esc(p)} '
                         f'<span class="note">{label}</span></li>')
    body = (
        '<div class="card"><h2 style="margin-top:0;font-size:1rem">'
        + ("Discarded" if ok else "Nothing to discard")
        + "</h2>"
        + ('<div class="note">The sandbox is back to where this session started. '
           "Modified records were restored, anything the session created is gone, "
           "and nothing ever reached the SOT.</div>"
           if ok else
           f'<div class="note">{_esc(result.get("reason", ""))}</div>')
        + (f'<ul class="files">{"".join(lines)}</ul>' if lines else "")
        + '<a href="/">&larr; dashboard</a></div>'
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Discarded</title>
<style>{_STYLE}</style></head><body>
<header><h1>Discarded</h1>
<span class="sub">unsaved work, put back</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def render_refresh_page(*, drafts, wip, result=None, environment="") -> str:
    """Confirm before a refresh, because a refresh is a deletion.

    `/api/refresh` had no page at all — it was an API route with no hub card and
    no confirmation, which was tolerable while a refresh was rare. With a second
    instance and the legacy dashboard still publishing to the same SOT, it
    becomes routine (LegacyToNewDashboardProcedure.md), and it is the one action
    that silently destroys drafts.

    So it gets what Discard Work in Progress already has: see the change first,
    act second. The list is the draft index, which computes exactly what would
    be lost.
    """
    where = f" &mdash; {_esc(environment)}" if environment else ""
    if result is not None:
        rows = "".join(f'<li class="mono">{_esc(k)}: {_esc(str(v))}</li>'
                       for k, v in (result.get("drift") or {}).items())
        body = (
            '<div class="card"><h2 style="margin-top:0;font-size:1rem">Refreshed</h2>'
            '<div class="note">Work in progress was discarded, the SOT was pulled '
            "into QA, binaries were reconciled against their restored sidecars, "
            "and the pulled state was adopted as a new baseline &mdash; without "
            "that last step the next promotion would sweep all of it up.</div>"
            + (f'<ul class="files">{rows}</ul>' if rows else "")
            + '<div class="note">The ontology and thesaurus were reloaded too, so '
            "the forms and TCAP now offer what arrived.</div>"
            '<a href="/">&larr; dashboard</a></div>'
        )
        return _refresh_shell(body, where)

    listed = "".join(
        f'<li><strong>{_esc(d["label"])}</strong> '
        f'<span class="note">{_esc(", ".join(d.get("kinds") or []))}</span></li>'
        for d in drafts or []
    )
    counts = (wip or {}).get("counts") or {}
    danger = bool(drafts) or not (wip or {}).get("clean", True)
    warn = (
        '<div class="err">This will delete work that has not been distributed. '
        f"{len(drafts or [])} draft(s) and {sum(counts.values()) if counts else 0} "
        "uncommitted file(s) are here now.</div>"
        if danger else
        '<div class="notice">Nothing is staged, so nothing will be lost.</div>'
    )
    body = f"""{warn}
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Refresh from the SOT</h2>
  <div class="note">Pulls the SOT into this sandbox and makes it the baseline.
  Do this <strong>before</strong> starting work when the SOT may have changed
  underneath &mdash; the legacy dashboard publishes to it too. Drift is only
  detected when you press <strong>Approve &amp; distribute</strong>, and the
  cure for drift is this refresh, which would then take the work with it.</div>
  {f'<ul class="files">{listed}</ul>' if listed else ""}
</div>
<div class="card">
  <form method="post" action="/refresh" style="display:inline"
        onsubmit="return confirm('Discard everything not yet distributed and pull the SOT?')">
    <button type="submit" class="primary">Refresh</button>
  </form>
  <a href="/drafts" class="button">Drafts</a>
  <a href="/" style="margin-left:1rem">&larr; dashboard</a>
  <div class="note" style="margin-top:.6rem">To keep a draft, distribute it or
  read it at <strong>Drafts &rarr; Review</strong> first &mdash; that page shows
  the triples as written, which is what you would be re-entering.</div>
</div>"""
    return _refresh_shell(body, where)


def _refresh_shell(body: str, where: str = "") -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Refresh</title>
<style>{_STYLE}</style></head><body>
<header><h1>Refresh{where}</h1>
<span class="sub">pull the SOT into this sandbox and make it the baseline</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def render_drafts_page(*, drafts, orphans=(), result=None, back_for=None) -> str:
    """Everything written and not yet distributed, as records.

    The list a user can act on: what it is called, what kind of thing it is, how
    old it is, and the one link that reopens it in the editor that made it.
    Rick's flow, 2026-09-18: "after review of a number of drafts a user may say,
    discard them all. If they want to return to a draft a link can take them
    back to the editor with the right work displaying the draft."
    """
    done = ""
    if result:
        if result.get("discarded"):
            names = ", ".join(_esc(r) for r in result.get("records") or [])
            done = (f'<div class="notice">Discarded: {names}. '
                    f'{len(result.get("removed") or [])} file(s) deleted, '
                    f'{len(result.get("restored") or [])} put back to the '
                    "distributed version.</div>")
        else:
            done = f'<div class="notice">{_esc(result.get("reason", ""))}</div>'

    if not drafts:
        body = (done + '<div class="card"><div class="notice">No drafts. '
                "Everything written here has been distributed.</div>"
                '<a href="/">&larr; dashboard</a></div>')
        return _drafts_shell(body)

    rows = []
    for d in drafts:
        kinds = ", ".join(d.get("kinds") or [])
        when = _ago(d.get("mtime") or 0)
        extra = len(d.get("files") or []) - 1
        href = (back_for(d) if back_for else "")
        rows.append(
            '<li class="draft">'
            f'<label class="check"><input type="checkbox" name="guid" '
            f'value="{_esc(d["guid"])}"><span>'
            f'<strong>{_esc(d["label"])}</strong>'
            + (f' <span class="note">{_esc(kinds)}</span>' if kinds else "")
            + f' <span class="note">&middot; {"new" if d.get("new") else "edited"}'
            f' &middot; {_esc(when)}'
            + (f" &middot; +{extra} file(s)" if extra > 0 else "")
            + "</span></span></label>"
            + f'<a class="button" href="/drafts/view?guid={_esc(d["guid"])}">Review</a>'
            + (f'<a class="button" href="{_esc(href)}">Open</a>' if href else "")
            + "</li>"
        )

    body = f"""{done}
<form method="post" action="/drafts/discard">
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Drafts
    <span class="note">({len(drafts)})</span></h2>
  <div class="note">Written here, not distributed. A draft is real and usable —
  the form that made it will reopen it — and it is also what the next
  <strong>Approve &amp; distribute</strong> will carry along, whichever workflow
  presses it.</div>
  <ul class="files">{''.join(rows)}</ul>
</div>
<div class="card">
  <button type="submit">Discard selected</button>
  <button type="submit" name="all" value="1">Discard all</button>
  <a href="/" style="margin-left:1rem">&larr; dashboard</a>
  <div class="note" style="margin-top:.6rem">Discarding a draft puts the record
  back to its last distributed version, or removes it if it never had one,
  together with the files that belong to it. This is not the same as
  <strong>Discard changes</strong> on a review, which undoes only the session
  you are in.</div>
</div></form>"""
    if orphans:
        listed = "".join(f'<li class="mono">{_esc(p)}</li>' for p in orphans)
        body += ('<div class="card"><h2 style="margin-top:0;font-size:1rem">'
                 "Not attributable to a record</h2>"
                 '<div class="note">Uncommitted files that name no record. They '
                 "will ride along with the next distribution. Discard Work in "
                 "Progress clears everything uncommitted, these included.</div>"
                 f'<ul class="files">{listed}</ul>'
                 '<a href="/wip/discard">Discard work in progress &rarr;</a></div>')
    return _drafts_shell(body)


def render_draft_page(*, draft, back: str = "") -> str:
    """One draft: what it says, and what it changes.

    The list answers "what have I got"; this answers "what does it SAY", which
    is the question you have to answer before discarding something. The text is
    shown verbatim for the same reason the review stop shows Generated RDF —
    the file list says what was written and the counts say how much, but only
    the text says whether the triples are right.
    """
    if not draft:
        return _drafts_shell(
            '<div class="card"><div class="notice">No such draft. It may have '
            "been distributed or discarded since this link was made.</div>"
            '<a href="/drafts">&larr; drafts</a></div>'
        )

    kinds = ", ".join(draft.get("kinds") or [])
    err = (f'<div class="err">{_esc(draft["error"])}</div>'
           if draft.get("error") else "")

    if not draft.get("distributed"):
        change = (
            '<div class="card"><h2 style="margin-top:0;font-size:1rem">Change</h2>'
            f'<div class="note">New record &mdash; {draft.get("triples", 0)} '
            "triple(s), none of it distributed yet. There is no previous version "
            "to compare it with; the whole of it is the change.</div></div>"
        )
    else:
        added = "".join(f'<li class="mono add">+ {_esc(x)}</li>'
                        for x in draft.get("added") or [])
        removed = "".join(f'<li class="mono gone">&minus; {_esc(x)}</li>'
                          for x in draft.get("removed") or [])
        counts = (f'{len(draft.get("added") or [])} added, '
                  f'{len(draft.get("removed") or [])} removed')
        change = (
            '<div class="card"><h2 style="margin-top:0;font-size:1rem">'
            f'Change since it was last distributed <span class="note">'
            f"({_esc(counts)})</span></h2>"
            + ('<ul class="files">' + removed + added + "</ul>"
               if (added or removed) else
               '<div class="note">Nothing. The record differs from the '
               "distributed version only in how it is written &mdash; blank-node "
               "names or statement order &mdash; which is the same graph.</div>")
            + '<div class="note">Compared as GRAPHS, not as text: two writings '
            "of one graph differ in blank-node labels and statement order and "
            "are the same graph. A blank node is matched by WHERE IT SITS &mdash; "
            '<span class="mono">[field schema:video]</span> is that field '
            "wherever it moves to &mdash; so changing one leaves the rest of the "
            "record out of the comparison.</div></div>"
        )

    def _links(rows, empty: str) -> str:
        if not rows:
            return f'<div class="note">{empty}</div>'
        out = []
        for r in rows:
            pred = str(r["predicate"]).rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            name = r.get("label") or f'({r["guid"][:8]}… unnamed)'
            tag = ' <span class="note">draft</span>' if r.get("draft") else ""
            href = f'/drafts/view?guid={_esc(r["guid"])}' if r.get("draft") else ""
            shown = (f'<a href="{href}">{_esc(name)}</a>' if href else _esc(name))
            out.append(f'<li><span class="mono">{_esc(pred)}</span> &rarr; '
                       f"{shown}{tag}</li>")
        return f'<ul class="files">{"".join(out)}</ul>'

    connections = (
        '<div class="card"><h2 style="margin-top:0;font-size:1rem">Connections</h2>'
        '<div class="note">Points at</div>'
        + _links(draft.get("points_at"), "Nothing &mdash; this record stands alone.")
        + '<div class="note" style="margin-top:.6rem">Pointed at by, '
        "among the other drafts</div>"
        + _links(draft.get("pointed_by"), "Nothing else staged refers to it.")
        + '<div class="note" style="margin-top:.6rem">Only other DRAFTS are '
        "searched for what points here: finding every distributed record that "
        "does would mean reading the whole store to draw one page.</div></div>"
    )

    body = f"""{err}
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">{_esc(draft["label"])}</h2>
  <div class="note mono">{_esc(draft["path"])}</div>
  <div class="note">{_esc(kinds) or "untyped"} &middot;
  {"new" if draft.get("new") else "edited"} &middot; {_esc(_ago(draft.get("mtime") or 0))}
  &middot; {len(draft.get("files") or [])} file(s)</div>
</div>
{connections}
{change}
<div class="card"><h2 style="margin-top:0;font-size:1rem">As written</h2>
  <pre class="src">{_esc(draft.get("text", ""))}</pre></div>
<div class="card">
  <form method="post" action="/drafts/discard" style="display:inline">
    <input type="hidden" name="guid" value="{_esc(draft["guid"])}">
    <button type="submit">Discard this draft</button>
  </form>
  {f'<a class="button" href="{_esc(back)}">Open in the editor</a>' if back else ""}
  <a href="/drafts" style="margin-left:1rem">&larr; drafts</a>
  <div class="note" style="margin-top:.6rem">Discarding puts this record back to
  its last distributed version, or removes it if it never had one, together with
  the files that belong to it.</div>
</div>"""
    return _drafts_shell(body)


def _ago(when: float) -> str:
    """Age in the units a person would use. A draft's age is the whole reason
    the list is ordered the way it is."""
    import time

    if not when:
        return "unknown age"
    secs = max(0, time.time() - when)
    for size, name in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if secs >= size:
            n = int(secs // size)
            return f"{n} {name}{'s' if n != 1 else ''} ago"
    return "just now"


def _drafts_shell(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Drafts</title>
<style>{_STYLE}</style></head><body>
<header><h1>Drafts</h1>
<span class="sub">written here, not distributed</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def render_site_page(*, runs: list | None = None, sites: list | None = None,
                     error: str = "", work_base: str = "") -> str:
    """updateWorkOnSite: what each site declares, before anything is staged.

    A confirm-first page like the promotion review, for the same reason: this is
    the only workflow that reaches OUTSIDE the sandbox (law 11), and a run that
    silently rewrote the workOnSite snapshots would be a network effect the user
    never saw. `GET` shows what is configured; `POST` runs it and shows what came
    back; staging then goes through the ordinary review stop.
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    if runs is None:
        listed = "".join(f'<li class="mono">{_esc(s_)}</li>' for s_ in (sites or []))
        body = (
            '<div class="card"><h2 style="margin-top:0;font-size:1rem">Sites to read</h2>'
            + (f"<ul>{listed}</ul>" if listed
               else '<div class="note">No sites configured. Add them under '
                    '<span class="mono">sites</span> in the dashboard config.</div>')
            + '<div class="note">Each page is fetched read-only and read for '
              "the works it links to its catalogue — "
              f'<span class="mono">{_esc(work_base)}&lt;guid&gt;</span>. '
              "Nothing is guessed from titles or pictures, so a work the site "
              "does not link is a work the site does not claim.</div>"
            + ('<form method="post"><button type="submit">Read the sites</button></form>'
               if sites else "")
            + "</div>"
        )
        return _site_shell(err + body)

    cards = []
    for r in runs:
        rows = "".join(
            f'<li><span class="ok-dot">&check;</span> <strong>{_esc(d["label"])}</strong> '
            f'<span class="mono note">{_esc(d["guid"])}</span></li>'
            for d in r.get("declared", [])
        )
        unknown = "".join(
            f'<li><span class="bad-dot">?</span> <span class="mono">{_esc(u)}</span></li>'
            for u in r.get("unknown", [])
        )
        unknown_block = (
            '<div class="notice">The site names these works and the QA store does '
            "not have them. Not necessarily wrong — the store may not be synced, "
            "or the work may have been withdrawn — but nothing is asserted about "
            "them, because a triple about a subject nobody can resolve is a "
            f"dangling reference of our own making.</div><ul>{unknown}</ul>"
            if unknown else ""
        )
        broken = "".join(
            f'<li class="mono">{_esc(m)}</li>' for m in r.get("malformed", [])
        )
        broken_block = (
            '<div class="notice">These catalog links almost name a work — the '
            "right address with something stray in it — so they will not resolve "
            "for a visitor either. Nothing is asserted for them; fix the link on "
            f'the site.</div><ul class="files">{broken}</ul>'
            if broken else ""
        )
        pages = ", ".join(_esc(u) for u in r.get("pages", [])) or "— nothing fetched —"
        # A run that finds nothing and says nothing is indistinguishable from a
        # site that publishes nothing. The first real run was exactly that: two
        # empty snapshots, no reason given, and the reason turned out to be that
        # DNS does not work inside the sandbox.
        problems = "".join(
            f'<li class="mono">{_esc(e)}</li>' for e in r.get("errors", [])
        )
        problem_block = (
            '<div class="err">A page could not be read, so this site was not '
            "fully observed. What is listed below is incomplete, not wrong.</div>"
            f'<ul class="files">{problems}</ul>'
            if problems else ""
        )
        cards.append(
            '<div class="card">'
            f'<h2 style="margin-top:0;font-size:1rem">{_esc(r["site"])}</h2>'
            f'<div class="note">read: {pages}</div>{problem_block}'
            + (f'<ul class="files">{rows}</ul>'
               if rows else
               # Naming the base we looked for is the ONLY defence against a
               # misconfigured `domain` (CE_DESIGN §13.4a): the dashboard and
               # cwvaServer-py declare it separately and neither can check the
               # other, since they need not be on the same machine. A wrong
               # domain and an empty site look identical without this line.
               '<div class="notice">This site names no works. Looked for links '
               f'beginning <span class="mono">{_esc(work_base)}</span> — if that '
               "is not where your catalogue lives, check "
               '<span class="mono">domain</span> in the dashboard config. '
               "Otherwise check that the site links each work to its catalog "
               "entry.</div>" if work_base else
               '<div class="notice">This site names no works. If that '
               "is a surprise, check that its pages link to each work's "
               "catalog entry.</div>")
            + unknown_block
            + broken_block
            + f'<div class="note mono">staged: {_esc(r.get("ttl", ""))}</div>'
            "</div>"
        )
    tail = (
        '<div class="card"><div class="note">The snapshots above are staged in QA '
        "and nothing has reached the SOT. Distribute them from the dashboard when "
        'you are ready.</div><a href="/">&larr; dashboard</a></div>'
    )
    return _site_shell(err + "".join(cards) + tail)


def render_annotate_page(*, works: list | None = None, schemes: list | None = None,
                         selected_work: str = "", selected: set | None = None,
                         error: str = "", notice: str = "",
                         narrowed_by: list | None = None,
                         tags_not_schemes: list | None = None,
                         outside: list | None = None,
                         episode: dict | None = None) -> str:
    """Annotate Work (#6): pick a work, pick concepts, let TCAP place them.

    It EDITS an annotation, it does not only add one (Rick, 2026-09-18): the
    page opens with the work's current concepts ticked, and Annotate makes the
    selection the whole of the record's annotation. So the page must always be
    honest about which work it is showing — hence `loaded_for`, which the submit
    compares against, and the dropdown navigating on change rather than quietly
    carrying one work's ticks onto another.

    The user picks CONCEPTS, never properties. TCAP decides which typed property
    each concept belongs on by walking to the most specific one the ontology
    allows — that is the whole point of the workflow, and a form offering
    `vad:hasWatercolorTechnique` directly would be asking the user to do the
    navigation by hand and to be right about it.

    Every scheme is offered. The Groovy named six in its source while the store
    holds 17; the other eleven were invisible with nothing saying so.
    """
    selected = selected or set()
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    note = f'<div class="notice">{_esc(notice)}</div>' if notice else ""

    if not works:
        return _annotate_shell(
            err + '<div class="card"><div class="notice">No annotatable works in '
            "the QA store yet. A work becomes annotatable once its record is "
            "here — create one from a profile card, or sync. Only works are "
            "offered: records typed as a "
            '<span class="mono">vad:ArtForm</span> subclass, which is also why '
            "an unsynced ontology empties this list.</div>"
            '<a href="/">&larr; dashboard</a></div>'
        )

    # The same dropdown Edit Record uses, ordered by date with title a radio
    # away (Rick, 2026-09-18) — the work you want to annotate is nearly always
    # the one you just entered.
    work_picker = render_work_picker(works, selected=selected_work,
                                     nav="/annotate?work=")
    groups = []
    for sch in schemes or []:
        boxes = "".join(
            f'<label class="check" for="c__{_esc(c["value"])}">'
            f'<input type="checkbox" id="c__{_esc(c["value"])}" name="concepts" '
            f'value="{_esc(c["value"])}"'
            + (" checked" if c["value"] in selected else "")
            + f'><span>{_esc(c["label"])}</span></label>'
            for c in sch["concepts"]
        )
        # Collapsed by default — 17 schemes and 780 concepts open at once is a
        # page you scroll past rather than read. The filter box opens whatever
        # matches, so nothing is hidden from someone looking for it.
        #
        # EXCEPT a scheme holding something already ticked. Returning from the
        # review stop restores a selection, and a selection you cannot see is
        # worse than no selection: it reads as if the choice was lost.
        has_selection = any(c["value"] in selected for c in sch["concepts"])
        groups.append(
            f'<details class="scheme"{" open" if has_selection else ""}>'
            f'<summary>{_esc(sch["label"])} '
            f'<span class="note">({len(sch["concepts"])})</span>'
            + (' <span class="ok-dot">&check;</span>' if has_selection else "")
            + "</summary>"
            f'<div class="check-grid">{boxes}</div></details>'
        )

    # Which record narrowed the list, named. A shortened picker with no stated
    # cause is indistinguishable from a vocabulary that lost most of itself.
    narrowing = ""
    if narrowed_by:
        who = ", ".join(f'<strong>{_esc(x["label"])}</strong>' for x in narrowed_by)
        narrowing = (
            f'<div class="notice">Showing the schemes named by {who} — an '
            "Operation record topic-tagged Thesaurus + Annotation. Edit that "
            "record to widen or narrow this list; delete it and every scheme "
            "returns.</div>"
        )
    # On the record, outside the schemes this picker shows. There is no box for
    # it, so it can be neither ticked nor removed — and a concept the page does
    # not show is exactly the thing a user goes hunting for later, after an
    # annotation they never made disappears.
    if outside:
        listed = ", ".join(f'<span class="mono">{_esc(x)}</span>' for x in outside)
        narrowing += (
            f'<div class="notice">This work also carries {listed}, outside the '
            "schemes above. Not shown, not changed: annotating here replaces "
            "only what this picker offers.</div>"
        )
    if tags_not_schemes:
        listed = ", ".join(f'<span class="mono">{_esc(t)}</span>' for t in tags_not_schemes)
        narrowing += (
            f'<div class="notice">Ignored {listed}: tagged on that record but not '
            "a <span class=\"mono\">skos:ConceptScheme</span>. "
            "<span class=\"mono\">the:tag</span> is general-purpose, so a record "
            "may carry tags meaning other things.</div>"
        )

    body = f"""{err}{note}{render_session_bar(episode)}
<form method="post" id="annotateForm"
      data-guard="Your concept selection has changed and has not been applied. Leave without annotating?">
<input type="hidden" name="loaded_for" value="{_esc(selected_work)}">
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Work</h2>
  {work_picker}
  <div class="note">Ticked below is what this work says now. Annotate makes your
  selection the whole of it — anything you untick is removed from the record.</div>
</div>
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Concepts</h2>
  <div class="note">Pick what the work IS about. The property each concept
  lands on is chosen for you — TCAP walks to the most specific one the
  ontology allows, and records a tie rather than guessing between equals.</div>
  {narrowing}
  <input type="search" id="conceptFilter" placeholder="filter concepts…"
         autocomplete="off">
  {''.join(groups)}
</div>
<div class="card"><button type="submit">Annotate</button>
  <a href="/" style="margin-left:1rem">&larr; dashboard</a></div>
</form>"""
    return _annotate_shell(body + _CONCEPT_FILTER_SCRIPT + _WORK_ORDER_SCRIPT
                           + _DIRTY_GUARD_SCRIPT)


# Filter across every scheme at once, hiding empty groups. No escape sequences,
# for the reason recorded on _LEAVE_GUARD: a literal newline inside a JS string
# once killed an entire IIFE silently.
_CONCEPT_FILTER_SCRIPT = """<script>
(function () {
  var box = document.getElementById('conceptFilter');
  if (!box) { return; }
  box.addEventListener('input', function () {
    var q = box.value.toLowerCase();
    var groups = document.querySelectorAll('details.scheme');
    for (var i = 0; i < groups.length; i++) {
      var labels = groups[i].querySelectorAll('label.check');
      var shown = 0;
      for (var j = 0; j < labels.length; j++) {
        var text = labels[j].textContent.toLowerCase();
        var hit = !q || text.indexOf(q) !== -1;
        labels[j].style.display = hit ? '' : 'none';
        if (hit) { shown++; }
      }
      groups[i].style.display = shown ? '' : 'none';
      if (q) { groups[i].open = true; }
    }
  });
})();
</script>"""


def rev_date(text: str) -> str:
    """A sort key that puts the NEWEST ISO date first, without parsing one.

    Public because it is the ONE date-ordering rule: the Edit Record picker,
    Annotate Work and the DTS generate card all sort works newest-first, and a
    second implementation would be a second answer to "which work did I just
    enter".

    Dates arrive as the user typed them — `2026-09-12`, sometimes a bare year —
    and a record is not worth refusing from a picker because its date is odd.
    Complementing each digit reverses the ordering of anything that compares
    lexicographically, which ISO dates do, and leaves everything else in a
    stable order rather than throwing.
    """
    return "".join(chr(ord("9") - (ord(c) - ord("0"))) if c.isdigit() else c
                   for c in text)


def render_record_chooser(records, *, nav: str, label: str, selected: str = "",
                          select_id: str = "recordPick", readonly=()) -> str:
    """A "which one are you editing" dropdown, by label, that navigates on change.

    Not `render_work_picker`: that one orders by `schema:datePublished` with a
    radio to switch to title, and an artist has no publication date. An order
    control that does nothing is a control that teaches you to ignore controls.

    ``readonly`` rows are facts of the record the editor may NOT change. They
    are shown here rather than left off the page: a field that vanishes reads as
    a field the system forgot, and the reason it cannot be edited is the part
    worth saying.
    """
    opts = "".join(
        f'<option value="{_esc(r["value"])}"'
        + (" selected" if r["value"] == selected else "")
        + f'>{_esc(r["label"])}</option>'
        for r in sorted(records or [], key=lambda r: str(r["label"]).lower())
    )
    fixed = "".join(
        f'<div class="field wide"><label>{_esc(name)}</label>'
        f'<div class="ro">{_esc(value)}</div>'
        f'<div class="note">{note}</div></div>'
        for name, value, note in readonly
    )
    return (
        f'<div class="card"><h2 style="margin-top:0;font-size:1rem">{_esc(label)}</h2>'
        f'<div class="pick-row"><select id="{_esc(select_id)}" data-order="d" '
        f'data-nav="{_esc(nav)}">{opts}</select></div>'
        '<div class="note">Choosing one opens it here. Unsaved changes to the '
        f"one you are on are challenged first.</div>{fixed}</div>"
    )


def render_work_picker(records, *, name: str = "work", selected: str = "",
                      select_id: str = "work", nav: str = "") -> str:
    """THE work dropdown — one widget, used by Edit Record and Annotate Work.

    Rick, 2026-09-18: "99% of the time you want to annotate or edit a work just
    entered." So the default order is **date, newest first**, with alphabetical
    a radio away. The filter box that used to sit above the edit list is gone:
    filtering answers "where is the one I am thinking of", and the answer is
    almost always "at the top".

    DATE is `schema:datePublished` — "it's important to use a date known to the
    user" (Rick, 2026-09-18). The first cut sorted on the record file's mtime,
    which is when the SANDBOX last wrote it: invisible from the record, and
    rewritten wholesale by a SOT→QA sync, so the order could not be checked
    against anything on screen. It is shown beside each label for the same
    reason — an order you cannot see is one you have to trust.

    A record with no publication date sorts last, alphabetically among its
    kind. That is a record that has not been published, which is exactly what
    "no date" says.

    Both orders are rendered into the option list, and the radio reorders it in
    the browser. No round trip — on the annotate page a round trip would lose a
    concept selection that is not yet submitted — and no state to keep.
    """
    recs = list(records or [])
    # Descending by date, undated last: sort on (has-no-date, reversed-date).
    by_date = sorted(recs, key=lambda r: (not r.get("published"),
                                          rev_date(str(r.get("published") or "")),
                                          str(r.get("label", "")).lower()))
    date_rank = {id(r): i for i, r in enumerate(by_date)}
    title_rank = {
        id(r): i for i, r in enumerate(
            sorted(recs, key=lambda r: (str(r.get("label", "")).lower(),
                                        str(r.get("value", ""))))
        )
    }
    opts = []
    for r in by_date:
        # The DATE and nothing else. The types were shown too, and they read as
        # if the store were inconsistent (Rick, 2026-09-18: "it looks confusing
        # like some types got RDFS inference and others did not") — which is
        # exactly what they are: ten records carry materialized types written
        # into them by an earlier tool, so the same kind of work listed one type
        # or nine. True, and nothing to do with choosing a record.
        note = str(r.get("published") or "")
        opts.append(
            f'<option value="{_esc(r["value"])}" '
            f'data-d="{date_rank[id(r)]}" data-t="{title_rank[id(r)]}"'
            + (" selected" if r["value"] == selected else "")
            + f'>{_esc(r["label"])}'
            + (f" &mdash; {_esc(note)}" if note else "")
            + "</option>"
        )
    select = (
        f'<select id="{_esc(select_id)}" name="{_esc(name)}" data-order="d"'
        # Where choosing GOES, for a picker that is not in a form of its own.
        # Annotate Work reloads on the chosen work, because the ticks below
        # belong to a work and carrying them across would annotate the wrong
        # one with the right-looking selection.
        + (f' data-nav="{_esc(nav)}"' if nav else "")
        + f">{''.join(opts)}</select>"
    )
    return ORDER_RADIOS + select


# The radios are separable from the select because Edit Record puts the select
# in a GET form of its own and the radios outside it — a UI preference has no
# business in the URL of a record.
ORDER_RADIOS = (
    '<div class="order">order '
    '<label class="radio"><input type="radio" name="workOrder" value="d" '
    "checked> date</label> "
    '<label class="radio"><input type="radio" name="workOrder" value="t"> '
    "title</label></div>"
)


_WORK_ORDER_SCRIPT = """<script>
(function () {
  var sel = document.querySelector('select[data-order]');
  if (!sel) { return; }
  var radios = document.querySelectorAll('input[name="workOrder"]');
  for (var i = 0; i < radios.length; i++) {
    radios[i].addEventListener('change', function () {
      var key = this.value === 't' ? 't' : 'd';
      var opts = Array.prototype.slice.call(sel.options);
      opts.sort(function (a, b) {
        return (+a.dataset[key]) - (+b.dataset[key]);
      });
      for (var j = 0; j < opts.length; j++) { sel.appendChild(opts[j]); }
      sel.dataset.order = key;
    });
  }
  if (sel.dataset.nav) {
    sel.dataset.open = sel.value;
    sel.addEventListener('change', function () {
      if (window.__editGuard && !window.__editGuard()) {
        sel.value = sel.dataset.open;  // nothing was opened; say so on screen
        return;
      }
      window.location = sel.dataset.nav + encodeURIComponent(sel.value);
    });
  }
  // Choosing a record OPENS it, which is a navigation away from whatever is in
  // the form below — so the form gets asked first. `__editGuard` is installed
  // only when a record is open with edits to lose; absent, this just navigates.
  var pick = document.getElementById('pickForm');
  if (!pick) { return; }
  sel.dataset.open = sel.value;
  sel.addEventListener('change', function () {
    if (window.__editGuard && !window.__editGuard()) {
      sel.value = sel.dataset.open;  // nothing was opened; say so on screen
      return;
    }
    pick.submit();
  });
  pick.addEventListener('submit', function (ev) {
    if (window.__editGuard && !window.__editGuard()) { ev.preventDefault(); }
  });
})();
</script>"""


# Unsaved edits are lost silently otherwise (Rick, 2026-09-18): the record
# picker sits on the form, so changing your mind about which record you are
# editing is one click from changing your mind about the edits you just typed.
# The same click that made the picker convenient made it dangerous.
#
# DIRTY IS COMPARED, not flagged on first keystroke: typing into a field and
# putting it back is not an edit, and a challenge for it teaches you to dismiss
# challenges. `beforeunload` is the backstop for what the page cannot intercept
# — the tab closing, the browser's back button — and browsers show their own
# wording there, which is why the in-page paths ask in ours.
_DIRTY_GUARD_SCRIPT = """<script>
(function () {
  var form = document.querySelector('form[data-guard]');
  if (!form) { return; }
  function snapshot() {
    var out = [], els = form.elements;
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      // The record picker and its order radios are NAVIGATION, not values being
      // edited. Counting them as edits would challenge you for changing the
      // sort order, and would call every work change dirty on a page where the
      // picker sits inside the form.
      if (!el.name || el.name === 'workOrder' || el.dataset.order) { continue; }
      out.push(el.name + '=' + ((el.type === 'checkbox' || el.type === 'radio')
        ? (el.checked ? '1' : '0') : el.value));
    }
    return out.join('\\n');
  }
  var clean = snapshot(), leaving = false;
  function dirty() { return !leaving && snapshot() !== clean; }
  function ask() {
    if (!dirty()) { return true; }
    if (window.confirm(form.dataset.guard)) {
      leaving = true;
      return true;
    }
    return false;
  }
  window.__editGuard = ask;
  form.addEventListener('submit', function () { leaving = true; });
  var links = document.querySelectorAll('a[href]');
  for (var j = 0; j < links.length; j++) {
    links[j].addEventListener('click', function (ev) {
      if (!ask()) { ev.preventDefault(); }
    });
  }
  window.addEventListener('beforeunload', function (ev) {
    if (!dirty()) { return; }
    ev.preventDefault();
    ev.returnValue = '';
  });
})();
</script>"""


#: The two groups the record picker offers, in the order they are shown.
#: Spelled the same as `edit_tools.WORKS` / `ENTITIES`, which is what the route
#: passes and the tool's enum enforces — the offered set IS the enforced set.
_EDIT_GROUPS = (("work", "Works"), ("entity", "Entities"))


def _edit_group_tabs(kind: str) -> str:
    """Works | Entities — two lists, named, never merged.

    The editor was works-only, and an entity could be reached only by typing
    `/edit/open?path=…` (Rick did, to repoint the Pillars background image at a
    4k JPEG, 2026-09-27). The editor itself always handled them: it is
    file-based, renders everything in the file and preserves verbatim what it
    cannot render — which is what an entity needs, since `skos:inScheme`,
    `the:conceptsExtracted` and a `skos:note` are no entry form's fields.

    A SECOND GROUP, not a loosened filter. Artists and artist profiles still do
    not appear, because they have editors that know what a persona owns and
    what may not change about it (CE_DESIGN §14.10) — and a picker that offers
    an artist to a form built for works is the thing the original rule
    prevented.

    Links rather than a control inside the form: the edit form below is a POST
    and forms cannot nest, and the dirty guard already challenges an outbound
    link, so switching group with unsaved edits asks first.
    """
    out = []
    for value, label in _EDIT_GROUPS:
        here = value == kind
        out.append(
            f'<a class="tab{" on" if here else ""}" href="/edit?kind={value}"'
            + (' aria-current="page"' if here else "")
            + f">{_esc(label)}</a>"
        )
    return f'<div class="tabs">{"".join(out)}</div>'


def _edit_picker_card(records, selected: str = "", kind: str = "work") -> str:
    """The record chooser, at the TOP OF THE FORM (Rick, 2026-09-18).

    It used to be a page of its own that you left behind on the way in, so
    changing your mind about which record you were editing meant going back to
    a list. Now the dropdown stays above the fields: picking from it navigates
    to that record, and the form below is simply what is currently chosen.

    Its own `<form>`, and the radio buttons sit OUTSIDE it — the edit form below
    is a POST and forms cannot nest, and an order radio submitted as a query
    parameter would put a UI preference in the URL of the record.

    The group rides along as a hidden field, so opening a record from the
    entities list comes back to the entities list.
    """
    select = render_work_picker(
        records, name="path", selected=selected, select_id="recordPick",
    ).replace(ORDER_RADIOS, "", 1)
    which = "entities" if kind == "entity" else "works"
    return (
        '<div class="card"><h2 style="margin-top:0;font-size:1rem">'
        f'Record <span class="note">({len(records)} {which})</span></h2>'
        f"{_edit_group_tabs(kind)}"
        f"{ORDER_RADIOS}"
        '<form method="get" action="/edit/open" class="pick-row" id="pickForm">'
        f'<input type="hidden" name="kind" value="{_esc(kind)}">'
        f'{select}<button type="submit">Open</button></form>'
        '<div class="note">Works are records typed as an art form; entities are '
        "the background images, criticism and documents in the entities scheme. "
        "Artists and artist profiles have editors of their own. System files — "
        "the workOnSite snapshots, the concept queue, the thesaurus aggregates "
        "— are not listed: they describe many records at once, so there is no "
        "single instance to edit.</div></div>"
    )


def render_edit_picker(*, records: list | None = None, error: str = "",
                       kind: str = "work") -> str:
    """The edit page with nothing chosen yet.

    Only single-subject files are offered — aggregates and system output
    (`workonsite_*.ttl`, `conceptQueue.ttl`) describe many things at once and
    editing one field of them makes no sense.
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    if not records:
        # The empty list says which GROUP is empty and why it might be, because
        # "nothing here" has two very different causes: a group with no records
        # yet, and a works list emptied by an ontology that has not synced —
        # without it nothing can be classified as an art form at all.
        why = (
            "This list offers entities — records in the "
            '<span class="mono">the:entities</span> scheme, which is what '
            "background images, criticism and documents carry."
            if kind == "entity" else
            "This list offers works — records typed as a "
            '<span class="mono">vad:ArtForm</span> subclass — so an empty list '
            "can also mean the ontology has not synced, since without it "
            "nothing can be classified."
        )
        return _edit_shell(
            err + '<div class="card">' + _edit_group_tabs(kind)
            + f'<div class="notice">No {"entity" if kind == "entity" else "work"} '
            f"records in the QA store. {why} Artists and artist profiles are not "
            "listed here; they have editors of their own.</div>"
            '<a href="/">&larr; dashboard</a></div>')
    return _edit_shell(
        err + _edit_picker_card(records, kind=kind)
        + '<div class="card"><div class="notice">Pick a record above to edit it.'
        '</div><a href="/">&larr; dashboard</a></div>' + _WORK_ORDER_SCRIPT
    )


def render_edit_form(*, instance: Mapping[str, Any], error: str = "",
                     notice: str = "", signatures: list | None = None,
                     records: list | None = None, episode: dict | None = None,
                     kind: str = "work") -> str:
    """One field per predicate, typed by what the data actually holds.

    The editor shows EVERYTHING in the file, which is what makes overwriting it
    safe: a form with a fixed field list would silently drop whatever it did not
    know about, and on a real watercolour that is most of the record.
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    note = f'<div class="notice">{_esc(notice)}</div>' if notice else ""
    picker = (_edit_picker_card(records, selected=str(instance.get("path") or ""),
                                kind=kind)
              if records else "")
    if not instance.get("editable"):
        return _edit_shell(
            f'{err}{picker}<div class="card"><div class="notice">'
            f'{_esc(instance.get("reason", "Not editable."))}</div>'
            f'<a href="/edit?kind={_esc(kind)}">&larr; pick another record</a>'
            "</div>"
            + (_WORK_ORDER_SCRIPT if picker else "")
        )

    brand_row = _brand_control(signatures) if any(
        f.get("kind") == "file" and f.get("file_kind") == "image"
        for f in instance["fields"]
    ) else ""

    rows = []
    for f in instance["fields"]:
        warn = (f'<div class="notice">{_esc(f["warning"])}</div>'
                if f.get("warning") else "")
        hint = f'<div class="hint">{_esc(f["curie"])}'
        if f.get("multiple"):
            hint += " &middot; several values, comma separated"
        hint += "</div>"
        if f["mode"] == "read_only":
            # An annotation reads as prose, not as a handle: it is a list of
            # concept NAMES, and the way to change it is one link away rather
            # than a sentence telling you to go and find it.
            cls = "ro" if f.get("kind") == "annotation" else "ro mono"
            to_annotate = (
                f' <a href="/annotate?work={_esc(instance.get("subject", ""))}">'
                "Annotate Work &rarr;</a>"
                if f.get("kind") == "annotation" else ""
            )
            widget = (
                f'<div class="{cls}">{_esc(f["value"])}</div>'
                f'<div class="note">Read-only. {_esc(f.get("reason", ""))}'
                f"{to_annotate}</div>"
            )
        else:
            widget = _edit_widget(f)
        rows.append(
            f'<div class="field wide"><label for="{_esc(f["predicate"])}">'
            f'{_esc(f["label"])}</label>{widget}{hint}{warn}</div>'
        )
        # Directly under the image picker: this is the field whose change makes
        # the question live, and at the foot of the form it was missed.
        if brand_row and f.get("kind") == "file" and f.get("file_kind") == "image":
            rows.append(brand_row)
            brand_row = ""

    return _edit_shell(f"""{err}{note}{render_session_bar(episode)}{picker}
<form method="post" action="/edit/save" id="editForm"
      data-guard="This record has unsaved edits. Leave without saving them?">
<input type="hidden" name="path" value="{_esc(instance['path'])}">
<input type="hidden" name="kind" value="{_esc(kind)}">
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">{_esc(instance['subject'])}</h2>
  <div class="note mono">{_esc(instance['path'])}</div>
</div>
<div class="card">{''.join(rows)}</div>
<div class="card"><button type="submit" class="primary">Save</button>
  <a href="/" style="margin-left:1rem">&larr; dashboard</a>
  <div class="note" style="margin-top:.6rem">Saving rewrites this file and stops
  at the usual review, so nothing reaches the SOT until you approve. An empty
  field removes the statement. Clearing an image reference does NOT delete the
  image — it leaves it unreferenced.</div>
</div></form>""" + (_WORK_ORDER_SCRIPT if picker else "")
                       + _REFRESH_SCRIPT + _DIRTY_GUARD_SCRIPT)


def _file_slot(slot: Mapping[str, Any], field: Mapping[str, Any],
               *, single: bool) -> str:
    """One drop-folder picker for one file the record cites.

    The CURRENT value is always the first option, whatever it is — otherwise
    opening a record and saving would silently change or clear it — and it is
    what `data-unchanged` tells the refresh script to put back, since a refresh
    that replaced it with "- choose -" would turn an accidental save into a
    cleared reference.
    """
    name = _esc(slot["name"])
    val = _esc(slot["value"])
    # An empty slot is a document the record does not cite yet: nothing to leave
    # "unchanged", and the same words the Refresh list script puts there.
    first = f"{val} &mdash; unchanged" if val else "- choose -"
    opts = [f'<option value="{val}" selected>{first}</option>']
    for c in field.get("candidates") or []:
        if c["value"] == slot["value"]:
            continue
        opts.append(f'<option value="{_esc(c["value"])}">{_esc(c["label"])}</option>')
    row = (f'<select id="{name}" name="{name}" data-unchanged="{val}">'
           f'{"".join(opts)}</select>')
    # The in-place Refresh list, which the edit form did not have: the remedy
    # for "nothing in your drop folder" is to put a file there, and without this
    # the only way to see it was to reload and lose everything typed (Rick,
    # 2026-09-27 — the same finding, on the other form).
    row += _refresh_row(slot["name"], field.get("subtree", ""),
                        field.get("file_kind", "image"))
    return row if single else f'<div class="slot">{row}</div>'


def _edit_widget(f: Mapping[str, Any]) -> str:
    name = _esc(f["predicate"])
    val = _esc(f["value"])
    kind = f.get("kind")
    if kind == "file":
        # ONE SELECT PER FILE. A field holding two images used to render as one
        # select whose only option was both names joined, so choosing a
        # replacement swapped BOTH for one, silently.
        slots = f.get("items") or [{"name": f["predicate"], "value": f["value"]}]
        picked = "".join(
            _file_slot(slot, f, single=len(slots) == 1) for slot in slots
        )
        tail = (
            '<div class="note">Only files from your drop folder are offered: '
            "anything already in the store belongs to some record, and pointing "
            "two records at one file passes every gate. Saving copies the chosen "
            "file in.</div>"
            if f.get("candidates") else
            '<div class="note">Nothing in your drop folder for this kind of file. '
            "Put one there and use Refresh list &mdash; reloading the page would "
            "lose everything you have typed.</div>"
        )
        # THE PARTS OF A COMPOSITE THE USER OWNS — the video description, which
        # was preserved across a file swap and had nowhere to be typed.
        parts = "".join(
            f'<div class="field wide" style="margin-top:.6rem">'
            f'<label for="{_esc(part["name"])}">{_esc(part["label"])}</label>'
            f'<textarea id="{_esc(part["name"])}" name="{_esc(part["name"])}" '
            f'rows="3">{_esc(part["value"])}</textarea>'
            + (f'<div class="note">{_esc(part["note"])}</div>' if part.get("note") else "")
            + "</div>"
            for part in f.get("parts") or []
        )
        return picked + tail + parts

    if kind == "reference":
        # A closed set from the store, shown by LABEL. The current value is
        # always offered — the same rule as a file field, for the same reason:
        # opening a record and saving must not change what it points at, even
        # when the thing it points at no longer satisfies the conditions.
        opts = [
            f'<option value="{val}" selected>'
            f'{_esc(f.get("display") or f["value"]) or "&mdash;"} &mdash; unchanged'
            "</option>"
        ]
        for c in f.get("candidates") or []:
            if c["value"] == f["value"]:
                continue
            opts.append(f'<option value="{_esc(c["value"])}">{_esc(c["label"])}</option>')
        tail = (
            '<div class="note">Backgrounds are records in the store, and this is '
            "all of them. Typing an IRI here would be a reference to nothing that "
            "the gate has to catch.</div>"
            if len(opts) > 1 else
            '<div class="note">No other background records in the store.</div>'
        )
        return f'<select id="{name}" name="{name}">{"".join(opts)}</select>{tail}'

    if kind == "textarea":
        return f'<textarea id="{name}" name="{name}" rows="4">{val}</textarea>'
    if kind == "boolean":
        opts = "".join(
            f'<option value="{v}"{" selected" if v == f["value"] else ""}>{v}</option>'
            for v in ("true", "false")
        )
        return f'<select id="{name}" name="{name}">{opts}</select>'
    # date/number/iri/text all take a text input: the value is edited as the
    # TTL means it, without the quoting or the ^^xs:float.
    itype = "date" if kind == "date" and not f.get("multiple") else "text"
    return f'<input type="{itype}" id="{name}" name="{name}" value="{val}">'


def render_backup_page(*, attic: Mapping[str, Any], commits: int = 0,
                       last: Mapping[str, Any] | None = None,
                       result: Mapping[str, Any] | None = None,
                       error: str = "") -> str:
    """QA backup: what SOT cannot give back, and a button to send it there.

    The attic count is the signal worth watching. While it is zero the only
    unbacked thing is the commit history; the moment it is not, there are bytes
    here that exist in no bucket and no production store — the rollback reserve
    for a replaced image.
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    files, mb = attic.get("files", 0), attic.get("bytes", 0) / 1e6
    tone = "ok-dot" if files == 0 else "bad-dot"
    done = ""
    if result:
        if result.get("ok"):
            done = (
                '<div class="notice">Backed up '
                f'{result.get("commits", 0)} commit(s), '
                f'{result.get("bundle_bytes", 0) / 1e6:.2f} MB'
                + (f' plus {result.get("attic_files", 0)} attic file(s)'
                   if result.get("attic_files") else "")
                + ' &rarr; <span class="mono">'
                + ", ".join(_esc(w) for w in result.get("written", []))
                + "</span></div>"
            )
        else:
            done = f'<div class="err">{_esc(result.get("error", "backup failed"))}</div>'

    when = (f'<div class="note">Last backup in SOT: <span class="mono">'
            f'{_esc(last.get("updated", ""))}</span>, '
            f'{last.get("bytes", 0) / 1e6:.2f} MB</div>'
            if last else
            '<div class="notice">No backup found in SOT. The commit history '
            "exists on this disk only.</div>")

    return _backup_shell(f"""{err}{done}
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">What SOT cannot give back</h2>
  <ul class="files">
    <li><span class="ok-dot">&check;</span> content and <span class="mono">.ptr</span>
        sidecars &mdash; <span class="note">recoverable: SOT holds the content and
        sidecars regenerate from the binaries</span></li>
    <li><span class="bad-dot">!</span> <strong>{commits} commit(s)</strong> of QA
        history &mdash; <span class="note">law 6 makes rollback depend on this;
        it exists here only</span></li>
    <li><span class="{tone}">{'&check;' if files == 0 else '!'}</span>
        <strong>{files} file(s) in the attic</strong> ({mb:.1f} MB) &mdash;
        <span class="note">superseded binaries; SOT holds the replacement, so
        these bytes exist nowhere else</span></li>
  </ul>
  {when}
  <form method="post"><button type="submit" class="primary">Back up now</button></form>
  <div class="note" style="margin-top:.6rem">Writes a git bundle (and the attic,
  if any) to the target's <span class="mono">operational/</span> prefix. That is
  not content: it never syncs back, and it is not a promotion.</div>
  <a href="/">&larr; dashboard</a>
</div>""")


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name).strip("-").lower()


def render_instances_page(*, targets: list | None = None, error: str = "",
                          refreshes: Mapping[str, Any] | None = None,
                          chrome: tuple | None = None) -> str:
    """Instance Control: Status / Refresh / Metrics across the configured
    servers, each card reporting for itself.

    The cards are rendered empty and filled by fetch, one request per server
    fired at the same moment. That is what "in parallel, displayed
    individually" buys: a refresh reloads a server's entire RDF store, so
    serially the third server's answer waits on the first two, and a slow or
    unreachable server would hold up results that are already known.

    No Stop, and no Charts. Neither is unimplemented-but-linked: there is no
    route and no client code for either.
    """
    err = f'<div class="err">{_esc(error)}</div>' if error else ""
    if not targets:
        return _instances_shell(
            err + '<div class="card"><div class="notice">No instances configured. '
            'Add them under <span class="mono">instances.targets</span> in the '
            "dashboard config.</div>"
            '<a href="/">&larr; dashboard</a></div>', chrome
        )

    cards = []
    for t in targets:
        n = _esc(t.name)
        slug = _slug(t.name)
        # A symbolic host (the Windows box seen from inside WSL) is shown
        # resolved as well as configured: "wsl-host" alone reads like a typo,
        # and when a call fails the first question is which address it dialled.
        try:
            dialled = instances.resolve_base(t.base)
        except instances.InstanceError as exc:
            dialled = f"unresolved: {exc}"
        shown = _esc(t.base) if dialled == t.base else (
            f"{_esc(t.base)} <span style=\"opacity:.6\">&rarr; {_esc(dialled)}</span>")
        last = (refreshes or {}).get(t.name) or {}
        cards.append(f"""
<div class="card instance" id="srv-{slug}" data-name="{n}">
  <div class="instance-head">
    <strong>{n}</strong> <span class="note">{_esc(t.tag)}{
        "" if getattr(t, "api", "py") == "py" else " &middot; " + _esc(t.api)}</span>
    <span class="mono note" style="margin-left:auto">{shown}</span>
  </div>
  <div class="instance-actions">
    <button type="button" id="{slug}-status" onclick="runOne('{n}','status')">Status</button>
    <button type="button" id="{slug}-refresh" onclick="runOne('{n}','refresh')">Refresh</button>
    <button type="button" id="{slug}-metrics" onclick="runOne('{n}','metrics')">Metrics</button>
  </div>
  <div class="instance-refreshed note" style="margin-top:.5rem"
       data-at="{_esc(last.get('at', ''))}"
       data-confirmed="{'true' if last.get('confirmed') else 'false'}">Last refresh: {
        _esc(last.get('at', '')) or 'none recorded'}</div>
  <div class="instance-result note">idle</div>
</div>""")

    return _instances_shell(f"""{err}
<div class="card">
  <div class="instance-actions">
    <strong style="margin-right:.6rem">All servers:</strong>
    <button type="button" onclick="runAll('status')">Status</button>
    <button type="button" onclick="runAll('refresh')">Refresh</button>
    <button type="button" onclick="runAll('metrics')">Metrics</button>
  </div>
  <div class="note" style="margin-top:.6rem">Every server is called at the same
  moment and each card answers for itself, so one slow or unreachable server
  does not hold up the rest. <strong>Refresh</strong> reloads a server's RDF
  stores from disk or GCP and can take a while on a large store. <strong>Last
  refresh</strong> is the last one fired from a dashboard on this machine; a
  server restart or a refresh script also reloads the store and is not seen
  here.</div>
</div>
{''.join(cards)}
<div class="card"><a href="/">&larr; dashboard</a></div>
{_INSTANCES_SCRIPT}""", chrome)


# One fetch per server, fired together. Free of escape sequences, like every
# other script here: a literal newline inside a JS string once killed an entire
# IIFE silently, and two unrelated symptoms were traced back to it.
_INSTANCES_SCRIPT = """<script>
(function () {
  function card(name) {
    var all = document.querySelectorAll('.card.instance');
    for (var i = 0; i < all.length; i++) {
      if (all[i].getAttribute('data-name') === name) { return all[i]; }
    }
    return null;
  }
  function show(name, text, cls) {
    var c = card(name);
    if (!c) { return; }
    var pane = c.querySelector('.instance-result');
    pane.className = 'instance-result ' + (cls || 'note');
    pane.textContent = text;
  }
  function age(ms) {
    var mins = Math.floor(ms / 60000);
    if (mins < 1) { return 'just now'; }
    if (mins < 60) { return mins + 'm ago'; }
    var hours = Math.floor(mins / 60);
    if (hours < 48) { return hours + 'h ' + (mins % 60) + 'm ago'; }
    return Math.floor(hours / 24) + 'd ago';
  }
  function paintRefreshed() {
    var all = document.querySelectorAll('.instance-refreshed');
    for (var i = 0; i < all.length; i++) {
      var at = all[i].getAttribute('data-at');
      if (!at) { all[i].textContent = 'Last refresh: none recorded'; continue; }
      var when = new Date(at);
      all[i].textContent = 'Last refresh: ' + when.toLocaleString()
        + ' (' + age(Date.now() - when.getTime()) + ')'
        + (all[i].getAttribute('data-confirmed') === 'true' ? ''
           : ' - unconfirmed, the server gave an empty answer');
    }
  }
  function noteRefreshed(name, last) {
    var c = card(name);
    if (!c || !last) { return; }
    var line = c.querySelector('.instance-refreshed');
    line.setAttribute('data-at', last.at);
    line.setAttribute('data-confirmed', last.confirmed ? 'true' : 'false');
    paintRefreshed();
  }
  paintRefreshed();
  setInterval(paintRefreshed, 60000);
  function summarize(r) {
    var nl = String.fromCharCode(10);
    var warn = r.warning ? nl + nl + r.warning : '';
    if (!r.ok) {
      return 'FAILED after ' + r.elapsed_ms + 'ms: ' + (r.error || 'unknown') + warn;
    }
    var head = 'ok in ' + r.elapsed_ms + 'ms' + warn;
    if (r.action === 'metrics' && r.data && typeof r.data === 'object') {
      head += ' — ' + Object.keys(r.data).length + ' day(s) recorded';
    }
    var body = typeof r.data === 'string' ? r.data : JSON.stringify(r.data, null, 2);
    return head + nl + nl + body;
  }
  window.runOne = function (name, action) {
    show(name, action + ' ...', 'note');
    fetch('/api/instances/' + action + '?target=' + encodeURIComponent(name),
          { method: 'POST' })
      .then(function (resp) { return resp.json(); })
      .then(function (body) {
        var r = (body.results || [])[0];
        if (!r) { show(name, body.error || 'no result', 'err'); return; }
        show(name, summarize(r), r.ok ? (r.warning ? 'warn' : 'ok') : 'err');
        noteRefreshed(name, r.last_refresh);
      })
      .catch(function (e) { show(name, 'request failed: ' + e, 'err'); });
  };
  window.runAll = function (action) {
    var all = document.querySelectorAll('.card.instance');
    for (var i = 0; i < all.length; i++) {
      window.runOne(all[i].getAttribute('data-name'), action);
    }
  };
})();
</script>"""


def _instances_shell(body: str, chrome: tuple | None = None) -> str:
    """The dashboard's Monitoring tab IS this page.

    There were two: a static Monitoring tab in the hub whose cards only linked
    here, and the live page. Two descriptions of one thing drift — the tab still
    advertised Stop, Charts and :8080 — so the tab was deleted and the hub's
    Monitoring nav item points here instead.
    """
    # A top-level destination, so it wears the hub's header (ux/hub_chrome.py):
    # the logo and the nav bar, Monitoring lit. Without one (a test calling
    # this directly) it falls back to its own way home.
    links, hub_css, hub_header = chrome or ("", "", "")
    home = "" if chrome else ('<span style="margin-left:auto"><a href="/">'
                              "&larr; dashboard</a></span>")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Monitoring &mdash; Instance Control</title>
{links}<style>{hub_css}{_STYLE}{_HUB_FIX if chrome else ""}</style></head><body>
{hub_header}
<header class="page-head"><h1>Monitoring</h1>
<span class="sub">instance control &mdash; status, refresh and metrics across the
configured servers</span>{home}</header>
<main>{body}</main></body></html>"""


# Restated after _STYLE, which styles a bare `header`; see ux/hub_chrome.py.
_HUB_FIX = """
.header{display:block;padding:1.25rem 2rem;font-family:'Outfit',sans-serif;
line-height:1.6;border-bottom:1px solid var(--border-color)}
.header h1{margin:0;font-size:1.25rem;font-weight:600;letter-spacing:-.02em}
.header a.nav-tab{color:var(--text-secondary)}
.header a.nav-tab:hover{color:var(--text-primary)}
.header .nav-tab.active{color:white}
"""


def _backup_shell(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>QA backup</title>
<style>{_STYLE}</style></head><body>
<header><h1>QA backup</h1>
<span class="sub">the history and the attic — what SOT cannot restore</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def _edit_shell(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Edit record</title>
<style>{_STYLE}</style></head><body>
<header><h1>Edit record</h1>
<span class="sub">field-level, one instance file at a time</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def _annotate_shell(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Annotate Work</title>
<style>{_STYLE}</style></head><body>
<header><h1>Annotate Work</h1>
<span class="sub">pick concepts; TCAP places them</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def _site_shell(body: str) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Update workOnSite</title>
<style>{_STYLE}</style></head><body>
<header><h1>Update workOnSite</h1>
<span class="sub">what each site says it publishes</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def render_discard_page(*, wip: Mapping[str, Any], done: bool = False) -> str:
    """The discard-work-in-progress confirmation.

    Uncommitted work exists in no git history, so discarding it is
    unrecoverable — which is exactly why it gets the promotion shape: see the
    full file list first, act second. A bare "are you sure?" would be worse than
    nothing here, because the pile is usually larger than the user remembers.
    """
    files = [
        *(("add", p) for p in wip.get("adds", [])),
        *(("modify", p) for p in wip.get("modifies", [])),
        *(("delete", p) for p in wip.get("deletes", [])),
    ]
    rows = "".join(
        f'<div class="gate"><span class="pill {"bad" if k == "delete" else "ok"}">{k}</span>'
        f'<span class="mono">{_esc(p)}</span></div>'
        for k, p in files
    )
    binaries = wip.get("binaries_removed") or []
    bin_rows = "".join(f'<li class="mono">{_esc(p)}</li>' for p in binaries)

    # Both exits go to the DASHBOARD, not to a form. Records start from a
    # profile card now, and this page used to link straight to RDF Entry — a
    # form the hub no longer offers, reachable only from here (Rick,
    # 2026-09-17). The hub is right in either shape: a deployment with no
    # profiles still shows the hand-written cards there.
    if done and wip.get("discarded"):
        body = f"""
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Discarded</h2>
  <div class="note">The QA working tree is back at
  <span class="mono">{_esc(str(wip.get('head', ''))[:12])}</span>.
  Committed work and the SOT were not touched.</div>
  {f'<div class="summary mono" style="margin-top:.75rem">{rows}</div>' if rows else ''}
  {f'<div class="note" style="margin-top:.6rem">Orphaned binaries removed:<ul>{bin_rows}</ul></div>' if bin_rows else ''}
</div>
<div class="card"><a href="/">&rarr; Start another record</a></div>"""
    elif wip.get("clean"):
        body = """
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">Nothing to discard</h2>
  <div class="note">The QA working tree is clean — every record is either
  committed or already distributed.</div>
</div>
<div class="card"><a href="/">&rarr; Start another record</a></div>"""
    else:
        counts = wip.get("counts", {})
        body = f"""
<div class="card">
  <h2 style="margin-top:0;font-size:1rem">This will be thrown away</h2>
  <div class="note" style="margin-bottom:.6rem">
    {counts.get('adds', 0)} added, {counts.get('modifies', 0)} modified,
    {counts.get('deletes', 0)} deleted — plus any managed binary whose sidecar
    goes with them (QR codes, ingested images).
  </div>
  {rows}
</div>
<div class="card">
  <div class="note" style="margin-bottom:.75rem"><strong>This cannot be undone.</strong>
  Uncommitted work exists in no git history. Committed and distributed records
  are not affected — undoing those is a rollback, not this.</div>
  <form method="post" action="/wip/discard" style="display:inline">
    <button type="submit" class="danger">Discard work in progress</button>
  </form>
  <a href="/" style="margin-left:1rem">Cancel</a>
</div>"""

    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Discard work in progress</title>
<style>{_STYLE}</style></head><body>
<header><h1>Discard work in progress</h1>
<span class="sub">QA working tree only — never the SOT, never history</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main></body></html>"""


def render_profile_cards(profiles, broken=(), *, fallback: bool = True,
                         undistributed=()) -> str:
    """The Content Management cards, one per artist profile (CE_DESIGN §14).

    Rick's design: "The names RDF Entry and RDF Digital go away, replaced by the
    labels from the respective artist profiles." So the card says *Watercolor
    materials profile*, and the form behind it is that profile's template.

    A profile that could not be read gets a card too — a DEAD one, saying why.
    Leaving it out would be indistinguishable from never having created it, and
    the person who can fix it is the one looking at the screen.

    `fallback` keeps the hand-written forms reachable when a deployment has no
    profiles at all: a dashboard whose Content tab is empty because nobody has
    written a profile yet is worse than one offering the three forms that have
    always been there.
    """
    cards = []
    for p in profiles:
        guid = str(p.uri).rstrip("/").rsplit("/", 1)[-1]
        desc = p.description or p.note or "Create a record from this profile"
        # A profile that exists only in QA works exactly like any other — and is
        # also the one a refresh, a discard or an Edit form will take away with
        # it. Said on the card, because the alternative is finding out when the
        # card is gone (Rick, 2026-09-17).
        draft = ""
        if guid in set(undistributed or ()):
            draft = ('<div class="card-desc" style="color:var(--warn)">'
                     "draft &mdash; not distributed yet</div>")
        cards.append(
            f'<a href="rdf/profile/{_esc(guid)}" class="card blue">'
            f'<div class="card-title">{_esc(p.label)}</div>'
            f'<div class="card-desc">{_esc(desc)}</div>{draft}</a>'
        )
    for b in broken:
        # A profile that cannot drive a form yet opens in the profile editor,
        # which is where one is given (2026-11-21). Every collection made with
        # cwva-py before the dashboard has profiles like this, so a dead card
        # would leave a new user with no way in.
        guid = str(b["uri"]).rstrip("/").rsplit("/", 1)[-1]
        no_form = "ops:template" in b["reason"]
        desc = ("has no entry form yet &mdash; open it to give it one" if no_form
                else f'cannot build a form &mdash; {_esc(b["reason"][:120])}')
        cards.append(
            f'<a href="/rdf/artist-profile/edit?guid={_esc(guid)}" class="card red" '
            f'title="{_esc(b["reason"])}">'
            f'<div class="card-title">{_esc(b["label"])}</div>'
            f'<div class="card-desc">{desc}</div></a>'
        )
    if not cards and fallback:
        cards = [
            '<a href="rdf/entry" class="card blue"><div class="card-title">RDF Entry</div>'
            '<div class="card-desc">Create a non-digital work record</div></a>',
            '<a href="rdf/digital" class="card blue"><div class="card-title">RDF Digital</div>'
            '<div class="card-desc">Create a new digital work record</div></a>',
        ]
    return "\n".join(cards)


def render_session_bar(episode: dict | None) -> str:
    """"You are in the middle of something, and here is the way out of it."

    The discard used to live only on the review page, so a user who pressed
    `Edit form` and then thought better of the whole thing had to submit again
    just to reach a button that would throw it away (Rick enumerated this,
    2026-09-18). An open session is an open session wherever you are standing.
    """
    if not episode:
        return ""
    what = str(episode.get("subject") or episode.get("workflow") or "this record")
    return (
        '<div class="card session"><form method="post" action="/episode/abandon" '
        f'id="abandonForm" {CONFIRM_ON_ABANDON} style="display:inline">'
        '<button type="submit">Discard changes</button></form>'
        f'<span class="note">Unsaved work on <span class="mono">{_esc(what)}</span>. '
        "Nothing is kept until <strong>Approve &amp; distribute</strong>; "
        "discarding puts it back to where this session started.</span></div>"
    )


def render_drafts_card(count: int) -> str:
    """The count on the card, because a number is what makes a pile visible.

    Rick, 2026-09-18: "there needs to be a visible drafts status on the Content
    page, even if it was a number — some way to stay on top of them." Drafts
    were discoverable only by reading a preview, which meant the way you found
    out you had three was that all three converged together.
    """
    if count:
        desc = (f"{count} record{'s' if count != 1 else ''} written here and not "
                "distributed")
        return ('<a href="drafts" class="card yellow">'
                f'<div class="card-title">Drafts &mdash; {count}</div>'
                f'<div class="card-desc">{_esc(desc)}</div></a>')
    return ('<a href="drafts" class="card">'
            '<div class="card-title">Drafts</div>'
            '<div class="card-desc">Nothing undistributed</div></a>')


def render_bootstrap_cards() -> str:
    """The two hand-written forms: an artist, and a profile for one of the
    things they make.

    Rendered at their OWN place on the hub rather than appended to the profile
    cards. They are how the cards at the top come to exist, so they belong on
    the same tab — but they are not works, and Rick's order puts them after the
    working functions (2026-09-17): profiles, Edit Record, Update workOnSite,
    Annotate Work, Entity, Proof, then these.
    """
    return "\n".join([
        '<a href="rdf/artist-profile" class="card cyan">'
        '<div class="card-title">New artist profile</div>'
        '<div class="card-desc">Describe a kind of work, and the form that records it</div></a>',
        '<a href="rdf/artist" class="card cyan">'
        '<div class="card-title">New artist</div>'
        '<div class="card-desc">The person or persona whose work this records</div></a>',
        '<a href="rdf/artist/edit" class="card cyan">'
        '<div class="card-title">Edit artist</div>'
        '<div class="card-desc">Name, contact, brand &mdash; the record, not the works</div></a>',
        '<a href="rdf/artist-profile/edit" class="card cyan">'
        '<div class="card-title">Edit artist profile</div>'
        '<div class="card-desc">Its template, for works made from now on</div></a>',
    ])


# ---------------------------------------------------------------------------
# SPARQL browser (inventory #17) over the sandbox.
#
# The layout and the five result formats are cwvaServer-py's `/sparql`; the
# query set, the notes and the prefix table are left off, as asked. It answers
# from the SANDBOX, drafts included, which is the point: the published server
# does not load provenance, so this is the only place to check it against the
# records it cites.
# ---------------------------------------------------------------------------

SPARQL_FORMATS = ("HTML", "CSV", "TSV", "JSON", "XML")

_SPARQL_CSS = """
.sparql-controls{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin-bottom:.5rem}
/* The shared `input{width:100%}` and block labels stack each radio on a line of
   its own above its caption. One label per choice, wrapping its radio, inline. */
.sparql-controls label.fmt{display:inline-flex;align-items:center;gap:.3rem;margin:0;
font-size:.9rem;color:var(--ink);text-transform:none;cursor:pointer}
.sparql-controls input[type=radio]{width:auto;flex:none;margin:0}
.sparql-controls button{margin-left:.5rem}
.sparql-status{font-size:.82rem;color:var(--muted);margin:.4rem 0}
.sparql-results{border:1px solid var(--line);overflow:auto;max-height:65vh;resize:both}
.sparql-table{border-collapse:collapse;width:100%;font-size:.85rem}
.sparql-table th{background:#1f2a3c;padding:4px 8px;text-align:left;position:sticky;top:0;
white-space:nowrap}
.sparql-table td{padding:3px 8px;border-bottom:1px solid var(--line);white-space:nowrap}
.sparql-table tr:hover td{background:#1b2537}
#query{width:100%;font-family:ui-monospace,monospace;font-size:.85rem}
.sparql-text{width:100%;font-family:ui-monospace,monospace;font-size:.8rem}
"""

#: Shortened in the table only; every format that is meant to be read by a
#: program carries the full IRI.
_SPARQL_SHORT = (
    ("vad:", "http://visualartsdna.org/model/"),
    ("the:", "http://visualartsdna.org/thesaurus/"),
    ("ops:", "http://visualartsdna.org/operations/"),
    ("tko:", "http://visualartsdna.org/takeout/"),
    ("schema:", "https://schema.org/"),
    ("rdf:", "http://www.w3.org/1999/02/22-rdf-syntax-ns#"),
    ("rdfs:", "http://www.w3.org/2000/01/rdf-schema#"),
    ("skos:", "http://www.w3.org/2004/02/skos/core#"),
    ("owl:", "http://www.w3.org/2002/07/owl#"),
    ("xsd:", "http://www.w3.org/2001/XMLSchema#"),
    ("prov:", "http://www.w3.org/ns/prov#"),
    ("foaf:", "http://xmlns.com/foaf/0.1/"),
)


def _short_iri(iri: str, work_ns: str) -> str:
    for pfx, ns in (("work:", work_ns), *_SPARQL_SHORT):
        if ns and iri.startswith(ns) and len(iri) > len(ns):
            return pfx + iri[len(ns):]
    return iri


def _sparql_table(res: Mapping[str, Any], work_ns: str) -> str:
    head = "".join(f"<th>{_esc(v)}</th>" for v in res["vars"])
    rows = []
    for row in res["rows"]:
        cells = []
        for cell in row:
            if cell is None:
                cells.append("<td></td>")
            elif cell["t"] == "uri":
                cells.append(f'<td title="{_esc(cell["v"])}" class="mono">'
                             f'{_esc(_short_iri(cell["v"], work_ns))}</td>')
            else:
                cells.append(f"<td>{_esc(cell['v'])}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return (f'<div class="sparql-results"><table class="sparql-table"><tr>{head}</tr>'
            + "".join(rows) + "</table></div>")


def sparql_text(res: Mapping[str, Any], fmt: str) -> str:
    """A SELECT result as CSV, TSV, SPARQL JSON or SPARQL XML."""
    import json as _json

    names, rows = res["vars"], res["rows"]
    value = lambda c: "" if c is None else c["v"]  # noqa: E731
    if fmt == "CSV":
        quote = lambda s: '"' + s.replace('"', '""') + '"'  # noqa: E731
        return "\r\n".join([",".join(names)] + [
            ",".join(quote(value(c)) for c in r) for r in rows]) + "\r\n"
    if fmt == "TSV":
        return "\n".join(["\t".join(f"?{v}" for v in names)] + [
            "\t".join(value(c) for c in r) for r in rows]) + "\n"
    if fmt == "JSON":
        kinds = {"uri": "uri", "bnode": "bnode", "literal": "literal"}
        return _json.dumps({"head": {"vars": names}, "results": {"bindings": [
            {v: {"type": kinds[c["t"]], "value": c["v"]}
             for v, c in zip(names, r) if c is not None} for r in rows]}}, indent=2)
    out = ['<?xml version="1.0"?>',
           '<sparql xmlns="http://www.w3.org/2005/sparql-results#">', "  <head>"]
    out += [f'    <variable name="{_esc(v)}"/>' for v in names]
    out += ["  </head>", "  <results>"]
    for r in rows:
        out.append("    <result>")
        for v, c in zip(names, r):
            if c is not None:
                tag = {"uri": "uri", "bnode": "bnode"}.get(c["t"], "literal")
                out.append(f'      <binding name="{_esc(v)}"><{tag}>{_esc(c["v"])}</{tag}></binding>')
        out.append("    </result>")
    out += ["  </results>", "</sparql>"]
    return "\n".join(out) + "\n"


def render_sparql_page(*, query: str = "", fmt: str = "HTML",
                       result: Mapping[str, Any] | None = None, error: str = "",
                       work_ns: str = "", ms: int = 0) -> str:
    fmt = fmt if fmt in SPARQL_FORMATS else "HTML"
    radios = "".join(
        f'<label class="fmt"><input type="radio" name="format" value="{f}"'
        f'{" checked" if f == fmt else ""}>{f}</label>'
        for f in SPARQL_FORMATS)
    body, rows, status = "", 0, "ok"
    if error:
        status = "error"
        body = f'<div class="err">{_esc(error)}</div>'
    elif result:
        kind = result.get("type")
        if kind == "select":
            rows = len(result["rows"])
            body = (_sparql_table(result, work_ns) if fmt == "HTML" else
                    f'<textarea readonly rows="20" class="sparql-text" spellcheck="false">'
                    f"{_esc(sparql_text(result, fmt))}</textarea>")
            if rows >= result.get("row_cap", 0) > 0:
                status = f"capped at {result['row_cap']:,} rows; add your own LIMIT to see others"
        elif kind == "ask":
            rows = 1
            body = (f'<textarea readonly rows="3" class="sparql-text">ASK result: '
                    f'{"true" if result["boolean"] else "false"}</textarea>')
        else:
            rows = result.get("triples", 0)
            body = (f'<textarea readonly rows="20" class="sparql-text" spellcheck="false">'
                    f'{_esc(result.get("ttl", ""))}</textarea>')
    loaded = (f" &nbsp;|&nbsp; {result['triples_loaded']:,} triples in the sandbox"
              if result and "triples_loaded" in result else "")
    status_line = (f'<div class="sparql-status">{ms} ms &nbsp;|&nbsp; {rows} rows'
                   f"{loaded} &nbsp;|&nbsp; {_esc(status)}</div>") if (query and (result or error)) else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>SPARQL Browser</title>
<style>{_STYLE}{_SPARQL_CSS}</style></head>
<body>
<header><h1>SPARQL Browser</h1>
<span class="sub">the sandbox as it stands, drafts included</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main><form class="card" id="sparqlForm" action="/sparql" method="get">
  <div class="sparql-controls">{radios}
    <button type="submit" class="primary">Execute</button></div>
  <textarea id="query" name="query" rows="12" spellcheck="false">{_esc(query)}</textarea>
  {status_line}
  {body}
</form></main></body></html>"""

