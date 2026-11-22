"""Dashboard UX.

Routes stay thin over the tool registry (CLAUDE law 10) — the web layer holds no
filesystem or SOT logic, and every capability is reached by dispatching a tool.

**Phase 4.7 replaced the generic renderer with the real dashboard (D1).** The
schema-driven ``dashboard.html`` is gone; ``html/function.html`` is served
directly as the hub and each function is wired behind its card one cycle at a
time. What that trades away is the zero-UX-code property: a newly registered
tool no longer appears in the UI by itself. What it must **not** trade away is
the property that made the affordance layer worth building — *what the form
offers is what the system enforces* — so ``forms.py`` builds every widget from
the tool schema and resolves every picker from the same source the gate checks.
A hand-typed ``<option>`` list would bind only the human and reopen the hole.
"""
