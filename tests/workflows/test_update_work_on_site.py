"""updateWorkOnSite (CE_DESIGN §7.2): a site DECLARES which works it publishes.

The fixtures below mirror the real pages rather than an idealised site, because
the idealised version is what the first rebuild was written against and it found
nothing. Measured 2026-09-09 against visualartsdna.org and art.visualartsdna.org:

- `/sitemap.xml` 404s on both, so sitemap-based discovery yields zero pages;
- OpenGraph is site-level — `og:title` is the site name — so there is nothing
  per-work to read;
- but the pages carry 97 and 25 explicit links to `visualartsdna.org/work/<guid>`
  (the "Catalog entry" links), in three different spellings.

So identity is read from those declarations and never inferred. There is no
confidence score in these tests because there is nothing to be unsure about.
"""

from __future__ import annotations

import pytest
from rdflib import Graph, Namespace, URIRef

from cwva_dashboard.sandbox.fileops import FileOps
from cwva_dashboard.sandbox.paths import Sandbox
from cwva_dashboard.tools.registry import ToolRegistry
from cwva_dashboard.workflows.update_work_on_site import (
    build_scrape_tools,
    observe_sites,
    extract_malformed_refs,
    extract_work_refs,
    malformed_ref_pattern,
    same_origin_links,
    work_ref_pattern,
    workonsite_ttl,
)

VAD = Namespace("http://visualartsdna.org/model/")
WORK = Namespace("http://visualartsdna.org/work/")
SITE = "https://test.art"
DOMAIN = "http://visualartsdna.org"

G1 = "321ad3da-4069-4f8d-8514-4094f0aa1862"   # catalog link
G2 = "a523dac9-82b6-4551-98f9-13f4f47f2c55"   # catalog link AND a viewer link
G3 = "ea5bb047-b21f-4b19-92a9-3cb8dd70c5df"   # ONLY a viewer link -> not a claim
G4 = "1b79e09d-1111-2222-3333-444455556666"   # only a bare CURIE in text
GONE = "0e5bef85-8839-41ca-b6c5-a855c7eb1ffe"  # catalog link, absent from the store
BROKEN = "e776711b-7b0a-4835-88bc-16c2cfa0179b"  # catalog link with a stray tab

# Shaped after the real pages, including the malformation found on the first
# narrowed run: a `%09` (tab) pasted into the middle of a catalog URL.
HOME = f"""<html><head>
<meta property="og:title" content="RS Art">
</head><body>
<a href="/gallery">Watercolors</a>
<a href="https://www.visualartsdna.org/work/{G1}">Catalog entry</a>
<a href="https://visualartsdna.org/work/{G2}">Catalog entry</a>
<a href="http://visualartsdna.org/modelviewer?work=work:{G2}">See the complete work in 3D</a>
<a href="http://visualartsdna.org/modelviewer?work=work:{G3}">See the complete work in 3D</a>
<p>Linked data for this work: work:{G4}</p>
<a href="https://visualartsdna.org/work/%09{BROKEN}">Catalog entry</a>
<a href="https://elsewhere.example/work/{GONE}">a work on someone else's site</a>
<a href="mailto:someone@example.com">contact</a>
</body></html>"""

GALLERY = f"""<html><body>
<a href="https://visualartsdna.org/work/{GONE}">Catalog entry</a>
<a href="/">home</a>
</body></html>"""


class FakeFetcher:
    """No network in tests; the effect stays explicit and injectable."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str) -> bytes:
        self.asked.append(url)
        try:
            return self.pages[url].encode()
        except KeyError:
            raise OSError(f"404 {url}")


@pytest.fixture
def env(tmp_path):
    sb = Sandbox.open(tmp_path / "stage", create=True)
    ops = FileOps(sb)
    ops.write_text(
        "content/ttl/data/works.ttl",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "@prefix work: <http://visualartsdna.org/work/> .\n"
        f'work:{G1} rdfs:label "Spirited Tree" .\n'
        f'work:{G2} rdfs:label "Last Supper" .\n'
        f'work:{G3} rdfs:label "Unmoored Swing" .\n'
        f'work:{BROKEN} rdfs:label "Broken Link Work" .\n',
        make_parents=True,
    )
    return sb, ops


def _tool(sites=(SITE,)):
    return build_scrape_tools(list(sites), DOMAIN)[0]


def _run(ops, fetcher, sites=(SITE,)):
    """Observe (trusted side), then stage (confined tool) — the real split.

    The fetch cannot happen inside the worker: Landlock confines it to the
    sandbox, and glibc's resolver needs /etc/resolv.conf to turn a hostname into
    an address. So `observe_sites` runs in the orchestrator and only a list of
    GUIDs crosses into the tool.
    """
    observed = observe_sites(list(sites), fetcher, work_ref_pattern(DOMAIN))
    result = _tool(sites).handler(
        ops,
        observations=[{"site": r.site, "declared": sorted(r.declared)} for r in observed],
    )
    # The report merges what the trusted pass saw, exactly as the route does.
    for run, seen in zip(result["runs"], observed):
        run["pages"] = seen.pages
        run["errors"] = seen.errors
    return result


def _default_pages():
    return {SITE: HOME, f"{SITE}/gallery": GALLERY}


# -- the declaration --------------------------------------------------------


def test_only_the_catalog_link_counts():
    """Narrowed 2026-09-09. The catalog URI is the claim "this site publishes
    this work"; the other two forms said something else and were dropped."""
    got = extract_work_refs(HOME, work_ref_pattern(DOMAIN))
    assert got == {G1, G2}


def test_a_viewer_link_is_an_invocation_not_a_claim():
    """`?work=work:<guid>` opens the 3D viewer. It says a visitor can look at
    the work, not that this site catalogues it — and it carried no host
    requirement, so a third-party page embedding the viewer counted as ours."""
    assert G3 not in extract_work_refs(HOME, work_ref_pattern(DOMAIN))


def test_a_bare_CURIE_in_text_is_not_a_declaration():
    """A convention nobody follows, invented on the assumption a site might list
    identifiers instead of linking them. Matching a namespace prefix loose in
    the page body is a lot of surface for a case that does not exist."""
    assert G4 not in extract_work_refs(HOME, work_ref_pattern(DOMAIN))


def test_a_work_link_on_ANOTHER_host_is_not_ours():
    """`elsewhere.example/work/<guid>` is a different deployer's namespace. The
    pattern derives from THIS deployer's work namespace for exactly this."""
    assert GONE not in extract_work_refs(HOME, work_ref_pattern(DOMAIN))


def test_the_pattern_derives_from_the_WORK_NAMESPACE():
    """A work's canonical URI is its subject URI. Deriving the pattern from
    `work_namespace` rather than re-assembling `<domain>/work/` means the two
    cannot disagree about what a work URI looks like."""
    from cwva_dashboard.tools.record_tools import work_namespace

    other = "https://debbiesdomain.art"
    pat = work_ref_pattern(other)
    assert extract_work_refs(f'<a href="{work_namespace(other)}{G1}">x</a>', pat) == {G1}
    assert extract_work_refs(f'<a href="https://visualartsdna.org/work/{G1}">x</a>', pat) == set()


def test_a_separate_SERVING_host_is_also_accepted():
    """Config carries `domain` (what the data says) and `host` (where the server
    answers); they are equal once DNS is set. A site links to wherever a reader
    can actually reach the entry."""
    pat = work_ref_pattern(DOMAIN, host="https://catalog.example.org")
    assert extract_work_refs(f'<a href="https://catalog.example.org/work/{G1}">x</a>', pat) == {G1}
    assert extract_work_refs(f'<a href="https://visualartsdna.org/work/{G1}">x</a>', pat) == {G1}


def test_a_malformed_catalog_link_is_reported_not_swallowed():
    """Found on the real site: `…/work/%09<guid>` — a tab pasted into the URL.
    It will not resolve for a visitor either. The loose pattern had been hiding
    it by matching the same work's viewer link instead."""
    pairs = extract_malformed_refs(HOME, malformed_ref_pattern(DOMAIN))
    assert (r"%09", BROKEN) in pairs


def test_a_WELL_FORMED_link_is_not_reported_as_malformed():
    pairs = extract_malformed_refs(HOME, malformed_ref_pattern(DOMAIN))
    assert BROKEN in {g for _j, g in pairs}
    assert G1 not in {g for _j, g in pairs}


def test_page_discovery_follows_same_site_links_only():
    """No sitemap: both real sites 404 that path and keep the catalogue behind a
    couple of internal links."""
    links = same_origin_links(HOME, SITE)
    assert links == [f"{SITE}/gallery"]  # off-site and mailto excluded


# -- the run ----------------------------------------------------------------


def test_declared_works_are_asserted_with_their_labels(env):
    _sb, ops = env
    run = _run(ops, FakeFetcher(_default_pages()))["runs"][0]

    assert {d["guid"] for d in run["declared"]} == {G1, G2}
    assert {d["label"] for d in run["declared"]} == {"Spirited Tree", "Last Supper"}


def test_a_work_the_STORE_does_not_have_is_reported_never_asserted(env):
    """Not an error — the site may publish something this QA tree has not synced,
    or something withdrawn. But asserting workOnSite for a guid we do not hold
    would mint a triple about a subject nobody can resolve: a dangling reference
    of our own making. The real sites have 6 and 1 of these."""
    _sb, ops = env
    res = _run(ops, FakeFetcher(_default_pages()))
    run = res["runs"][0]

    assert run["unknown"] == [GONE]
    assert GONE not in {d["guid"] for d in run["declared"]}
    ttl = Graph().parse(data=_ttl_of(ops, run), format="turtle")
    assert (WORK[GONE], VAD.workOnSite, None) not in ttl


def _ttl_of(ops, run):
    return ops.read_text(run["ttl"])


def test_a_site_that_declares_nothing_yields_nothing(env):
    """Correct rather than empty: silence from the site is an answer."""
    _sb, ops = env
    run = _run(ops, FakeFetcher({SITE: "<html><body>no links here</body></html>"}))["runs"][0]

    assert run["declared"] == [] and run["unknown"] == []
    ttl = Graph().parse(data=_ttl_of(ops, run), format="turtle")
    assert list(ttl.subject_objects(VAD.workOnSite)) == []


def test_an_unreachable_site_REPORTS_why(env):
    """Silence is not an answer here. The first real run produced two empty
    snapshots and no reason, and the reason mattered — DNS does not work inside
    the sandbox."""
    _sb, ops = env
    res = _run(ops, FakeFetcher({}))

    assert res["runs"][0]["declared"] == []
    assert res["runs"][0]["pages"] == []
    assert res["runs"][0]["errors"], "an unreadable site must say so"


def test_one_dead_page_does_not_lose_the_rest(env):
    """A link to a page that 404s must not discard what the home page declared."""
    _sb, ops = env
    pages = {SITE: HOME}  # /gallery missing
    run = _run(ops, FakeFetcher(pages))["runs"][0]

    assert {d["guid"] for d in run["declared"]} == {G1, G2}


def test_no_image_is_ever_fetched(env):
    """The previous design downloaded every page image to hash it. Identity is
    declared now, so that traffic — against someone else's site — has no
    question left to answer."""
    _sb, ops = env
    f = FakeFetcher(_default_pages())
    _run(ops, f)

    assert all(not u.endswith((".jpg", ".png")) for u in f.asked), f.asked


# -- the TTL ----------------------------------------------------------------


def test_tool_registered(env):
    _sb, _ops = env
    reg = ToolRegistry()
    for t in build_scrape_tools([SITE], DOMAIN):
        reg.register(t)
    assert "workflow.update_work_on_site" in reg.names()


def test_the_tool_itself_never_fetches(env):
    """It stages what it is TOLD was observed. The site read is a
    trusted-orchestrator effect because the confined worker cannot resolve a
    hostname — an IP-literal fetch from it succeeds, a named-host fetch fails
    with EAI_AGAIN (measured 2026-09-09)."""
    _sb, ops = env
    f = FakeFetcher(_default_pages())
    _tool().handler(ops, observations=[{"site": SITE, "declared": [G1]}])

    assert f.asked == [], "the tool must not go to the network"


def test_a_malformed_guid_from_outside_is_ignored(env):
    """The observation list is built outside the worker, so its contents are
    checked for shape here rather than trusted straight into a URI."""
    _sb, ops = env
    res = _tool().handler(
        ops,
        observations=[{"site": SITE, "declared": ["not-a-guid", "../../etc/passwd", G1]}],
    )

    assert [d["guid"] for d in res["runs"][0]["declared"]] == [G1]


def test_per_site_ttl_has_workonsite_and_provenance(env):
    _sb, ops = env
    run = _run(ops, FakeFetcher(_default_pages()))["runs"][0]
    g = Graph().parse(data=_ttl_of(ops, run), format="turtle")

    assert (WORK[G1], VAD.workOnSite, URIRef(SITE)) in g
    prov = Namespace("http://www.w3.org/ns/prov#")
    assert (URIRef(SITE), prov.wasAttributedTo, None) in g


def test_full_snapshot_ttl_is_deterministic():
    """No run timestamp — that would defeat idempotency, and re-running would
    show a diff every time."""
    a = workonsite_ttl(SITE, [G1, G2], WORK)
    b = workonsite_ttl(SITE, [G2, G1], WORK)
    assert a == b


def test_a_vanished_work_is_a_removal_next_run(env):
    """The snapshot is regenerated whole, so a work taken off the site is an
    absence in the next TTL — the takedown signal."""
    _sb, ops = env
    first = _run(ops, FakeFetcher(_default_pages()))["runs"][0]
    assert WORK[G1] in Graph().parse(data=_ttl_of(ops, first), format="turtle").subjects()

    stripped = HOME.replace(f'<a href="https://www.visualartsdna.org/work/{G1}">Catalog entry</a>', "")
    second = _run(ops, FakeFetcher({SITE: stripped, f"{SITE}/gallery": GALLERY}))["runs"][0]

    g = Graph().parse(data=_ttl_of(ops, second), format="turtle")
    assert WORK[G1] not in set(g.subjects())
    assert WORK[G2] in set(g.subjects())


def test_each_site_gets_its_own_snapshot(env):
    _sb, ops = env
    other = "https://second.art"
    f = FakeFetcher({SITE: HOME, f"{SITE}/gallery": GALLERY, other: GALLERY})
    res = _run(ops, f, sites=(SITE, other))

    assert res["sites"] == 2
    assert {r["ttl"] for r in res["runs"]} == {
        "content/ttl/data/workonsite_test_art.ttl",
        "content/ttl/data/workonsite_second_art.ttl",
    }


def test_the_report_lists_works_alphabetically_by_label(env):
    """The reader is checking "is my work here". GUID order answers a question
    nobody asked."""
    _sb, ops = env
    run = _run(ops, FakeFetcher(_default_pages()))["runs"][0]

    labels = [d["label"] for d in run["declared"]]
    assert labels == sorted(labels, key=str.lower)
    assert labels == ["Last Supper", "Spirited Tree"]  # not GUID order (G1 < G2)


def test_the_TTL_keeps_its_GUID_ordering(env):
    """The snapshot is diffed run against run, so it is ordered by a field the
    user cannot edit. Sorting it by label would show a retitle as a reshuffle."""
    _sb, ops = env
    run = _run(ops, FakeFetcher(_default_pages()))["runs"][0]
    subjects = [
        line.split()[0] for line in _ttl_of(ops, run).splitlines()
        if line.startswith("work:")
    ]

    assert subjects == sorted(subjects)
