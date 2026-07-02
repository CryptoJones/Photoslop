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


def levels_lut(in_black: int, in_white: int, gamma: float,
               out_black: int = 0, out_white: int = 255) -> np.ndarray:
    """Classic Levels mapping as a single 256-entry LUT (same for R/G/B)."""
    x = np.arange(256, dtype=np.float64)
    span = max(in_white - in_black, 1)
    x = np.clip((x - in_black) / span, 0.0, 1.0)
    x = x ** (1.0 / max(gamma, 0.01))
    out = out_black + x * (out_white - out_black)
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def apply_luts(img: QImage, luts: np.ndarray) -> None:
    """Apply (3, 256) per-channel LUTs in place, premultiplication-aware and
    processed in row bands (same frugality contract as apply_settings)."""
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

        r = luts[0][r].astype(np.uint16)
        g = luts[1][g].astype(np.uint16)
        b = luts[2][b].astype(np.uint16)

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


def curve_lut(points: list[tuple[float, float]]) -> np.ndarray:
    """(256,) uint8 LUT through control points (x, y in 0..255) using a
    monotone cubic (Fritsch–Carlson): no overshoot, no oscillation."""
    pts = sorted((float(x), float(y)) for x, y in points)
    if len(pts) == 1:
        return np.full(256, np.clip(round(pts[0][1]), 0, 255), dtype=np.uint8)
    xs = np.array([p[0] for p in pts])
    ys = np.array([p[1] for p in pts])
    h = np.diff(xs)
    h[h == 0] = 1e-6
    delta = np.diff(ys) / h
    m = np.empty(len(xs))
    m[0], m[-1] = delta[0], delta[-1]
    if len(xs) > 2:
        inner = np.zeros(len(xs) - 2)
        same_sign = delta[:-1] * delta[1:] > 0
        with np.errstate(divide="ignore", invalid="ignore"):
            harmonic = 2.0 / (1.0 / np.where(delta[:-1] == 0, 1, delta[:-1])
                              + 1.0 / np.where(delta[1:] == 0, 1, delta[1:]))
        inner[same_sign] = harmonic[same_sign]
        m[1:-1] = inner

    x = np.arange(256, dtype=np.float64)
    seg = np.clip(np.searchsorted(xs, x, side="right") - 1, 0, len(xs) - 2)
    t = (x - xs[seg]) / h[seg]
    t = np.clip(t, 0.0, 1.0)
    h00 = (1 + 2 * t) * (1 - t) ** 2
    h10 = t * (1 - t) ** 2
    h01 = t * t * (3 - 2 * t)
    h11 = t * t * (t - 1)
    y = (h00 * ys[seg] + h10 * h[seg] * m[seg]
         + h01 * ys[seg + 1] + h11 * h[seg] * m[seg + 1])
    y[x <= xs[0]] = ys[0]
    y[x >= xs[-1]] = ys[-1]
    y = np.clip(y, 0.0, 255.0)
    y = np.maximum.accumulate(y) if ys[-1] >= ys[0] else y
    return np.round(y).astype(np.uint8)


def curves_luts(channel_points: dict) -> np.ndarray:
    """(3, 256) LUTs from per-channel curve points. The "rgb" master curve
    applies first, then each channel's own curve composes on top."""
    identity = [(0.0, 0.0), (255.0, 255.0)]
    master = curve_lut(channel_points.get("rgb", identity))
    luts = np.empty((3, 256), dtype=np.uint8)
    for i, key in enumerate(("r", "g", "b")):
        own = curve_lut(channel_points.get(key, identity))
        luts[i] = own[master]
    return luts


def color_balance_luts(values: dict[str, tuple[float, float, float]]) -> np.ndarray:
    """(3, 256) LUTs for Photoshop-style Color Balance.

    `values` maps band name ("shadows"/"midtones"/"highlights") to a
    (cyan-red, magenta-green, yellow-blue) triple in [-100, 100]; positive
    pushes toward red/green/blue respectively. Band weights are smooth bumps
    over the tonal range, so the three bands blend into one monotone-ish LUT
    per channel.
    """
    x = np.linspace(0.0, 1.0, 256)
    weights = {
        "shadows": np.clip(1.0 - x / 0.5, 0.0, 1.0) ** 1.5,
        "midtones": np.clip(1.0 - np.abs(x - 0.5) / 0.5, 0.0, 1.0) ** 1.5,
        "highlights": np.clip((x - 0.5) / 0.5, 0.0, 1.0) ** 1.5,
    }
    luts = np.empty((3, 256), dtype=np.uint8)
    for channel in range(3):
        v = x.copy()
        for band, weight in weights.items():
            amount = values.get(band, (0.0, 0.0, 0.0))[channel]
            v = v + 0.3 * (amount / 100.0) * weight
        v = np.clip(v, 0.0, 1.0)
        v = np.maximum.accumulate(v)
        luts[channel] = np.round(v * 255.0).astype(np.uint8)
    return luts


def apply_hsl(img: QImage, hue_deg: float, saturation: float,
              lightness: float) -> None:
    """Hue rotation (luminance-preserving RGB matrix), saturation mix toward
    luma, and lightness toward black/white — in place, in row bands."""
    if hue_deg == 0 and saturation == 0 and lightness == 0:
        return
    theta = np.deg2rad(hue_deg)
    cos_a, sin_a = np.cos(theta), np.sin(theta)
    # standard luminance-preserving hue-rotate matrix (as used by SVG/CSS)
    lr, lg, lb = 0.213, 0.715, 0.072
    m = np.array([
        [lr + cos_a * (1 - lr) + sin_a * (-lr),
         lg + cos_a * (-lg) + sin_a * (-lg),
         lb + cos_a * (-lb) + sin_a * (1 - lb)],
        [lr + cos_a * (-lr) + sin_a * 0.143,
         lg + cos_a * (1 - lg) + sin_a * 0.140,
         lb + cos_a * (-lb) + sin_a * (-0.283)],
        [lr + cos_a * (-lr) + sin_a * (-(1 - lr)),
         lg + cos_a * (-lg) + sin_a * lg,
         lb + cos_a * (1 - lb) + sin_a * lb],
    ], dtype=np.float32)
    sat_factor = 1.0 + saturation / 100.0

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

        rf = r.astype(np.float32)
        gf = g.astype(np.float32)
        bf = b.astype(np.float32)
        if hue_deg != 0:
            rf, gf, bf = (m[0, 0] * rf + m[0, 1] * gf + m[0, 2] * bf,
                          m[1, 0] * rf + m[1, 1] * gf + m[1, 2] * bf,
                          m[2, 0] * rf + m[2, 1] * gf + m[2, 2] * bf)
        if saturation != 0:
            luma = 0.299 * rf + 0.587 * gf + 0.114 * bf
            rf = luma + (rf - luma) * sat_factor
            gf = luma + (gf - luma) * sat_factor
            bf = luma + (bf - luma) * sat_factor
        if lightness > 0:
            k = lightness / 100.0
            rf = rf + (255.0 - rf) * k
            gf = gf + (255.0 - gf) * k
            bf = bf + (255.0 - bf) * k
        elif lightness < 0:
            k = 1.0 + lightness / 100.0
            rf, gf, bf = rf * k, gf * k, bf * k

        r = (np.clip(rf, 0, 255) + 0.5).astype(np.uint16)
        g = (np.clip(gf, 0, 255) + 0.5).astype(np.uint16)
        b = (np.clip(bf, 0, 255) + 0.5).astype(np.uint16)

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
