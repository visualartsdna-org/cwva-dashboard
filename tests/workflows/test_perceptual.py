"""Perceptual image hash (dHash) — stable under scaling, distinct across images."""

from __future__ import annotations

import math
from io import BytesIO

from PIL import Image

from cwva_dashboard.workflows.perceptual import dhash, hamming, similar


def _png(fn, size=(48, 48)):
    img = Image.new("L", size)
    px = img.load()
    for y in range(size[1]):
        for x in range(size[0]):
            px[x, y] = fn(x, y, size)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _wave(kx, ky, phase=0.0):
    # low-frequency 2D sinusoid: survives scaling, varies horizontally (so the
    # difference-hash bits are non-degenerate), distinct per (kx, ky, phase).
    return lambda x, y, s: int(
        127 + 120 * math.sin(kx * math.pi * x / s[0] + phase) * math.sin(ky * math.pi * y / s[1] + phase)
    )


def test_identical_images_zero_distance():
    b = _png(_wave(2, 2))
    assert hamming(dhash(b), dhash(b)) == 0


def test_scaled_image_is_similar():
    pattern = _wave(2, 2)
    big = _png(pattern, size=(96, 96))
    small = _png(pattern, size=(32, 32))
    assert similar(dhash(big), dhash(small))  # survives scaling


def test_different_images_are_dissimilar():
    assert not similar(dhash(_png(_wave(2, 2))), dhash(_png(_wave(5, 1))))


def test_hash_length_is_16_hex_for_size_8():
    assert len(dhash(_png(_wave(2, 2)))) == 16  # 64 bits
