"""The cwva-py viewer's card and page (/viewer)."""

from __future__ import annotations

from typing import Any, Mapping

from .forms import _STYLE, _esc

__all__ = ["render_viewer_card", "render_viewer_page"]

_WORDS = {
    "running": "running",
    "loading": "loading the sandbox",
    "stopped": "stopped",
    "failed": "stopped with an error",
}


def render_viewer_card(status: Mapping[str, Any] | None) -> str:
    if status is None:
        return ('<a href="viewer" class="card">'
                '<div class="card-title">cwva-py view</div>'
                '<div class="card-desc">Not configured (config viewer)</div></a>')
    state = status["state"]
    colour = {"running": " cyan", "loading": " yellow", "failed": " red"}.get(state, "")
    desc = ("See this sandbox, drafts included, in cwva-py"
            if state == "stopped" else f"{_WORDS[state]} on port {status['port']}")
    return (f'<a href="viewer" class="card{colour}">'
            '<div class="card-title">cwva-py view</div>'
            f'<div class="card-desc">{_esc(desc)}</div></a>')


_CSS = """
.state{font-weight:600}
.state.running{color:var(--ok)}.state.loading{color:var(--warn)}
.state.failed{color:var(--bad)}.state.stopped{color:var(--muted)}
.actions{display:flex;gap:.5rem;margin:.8rem 0}
.actions button{padding:.5rem .9rem;border:1px solid var(--line);border-radius:8px;
background:#0d121c;color:var(--ink);cursor:pointer;font:inherit}
.actions button:hover{border-color:var(--accent)}
.actions button:disabled{opacity:.4;cursor:default}
pre.log{white-space:pre-wrap;font-size:.75rem;max-height:24rem;overflow:auto;
background:#0d121c;border:1px solid var(--line);border-radius:8px;padding:.6rem}
.note{color:var(--muted);font-size:.85rem}
"""

_SCRIPT = """
<script>
function act(name) {
  document.querySelectorAll('.actions button').forEach(function (b) { b.disabled = true; });
  document.getElementById('msg').textContent = name === 'stop' ? 'stopping...' : 'starting...';
  fetch('/api/viewer/' + name, {method: 'POST'})
    .then(function (r) { return r.json(); })
    .then(function (j) {
      if (j.error) { document.getElementById('msg').textContent = j.error; }
      poll();
    });
}
function poll() {
  fetch('/api/viewer').then(function (r) { return r.json(); }).then(function (j) {
    var s = document.getElementById('state');
    s.textContent = j.state; s.className = 'state ' + j.state;
    document.getElementById('log').textContent = j.log || '';
    var on = j.state === 'running' || j.state === 'loading';
    document.getElementById('start').disabled = on;
    document.getElementById('reload').disabled = !on;
    document.getElementById('stop').disabled = !on;
    document.getElementById('open').style.display = j.state === 'running' ? '' : 'none';
    if (j.state === 'loading') { setTimeout(poll, 2000); }
    else if (j.state === 'running') { document.getElementById('msg').textContent = ''; }
  });
}
document.addEventListener('DOMContentLoaded', poll);
</script>
"""


def render_viewer_page(status: Mapping[str, Any] | None, *, log: str = "",
                       label: str = "") -> str:
    if status is None:
        body = ('<section class="card"><p>No viewer is configured. Add a '
                '<code>viewer</code> block to the dashboard config.</p></section>')
    else:
        state = status["state"]
        which = f"the {label} sandbox" if label else "this dashboard's sandbox"
        body = f"""<section class="card">
<p>cwva-py, running over {_esc(which)} <code>{_esc(status['sandbox'])}</code>,
drafts included. <span class="state {state}" id="state">{_esc(state)}</span></p>
<div class="actions">
  <button id="start" onclick="act('start')">Start</button>
  <button id="reload" onclick="act('reload')" title="restart, re-reading the sandbox">Reload</button>
  <button id="stop" onclick="act('stop')">Stop</button>
  <a id="open" class="button" href="{_esc(status['url'])}" target="_blank"
     style="display:none">Open {_esc(status['url'])} &rarr;</a>
</div>
<p id="msg" class="note"></p>
<p class="note">Read-only: the process can write nothing in the sandbox (Landlock),
listens on this machine only, and reaches no bucket. After a change here, press
<b>Reload</b> to see it; loading takes about 20 seconds.</p>
<pre class="log" id="log">{_esc(log)}</pre>
</section>"""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>cwva-py view</title>
<style>{_STYLE}{_CSS}</style></head>
<body>
<header><h1>cwva-py view</h1>
<span class="sub">see a change before it is distributed</span>
<span style="margin-left:auto"><a href="/">&larr; dashboard</a></span></header>
<main>{body}</main>{_SCRIPT}</body></html>"""
