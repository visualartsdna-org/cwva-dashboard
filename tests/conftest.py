"""Shared test identity.

The code carries **no default domain** (CE_DESIGN §13.4a): the deployer
configures the dashboard, and a fallback in code was one deployment's identity
reachable by omission — every record minted under it would carry the wrong
sovereign `work:` namespace, which is not correctable later without a rebase.

So tests declare their own. This value happens to match the current CWVA
deployment because the fixtures assert against URIs that were captured from real
data; a test wanting a different identity passes its own.
"""

from __future__ import annotations

TEST_DOMAIN = "http://visualartsdna.org"
