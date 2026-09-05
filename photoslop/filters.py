# SPDX-License-Identifier: Apache-2.0
"""Filter plugins — the entry-point-based filter framework (#109).

A filter is a class with a kebab-case ``name``, a menu ``label``, a
``params`` tuple of ParamSpec, and an ``apply(image, params)`` that edits
the QImage in place. Photoslop discovers filters from the
``photoslop.filters`` entry-point group (same pattern as model adapters),
plus the built-ins below; the Filter menu, the smart-filter replay, and
the CLI ``--filter`` op are all generated from the same registry, so a
pip-installed plugin shows up in all three with zero extra wiring.

Filters run through the selection-aware plumbing (``_run_filter`` in the
GUI, ``_filter_region`` in the CLI) — a plugin never needs to know about
selections, feathering, or undo. Buffers handed to ``apply`` are transient
per-layer copies (DD-001)."""

from __future__ import annotations

import math
import traceback
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from PySide6.QtGui import QImage

from photoslop import dither
from photoslop.adjust import CHUNK_ROWS
from photoslop.npimage import view_u32


class ParamSpec(NamedTuple):
    key: str
    label: str
    type: str  # "int" | "float" | "str" | "choice"
    minimum: float
    maximum: float
    default: float | str
    # "choice" only: the permitted values. The dialog renders a combo box and
    # the CLI validates membership, so a filter with a mode never has to encode
    # one as a magic integer in a spin box.
    choices: tuple[str, ...] = ()


class Filter:
    """Base filter. Subclasses set name/label/params and implement apply."""

    name = "abstract"
    label = "Abstract filter"
    params: tuple[ParamSpec, ...] = ()
    unsafe = False  # native processes and third-party code must opt in

    def apply(self, image: QImage, params: dict) -> None:
        raise NotImplementedError


class SepiaFilter(Filter):
    name = "sepia"
    label = "Sepia"
    params = (ParamSpec("amount", "Amount", "int", 0, 100, 80),)

    def apply(self, image: QImage, params: dict) -> None:
        k = float(params.get("amount", 80)) / 100.0
        arr = view_u32(image)
        a = (arr >> np.uint32(24)).astype(np.float32)
        r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
        g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
        b = (arr & 0xFF).astype(np.float32)
        luma = 0.299 * r + 0.587 * g + 0.114 * b
        # classic sepia tone, alpha-aware (buffers are premultiplied)
        scale = np.where(a > 0, a / 255.0, 0.0)
        sr = np.minimum(luma * 1.07, 255.0 * scale)
        sg = luma * 0.89
        sb = luma * 0.62
        r = r + (sr - r) * k
        g = g + (sg - g) * k
        b = b + (sb - b) * k
        arr[...] = (
            (a.astype(np.uint32) << np.uint32(24))
            | (np.clip(r, 0, 255).astype(np.uint32) << np.uint32(16))
            | (np.clip(g, 0, 255).astype(np.uint32) << np.uint32(8))
            | np.clip(b, 0, 255).astype(np.uint32)
        )


class PixelateFilter(Filter):
    name = "pixelate"
    label = "Pixelate"
    params = (ParamSpec("size", "Block size", "int", 2, 128, 8),)

    def apply(self, image: QImage, params: dict) -> None:
        size = max(2, int(params.get("size", 8)))
        w, h = image.width(), image.height()
        small = image.scaled(max(1, w // size), max(1, h // size))
        big = small.scaled(w, h)  # nearest-neighbour back up = blocks
        arr = view_u32(image)
        arr[...] = view_u32(big)


_REGISTRY: dict[str, type[Filter]] = {}
_BUILT_INS: tuple[type[Filter], ...] = (SepiaFilter, PixelateFilter)


@dataclass(frozen=True)
class PluginFailure:
    group: str
    name: str
    details: str


_PLUGIN_FAILURES: dict[tuple[str, str], PluginFailure] = {}


def register_filter(cls: type[Filter]) -> None:
    if not getattr(cls, "name", None) or cls.name == "abstract":
        raise ValueError("filter plugins need a unique kebab-case name")
    _REGISTRY[cls.name] = cls


def available_filters(*, allow_unsafe: bool = False) -> dict[str, type[Filter]]:
    """Return safe built-ins, plus explicitly enabled native/plugin filters."""
    # Imported here, not at module scope: nodemachine imports Filter/ParamSpec
    # from this module, so a top-level import either way is a cycle.
    from photoslop.nodemachine import NODE_MACHINE_FILTERS

    for cls in (*_BUILT_INS, *NODE_MACHINE_FILTERS):
        _REGISTRY.setdefault(cls.name, cls)
    if allow_unsafe:
        from photoslop import geglpack, gimpbridge, gmicpack

        gmicpack.register_all()
        geglpack.register_all()
        gimpbridge.register_all()
        from importlib.metadata import entry_points

        for ep in entry_points(group="photoslop.filters"):
            if ep.name in _REGISTRY:
                continue
            try:
                cls = ep.load()
                cls.unsafe = True
                register_filter(cls)
            except Exception:  # a broken plugin must not break the app
                key = ("photoslop.filters", ep.name)
                _PLUGIN_FAILURES[key] = PluginFailure(key[0], key[1], traceback.format_exc())
                continue
    return {
        name: cls
        for name, cls in _REGISTRY.items()
        if allow_unsafe or not getattr(cls, "unsafe", False)
    }


def plugin_failures() -> tuple[PluginFailure, ...]:
    return tuple(_PLUGIN_FAILURES.values())


def parse_params(cls: type[Filter], text: str) -> dict:
    """Parse and validate "key=val,..." against the filter's ParamSpecs.
    Shared by the CLI op and the tests; empty text means all defaults."""
    specs = {spec.key: spec for spec in cls.params}
    values = {spec.key: spec.default for spec in cls.params}
    if not text:
        return values
    if len(cls.params) == 1 and cls.params[0].type == "str":
        # single free-text param: everything after "key=" verbatim
        # (commas belong to the value, e.g. gmic:command=blur 3,1)
        key, sep, val = text.partition("=")
        if not sep or key.strip() != cls.params[0].key:
            raise ValueError(f"{cls.name}: expects {cls.params[0].key}=<text>")
        values[cls.params[0].key] = val
        return values
    for chunk in text.split(","):
        key, sep, num = chunk.partition("=")
        key = key.strip()
        if not sep or key not in specs:
            raise ValueError(
                f"{cls.name}: unknown parameter {key!r}; expects " + ", ".join(specs)
                if specs
                else f"{cls.name} takes no parameters"
            )
        spec = specs[key]
        if spec.type == "choice":
            value = num.strip()
            if value not in spec.choices:
                raise ValueError(f"{cls.name}: {key} must be one of " + ", ".join(spec.choices))
            values[key] = value
            continue
        if spec.type == "str":
            # A free-text value among several parameters, which is why it may
            # not contain a comma — that is the separator. The single-param
            # case above stays the escape hatch for values that need one.
            values[key] = num.strip()
            continue
        try:
            v = int(num) if spec.type == "int" else float(num)
        except ValueError as exc:
            raise ValueError(f"{cls.name}: {key}: {exc}") from exc
        if not spec.minimum <= v <= spec.maximum:
            raise ValueError(f"{cls.name}: {key} must be in {spec.minimum}..{spec.maximum}")
        values[key] = v
    return values


class DenoiseFilter(Filter):
    """Baseline chroma denoise (#112): luma is preserved exactly; the
    chroma planes get a strength-scaled separable blur — the classic
    fast fix for color speckle noise. Local, dependency-free. For
    heavyweight AI denoising use the model adapter route instead."""

    name = "denoise"
    label = "Denoise (Chroma)"
    params = (ParamSpec("strength", "Strength", "int", 1, 100, 40),)

    def apply(self, image: QImage, params: dict) -> None:
        radius = max(1, int(params.get("strength", 40)) // 10)
        arr = view_u32(image)
        a = (arr >> np.uint32(24)).astype(np.float32)
        r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
        g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
        b = (arr & 0xFF).astype(np.float32)
        y = 0.299 * r + 0.587 * g + 0.114 * b
        cb = b - y
        cr = r - y

        def box(chan: np.ndarray) -> np.ndarray:
            for axis in (0, 1):
                for _ in range(3):  # 3x box ~ gaussian
                    k = 2 * radius + 1
                    pad = np.pad(
                        chan,
                        [(radius, radius) if ax == axis else (0, 0) for ax in (0, 1)],
                        mode="edge",
                    )
                    csum = np.cumsum(pad, axis=axis, dtype=np.float32)
                    take = np.take(csum, range(k - 1, pad.shape[axis]), axis=axis)
                    lead = np.take(csum, range(0, pad.shape[axis] - k + 1), axis=axis)
                    first = np.take(csum, [k - 1], axis=axis)
                    chan = (
                        np.concatenate(
                            [first, take[1:] - lead[:-1]]
                            if axis == 0
                            else [np.take(take, [0], axis=1), take[:, 1:] - lead[:, :-1]],
                            axis=axis,
                        )
                        / k
                    )
            return chan

        cb = box(cb)
        cr = box(cr)
        r = np.clip(y + cr, 0, 255)
        b = np.clip(y + cb, 0, 255)
        g = np.clip((y - 0.299 * r - 0.114 * b) / 0.587, 0, 255)
        arr[...] = (
            (a.astype(np.uint32) << np.uint32(24))
            | (r.astype(np.uint32) << np.uint32(16))
            | (g.astype(np.uint32) << np.uint32(8))
            | b.astype(np.uint32)
        )


class RetroConsoleFilter(Filter):
    """80s/90s console look (#130): shrink the image into chunky pixels, crush
    the colour depth to a few levels per channel, and (optionally) apply a 4x4
    ordered (Bayer) dither so smooth gradients break into the crosshatch
    patterns of an old game. Dependency-free and alpha-preserving. The
    quantise runs on the downsampled copy so the dither lands on the block
    grid; a nearest-neighbour upscale then restores the crisp blocks."""

    name = "retro-console"
    label = "Retro Console (8-Bit)"
    params = (
        ParamSpec("size", "Pixel size", "int", 1, 64, 6),
        ParamSpec("levels", "Colour levels", "int", 2, 8, 4),
        ParamSpec("dither", "Dither (0=off, 1=on)", "int", 0, 1, 1),
    )

    # 4x4 Bayer threshold matrix, centred to [-0.5, 0.5)
    _BAYER = (
        np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], dtype=np.float32)
        + 0.5
    ) / 16.0 - 0.5

    def apply(self, image: QImage, params: dict) -> None:
        size = max(1, int(params.get("size", 6)))
        levels = max(2, int(params.get("levels", 4)))
        dither = int(params.get("dither", 1))
        w, h = image.width(), image.height()

        small = image.scaled(max(1, w // size), max(1, h // size))
        arr = view_u32(small)
        a = (arr >> np.uint32(24)).astype(np.float32)
        r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
        g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
        b = (arr & 0xFF).astype(np.float32)

        # buffers are premultiplied (DD-001); recover straight colour to crush
        unpm = np.where(a > 0, 255.0 / a, 0.0)
        r *= unpm
        g *= unpm
        b *= unpm

        step = 255.0 / (levels - 1)
        if dither:
            sh = arr.shape
            bias = np.tile(self._BAYER, (sh[0] // 4 + 1, sh[1] // 4 + 1))[: sh[0], : sh[1]]
            bias = bias * step
            r = r + bias
            g = g + bias
            b = b + bias

        def crush(c: np.ndarray) -> np.ndarray:
            return np.clip(np.round(np.clip(c, 0, 255) / step) * step, 0, 255)

        r, g, b = crush(r), crush(g), crush(b)

        # re-premultiply by the untouched alpha and pack back to ARGB32
        af = a / 255.0
        arr[...] = (
            (a.astype(np.uint32) << np.uint32(24))
            | ((r * af).astype(np.uint32) << np.uint32(16))
            | ((g * af).astype(np.uint32) << np.uint32(8))
            | (b * af).astype(np.uint32)
        )

        big = small.scaled(w, h)  # nearest-neighbour up = crisp blocks
        view_u32(image)[...] = view_u32(big)


def _sort_runs(work: np.ndarray, low: int, high: int, reverse: bool) -> None:
    """Sort each contiguous in-band run of every row of ``work`` by luma.

    ``work`` is a C-contiguous (h, w) uint32 array of premultiplied ARGB
    pixels, edited in place. Whole pixels are permuted — never recombined —
    so colour and alpha travel together and no value is invented."""
    a = (work >> np.uint32(24)).astype(np.float32)
    r = ((work >> np.uint32(16)) & 0xFF).astype(np.float32)
    g = ((work >> np.uint32(8)) & 0xFF).astype(np.float32)
    b = (work & 0xFF).astype(np.float32)
    # straight colour, so a threshold band means the same thing at any alpha
    unpm = np.where(a > 0, 255.0 / np.maximum(a, 1.0), 0.0)
    luma = (0.299 * r + 0.587 * g + 0.114 * b) * unpm

    mask = (luma >= low) & (luma <= high)
    if not mask.any():
        return
    # a run starts at any in-band pixel whose left neighbour is out of band;
    # column 0 always starts one, which is what keeps runs inside their row
    starts = mask.copy()
    starts[:, 1:] &= ~mask[:, :-1]
    run_id = np.cumsum(starts.reshape(-1), dtype=np.int64)

    idx = np.flatnonzero(mask.reshape(-1))
    key = luma.reshape(-1)[idx]
    if reverse:
        key = -key
    # primary key run, secondary key luma: one pass sorts every run at once
    order = np.lexsort((key, run_id[idx]))
    flat = work.reshape(-1)
    flat[idx] = flat[idx][order]


class PixelSortFilter(Filter):
    """Pixel sorting — the glitch-art staple, and the effect behind the
    Cyberpunk 2077 cyberspace dive and The Peripheral's title sequence.

    Pixels whose brightness falls inside a threshold band are gathered into
    contiguous runs along each row (or column) and sorted by luma within the
    run. Everything outside the band stays exactly where it is, and that is
    the whole trick: untouched darks and highlights bound the smear, so the
    image stays legible while the midtones melt into ribbons. A wide band
    (0..255) liquefies the frame; a narrow one picks out edges.

    Vectorised — one lexsort over the masked positions keyed by (run, luma),
    so a full-frame sort costs no per-pixel Python."""

    name = "pixel-sort"
    label = "Pixel Sort (Glitch)"
    params = (
        ParamSpec("low", "Threshold low", "int", 0, 255, 60),
        ParamSpec("high", "Threshold high", "int", 0, 255, 200),
        ParamSpec("vertical", "Vertical (0=rows, 1=columns)", "int", 0, 1, 0),
        ParamSpec("reverse", "Reverse (0=dark first, 1=bright first)", "int", 0, 1, 0),
    )

    def apply(self, image: QImage, params: dict) -> None:
        low = int(params.get("low", 60))
        high = int(params.get("high", 200))
        if low > high:  # a band given backwards is still a band
            low, high = high, low
        reverse = bool(int(params.get("reverse", 0)))
        arr = view_u32(image)
        if int(params.get("vertical", 0)):
            # the transpose is a non-contiguous view; sort a compact copy
            work = np.ascontiguousarray(arr.T)
            _sort_runs(work, low, high, reverse)
            arr[...] = work.T
        else:
            _sort_runs(arr, low, high, reverse)


def _mosh_blocks(arr: np.ndarray, block: int, amount: float, drift: int, seed: int) -> None:
    """Displace macroblocks by motion vectors that accumulate down the rows."""
    h, w = arr.shape
    nby = (h + block - 1) // block
    nbx = (w + block - 1) // block
    vx = np.zeros(nbx, dtype=np.int64)
    vy = np.zeros(nbx, dtype=np.int64)
    ydrift = max(1, drift // 2)  # sideways smear reads as motion, vertical as tearing
    src = arr.copy()  # the single "previous frame" every block samples from
    for i in range(nby):
        # Three independent streams keyed by (seed, row, draw) rather than one
        # running stream. Size then cannot shift the sequence: a wider image
        # takes a longer *prefix* of each stream, a taller one only adds rows,
        # and every block keeps the values its position earns. One seed can
        # therefore lay the same glitch over a whole set of images (#319) —
        # which a single stream cannot do, because the first draw's length
        # would displace every draw after it.
        seq = np.random.SeedSequence([seed, i])
        rf, rx, ry = (np.random.default_rng(c) for c in seq.spawn(3))
        # a fresh vector on some blocks; every other block keeps the one
        # above it, and that inheritance is the P-frame chain that makes
        # this read as datamosh rather than as block noise
        fresh = rf.random(nbx) < amount
        vx += np.where(fresh, rx.integers(-drift, drift + 1, nbx), 0)
        vy += np.where(fresh, ry.integers(-ydrift, ydrift + 1, nbx), 0)
        y0 = i * block
        y1 = min(y0 + block, h)
        bh = y1 - y0
        for j in range(nbx):
            x0 = j * block
            x1 = min(x0 + block, w)
            bw = x1 - x0
            sy = int(np.clip(y0 + vy[j], 0, h - bh))
            sx = int(np.clip(x0 + vx[j], 0, w - bw))
            arr[y0:y1, x0:x1] = src[sy : sy + bh, sx : sx + bw]


def _radial_sample(chan: np.ndarray, scale: float, cx: float, cy: float) -> np.ndarray:
    """Nearest-neighbour resample of one float plane about (cx, cy)."""
    h, w = chan.shape
    out = np.empty_like(chan)
    xs = np.arange(w, dtype=np.float32)
    sx = np.clip(cx + (xs - cx) / scale, 0, w - 1).astype(np.int32)[None, :]
    for y0 in range(0, h, CHUNK_ROWS):  # house pattern: chunk the per-pixel work
        y1 = min(y0 + CHUNK_ROWS, h)
        ys = np.arange(y0, y1, dtype=np.float32)
        sy = np.clip(cy + (ys - cy) / scale, 0, h - 1).astype(np.int32)[:, None]
        out[y0:y1] = chan[sy, sx]
    return out


def _chromatic_aberration(arr: np.ndarray, px: float) -> None:
    """Scale R out and B in about the centre — the lens fringe, radial."""
    h, w = arr.shape
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    rmax = math.hypot(cx, cy) or 1.0
    k = min(px / rmax, 0.9)  # px is the fringe width at the far corner
    a = (arr >> np.uint32(24)).astype(np.uint32)
    af = a.astype(np.float32)
    unpm = np.where(af > 0, 255.0 / np.maximum(af, 1.0), 0.0).astype(np.float32)
    r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32) * unpm
    g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32) * unpm
    b = (arr & 0xFF).astype(np.float32) * unpm
    r = _radial_sample(r, 1.0 + k, cx, cy)
    b = _radial_sample(b, 1.0 - k, cx, cy)
    # alpha is deliberately not shifted: fringing the cutout would eat edges
    af /= 255.0
    arr[...] = (
        (a << np.uint32(24))
        | (np.clip(r * af, 0, 255).astype(np.uint32) << np.uint32(16))
        | (np.clip(g * af, 0, 255).astype(np.uint32) << np.uint32(8))
        | np.clip(b * af, 0, 255).astype(np.uint32)
    )


class DatamoshFilter(Filter):
    """Datamosh + chromatic aberration — the Neuromancer-trailer glitch.

    Real datamoshing is an *interframe* artifact: drop a video's I-frames and
    the surviving P-frames keep applying their motion vectors to whatever
    pixels happen to be underneath, so motion from one shot smears across the
    image of another. A still has no frames to mosh, so this reproduces the
    mechanism rather than the file corruption. The image is cut into a
    macroblock grid and a fraction of blocks are handed a random motion
    vector; every other block inherits the vector of the block above it, so
    displacement accumulates down the frame exactly as a P-frame chain does
    with no keyframe to reset it. That inheritance is what separates a mosh
    from mere block noise, and keeping ``block`` near a codec's real 16 px
    macroblock is what keeps it reading as compression rather than mosaic.

    Blocks are copied whole from one source snapshot, so no pixel value is
    invented. Chromatic aberration then fringes the result radially — the
    lens artifact the look is conventionally paired with. Set ``aberration``
    to 0 for the mosh alone, or ``amount`` to 0 for the fringe alone.

    Deterministic by ``seed``, and deterministic *by block position* rather
    than by draw order — so one seed lays the same glitch over a whole set of
    images, whatever their sizes, and actions and smart-filter replay
    reproduce it exactly. The one limit is the canvas edge: displacement is
    clamped to the image, so a drift large enough to run a block off a small
    picture cannot land identically on a larger one. Change the seed to
    reroll."""

    name = "datamosh"
    label = "Datamosh + Chromatic Aberration"
    params = (
        ParamSpec("block", "Macroblock size", "int", 4, 64, 16),
        ParamSpec("amount", "Corrupted blocks (%)", "int", 0, 100, 35),
        ParamSpec("drift", "Motion drift (px)", "int", 0, 64, 12),
        ParamSpec("aberration", "Chromatic aberration (px)", "float", 0, 20, 3.0),
        ParamSpec("seed", "Seed", "int", 0, 9999, 7),
    )

    def apply(self, image: QImage, params: dict) -> None:
        block = max(4, int(params.get("block", 16)))
        amount = float(params.get("amount", 35)) / 100.0
        drift = int(params.get("drift", 12))
        aberration = float(params.get("aberration", 3.0))
        seed = int(params.get("seed", 7))
        arr = view_u32(image)
        if amount > 0 and drift > 0:
            _mosh_blocks(arr, block, amount, drift, seed)
        if aberration > 0:
            _chromatic_aberration(arr, aberration)


_BUILT_INS = (
    *_BUILT_INS,
    DenoiseFilter,
    RetroConsoleFilter,
    PixelSortFilter,
    DatamoshFilter,
)


class FilmNegativeFilter(Filter):
    """Develop a scanned film negative into the positive photograph.

    Not the same operation as inverting the pixels. A colour negative carries
    an **orange mask** — a deliberate dye layer in the film base that corrects
    the dyes' unwanted absorptions — so ``255 - v`` yields the familiar muddy
    cyan-blue image with the mask still in it. And film records *transmittance*,
    so the inversion is a reciprocal, not a subtraction: the positive is
    ``base / v``, which is a subtraction in density space, not in scan values.

    Both problems fall to one operation: normalise **each channel
    independently** in reciprocal space between its own clipped extremes. The
    per-channel part removes the orange mask (the mask is a constant offset per
    channel, so it cancels), and the reciprocal part gets film's tonality right.

    A black-and-white negative has no mask and must stay neutral — normalising
    its channels independently would amplify whatever tint the acetate base and
    the scanner contributed into a colour cast. So mono negatives are developed
    from a single luma channel and written back neutral.

    ``mode=auto`` tells the two apart by mean per-pixel chroma: the orange mask
    puts a colour negative far from neutral everywhere (typically 40-80 of 255),
    while a monochrome scan sits near zero. The threshold has generous margin on
    both sides, and ``mode`` overrides it when a negative is unusual — a heavily
    faded or cross-processed frame, or a colour negative scanned to greyscale.
    """

    name = "film-negative"
    label = "Film Negative → Positive"
    params = (
        ParamSpec("mode", "Negative type", "choice", 0, 0, "auto", ("auto", "color", "mono")),
        ParamSpec("clip", "Clip (%)", "float", 0.0, 5.0, 0.5),
    )

    # Mean per-pixel chroma, 0-255, above which a scan is treated as a colour
    # negative. Measured margin is wide: an orange mask lands far above it and a
    # greyscale scan at essentially zero, so the exact value is not delicate.
    MONO_CHROMA_MAX = 24.0

    def apply(self, image: QImage, params: dict) -> None:
        mode = str(params.get("mode", "auto"))
        clip = float(params.get("clip", 0.5))
        arr = view_u32(image)
        height = arr.shape[0]
        if height == 0 or arr.shape[1] == 0:
            return

        # Pass 1 — 256-bin histograms and the chroma statistic, chunked so a
        # large layer never materialises a full-size float array (DD-001).
        hist = np.zeros((4, 256), dtype=np.int64)  # R, G, B, luma
        chroma_sum = 0.0
        opaque_count = 0
        for y0 in range(0, height, CHUNK_ROWS):
            chunk = arr[y0 : y0 + CHUNK_ROWS]
            a = (chunk >> np.uint32(24)) & np.uint32(0xFF)
            keep = a > 0
            if not keep.any():
                continue
            r, g, b = _unpremultiplied_rgb(chunk, a)
            r, g, b = r[keep], g[keep], b[keep]
            for index, channel in enumerate((r, g, b)):
                hist[index] += np.bincount(channel, minlength=256)
            luma = np.rint(0.299 * r + 0.587 * g + 0.114 * b).astype(np.int64)
            hist[3] += np.bincount(np.clip(luma, 0, 255), minlength=256)
            top = np.maximum(np.maximum(r, g), b).astype(np.int32)
            bottom = np.minimum(np.minimum(r, g), b).astype(np.int32)
            chroma_sum += float((top - bottom).sum())
            opaque_count += int(keep.sum())

        if opaque_count == 0:
            return
        if mode == "auto":
            chroma = chroma_sum / opaque_count
            mode = "mono" if chroma <= self.MONO_CHROMA_MAX else "color"

        channels = (3, 3, 3) if mode == "mono" else (0, 1, 2)
        bounds = [_clipped_bounds(hist[index], opaque_count, clip) for index in channels]

        # Pass 2 — develop. Reciprocal space, per channel, between its own
        # clipped extremes: dense negative (low scan value) -> bright positive.
        tables = [_negative_lut(lo, hi) for lo, hi in bounds]
        for y0 in range(0, height, CHUNK_ROWS):
            chunk = arr[y0 : y0 + CHUNK_ROWS]
            a = (chunk >> np.uint32(24)) & np.uint32(0xFF)
            r, g, b = _unpremultiplied_rgb(chunk, a)
            if mode == "mono":
                luma = np.clip(np.rint(0.299 * r + 0.587 * g + 0.114 * b).astype(np.int32), 0, 255)
                out_r = out_g = out_b = tables[0][luma]
            else:
                out_r, out_g, out_b = tables[0][r], tables[1][g], tables[2][b]
            _store_premultiplied(chunk, a, out_r, out_g, out_b)


def _hex_rgb(text, fallback: tuple[int, int, int]) -> tuple[int, int, int]:
    """``#RRGGBB`` (or ``RRGGBB``, or ``#RGB``) to a 0-255 triple.

    A colour that cannot be read falls back rather than raising: these arrive
    from a free-text box, and a half-typed value should not abort a render the
    user is watching.
    """
    raw = str(text).strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6:
        return fallback
    try:
        return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    except ValueError:
        return fallback


def _downsample(plane: np.ndarray, factor: int) -> np.ndarray:
    """Block-average by an integer factor, which is what makes the dither
    coarse: the algorithm sees one value per output cell, so a cell is either
    on or off as a whole rather than dissolving into per-pixel noise."""
    if factor <= 1:
        return plane
    height, width = plane.shape
    rows, cols = height // factor, width // factor
    if rows == 0 or cols == 0:
        return plane
    trimmed = plane[: rows * factor, : cols * factor]
    return trimmed.reshape(rows, factor, cols, factor).mean(axis=(1, 3))


def _upsample(plane: np.ndarray, factor: int, shape: tuple[int, int]) -> np.ndarray:
    """Nearest-neighbour back up to ``shape``. Nearest, never smooth: the whole
    point is hard-edged cells, and any interpolation here would reintroduce the
    intermediate tones the dither just spent its effort removing."""
    if factor <= 1 and plane.shape == shape:
        return plane
    grown = np.repeat(np.repeat(plane, factor, axis=0), factor, axis=1)
    height, width = shape
    if grown.shape[0] < height or grown.shape[1] < width:
        # The trailing partial cell the block average had to drop.
        grown = np.pad(
            grown,
            ((0, max(0, height - grown.shape[0])), (0, max(0, width - grown.shape[1]))),
            mode="edge",
        )
    return grown[:height, :width]


class BeamDitherFilter(Filter):
    """One-bit rendering with a CRT beam model (#384).

    Two stages, and they are separable on purpose. First the picture is
    *conditioned* — levels, blur, sharpen, grain — because every dither is only
    as good as the contrast handed to it: error diffusion applied to a flat
    photograph gives flat noise, and the same photograph pushed to a hard
    tonal curve first gives structure. Then it is *rendered*, either by a
    dither that preserves average tone or by beam modulation that does not.

    The beam mode is the interesting one. A dither asks which pixels to light
    so the average is right; a beam raster asks what the picture does to a line
    being swept across it. Bright regions deflect their beam off its resting
    row and widen it, so the output is bending scanlines that trace contours,
    which is why it reads as engraving rather than as noise.
    """

    name = "beam-dither"
    label = "Beam Dither"
    params = (
        ParamSpec(
            "algorithm",
            "Algorithm",
            "choice",
            0,
            0,
            "beam",
            (
                "beam",
                "floyd-steinberg",
                "atkinson",
                "jarvis",
                "stucki",
                "sierra",
                "burkes",
                "bayer-2",
                "bayer-4",
                "bayer-8",
                "threshold",
            ),
        ),
        ParamSpec("mode", "Render mode", "choice", 0, 0, "mono", ("mono", "tonal", "color")),
        ParamSpec("scale", "Cell size", "int", 1, 32, 3),
        ParamSpec("levels", "Tone levels", "int", 2, 8, 2),
        ParamSpec("brightness", "Brightness", "int", -100, 100, 0),
        ParamSpec("contrast", "Contrast", "int", -100, 100, 0),
        ParamSpec("blur", "Blur", "int", 0, 20, 0),
        ParamSpec("sharpen", "Sharpen strength", "int", 0, 300, 0),
        ParamSpec("sharpen_radius", "Sharpen radius", "int", 1, 20, 2),
        ParamSpec("noise", "Denoise / Noise", "int", -100, 100, 0),
        ParamSpec("beam_pitch", "Beam pitch", "int", 2, 64, 6),
        ParamSpec("beam_amplitude", "Beam displacement", "float", 0.0, 8.0, 1.5),
        ParamSpec("highlights", "Highlights", "str", 0, 0, "#FFFFFF"),
        ParamSpec("midtones", "Midtones", "str", 0, 0, "#B0B0B0"),
        ParamSpec("shadows", "Shadows", "str", 0, 0, "#5A5A5A"),
        ParamSpec("background", "Background", "str", 0, 0, "#000000"),
    )

    def apply(self, image: QImage, params: dict) -> None:
        from photoslop.appearance import _blur_plane

        arr = view_u32(image)
        alpha = (arr >> np.uint32(24)) & np.uint32(0xFF)
        red, green, blue = _unpremultiplied_rgb(arr, alpha)

        algorithm = str(params.get("algorithm", "beam"))
        mode = str(params.get("mode", "mono"))
        scale = max(1, int(params.get("scale", 3)))
        levels = max(2, int(params.get("levels", 2)))

        def conditioned(channel: np.ndarray) -> np.ndarray:
            plane = channel.astype(np.float32) / 255.0
            return self._condition(plane, params, _blur_plane)

        def rendered(plane: np.ndarray) -> np.ndarray:
            shape = plane.shape
            small = _downsample(plane, scale)
            tone = self._render(small, algorithm, levels, params)
            return _upsample(tone, scale, shape)

        if mode == "color":
            # Each channel dithered on its own: the classic indexed-palette
            # look, where the cross-channel disagreement is what produces the
            # colour speckle rather than a shared mask tinting a grey.
            out_r = rendered(conditioned(red))
            out_g = rendered(conditioned(green))
            out_b = rendered(conditioned(blue))
            new_r = np.rint(out_r * 255.0).astype(np.int32)
            new_g = np.rint(out_g * 255.0).astype(np.int32)
            new_b = np.rint(out_b * 255.0).astype(np.int32)
        else:
            luma = (
                0.299 * red.astype(np.float32)
                + 0.587 * green.astype(np.float32)
                + 0.114 * blue.astype(np.float32)
            ) / 255.0
            conditioned_luma = self._condition(luma, params, _blur_plane)
            tone = rendered(conditioned_luma)
            new_r, new_g, new_b = self._colorise(tone, conditioned_luma, mode, params)

        _store_premultiplied(arr, alpha, new_r, new_g, new_b)

    @staticmethod
    def _condition(plane: np.ndarray, params: dict, blur_plane) -> np.ndarray:
        """Levels, blur, sharpen and grain, in the order a darkroom would.

        Sharpen runs after blur so the pair is a band-pass rather than a
        cancellation, and grain is added last so the dither sees it as signal —
        added earlier, the blur would simply erase it.
        """
        brightness = float(params.get("brightness", 0)) / 100.0
        contrast = float(params.get("contrast", 0)) / 100.0
        plane = np.clip(plane + brightness, 0.0, 1.0)
        if contrast:
            # Pivot on mid grey, so contrast opens the tonal range rather than
            # also shifting its centre the way a plain multiply would.
            gain = (1.0 + contrast) if contrast > 0 else (1.0 / (1.0 - contrast))
            plane = np.clip((plane - 0.5) * gain + 0.5, 0.0, 1.0)

        blur = int(params.get("blur", 0))
        if blur > 0:
            plane = blur_plane(plane.astype(np.float32), blur)

        sharpen = float(params.get("sharpen", 0)) / 100.0
        if sharpen > 0:
            radius = max(1, int(params.get("sharpen_radius", 2)))
            # Unsharp mask: the picture plus its own missing high frequencies.
            low = blur_plane(plane.astype(np.float32), radius)
            plane = np.clip(plane + sharpen * (plane - low), 0.0, 1.0)

        noise = int(params.get("noise", 0))
        if noise > 0:
            # Seeded, so the same document and settings render identically —
            # a filter that changed under a re-render would make the undo
            # stack lie about what it was restoring.
            rng = np.random.default_rng(0x0D17)
            plane = np.clip(
                plane + rng.uniform(-1.0, 1.0, plane.shape).astype(np.float32) * (noise / 200.0),
                0.0,
                1.0,
            )
        elif noise < 0:
            plane = blur_plane(plane.astype(np.float32), max(1, -noise // 20))
        return plane.astype(np.float32)

    @staticmethod
    def _render(plane: np.ndarray, algorithm: str, levels: int, params: dict) -> np.ndarray:
        if algorithm == "beam":
            coverage = dither.beam_mask(
                plane,
                int(params.get("beam_pitch", 6)),
                float(params.get("beam_amplitude", 1.5)),
            )
            # The beam's shoulders are soft, and left that way the result is a
            # smooth grey edge on every line — which is not what a one-bit
            # display does. Dithering the coverage breaks those shoulders into
            # stipple, so a beam thins into dots as it leaves the light instead
            # of fading to grey, and the whole render stays honestly two-tone.
            # `levels` is the way out of it: above 2 the beam keeps its
            # gradient and is merely posterised.
            if levels <= 2:
                return dither.ordered_dither(coverage, 4, 2)
            return dither.quantise(coverage, levels)
        if algorithm.startswith("bayer-"):
            return dither.ordered_dither(plane, int(algorithm.split("-")[1]), levels)
        if algorithm == "threshold":
            return dither.threshold(plane, levels)
        return dither.error_diffuse(plane, algorithm, levels)

    @staticmethod
    def _colorise(tone: np.ndarray, luma: np.ndarray, mode: str, params: dict):
        """Ink the rendered tone.

        `tonal` is tri-tone mapping: which ink a lit pixel takes is decided by
        the *original* luminance under it, not by the rendered value, so the
        shadows keep their own colour even where the dither happens to light
        them. Deciding from the rendered value instead would collapse every
        lit pixel onto one ink and lose the tri-tone entirely.
        """
        background = _hex_rgb(params.get("background", "#000000"), (0, 0, 0))
        if mode != "tonal":
            ink = _hex_rgb(params.get("highlights", "#FFFFFF"), (255, 255, 255))
            inks = (np.float32(ink[0]), np.float32(ink[1]), np.float32(ink[2]))
        else:
            shadows = _hex_rgb(params.get("shadows", "#5A5A5A"), (90, 90, 90))
            midtones = _hex_rgb(params.get("midtones", "#B0B0B0"), (176, 176, 176))
            highlights = _hex_rgb(params.get("highlights", "#FFFFFF"), (255, 255, 255))
            band = np.digitize(luma, [1.0 / 3.0, 2.0 / 3.0])
            palette = np.array([shadows, midtones, highlights], dtype=np.float32)
            inks = (palette[band, 0], palette[band, 1], palette[band, 2])

        out = []
        for channel, back in zip(inks, background, strict=True):
            mixed = np.float32(back) + (channel - np.float32(back)) * tone
            out.append(np.clip(np.rint(mixed), 0, 255).astype(np.int32))
        return out[0], out[1], out[2]


def _unpremultiplied_rgb(chunk: np.ndarray, a: np.ndarray):
    """Straight (un-premultiplied) 0-255 channels for a packed ARGB chunk.

    Statistics taken over premultiplied values would be pulled toward zero by
    any partial alpha, so a soft-edged layer would develop differently from the
    same pixels at full opacity.
    """
    r = ((chunk >> np.uint32(16)) & np.uint32(0xFF)).astype(np.int32)
    g = ((chunk >> np.uint32(8)) & np.uint32(0xFF)).astype(np.int32)
    b = (chunk & np.uint32(0xFF)).astype(np.int32)
    alpha = a.astype(np.int32)
    partial = (alpha > 0) & (alpha < 255)
    if partial.any():
        scale = np.where(partial, 255.0 / np.maximum(alpha, 1), 1.0)
        r = np.clip(np.rint(r * scale), 0, 255).astype(np.int32)
        g = np.clip(np.rint(g * scale), 0, 255).astype(np.int32)
        b = np.clip(np.rint(b * scale), 0, 255).astype(np.int32)
    return r, g, b


def _store_premultiplied(chunk, a, r, g, b) -> None:
    """Write straight channels back into a premultiplied ARGB chunk in place."""
    alpha = a.astype(np.int32)
    scale = alpha / 255.0
    pr = np.clip(np.rint(r * scale), 0, 255).astype(np.uint32)
    pg = np.clip(np.rint(g * scale), 0, 255).astype(np.uint32)
    pb = np.clip(np.rint(b * scale), 0, 255).astype(np.uint32)
    chunk[...] = (a << np.uint32(24)) | (pr << np.uint32(16)) | (pg << np.uint32(8)) | pb


def _clipped_bounds(counts: np.ndarray, total: int, clip: float) -> tuple[int, int]:
    """Lowest and highest scan value left after discarding ``clip`` percent of
    the pixels from each end — the film base and any dust speck or scanner
    flare that would otherwise define the whole range on its own."""
    if total <= 0:
        return 0, 255
    drop = int(total * clip / 100.0)
    cumulative = np.cumsum(counts)
    lo = int(np.searchsorted(cumulative, drop, side="right"))
    hi = int(np.searchsorted(cumulative, total - drop, side="left"))
    lo = min(max(lo, 0), 255)
    hi = min(max(hi, 0), 255)
    if hi <= lo:  # a flat frame: nothing to stretch, keep the full range
        return 0, 255
    return lo, hi


def _negative_lut(lo: int, hi: int) -> np.ndarray:
    """256-entry lookup mapping scan value -> developed positive.

    ``1/v`` puts the work in transmittance space, where film's response lives;
    normalising that between the clipped extremes both inverts the image and
    removes the channel's constant base density — the orange mask, for a colour
    negative — because a constant offset in density is a constant factor here
    and divides straight out.
    """
    values = np.arange(256, dtype=np.float64)
    recip = 1.0 / np.maximum(values, 1.0)
    top = 1.0 / max(lo, 1)  # densest kept value -> brightest positive
    bottom = 1.0 / max(hi, 1)  # film base -> black
    span = top - bottom
    if span <= 0:
        return np.zeros(256, dtype=np.int32)
    scaled = (recip - bottom) / span
    return np.clip(np.rint(scaled * 255.0), 0, 255).astype(np.int32)


_BUILT_INS = (*_BUILT_INS, FilmNegativeFilter, BeamDitherFilter)
