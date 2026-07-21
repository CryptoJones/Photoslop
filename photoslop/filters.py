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

import traceback
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np
from PySide6.QtGui import QImage

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


_BUILT_INS = (*_BUILT_INS, DenoiseFilter, RetroConsoleFilter)
