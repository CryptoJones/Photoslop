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

from photoslop.adjust import CHUNK_ROWS
from photoslop.npimage import view_u32


class ParamSpec(NamedTuple):
    key: str
    label: str
    type: str  # "int" | "float"
    minimum: float
    maximum: float
    default: float


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
    for cls in _BUILT_INS:
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
