# SPDX-License-Identifier: Apache-2.0
"""Lightroom-style Basic adjustments, memory-frugally.

Temperature/tint/exposure/contrast/highlights/shadows/whites/blacks all fold
into three 256-entry per-channel LUTs (no float buffers at all); vibrance and
saturation need cross-channel math, done in float32 — but the image is
processed in row bands, so transient memory stays bounded regardless of
layer size.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from photoslop.npimage import view_u32

CHUNK_ROWS = 256


class AdjustSettings:
    """All values are 0 at identity. Ranges: exposure in stops [-4, 4];
    everything else [-100, 100]."""

    FIELDS = (
        "temperature", "tint", "exposure", "contrast", "highlights",
        "shadows", "whites", "blacks", "vibrance", "saturation",
    )

    def __init__(self, **kwargs: float) -> None:
        for field in self.FIELDS:
            setattr(self, field, float(kwargs.get(field, 0.0)))

    def is_identity(self) -> bool:
        return all(getattr(self, field) == 0.0 for field in self.FIELDS)


def _smooth01(x: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def build_luts(s: AdjustSettings) -> np.ndarray:
    """(3, 256) uint8 LUTs for R, G, B — the full tone + white-balance chain."""
    x = np.linspace(0.0, 1.0, 256)
    gains = (
        1.0 + 0.0035 * s.temperature,  # R: warmer → up
        1.0 - 0.0035 * s.tint,  # G: positive tint → magenta → less green
        1.0 - 0.0035 * s.temperature,  # B: warmer → down
    )
    luts = np.empty((3, 256), dtype=np.uint8)
    for channel, gain in enumerate(gains):
        v = x * gain
        v = v * (2.0 ** s.exposure)
        k = np.tan(np.pi / 4.0 * (1.0 + 0.6 * s.contrast / 100.0))
        v = (v - 0.5) * k + 0.5
        v = v + 0.3 * (s.highlights / 100.0) * _smooth01((v - 0.35) / 0.65)
        v = v + 0.3 * (s.shadows / 100.0) * _smooth01((0.65 - v) / 0.65)
        v = v + 0.25 * (s.whites / 100.0) * np.clip(v, 0, 1) ** 2
        v = v + 0.25 * (s.blacks / 100.0) * (1.0 - np.clip(v, 0, 1)) ** 2
        v = np.clip(v, 0.0, 1.0)
        v = np.maximum.accumulate(v)  # guarantee a monotonic tone curve
        luts[channel] = np.round(v * 255.0).astype(np.uint8)
    return luts


def apply_settings(img: QImage, s: AdjustSettings) -> None:
    """Apply in place to a premultiplied ARGB32 QImage, in row bands."""
    if s.is_identity():
        return
    luts = build_luts(s)
    sat_factor = s.saturation / 100.0
    vib_factor = s.vibrance / 100.0
    needs_mix = sat_factor != 0.0 or vib_factor != 0.0

    arr = view_u32(img)
    height = arr.shape[0]
    for y0 in range(0, height, CHUNK_ROWS):
        chunk = arr[y0 : y0 + CHUNK_ROWS]
        a = (chunk >> np.uint32(24)).astype(np.uint16)
        r = ((chunk >> np.uint32(16)) & 0xFF).astype(np.uint16)
        g = ((chunk >> np.uint32(8)) & 0xFF).astype(np.uint16)
        b = (chunk & 0xFF).astype(np.uint16)

        opaque = bool((a == 255).all())
        if not opaque:
            safe_a = np.maximum(a, 1)
            r = np.minimum(255, r * 255 // safe_a)
            g = np.minimum(255, g * 255 // safe_a)
            b = np.minimum(255, b * 255 // safe_a)

        r = luts[0][r]
        g = luts[1][g]
        b = luts[2][b]

        if needs_mix:
            rf = r.astype(np.float32)
            gf = g.astype(np.float32)
            bf = b.astype(np.float32)
            luma = 0.299 * rf + 0.587 * gf + 0.114 * bf
            spread = (np.maximum(np.maximum(rf, gf), bf)
                      - np.minimum(np.minimum(rf, gf), bf)) / 255.0
            factor = 1.0 + sat_factor + vib_factor * (1.0 - spread)
            rf = np.clip(luma + (rf - luma) * factor, 0.0, 255.0)
            gf = np.clip(luma + (gf - luma) * factor, 0.0, 255.0)
            bf = np.clip(luma + (bf - luma) * factor, 0.0, 255.0)
            r = (rf + 0.5).astype(np.uint16)  # round, don't truncate
            g = (gf + 0.5).astype(np.uint16)
            b = (bf + 0.5).astype(np.uint16)
        else:
            r = r.astype(np.uint16)
            g = g.astype(np.uint16)
            b = b.astype(np.uint16)

        if not opaque:
            r = r * a // 255
            g = g * a // 255
            b = b * a // 255

        chunk[:] = (
            (a.astype(np.uint32) << np.uint32(24))
            | (r.astype(np.uint32) << np.uint32(16))
            | (g.astype(np.uint32) << np.uint32(8))
            | b.astype(np.uint32)
        )
