"""Reading real OriginStamp certificates.

**Opt-in, like `tests/live_gcs`.** These need actual certificates, which are
the artist's own documents and far too large to commit (2.5 MB each for 17 KB
of fact). Point `CWVA_PROOF_CERTS` at a directory of them to run.

The extractor is the disposable half of the workflow -- an API adapter
replaces it -- so its tests being opt-in is the right trade. The gates it feeds
are tested unconditionally in `test_validate.py`.
"""

import os
import pathlib

import pytest

from cwva_dashboard.proof.certificate import read_certificate
from cwva_dashboard.proof.merkle import pack, unpack, verify

CERTS = os.environ.get("CWVA_PROOF_CERTS", "/mnt/c/stage/tmp/proof")
_files = sorted(pathlib.Path(CERTS).glob("*.pdf")) if pathlib.Path(CERTS).is_dir() else []

pytestmark = pytest.mark.skipif(
    not _files, reason=f"no certificates in {CERTS}; set CWVA_PROOF_CERTS")


@pytest.mark.parametrize("pdf", _files, ids=lambda p: p.name[22:34])
def test_a_real_certificate_yields_a_path_that_verifies(pdf):
    """The whole point. Everything else here is diagnosis."""
    c = read_certificate(pdf.read_bytes())
    assert verify(c.data_hash, c.path, c.root_hash)


@pytest.mark.parametrize("pdf", _files, ids=lambda p: p.name[22:34])
def test_every_field_the_record_needs_is_present(pdf):
    c = read_certificate(pdf.read_bytes())
    assert len(c.data_hash) == 64 and len(c.root_hash) == 64 and len(c.transaction) == 64
    assert c.blockchain, "the 'Bitcoin Certificate' heading names the chain"
    assert c.when is not None


@pytest.mark.parametrize("pdf", _files, ids=lambda p: p.name[22:34])
def test_the_filename_agrees_with_the_data_hash(pdf):
    """OriginStamp names the file after the leaf. The pipeline keys on the
    CONTENT, not the name -- `normalize_filename` collapses names at ingest
    and a vendor's convention is not ours to depend on -- but when both are
    available they must agree."""
    if "certificate-" in pdf.name:
        assert pdf.name.split("certificate-")[1][:64] == c_hash(pdf)


def c_hash(pdf):
    return read_certificate(pdf.read_bytes()).data_hash


@pytest.mark.parametrize("pdf", _files, ids=lambda p: p.name[22:34])
def test_the_packed_path_round_trips(pdf):
    c = read_certificate(pdf.read_bytes())
    assert unpack(pack(c.path)) == c.path


@pytest.mark.parametrize("pdf", _files, ids=lambda p: p.name[22:34])
def test_the_SEARCH_route_finds_the_same_path_as_the_JSON(pdf):
    """Route B is the robustness layer: it ignores structure entirely, so a
    layout or format change degrades the scraper instead of corrupting it.
    Where both routes work they must agree."""
    from cwva_dashboard.proof.merkle import reconstruct
    c = read_certificate(pdf.read_bytes())
    found = reconstruct(c.data_hash, c.root_hash, c.hashes)
    assert found is not None, "the hash bag alone should be enough"
    assert verify(c.data_hash, found, c.root_hash)


def test_a_file_that_is_not_a_certificate_raises():
    from cwva_dashboard.proof.certificate import CertificateError
    with pytest.raises(CertificateError):
        read_certificate(b"%PDF-1.7\nnot really\n")
