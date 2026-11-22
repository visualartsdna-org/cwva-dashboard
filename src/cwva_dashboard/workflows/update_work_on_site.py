"""updateWorkOnSite — observe which works a site publishes (CE_DESIGN §7.2).

Assert ``work:<guid> vad:workOnSite <site>``, one TTL per site, full snapshot
per run. Effect pattern: read-only HTTP to config-listed sites (the sanctioned
network-effect class, law 11) + a QA write terminating in a promotion unit. The
HTTP client is **injectable** (`Fetcher`) so tests never touch the network.

**Identity is DECLARED by the site, never inferred.** A page is read for the
work URIs it names — in link hrefs or in text — and nothing else about the page
matters. No DOM structure, no title matching, no image hashing.

That is a correction, made on evidence (2026-09-09). Two earlier designs both
inferred identity: the Groovy scraped rendered text and matched lines against
`rdfs:label` between hardcoded start/stop markers; the first rebuild fetched
`/sitemap.xml` and read OpenGraph per page. Measured against the real sites:

- **the sitemap does not exist** (404 on both), so the rebuild found nothing;
- **OpenGraph is site-level** — `og:title` is the site name, `og:description` is
  whatever text Google lifted — so there is nothing per-work to read;
- the text scrape did work (87 label matches) but is a heuristic on someone
  else's page layout, and a redesign silently breaks it;
- meanwhile **the pages already carry 97 and 25 explicit links** to
  `visualartsdna.org/work/<guid>` — the "Catalog entry" links, which the Groovy
  was stepping over as noise on its way to guessing from titles.

So the convention is: **a site names the works it publishes.** It is what this
site already does, it is a reasonable thing to ask of any CE deployer (link to
the work's canonical URI, or list the CURIEs), and it makes the answer exact —
there is no confidence score because there is nothing to be unsure about. A
site that says nothing yields nothing, which is correct rather than empty.

Three spellings are accepted, all three observed in the real pages:
``https://www.visualartsdna.org/work/<guid>``, ``…/modelviewer?work=work:<guid>``
and a bare ``work:<guid>`` CURIE in text.
"""

from __future__ import annotations

import re
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef

from ..promotion.layout import Layout
from ..tools.base import Tool
from ..tools.record_tools import VAD, work_namespace

__all__ = [
    "Fetcher", "UrllibFetcher", "SotWork", "SiteRun", "scrape_site",
    "work_ref_pattern", "extract_work_refs", "same_origin_links",
    "malformed_ref_pattern", "extract_malformed_refs",
    "observe_sites", "build_scrape_tools",
]

PROV = Namespace("http://www.w3.org/ns/prov#")


# -- HTTP (sanctioned network effect; injectable) ---------------------------


class Fetcher(Protocol):
    def get(self, url: str) -> bytes: ...


class UrllibFetcher:
    """Read-only HTTP GET via stdlib. The default production fetcher."""

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    def get(self, url: str) -> bytes:
        req = urllib.request.Request(url, headers={"User-Agent": "cwva-dashboard/0.1"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (config-listed sites only)
            return resp.read()


# -- what the page DECLARES --------------------------------------------------


def work_ref_pattern(domain: str, *, host: str | None = None) -> re.Pattern:
    """The catalog-entry URI, and only that.

    A work's canonical URI **is** its subject URI: :func:`work_namespace` builds
    it as ``<domain>/work/<guid>``, so this pattern is derived from that function
    rather than assembling the same string a second time. If the namespace ever
    changes shape, the pattern follows instead of silently disagreeing with the
    records it is trying to identify.

    ONE form is accepted, deliberately narrowed 2026-09-09. Two others were
    matched before and both were wrong to accept:

    - ``?work=work:<guid>`` is the 3D viewer's query — an INVOCATION of a
      viewer, not a claim that this site catalogues the work. It also carried no
      host requirement, so a third-party page embedding the viewer counted.
    - a bare ``work:<guid>`` in text was a convention nobody follows, invented
      on the assumption that a site might list identifiers instead of linking
      them. Matching a namespace prefix loose in the page body is a lot of
      surface for a case that does not exist.

    ``host`` covers the deployment where the catalogue is SERVED somewhere other
    than the domain the data names (config carries both; they are equal when DNS
    is set). Both are accepted, because the site links to wherever a reader can
    actually reach the entry.
    """
    bases = {work_namespace(domain)}
    if host:
        bases.add(work_namespace(host))
    alternatives = sorted(
        re.escape(re.sub(r"^https?://(?:www\.)?", "", str(b))) for b in bases
    )
    guid = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    return re.compile(
        rf"https?://(?:www\.)?(?:{'|'.join(alternatives)})({guid})"
    )


def malformed_ref_pattern(domain: str, *, host: str | None = None) -> re.Pattern:
    """Catalog links that ALMOST name a work: the right base, then junk, then a
    GUID.

    Found on the first narrowed run: one link reads
    ``…/work/%09e776711b-…`` — a tab that got pasted into the URL. It is a
    broken link on the site (it will not resolve), and the loose pattern had
    been papering over it by matching the same work's 3D-viewer link instead.

    Reported rather than tolerated. Accepting the junk would hide a link the
    site's own visitors cannot follow, and silently dropping it would lose a
    work with no explanation — the failure mode this workflow has already had
    once.
    """
    bases = {work_namespace(domain)}
    if host:
        bases.add(work_namespace(host))
    alternatives = sorted(
        re.escape(re.sub(r"^https?://(?:www\.)?", "", str(b))) for b in bases
    )
    guid = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    return re.compile(
        rf"https?://(?:www\.)?(?:{'|'.join(alternatives)})([^\"'\s]{{1,12}}?)({guid})"
    )


def extract_malformed_refs(html: str, pattern: re.Pattern) -> list[tuple[str, str]]:
    """``(junk, guid)`` for each near-miss catalog link."""
    return [(m.group(1), m.group(2)) for m in pattern.finditer(html)]


def extract_work_refs(html: str, pattern: re.Pattern) -> set[str]:
    """The work GUIDs a page's catalog links name.

    Deliberately reads the RAW HTML rather than rendered text: the href is the
    declaration, and rendering it away would leave only the link's caption —
    "Catalog entry" — which is the guessing game this replaced.

    A match still has to survive the store: the caller intersects these GUIDs
    with the works the QA tree actually holds, so a URI-shaped string that
    happens to appear on a page cannot become an assertion on its own.
    """
    return {m.group(1) for m in pattern.finditer(html)}


def same_origin_links(html: str, site: str) -> list[str]:
    """Same-site pages linked from this one, absolute-ised, in document order.

    Page discovery without a sitemap — both real sites 404 that path, and both
    keep their whole catalogue behind two or three internal links. Depth is the
    caller's business; this is one hop.
    """
    root = site.rstrip("/")
    host = re.sub(r"^https?://(www\.)?", "", root).lower()
    out: list[str] = []
    for href in re.findall(r'href="([^"#]+)"', html):
        if href.startswith("/"):
            url = root + href
        elif re.match(r"^https?://", href):
            if re.sub(r"^https?://(www\.)?", "", href).lower().split("/")[0] != host:
                continue  # off-site
            url = href
        else:
            continue  # mailto:, relative, javascript:
        url = url.rstrip("/")
        if url not in out and url != root:
            out.append(url)
    return out


@dataclass(frozen=True)
class SotWork:
    """A work the store knows about. `label` is for the report — the match is by
    identifier, so nothing depends on the label being right."""

    guid: str
    label: str


@dataclass
class SiteRun:
    site: str
    pages: list[str] = field(default_factory=list)
    declared: set[str] = field(default_factory=set)
    # Why a page could not be read. A run that finds nothing and says nothing is
    # indistinguishable from a site that publishes nothing — the first real run
    # produced exactly that, an empty TTL with no reason given.
    errors: list[str] = field(default_factory=list)
    # Catalog links that almost name a work — right base, then junk, then a
    # GUID. A broken link on the site, reported so it can be fixed there.
    malformed: list[str] = field(default_factory=list)
    # Named by the site but absent from the store. NOT an error: the site may
    # publish a work this QA tree has not synced, or one that was withdrawn.
    # Reported so a human can tell the difference; never asserted, because a
    # triple about a subject we do not have is a dangling reference we created.
    unknown: list[str] = field(default_factory=list)


def scrape_site(
    site: str,
    fetcher: Fetcher,
    known: set[str],
    *,
    pattern: re.Pattern,
    malformed_pattern: re.Pattern | None = None,
    max_pages: int = 50,
) -> SiteRun:
    """Fetch a site's pages and collect the work GUIDs they declare."""
    run = SiteRun(site=site)
    root = site.rstrip("/")
    try:
        home = fetcher.get(root).decode("utf-8", "replace")
    except Exception as exc:
        run.errors.append(f"{root}: {type(exc).__name__}: {exc}")
        return run

    run.pages.append(root)
    run.declared |= extract_work_refs(home, pattern)
    _note_malformed(run, home, pattern, malformed_pattern)

    for url in same_origin_links(home, root)[: max_pages - 1]:
        try:
            html = fetcher.get(url).decode("utf-8", "replace")
        except Exception as exc:
            run.errors.append(f"{url}: {type(exc).__name__}: {exc}")
            continue  # one dead link does not fail the run
        run.pages.append(url)
        run.declared |= extract_work_refs(html, pattern)
        _note_malformed(run, html, pattern, malformed_pattern)

    run.unknown = sorted(run.declared - known)
    run.malformed = sorted(set(run.malformed))
    return run


def _note_malformed(run, html, pattern, malformed_pattern) -> None:
    """Record near-miss links, but only for works the page does not ALSO name
    correctly elsewhere — a page that carries both a good and a broken link to
    the same work has nothing wrong with the good one."""
    if malformed_pattern is None:
        return
    clean = extract_work_refs(html, pattern)
    for junk, guid in extract_malformed_refs(html, malformed_pattern):
        if guid not in clean:
            run.malformed.append(f"{guid} (link contains {junk!r})")


def observe_sites(sites, fetcher: Fetcher, pattern: re.Pattern,
                  malformed_pattern: re.Pattern | None = None) -> list[SiteRun]:
    """Read every configured site. **Trusted-orchestrator only.**

    This performs the network effect, and it cannot live in the confined worker
    — not by policy but by construction. Landlock restricts the worker to the
    sandbox, and glibc's resolver needs `/etc/resolv.conf` and the NSS libraries
    to turn a hostname into an address. Measured 2026-09-09: a fetch from the
    worker to `http://127.0.0.1:<port>` succeeds, and the same fetch to a NAMED
    host fails with `EAI_AGAIN`. The first real run therefore produced two empty
    snapshots and no explanation.

    That is a better outcome than it sounds. The sandbox denies the agent
    network reach as a *structural consequence* of filesystem confinement, not
    as a rule someone has to remember — and the sanctioned effect sits in the
    trusted layer beside ingest and the promotion tail, where it is explicit and
    auditable. Extraction stays a pure function over the fetched bytes, so doing
    it here grants no capability the worker gives up.
    """
    return [
        scrape_site(site, fetcher, set(), pattern=pattern,
                    malformed_pattern=malformed_pattern)
        for site in sites
    ]


# -- output -----------------------------------------------------------------


# Stable software-agent identity — deterministic so the snapshot is idempotent.
#: The scraper, in the OPERATIONS ontology alongside every other agent
#: and role (2026-09-30). It used to mint its own `…/agent/` namespace,
#: which parsed and resolved to nothing: no class said what an agent
#: was and no role said what it did.
SCRAPER_AGENT = URIRef("http://visualartsdna.org/operations/updateWorkOnSite")


def workonsite_ttl(site: str, guids: list[str], work_ns: Namespace) -> str:
    """Full-snapshot per-site TTL: ``work:<guid> vad:workOnSite <site>``, with a
    **deterministic** observed-by-scraper attribution (§7.2, §8). No run
    timestamp — that would defeat idempotency; the run time lives in the report
    and audit log. Regenerated whole each run: appearing works are adds,
    vanished works are removals (takedown signal)."""
    g = Graph()
    g.bind("work", work_ns)
    g.bind("vad", VAD)
    g.bind("prov", PROV)
    site_ref = URIRef(site)
    g.add((site_ref, RDF.type, PROV.Entity))
    g.add((site_ref, PROV.wasAttributedTo, SCRAPER_AGENT))
    g.add((SCRAPER_AGENT, RDF.type, PROV.SoftwareAgent))
    g.add((SCRAPER_AGENT, RDFS.label, Literal("updateWorkOnSite scraper (observed-by-scraper)")))
    for guid in sorted(set(guids)):
        g.add((work_ns[guid], VAD.workOnSite, site_ref))
    return g.serialize(format="turtle")


def build_sot_index(fileops, data_dir: str) -> dict[str, str]:
    """guid -> rdfs:label for everything in the QA content tree.

    Identity comes from the site's own links, so this is only needed to answer
    two questions for the human: what is each declared work CALLED, and does the
    store actually have it. No image hashing — the previous design read and
    hashed every original to guess at identity, which is work that no longer has
    a question to answer.
    """
    # The SHARED cached graph, not a private re-read. Reading every record here
    # cost one `list_dir` plus one `read_text` per file — 330 fileops on the
    # real store — which blew the 600-ops-per-minute quota the moment the
    # workflow-state panel was also polling. Exactly the failure the panel
    # itself had, and it has a cache for it: per-file, invalidated on
    # (size, mtime) with a racy-clean window. Warm, this costs one `list_dir`.
    from ..tools.workflow_tools import _content_graph

    graph = _content_graph(fileops, data_dir)
    out: dict[str, str] = {}
    for subj in set(graph.subjects(RDFS.label, None)):
        uri = str(subj)
        if "/work/" not in uri:
            continue
        out[uri.rsplit("/", 1)[-1]] = str(graph.value(subj, RDFS.label))
    return out


def _slug(site: str) -> str:
    netloc = re.sub(r"^https?://", "", site).rstrip("/")
    return re.sub(r"[^a-z0-9]+", "_", netloc.lower()).strip("_")


_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def build_scrape_tools(sites, domain, fetcher: Fetcher | None = None, *, layout=None) -> list[Tool]:
    """The workOnSite STAGING tool: turn observations into per-site snapshots.

    It does not fetch. The reading of the sites happens in the trusted
    orchestrator (:func:`observe_sites`) because the confined worker cannot
    resolve a hostname at all, and what crosses into the worker is a list of
    GUIDs — data, not a capability. `sites` and `fetcher` are still accepted so
    existing callers and the registry builder need no change; `sites` seeds the
    default observation list for a caller that has none.
    """
    work_ns = work_namespace(domain)
    sites = list(sites or [])
    lay = layout or Layout.default()  # active target's placement map (B1)
    work_dir = lay.dir("work_ttl")

    def _run(fileops, observations=None, dest_dir=work_dir, data_dir=work_dir):
        index = build_sot_index(fileops, data_dir)
        known = set(index)
        obs = observations if observations is not None else [
            {"site": s_, "declared": []} for s_ in sites
        ]
        runs = []
        for o in obs:
            site = str(o.get("site", "")).strip()
            if not site:
                continue
            # The GUIDs arrive from outside the worker, so they are checked for
            # shape here rather than trusted into a URI.
            declared = {g for g in o.get("declared") or [] if _GUID_RE.match(str(g))}
            # Only works the store HAS are asserted. Asserting workOnSite for a
            # guid we do not hold would mint a triple about a subject nobody can
            # resolve — a dangling reference of our own making, reported instead.
            present = sorted(declared & known)
            res = fileops.write_text(
                f"{dest_dir.rstrip('/')}/workonsite_{_slug(site)}.ttl",
                workonsite_ttl(site, present, work_ns),
                make_parents=True,
            )
            runs.append({
                "site": site,
                "ttl": res.path,
                # Alphabetical BY LABEL for the report — the reader is
                # checking "is my work here", and GUID order answers a question
                # nobody asked. The TTL keeps its GUID ordering: that snapshot
                # is diffed run against run, and ordering it by a field the user
                # can edit would show a reshuffle as a change.
                "declared": sorted(
                    ({"guid": g, "label": index[g]} for g in present),
                    key=lambda d: (d["label"].lower(), d["guid"]),
                ),
                "unknown": sorted(declared - known),
            })
        return {"runs": runs, "sites": len(runs)}

    return [
        Tool(
            name="workflow.update_work_on_site",
            description=(
                "Stage per-site workOnSite TTL from observed work declarations. "
                "Does NOT fetch: the site read is a trusted-orchestrator effect "
                "(law 11), and the confined worker cannot resolve a hostname."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "observations": {
                        "type": "array",
                        "description": "Per-site observations: {site, declared:[guid]}.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "site": {"type": "string", "description": "Site URL."},
                                "declared": {
                                    "type": "array",
                                    "description": "Work GUIDs the site names.",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": ["site"],
                            "additionalProperties": False,
                        },
                    },
                    "dest_dir": {"type": "string", "description": "Where to stage per-site TTL.", "default": work_dir},
                    "data_dir": {"type": "string", "description": "QA content dir for the label index.", "default": work_dir},
                },
                "required": [],
                "additionalProperties": False,
            },
            handler=_run,
        )
    ]
