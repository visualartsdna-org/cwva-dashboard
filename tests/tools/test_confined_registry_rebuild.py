"""The registry rebuild, run where it actually runs: inside the confined worker.

Building the registry reads things — the ontology, the profiles, the shapes that
validate them — and it happens **in the Landlock-confined worker** on every
reload. The worker may read the sandbox, `sys.prefix` and `/usr`, and nothing
else. Anything the rebuild reaches for in the project tree fails with EACCES and
takes the rebuild with it.

Twice now that has reached Rick as a server error, in two different disguises:

  * 2026-09-16, a deferred IMPORT — `edit_tools` reaching for `property_map`
    inside a handler. Guarded since by a scan of deferred first-party imports.
  * 2026-09-17, a deferred FILE READ — `profiles.shapes_graph()` opening
    `config/shapes/artist_profile.ttl`, which no import scan can see. It
    surfaced on saving an artist, because creating a bootstrap record rebuilds
    the registry on purpose.

The scan cannot catch the second kind, and neither can any fixture that passes
`enforce_landlock=False` — which is every UX fixture in this suite. So this test
does the one thing that catches both: it really confines a worker and really
rebuilds.
"""

from __future__ import annotations

import pytest

from cwva_dashboard.sandbox.broker import landlock_abi
from cwva_dashboard.sandbox.worker import WorkerClient
from cwva_dashboard.tools.fileops_tools import build_default_registry

from conftest import TEST_DOMAIN

pytestmark = pytest.mark.skipif(landlock_abi() < 1,
                                reason="Landlock unavailable on this kernel")

PROFILE = """@prefix vad:    <http://visualartsdna.org/model/> .
@prefix ops:    <http://visualartsdna.org/operations/> .
@prefix work:   <http://visualartsdna.org/work/> .
@prefix schema: <https://schema.org/> .
@prefix skos:   <http://www.w3.org/2004/02/skos/core#> .
@prefix rdfs:   <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

work:artist-1 a vad:Painter ; rdfs:label "A Painter" ; vad:brand "example.art" .

work:prof-1 a vad:ArtistProfile ;
    vad:artist work:artist-1 ;
    rdfs:label "A profile" ;
    vad:measurementSystem [ a skos:Concept ; schema:unitCode "INH" ] ;
    ops:template [
        ops:templateType vad:Watercolor ;
        ops:field [ ops:property rdf:type   ; ops:order 1 ; ops:required true ] ;
        ops:field [ ops:property rdfs:label ; ops:order 2 ; ops:required true ] ;
    ] .
"""


@pytest.fixture
def make_worker(tmp_path):
    """Build a confined worker over a sandbox holding one profile.

    `warm` decides whether the shapes are parsed BEFORE the fork, which is the
    whole question: a child inherits the parent's memory at fork time, so
    warming afterwards reaches nobody. Getting that wrong is how the first
    version of this test passed for the wrong reason.
    """
    from cwva_dashboard import profiles as profiles_mod

    data = tmp_path / "ttl" / "data"
    data.mkdir(parents=True)
    (data / "p.ttl").write_text(PROFILE)
    workers = []

    def build(warm: bool):
        profiles_mod._SHAPES_CACHE.clear()
        if warm:
            profiles_mod.warm_shapes()

        def rebuild():
            return build_default_registry(
                domain=TEST_DOMAIN,
                profiles=profiles_mod.load_from_dir(data)[0],
                artists=profiles_mod.load_artists_from_dir(data),
            )

        w = WorkerClient(str(tmp_path), build_default_registry(domain=TEST_DOMAIN),
                         enforce_landlock=True, rebuild=rebuild)
        workers.append(w)
        return w

    try:
        yield build
    finally:
        for w in workers:
            w.close()
        profiles_mod._SHAPES_CACHE.clear()


def test_the_worker_can_rebuild_a_registry_that_reads_PROFILES(make_worker):
    """The whole point. A reload that fails is a dashboard that 500s on the next
    thing the user does — and reloads happen on purpose: creating an artist or a
    profile rebuilds so the new card appears."""
    out = make_worker(warm=True).reload()

    assert out["ok"], out.get("error")
    assert any(t.startswith("record.new.") for t in out["tools"]), (
        "the profile in the sandbox produced its tool"
    )


def test_a_COLD_SHAPES_CACHE_is_what_broke_it(make_worker):
    """Named so the fix cannot be quietly undone. Forked without the shapes in
    memory, the child reaches into the project tree for them and is refused —
    which is the error Rick saw on saving an artist."""
    out = make_worker(warm=False).reload()

    assert not out["ok"]
    assert "Permission denied" in str(out.get("error"))
    assert "artist_profile.ttl" in str(out.get("error"))


def test_warming_AFTER_the_fork_reaches_nobody(make_worker):
    """The property that makes `warm_shapes()` a startup step rather than a
    lazy one: a child's memory is a copy taken at fork time."""
    from cwva_dashboard import profiles as profiles_mod

    worker = make_worker(warm=False)
    profiles_mod.warm_shapes()          # parent only, and too late

    assert not worker.reload()["ok"]
