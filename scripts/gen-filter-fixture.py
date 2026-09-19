# SPDX-License-Identifier: Apache-2.0
"""Regenerate the iOS filter parity fixture from the desktop filter library.

The Swift ports in ``ipados/Photoslop/Filters*.swift`` (#327) claim identity
with the built-in filters in ``photoslop.filters`` — Sepia, Pixelate, Denoise,
Retro Console, Pixel Sort, Datamosh + Chromatic Aberration and Film Negative —
not mere similarity. This script is the proof: it builds small synthetic
``QImage`` inputs, runs each *desktop* filter over them at two or three
parameter sets, and writes the before/after pixels as a Swift source file that
``FilterParityTests`` compares against word for word.

Pixels are written as the ``view_u32`` values — little-endian ``ARGB32``
premultiplied — which is exactly the word a ``PixelBuffer`` exposes on iOS.
Every input carries partial and zero alpha so the unpremultiply/re-premultiply
dance is exercised, and sizes are deliberately not multiples of the block or
pixel sizes so the edge handling (Qt's nearest-neighbour ``scaled``, the
datamosh clamp) is covered.

Run from the repository root::

    QT_QPA_PLATFORM=offscreen uv run python scripts/gen-filter-fixture.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from photoslop import adjust, filters, npimage

OUT = Path(__file__).resolve().parent.parent / "ipados/PhotoslopTests/Fixtures/FilterFixture.swift"


def premultiply(a: np.ndarray, r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pack straight 0-255 channels as premultiplied ARGB32 words
    (``c * a // 255``, the desktop's ``premultiplied_u32``)."""
    a = a.astype(np.uint32)
    pr = (r.astype(np.uint32) * a) // 255
    pg = (g.astype(np.uint32) * a) // 255
    pb = (b.astype(np.uint32) * a) // 255
    return (a << 24) | (pr << 16) | (pg << 8) | pb


def make_image(words: np.ndarray) -> QImage:
    h, w = words.shape
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    npimage.view_u32(img)[...] = words
    return img


def gradient_input(w: int, h: int, seed: int) -> np.ndarray:
    """A colour gradient with speckle noise, a half-alpha column, a
    quarter-alpha row and one fully transparent pixel."""
    rng = np.random.default_rng(seed)
    ys, xs = np.mgrid[0:h, 0:w]
    r = (xs * 255 // max(1, w - 1)).astype(np.int64)
    g = (ys * 255 // max(1, h - 1)).astype(np.int64)
    b = ((xs + ys) * 255 // max(1, w + h - 2)).astype(np.int64)
    noise = rng.integers(-40, 41, size=(3, h, w))
    r = np.clip(r + noise[0], 0, 255)
    g = np.clip(g + noise[1], 0, 255)
    b = np.clip(b + noise[2], 0, 255)
    a = np.full((h, w), 255, dtype=np.int64)
    a[:, w - 2] = 128
    a[1, :] = 64
    a[0, 0] = 0
    return premultiply(a, r, g, b)


def negative_input(w: int, h: int) -> np.ndarray:
    """A scanned colour negative: an orange base with a dark subject band,
    so auto mode picks colour, plus a half-alpha column."""
    ys, xs = np.mgrid[0:h, 0:w]
    r = 200 - xs * 6 - (ys % 3) * 4
    g = 120 - ys * 4 - (xs % 2) * 3
    b = 60 + xs * 3
    r[3:7, 4:12] -= 90
    g[3:7, 4:12] -= 50
    b[3:7, 4:12] -= 20
    a = np.full((h, w), 255, dtype=np.int64)
    a[:, 2] = 128
    a[9, 5] = 0
    return premultiply(a, np.clip(r, 0, 255), np.clip(g, 0, 255), np.clip(b, 0, 255))


def mono_negative_input(w: int, h: int) -> np.ndarray:
    """A greyscale negative (near-zero chroma) so auto mode picks mono."""
    ys, xs = np.mgrid[0:h, 0:w]
    v = np.clip(220 - xs * 9 - ys * 5, 0, 255)
    r = np.clip(v + (xs % 2), 0, 255)
    a = np.full((h, w), 255, dtype=np.int64)
    a[4, :] = 96
    return premultiply(a, r, v, v)


# (name, width, height, builder)
INPUTS = [
    ("gradient16", 16, 12, lambda: gradient_input(16, 12, seed=327)),
    ("gradient22", 22, 18, lambda: gradient_input(22, 18, seed=3271)),
    ("negative16", 16, 12, lambda: negative_input(16, 12)),
    ("mono16", 16, 12, lambda: mono_negative_input(16, 12)),
]

# (filter name, case name, input name, params, what the case proves)
CASES = [
    (
        "beam-dither",
        "beam",
        "gradient16",
        {"algorithm": "beam", "scale": 1, "beam_pitch": 6, "beam_amplitude": 1.5},
        "beam modulation: the raster is deflected and its shoulders stippled",
    ),
    (
        "beam-dither",
        "beam-straight",
        "gradient22",
        {"algorithm": "beam", "scale": 3, "beam_amplitude": 0.0, "beam_pitch": 5},
        "no displacement: pure scanlines, and a cell size that is not a divisor",
    ),
    (
        "beam-dither",
        "floyd",
        "gradient16",
        {"algorithm": "floyd-steinberg", "scale": 1},
        "serpentine error diffusion over the whole plane",
    ),
    (
        "beam-dither",
        "atkinson-4",
        "gradient22",
        {"algorithm": "atkinson", "scale": 2, "levels": 4},
        "the 6/8 kernel at four tones, where the thirds are not exact in float32",
    ),
    (
        "beam-dither",
        "bayer8",
        "gradient16",
        {"algorithm": "bayer-8", "scale": 1, "levels": 3},
        "ordered dithering between adjacent tones",
    ),
    (
        "beam-dither",
        "tonal",
        "gradient16",
        {
            "algorithm": "floyd-steinberg",
            "scale": 1,
            "mode": "tonal",
            "background": "#000000",
            "shadows": "#0B3C5D",
            "midtones": "#6CCFF6",
            "highlights": "#FFFFFF",
        },
        "tri-tone inking, chosen by the original luminance under each pixel",
    ),
    (
        "beam-dither",
        "colour",
        "gradient22",
        {"algorithm": "floyd-steinberg", "scale": 2, "mode": "color"},
        "each channel dithered on its own",
    ),
    ("sepia", "default", "gradient16", {"amount": 80}, "the default 80% tone"),
    ("sepia", "full", "gradient16", {"amount": 100}, "a full tone, where the R clamp bites"),
    ("sepia", "off", "gradient16", {"amount": 0}, "amount 0 leaves every word alone"),
    ("pixelate", "size2", "gradient16", {"size": 2}, "an even divisor"),
    ("pixelate", "size3", "gradient16", {"size": 3}, "16 and 12 are not multiples of 3"),
    ("pixelate", "size5", "gradient22", {"size": 5}, "a >2x shrink on an odd-shaped canvas"),
    ("denoise", "radius1", "gradient16", {"strength": 10}, "radius 1"),
    (
        "denoise",
        "radius4",
        "gradient16",
        {"strength": 40},
        "the default, radius 4: the pad exceeds half the height",
    ),
    (
        "denoise",
        "radius10",
        "gradient22",
        {"strength": 100},
        "radius 10 on a canvas the pad dwarfs",
    ),
    (
        "retro-console",
        "default",
        "gradient16",
        {"size": 6, "levels": 4, "dither": 1},
        "the defaults: 6-px blocks, 4 levels, dithered",
    ),
    (
        "retro-console",
        "size1nodither",
        "gradient16",
        {"size": 1, "levels": 2, "dither": 0},
        "no shrink, a 1-bit crush, no dither",
    ),
    (
        "retro-console",
        "size3levels8",
        "gradient22",
        {"size": 3, "levels": 8, "dither": 1},
        "an odd block size with the finest crush",
    ),
    (
        "pixel-sort",
        "rows",
        "gradient16",
        {"low": 60, "high": 200, "vertical": 0, "reverse": 0},
        "the default band along rows",
    ),
    (
        "pixel-sort",
        "columnsReverse",
        "gradient16",
        {"low": 0, "high": 255, "vertical": 1, "reverse": 1},
        "the full band down columns, bright first",
    ),
    (
        "pixel-sort",
        "backwardsBand",
        "gradient22",
        {"low": 220, "high": 40, "vertical": 0, "reverse": 1},
        "a band given backwards is still a band",
    ),
    (
        "datamosh",
        "default",
        "gradient22",
        {"block": 4, "amount": 35, "drift": 12, "aberration": 3.0, "seed": 7},
        "the default mosh at 4-px blocks with the fringe",
    ),
    (
        "datamosh",
        "moshOnly",
        "gradient22",
        {"block": 8, "amount": 100, "drift": 3, "aberration": 0.0, "seed": 42},
        "every block fresh, partial edge blocks, no fringe",
    ),
    (
        "datamosh",
        "fringeOnly",
        "gradient22",
        {"block": 4, "amount": 0, "drift": 12, "aberration": 5.0, "seed": 1},
        "amount 0 skips the mosh; the fringe alone",
    ),
    (
        "datamosh",
        "smallBlocksHighDrift",
        "gradient16",
        {"block": 4, "amount": 60, "drift": 40, "aberration": 1.5, "seed": 9999},
        "drift larger than the canvas clamps to its edge",
    ),
    (
        "film-negative",
        "auto",
        "negative16",
        {"mode": "auto", "clip": 0.5},
        "auto detects the orange mask and develops in colour",
    ),
    (
        "film-negative",
        "autoMono",
        "mono16",
        {"mode": "auto", "clip": 0.5},
        "auto detects a greyscale scan and develops mono",
    ),
    (
        "film-negative",
        "monoClipped",
        "negative16",
        {"mode": "mono", "clip": 2.0},
        "mono forced on a colour scan with a wide clip",
    ),
    (
        "film-negative",
        "colourNoClip",
        "negative16",
        {"mode": "color", "clip": 0.0},
        "colour with nothing clipped",
    ),
    (
        "invert",
        "default",
        "gradient16",
        {},
        "255 - c on a gradient that carries a transparent pixel, a half-alpha"
        " column and a quarter-alpha row — the un-premultiply and re-premultiply"
        " path the desktop LUTs take",
    ),
    (
        "invert",
        "wide",
        "gradient22",
        {},
        "the same alpha traps on a 22x18 canvas, exercising a band boundary",
    ),
]


def words(arr: np.ndarray) -> str:
    rows = []
    for y in range(arr.shape[0]):
        rows.append("      " + ", ".join(f"0x{int(v):08X}" for v in arr[y]) + ",")
    return "\n".join(rows)


def swift_params(params: dict, cls=None) -> str:
    kinds = {spec.key: spec.type for spec in (cls.params if cls else ())}
    parts = []
    for key, value in params.items():
        if isinstance(value, str):
            case = "string" if kinds.get(key) == "str" else "choice"
            parts.append(f'"{key}": .{case}("{value}")')
        elif isinstance(value, float):
            parts.append(f'"{key}": .float({value!r})')
        else:
            parts.append(f'"{key}": .int({int(value)})')
    if not parts:
        return "[:]"
    return "[" + ", ".join(parts) + "]"


def main() -> int:
    registry = filters.available_filters()
    inputs = {name: (w, h, build()) for name, w, h, build in INPUTS}
    out = [
        "// SPDX-License-Identifier: Apache-2.0",
        "// GENERATED by scripts/gen-filter-fixture.py from the desktop",
        "// photoslop.filters built-ins — do not edit by hand. Regenerate with:",
        "//   QT_QPA_PLATFORM=offscreen uv run python scripts/gen-filter-fixture.py",
        "",
        "@testable import PhotoslopIPad",
        "",
        "/// Desktop-produced expected pixels for the iOS filter ports (#327). Words",
        "/// are little-endian ARGB32 premultiplied, i.e. `PixelBuffer.words`. Each",
        "/// case names its input image and the parameters it was run with.",
        "enum FilterFixture {",
        "  struct Image {",
        "    let width: Int",
        "    let height: Int",
        "    let words: [UInt32]",
        "  }",
        "",
        "  struct Case {",
        "    let filter: String",
        "    let name: String",
        "    let input: String",
        "    let params: FilterParams",
        "    let expected: [UInt32]",
        "  }",
        "",
        "  static let inputs: [String: Image] = [",
    ]
    for name, (w, h, arr) in inputs.items():
        out += [f'    "{name}": Image(width: {w}, height: {h}, words: [', words(arr), "    ]),"]
    out += ["  ]", "", "  static let cases: [Case] = ["]
    for filter_name, case_name, input_name, params, doc in CASES:
        _w, _h, arr = inputs[input_name]
        img = make_image(arr.copy())
        if filter_name == "invert":
            # Invert is an adjustment (desktop Image ▸ Adjustments ▸ Invert and
            # `--invert`), not a filter-registry plugin: `examples/invert-filter`
            # already reserves the `invert` name with different maths. So drive
            # Invert through its real desktop code path — the reverse-ramp LUTs in
            # `apply_luts` — and let the port below match those words, not a
            # reconstruction of them (#389).
            cls = None
            adjust.apply_luts(img, adjust.invert_luts())
        else:
            cls = registry[filter_name]
            cls().apply(img, dict(params))
        result = npimage.view_u32(img).copy()
        expect_change = filter_name != "sepia" or params["amount"] != 0
        if expect_change and np.array_equal(result, arr):
            print(f"case {filter_name}/{case_name} changed nothing", file=sys.stderr)
            return 1
        out += [
            f"    // {doc}",
            f'    Case(filter: "{filter_name}", name: "{case_name}", input: "{input_name}",',
            f"      params: {swift_params(params, cls)},",
            "      expected: [",
            words(result),
            "    ]),",
        ]
    out += ["  ]", "}", ""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
