"""Movable hub cards: a handle on each card, drag to reorder, the order kept.

Rendered as one inline block placed straight after the section's grid, so the
saved order is applied before the page is first painted rather than visibly
shuffled afterwards. The grid itself stays CSS grid with ``auto-fill``: moving
a card changes only the ORDER, and the grid packs the cards with no gaps, which
is the "always a minimal configuration" part. FLIP (record each card's place,
move, animate from the old place) is what makes the others slide.
"""

from __future__ import annotations

import json

__all__ = ["render_card_mover"]

_CSS = """
<style>
.card-grid[data-section] .card{position:relative}
.card-handle{position:absolute;top:.45rem;right:.45rem;width:1.3rem;height:1.3rem;
display:flex;align-items:center;justify-content:center;border-radius:5px;
color:var(--text-muted);font-size:.85rem;line-height:1;cursor:grab;
opacity:.35;touch-action:none;user-select:none}
.card:hover .card-handle{opacity:.9}
.card-handle:hover{background:rgba(255,255,255,.08)}
.card.dragging{opacity:.55;outline:2px dashed var(--border-accent);
outline-offset:2px;z-index:5}
.card.dragging,.card.dragging .card-handle{cursor:grabbing}
.cards-reset{margin-left:.6rem;font-size:.7rem;color:var(--text-muted);
background:none;border:1px solid var(--border-color);border-radius:999px;
padding:.1rem .55rem;cursor:pointer}
.cards-reset:hover{color:var(--text-primary)}
</style>
"""

_JS = r"""
<script>
(function () {
  var grid = document.querySelector('.card-grid[data-section="%(section)s"]');
  if (!grid) { return; }
  var saved = %(order)s;
  function keyOf(card) {
    var h = card.getAttribute('href');
    if (h && h !== '#') { return h; }
    var t = card.querySelector('.card-title');
    return 'title:' + (t ? t.textContent.trim() : '');
  }
  function cards() { return Array.prototype.slice.call(grid.querySelectorAll(':scope > .card')); }

  // The saved order first; anything it does not name keeps its own order after.
  if (saved.length) {
    var byKey = {};
    cards().forEach(function (c) { byKey[keyOf(c)] = c; });
    var anchor = grid.firstChild;
    saved.forEach(function (k) {
      var c = byKey[k];
      if (c) { grid.insertBefore(c, anchor); anchor = c.nextSibling; delete byKey[k]; }
    });
  }

  cards().forEach(function (c) {
    var h = document.createElement('span');
    h.className = 'card-handle';
    h.title = 'drag to move';
    h.setAttribute('aria-hidden', 'true');
    h.textContent = '⠇⠇';
    c.appendChild(h);
  });

  // FLIP: where everything is, move, then animate from there to here.
  function rects() {
    var m = new Map();
    cards().forEach(function (c) { m.set(c, c.getBoundingClientRect()); });
    return m;
  }
  function slide(before, except) {
    cards().forEach(function (c) {
      if (c === except) { return; }
      var a = before.get(c), b = c.getBoundingClientRect();
      if (!a) { return; }
      var dx = a.left - b.left, dy = a.top - b.top;
      if (!dx && !dy) { return; }
      c.style.transition = 'none';
      c.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
      requestAnimationFrame(function () {
        c.style.transition = 'transform 180ms ease';
        c.style.transform = '';
      });
    });
  }

  var dragging = null, moved = false;
  grid.addEventListener('pointerdown', function (e) {
    var h = e.target.closest('.card-handle');
    if (!h) { return; }
    e.preventDefault(); e.stopPropagation();
    dragging = h.parentElement; moved = false;
    dragging.classList.add('dragging');
    h.setPointerCapture(e.pointerId);
  });
  grid.addEventListener('pointermove', function (e) {
    if (!dragging) { return; }
    var el = document.elementFromPoint(e.clientX, e.clientY);
    var over = el && el.closest('.card');
    if (!over || over === dragging || over.parentElement !== grid) { return; }
    var r = over.getBoundingClientRect();
    var after = (e.clientY > r.top + r.height / 2) ||
                (e.clientY > r.top && e.clientX > r.left + r.width / 2);
    var ref = after ? over.nextSibling : over;
    if (ref === dragging || ref === dragging.nextSibling) { return; }
    var before = rects();
    grid.insertBefore(dragging, ref);
    moved = true;
    slide(before, dragging);
  });
  function drop() {
    if (!dragging) { return; }
    dragging.classList.remove('dragging');
    dragging = null;
    if (!moved) { return; }
    save(cards().map(keyOf));
  }
  grid.addEventListener('pointerup', drop);
  grid.addEventListener('pointercancel', drop);
  // A click on the handle must never open the card's page.
  grid.addEventListener('click', function (e) {
    if (e.target.closest('.card-handle')) { e.preventDefault(); e.stopPropagation(); }
  }, true);

  var reset = document.getElementById('resetCards-%(section)s');
  function save(order) {
    fetch('/api/hub/layout', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({section: '%(section)s', order: order})});
    if (reset) { reset.hidden = !order.length; }
  }
  if (reset) {
    reset.hidden = !saved.length;
    reset.addEventListener('click', function () { save([]); location.reload(); });
  }
})();
</script>
"""


def render_card_mover(section: str, saved_order: list) -> str:
    """The CSS + script for one section, carrying its saved order."""
    order = json.dumps(list(saved_order)).replace("</", "<\\/")
    return _CSS + _JS % {"section": section, "order": order}
