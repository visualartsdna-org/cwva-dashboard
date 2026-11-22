"""Perceptual image hashing (CE_DESIGN §7.2 matching).

dHash (difference hash) over Pillow — no extra dependency. Robust to scaling and
mild recompression, which is what site branding/thumbnailing does to a SOT
original. A scraped site image is matched to a SOT work by small Hamming
distance between their dHashes.

(dHash is the perceptual-hash slot; it can be swapped for DCT pHash later without
changing the interface.)
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

__all__ = ["dhash", "hamming", "similar"]


def dhash(data: bytes, *, size: int = 8) -> str:
    """Difference hash of image bytes as a hex string (``size*size`` bits)."""
    img = Image.open(BytesIO(data)).convert("L").resize((size + 1, size))
    px = img.load()
    bits = 0
    for y in range(size):
        for x in range(size):
            bits = (bits << 1) | (1 if px[x, y] > px[x + 1, y] else 0)
    return format(bits, "0{}x".format(size * size // 4))


def hamming(a: str, b: str) -> int:
    """Bit distance between two hex hashes."""
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def similar(a: str, b: str, *, max_distance: int = 10) -> bool:
    return hamming(a, b) <= max_distance
