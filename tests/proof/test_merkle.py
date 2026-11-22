"""The Merkle arithmetic, and the packed literal it is stored in.

Values are from a real OriginStamp certificate for TensionT5Clash.jpg,
verified against the blockchain on 2026-10-31 (`PROOF_VERIFICATION.md` §6).
"""

import pytest

from cwva_dashboard.proof.merkle import (
    PackedPathError, Step, combine, fold, pack, reconstruct, unpack, verify,
)

LEAF = "fb0b5307d925e290b5a87a68edb0c0102a29b8d3cb98acca98c4318cc66a5812"
ROOT = "19228b83533509d9e037cb442be4ee057622a7c3bce978832498b96a19b6273b"
PATH = [
    Step("L", "fad4c150045c6d39fb49962872bfa2445ef2255318203430f53af840d9342774"),
    Step("L", "ce39e9cd98c82734e9a18ca1da775a985aae86ad8f6eb53f9ca790d94805a05a"),
    Step("R", "c395c6b6d2d19e0c62de13a5ba3e31f4f7b3be516feec6b26b7920ea44064fb6"),
    Step("R", "8d5f52cd908a61806882207615b610864259dc86a1614a10a940b72f11a325b2"),
    Step("R", "40199daec622704bb612c1dad5aeaf6a5e67bf694ee5a6879c09a97ec600c4a8"),
    Step("L", "90017ac544d3cb7af0485c13ba461fa7baa910919008968ec2463703ce495c89"),
    Step("R", "9f0fa79b752f64db2b45bd9cbd01652f2c7c287291dea7cf8ab9f2c907159fcc"),
    Step("L", "c7609d76dbde85b8fbdd39aa300e878192a540e1dab05b42bec3839ab170091e"),
    Step("R", "ed2291a82c8ebd2339b17fd1356c3187e94bb9049029d0f4e1aa34675b81f5a1"),
    Step("R", "ee5eed6fd37084e9c1304b827c20b120e154dd842b1c12f41d5cd0b83985416a"),
    Step("L", "258322bc01b9ad29acded38749f18ea78c8a67df3e33847748cb9a4560fcc668"),
]


def test_the_real_path_reaches_the_real_root():
    assert fold(LEAF, PATH) == ROOT
    assert verify(LEAF, PATH, ROOT)


def test_the_rule_is_ASCII_HEX_not_raw_bytes():
    """The one thing nobody can guess. Bitcoin's own tree hashes the raw
    digests twice; OriginStamp hashes the hex STRINGS once. A reader who
    assumes the familiar construction concludes a sound proof is invalid."""
    import hashlib
    l, r = PATH[0].sibling, LEAF
    assert combine(l, r) == hashlib.sha256((l + r).encode()).hexdigest()
    raw = hashlib.sha256(bytes.fromhex(l) + bytes.fromhex(r)).hexdigest()
    assert combine(l, r) != raw


def test_side_says_which_operand_the_SIBLING_is():
    """Both readings are plausible and only one works, so it is asserted."""
    assert combine("aa" * 32, LEAF) == fold(LEAF, [Step("L", "aa" * 32)])
    assert combine(LEAF, "aa" * 32) == fold(LEAF, [Step("R", "aa" * 32)])


def test_a_single_wrong_sibling_breaks_it():
    broken = list(PATH)
    broken[5] = Step("L", "00" * 32)
    assert not verify(LEAF, broken, ROOT)


def test_a_wrong_SIDE_breaks_it_too():
    broken = list(PATH)
    broken[0] = Step("R", PATH[0].sibling)
    assert not verify(LEAF, broken, ROOT)


def test_the_0x_prefix_is_tolerated_everywhere():
    """The RDF carries `0x`-prefixed values because OriginStamp reports them
    that way; the prefix must never reach the hash function."""
    assert verify("0x" + LEAF, PATH, "0x" + ROOT)


def test_packed_round_trip():
    assert unpack(pack(PATH)) == PATH


def test_the_packed_form_is_leaf_first_and_readable():
    p = pack(PATH)
    assert p.startswith("L:fad4c150")
    assert p.endswith("258322bc01b9ad29acded38749f18ea78c8a67df3e33847748cb9a4560fcc668")
    assert len(p.split()) == 11
    assert '"' not in p and "\\" not in p, "must need no escaping in a Turtle literal"


@pytest.mark.parametrize("bad", ["", "X:" + "aa" * 32, "L:" + "aa" * 31, "L" + "aa" * 32,
                                 "L:" + "AA" * 32])
def test_a_malformed_packed_path_RAISES_rather_than_failing_quietly(bad):
    """Unreadable is a defect in the record; wrong is a defect in the
    evidence. They must not be the same answer."""
    with pytest.raises(PackedPathError):
        unpack(bad)


def test_reconstruct_finds_the_path_from_a_BAG_of_hashes():
    """The robust extraction route: no structure, no order, no layout."""
    bag = {LEAF, ROOT} | {s.sibling for s in PATH}
    cur = LEAF
    for s in PATH:                       # every intermediate must be in the bag
        cur = fold(cur, [s])
        bag.add(cur)
    found = reconstruct(LEAF, ROOT, bag)
    assert found is not None and verify(LEAF, found, ROOT)


def test_reconstruct_returns_None_when_the_bag_is_short():
    assert reconstruct(LEAF, ROOT, {LEAF, ROOT}) is None
