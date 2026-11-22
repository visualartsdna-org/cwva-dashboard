"""Concept hygiene: lexical dup matching, merge/demote, and the hygiene ledger.

The ledger is the shared record of *dismissals* — the only tracked workflow
state (CE_DESIGN §7.1) — and later of unresolved concept-dup pairs (§6). It
lands early because the workflow-state engine needs it now.
"""
