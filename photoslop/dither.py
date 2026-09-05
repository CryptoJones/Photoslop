# SPDX-License-Identifier: Apache-2.0
"""Dither and beam-modulation rendering: the engine behind the Beam Dither
filter (#384).

Nothing here touches Qt. The filter hands in a luminance plane as float 0..1
and gets back either a quantised plane or a boolean beam mask, which keeps
every algorithm testable as arithmetic rather than as pixels on a canvas.

Two families live here and they are genuinely different ideas:

**Error diffusion and ordered dithering** answer "which pixels do I turn on so
that a coarse palette still averages out to the original tone". Error
diffusion pushes each pixel's rounding error into neighbours it has not
visited yet; ordered dithering compares against a fixed threshold matrix and
has no memory at all.

**Beam modulation** answers a different question. It does not try to preserve
average tone — it draws a raster of horizontal beams and lets the picture
*deflect* them, the way the vertical deflection coil of a CRT is driven by a
signal. Bright pixels push their beam off its resting line and widen it, so
the image appears as bending, thickening scanlines rather than as a cloud of
dots. That is why it reads as engraved or oscilloscopic instead of as noise.
"""

from __future__ import annotations

import numpy as np

# (dx, dy, weight) triples and their divisor, as the literature writes them:
# the current pixel is X, dx runs right, dy runs down.
#
#   Floyd-Steinberg        Atkinson            Stucki
#         X 7                  X 1 1             X 8 4
#     3 5 1  /16           1 1 1        /8   2 4 8 4 2
#                            1                1 2 4 2 1  /42
#
# Atkinson deliberately diffuses only 6/8 of the error, which throws away
# contrast and is exactly why classic Macintosh dithers look crisp and a
# little blown out rather than flat.
ERROR_KERNELS: dict[str, tuple[tuple[tuple[int, int, int], ...], int]] = {
    "floyd-steinberg": (((1, 0, 7), (-1, 1, 3), (0, 1, 5), (1, 1, 1)), 16),
    "atkinson": (((1, 0, 1), (2, 0, 1), (-1, 1, 1), (0, 1, 1), (1, 1, 1), (0, 2, 1)), 8),
    "jarvis": (
        (
            (1, 0, 7),
            (2, 0, 5),
            (-2, 1, 3),
            (-1, 1, 5),
            (0, 1, 7),
            (1, 1, 5),
            (2, 1, 3),
            (-2, 2, 1),
            (-1, 2, 3),
            (0, 2, 5),
            (1, 2, 3),
            (2, 2, 1),
        ),
        48,
    ),
    "stucki": (
        (
            (1, 0, 8),
            (2, 0, 4),
            (-2, 1, 2),
            (-1, 1, 4),
            (0, 1, 8),
            (1, 1, 4),
            (2, 1, 2),
            (-2, 2, 1),
            (-1, 2, 2),
            (0, 2, 4),
            (1, 2, 2),
            (2, 2, 1),
        ),
        42,
    ),
    "sierra": (
        (
            (1, 0, 5),
            (2, 0, 3),
            (-2, 1, 2),
            (-1, 1, 4),
            (0, 1, 5),
            (1, 1, 4),
            (2, 1, 2),
            (-1, 2, 2),
            (0, 2, 3),
            (1, 2, 2),
        ),
        32,
    ),
    "burkes": (
        ((1, 0, 8), (2, 0, 4), (-2, 1, 2), (-1, 1, 4), (0, 1, 8), (1, 1, 4), (2, 1, 2)),
        32,
    ),
}


def bayer_matrix(size: int) -> np.ndarray:
    """The recursive Bayer threshold matrix, normalised to 0..1 exclusive.

    Built by the standard doubling recurrence rather than typed out, so 2, 4,
    8 and 16 all come from one rule:

        M(2n) = [[4M(n),     4M(n)+2],
                 [4M(n)+3,   4M(n)+1]]
    """
    if size < 2 or size & (size - 1):
        raise ValueError("bayer matrix size must be a power of two >= 2")
    matrix = np.array([[0, 2], [3, 1]], dtype=np.float64)
    while matrix.shape[0] < size:
        matrix = np.block(
            [
                [4 * matrix, 4 * matrix + 2],
                [4 * matrix + 3, 4 * matrix + 1],
            ]
        )
    return (matrix + 0.5) / matrix.size


def quantise(value: np.ndarray, levels: int) -> np.ndarray:
    """Snap 0..1 values onto ``levels`` evenly spaced tones."""
    steps = max(2, int(levels)) - 1
    return np.clip(np.rint(value * steps) / steps, 0.0, 1.0)


def error_diffuse(lum: np.ndarray, kernel: str, levels: int = 2) -> np.ndarray:
    """Serpentine error diffusion, returning the quantised plane.

    Serpentine (alternate rows run right-to-left) because a fixed scan
    direction lets the residual error drift the same way on every row and
    prints as diagonal worming; reversing every other row cancels it.

    The loop is Python over row lists rather than numpy scalar indexing. That
    reads like a step backwards and is not: the dependency is inherently
    sequential — a pixel cannot be quantised until its left neighbour has
    pushed error into it — and numpy scalar access costs more per element than
    the float arithmetic it would be wrapping. The `scale` control on the
    filter is what keeps the pixel count sane; this is O(pixels x kernel).
    """
    offsets, divisor = ERROR_KERNELS[kernel]
    height, width = lum.shape
    if height == 0 or width == 0:
        return lum.copy()
    steps = max(2, int(levels)) - 1

    rows = [row.tolist() for row in lum.astype(np.float64)]
    out = np.empty((height, width), dtype=np.float32)
    for y in range(height):
        row = rows[y]
        rightwards = y % 2 == 0
        order = range(width) if rightwards else range(width - 1, -1, -1)
        sign = 1 if rightwards else -1
        out_row = out[y]
        for x in order:
            old = row[x]
            new = round(old * steps) / steps
            new = 0.0 if new < 0.0 else 1.0 if new > 1.0 else new
            out_row[x] = new
            error = old - new
            if error == 0.0:
                continue
            for dx, dy, weight in offsets:
                ny = y + dy
                if ny >= height:
                    continue
                nx = x + dx * sign
                if 0 <= nx < width:
                    rows[ny][nx] += error * weight / divisor
    return out


def ordered_dither(lum: np.ndarray, size: int, levels: int = 2) -> np.ndarray:
    """Bayer ordered dithering — fully vectorised, and stable under animation
    because the threshold depends on position alone, never on neighbours."""
    matrix = bayer_matrix(size)
    height, width = lum.shape
    tile = np.tile(
        matrix,
        ((height + size - 1) // size, (width + size - 1) // size),
    )[:height, :width]
    steps = max(2, int(levels)) - 1
    # The threshold is applied inside one quantisation step, so the pattern
    # dithers *between* adjacent tones rather than only between black and white.
    nudged = lum * steps + (tile - 0.5)
    return np.clip(np.rint(nudged) / steps, 0.0, 1.0)


def threshold(lum: np.ndarray, levels: int = 2) -> np.ndarray:
    """No dithering at all: straight posterisation, the honest baseline the
    other modes are worth comparing against."""
    return quantise(lum, levels)


def beam_mask(lum: np.ndarray, pitch: int, amplitude: float, bend: float = 1.0) -> np.ndarray:
    """Beam modulation: a raster of horizontal beams deflected by the picture.

    A CRT draws by sweeping a beam along a line while the signal drives its
    deflection and its intensity. This does both, per pixel:

    * **Deflection.** The beam's phase is advanced by ``amplitude * lum``, so a
      bright region pushes its beam off the resting line. Because neighbouring
      columns see different luminance, the line *bends* around whatever is in
      the picture, and it is that bending — not the dot pattern — that makes
      the result read as engraved contour rather than as halftone.
    * **Intensity.** How much of each beam's width lights up is taken from the
      same luminance, so beams thicken into solid white in highlights and thin
      to broken dashes in shadow.

    Returns a float plane in 0..1: the beam's coverage at each pixel, which the
    caller can threshold or tone-map.
    """
    height, width = lum.shape
    pitch = max(2, int(pitch))
    rows = np.arange(height, dtype=np.float32).reshape(-1, 1)
    # Phase along the vertical raster, advanced by the signal. `bend` lets the
    # deflection be dialled out entirely (straight scanlines) without losing
    # the intensity modulation.
    phase = rows / pitch + float(amplitude) * bend * lum
    # cos gives a smooth beam profile centred on the line: 1 at the core,
    # 0 at the gap between beams. A square wave here would alias into stair
    # steps the moment the beam bends.
    profile = 0.5 + 0.5 * np.cos(2.0 * np.pi * phase)
    # Coverage: luminance sets how much of the beam's width survives, as a
    # threshold on the profile rather than a scaling of it. Written the other
    # way round — scaling the profile by luminance — a full-white region only
    # ever reaches the beam's own average and highlights never close up into
    # solid white, which is the whole top end of the tonal range missing.
    #
    #   lum 0 -> threshold 1, nothing but the exact crest survives
    #   lum 1 -> threshold 0, the entire beam lights and the gaps close
    #
    # `edge` is the width of the soft shoulder, in profile units. A hard
    # comparison here would alias into stair steps along every bent beam.
    edge = 0.12
    # The threshold is stretched to run from 1 down to -edge rather than to 0.
    # Stopping at 0 leaves the gap between beams permanently unlit — the beam
    # profile dips to 0 there, so it never clears a zero threshold by the full
    # shoulder width — and pure white then renders as 83% coverage with the
    # raster still showing through. Highlights have to be able to close up.
    level = (1.0 - lum) * (1.0 + edge) - edge
    return np.clip((profile - level) / edge, 0.0, 1.0)
