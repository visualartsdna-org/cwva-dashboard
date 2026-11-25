"""What a `domain` may look like.

The domain is the base of every IRI the dashboard mints, and an IRI is an exact
string: `https://a.org` and `http://a.org:80` are other identities than
`http://a.org`, and `a.org` is not an IRI at all. Records made under an unusable
one are valid RDF that nothing complains about, so it is refused, not corrected
(CE_DESIGN §13.4a). cwva-py reads `domain` by the same rule, agreed in November
2026; `tests/test_domain.py` is the shared table.
"""

from __future__ import annotations

import re

_LABEL = r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
_DOMAIN = re.compile(rf"(https?)://({_LABEL}(?:\.{_LABEL})*)(?::([1-9][0-9]{{0,4}}))?")
_DEFAULT_PORT = {"http": "80", "https": "443"}
COMMONS = "http://visualartsdna.org"


def check_domain(raw: str) -> str:
    """``raw`` less surrounding space and trailing slashes, or ValueError saying
    what to write instead. Changes nothing else."""
    value = str(raw).strip().rstrip("/")
    m = _DOMAIN.fullmatch(value)
    if m is None or (m.group(3) and int(m.group(3)) > 65535):
        raise ValueError(
            f"`domain` is {raw!r}, which cannot be the base of a record's "
            "identifier. Write http:// or https://, then a lower-case host name "
            "(and a port only if your site needs one), and nothing after it: "
            "http://janedoe-art.com"
        )
    scheme, host, port = m.groups()
    if port == _DEFAULT_PORT[scheme]:
        raise ValueError(
            f"`domain` is {raw!r}: port {port} is what {scheme} already means, "
            f"so leave it out: {scheme}://{host}"
        )
    if host == "visualartsdna.org" and value != COMMONS:
        raise ValueError(
            f"`domain` is {raw!r}: records under visualartsdna.org are "
            f"identified by {COMMONS}, so write exactly that."
        )
    return value
