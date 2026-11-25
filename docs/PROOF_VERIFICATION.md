# PROOF_VERIFICATION.md — how to prove a file existed on a date, without OriginStamp

**Written 2026-10-31, and written for a reader who has none of today's context.** It assumes OriginStamp may no longer exist, that nobody remaining remembers how these records were made, and that the reader has only the RDF, the file, and a public Bitcoin node. Every value below is real and the worked example at the end was verified on the date above.

## 1. What a proof record claims, and what it does not

A `vad:ProofEvent` record claims exactly one thing: **these exact bytes existed no later than this block's time.** Nothing else. It does not say who made the file, that the work is original, or that anyone owned it. Those are different claims needing different evidence.

The claim is worth something because it cannot be back-dated. Changing it would mean rewriting Bitcoin's history from that block forward, against the accumulated work of the whole network.

## 2. The four values, and what each is for

A complete record carries these (`ttl/proof/<guid>.ttl`):

```turtle
work:5dd11a56-3b25-44d5-bb2a-d0ff7d2863fd
    a vad:ProofEvent ;
    vad:asset       <http://visualartsdna.org/images/TensionT5Clash.jpg> ;
    vad:assetOf     work:e776711b-7b0a-4835-88bc-16c2cfa0179b ;
    vad:blockchain  "Bitcoin" ;
    vad:dataHash    "0xfb0b5307d925e290b5a87a68edb0c0102a29b8d3cb98acca98c4318cc66a5812" ;
    vad:rootHash    "0x19228b83533509d9e037cb442be4ee057622a7c3bce978832498b96a19b6273b" ;
    vad:transaction "0xeb8b605c2d324e63ff88ea2beca0e434da556787e39d6d5575d9652c199c8d71" ;
    vad:timestamp   "2026-02-04T19:12:03-05"^^xs:dateTime ;
    schema:startDate "2026-02-04"^^xs:date .
```

- **`vad:dataHash`** — the SHA-256 of the file's bytes, `0x`-prefixed. This is the number that was actually submitted; the file itself never left the machine. **It is the authoritative hash.** A `vad:sha256` property existed on older records, recomputed locally as a check, and it was WRONG on three of the ten records where both were present — so if you meet one, distrust it and prefer `dataHash`.
- **`vad:rootHash`** — the root of a Merkle tree over a whole *batch* of submissions, most of them other people's. This is the number written into the blockchain.
- **`vad:transaction`** — the Bitcoin transaction that carries the root hash, in an `OP_RETURN` output.
- **`vad:timestamp`** — when the transaction was broadcast, in US Eastern local time **with its offset**, as the service reported it. `schema:startDate` is its date part, read in that same offset. **Read the local date, never the UTC date:** `xsd:date` cannot carry a zone, so a UTC reading would silently assert a convention nothing states. For most of these records the UTC date is the *following* day, because the service broadcast just after midnight UTC.

**The missing piece is the Merkle path**, and §4 is about getting it.

## 3. Verifying, in five steps

Nothing here needs OriginStamp, or any paid service, or this project's code.

**Step 1 — hash the file.** `sha256sum TensionT5Clash.jpg`. It must equal `vad:dataHash` without the `0x`. If it does not, the file has changed since it was submitted and the proof is about different bytes. (This has happened: `PassionT3.jpg` recorded a hash matching no existing file, 2026-10-30.)

**Step 2 — get the Merkle path** (§4). A list of sibling hashes, one per level, each marked left or right.

**Step 3 — climb from the leaf to the root.** Start with `dataHash`. At each level combine with the sibling, in the order the path gives, until you have one value. The combining rule is in §5 and you will get a wrong answer without it. The result must equal `vad:rootHash`.

**Step 4 — find the transaction.** Look up `vad:transaction` on any Bitcoin block explorer, or query a node directly:
`bitcoin-cli getrawtransaction <txid> true`. Read its `OP_RETURN` output and confirm it contains `vad:rootHash`. Read which block the transaction is in, and that block's time.

**Step 5 — read the conclusion.** The block's time is the latest moment the file can have come into existence, because the root could not have been computed without the file's hash, and the root is in a block mined at that time. `vad:timestamp` should agree with the block time; the block is the authority if they differ.

## 4. Where the Merkle path comes from — and why it cannot be derived

**Two different Merkle trees are involved and confusing them wastes days.**

**Bitcoin's block tree** has *transactions* as leaves and its root in the block header. Public, reconstructible from the block. It proves a transaction is in a block — step 4.

**OriginStamp's batch tree** has *submitted hashes* as leaves — yours beside strangers' — and its root is `vad:rootHash`. **Only the root ever reaches the blockchain.** The tree was built privately from one batch, so the siblings you need are other customers' hashes. No amount of blockchain archaeology recovers them.

Tested on 2026-10-31 across all ten batches in this collection: **the root was derivable from the project's own hashes in zero of them**, including batches where only one of the project's files was present. The verified example's tree was 11 levels deep — up to 2,048 leaves — so the project's submissions were always a tiny minority.

So the path must be obtained while the service exists, and stored:
- the **certificate PDF** OriginStamp issues per submission, named by the leaf hash (`originstamp-certificate-<dataHash>.pdf`), contains the path as JSON;
- their **API** delivers it too, but only by webhook to a public HTTPS address, so the dashboard reads the certificate instead.

**If no path was stored and the service is gone, that record cannot be completed.** What survives is weaker but not nothing: the file still hashes to `dataHash`, and the transaction still proves *that root* was committed at that time. What is lost is the link between them.

**One consolation: the path requires no trust.** A wrong or tampered path simply fails to produce the root. You cannot hold a forged path that passes, and a transcription error announces itself immediately. So extracting it by hand from a PDF is safe — if it verifies, it is right.

## 5. The combining rule — the one thing nobody can guess

```
parent = sha256( ASCII(lowercase hex of left) + ASCII(lowercase hex of right) )
```

**It hashes the 64-character hex STRINGS, concatenated, not the 32 raw bytes.** Bitcoin's own tree does the opposite — raw bytes, hashed twice — so a reader who assumes the familiar construction gets nonsense and may conclude the proof is invalid. Verified against all eleven levels of the worked example.

Three more rules the example shows:

- **Order matters.** Left then right, as the path states. Swapping them gives a different hash.
- **An odd level duplicates its last node**, so `left == right` at some levels. This is normal padding, not corruption. It occurs at depths 1, 2 and 4 below.
- **Lowercase hex, no `0x` prefix,** when hashing. The `0x` in the RDF is presentation; strip it.

In Python, with no dependencies:

```python
import hashlib
def combine(left_hex, right_hex):
    return hashlib.sha256((left_hex + right_hex).encode()).hexdigest()
```

## 6. A worked example, verified 2026-10-31

File `TensionT5Clash.jpg`, record `work:5dd11a56-3b25-44d5-bb2a-d0ff7d2863fd`, proving the work `work:e776711b` existed by 4 February 2026.

Leaf, from `sha256sum` and equal to `vad:dataHash`:

```
fb0b5307d925e290b5a87a68edb0c0102a29b8d3cb98acca98c4318cc66a5812
```

Climbing, one line per level. "with left" means the sibling goes first in the concatenation.

| depth | sibling | side | result |
|---|---|---|---|
| 10 | `fad4c150045c6d39…` | left | `73e44cf943b0691e…` |
| 9 | `ce39e9cd98c82734…` | left | `57b7531258949466…` |
| 8 | `c395c6b6d2d19e0c…` | right | `1be0bce1ffe003fe…` |
| 7 | `8d5f52cd908a6180…` | right | `68d99471246406c5…` |
| 6 | `40199daec622704b…` | right | `7f29b55a293c8856…` |
| 5 | `90017ac544d3cb7a…` | left | `9f0fa79b752f64db…` |
| 4 | `9f0fa79b752f64db…` | right | `ee74813e169d3038…` ← the duplicated level |
| 3 | `c7609d76dbde85b8…` | left | `ed2291a82c8ebd23…` |
| 2 | `ed2291a82c8ebd23…` | right | `ee5eed6fd37084e9…` ← duplicated |
| 1 | `ee5eed6fd37084e9…` | right | `5a40e1c1b9f1d771…` ← duplicated |
| 0 | `258322bc01b9ad29…` | left | `19228b83533509d9…` |

Final value:

```
19228b83533509d9e037cb442be4ee057622a7c3bce978832498b96a19b6273b
```

which is `vad:rootHash` exactly. Then look up transaction
`0xeb8b605c2d324e63ff88ea2beca0e434da556787e39d6d5575d9652c199c8d71`,
confirm its `OP_RETURN` carries that root, and read the block's time.

**Conclusion: those bytes existed before that block was mined.** The record says 2026-02-04T19:12:03−05:00, which is 2026-02-05 00:12:03 UTC.

## 7. If something does not verify

- **File hash ≠ `dataHash`** → the file changed after submission. The proof is about the earlier bytes. Look for an older copy; the `.qa/attic` keeps replaced binaries by SHA-256.
- **Path does not reach `rootHash`** → wrong combining rule (§5), wrong order, or a transcription error. Re-read §5 before suspecting the data.
- **`OP_RETURN` does not contain `rootHash`** → wrong transaction, or the record borrowed a sibling record's values. This has happened: `UnmooredSwing.jpg` carried its companion `.glb`'s transaction and root for a proof that was never created (2026-10-30).
- **`vad:timestamp` disagrees with the block time** → the block is authoritative. The timestamps in this collection were transcribed by hand from a 12-hour clock and every one of them was twelve hours early until corrected on 2026-10-31; three also carried an impossible or wrong UTC offset.
- **Two records share a transaction but disagree on the instant** → one is mis-transcribed. **Records sharing a transaction must share a root hash and a timestamp**, because they were anchored by the same event. That invariant found two errors in this collection.
