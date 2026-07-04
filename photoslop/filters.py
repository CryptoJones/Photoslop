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
        arr[...] = ((a.astype(np.uint32) << np.uint32(24))
                    | (np.clip(r, 0, 255).astype(np.uint32) << np.uint32(16))
                    | (np.clip(g, 0, 255).astype(np.uint32) << np.uint32(8))
                    | np.clip(b, 0, 255).astype(np.uint32))


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


def register_filter(cls: type[Filter]) -> None:
    if not getattr(cls, "name", None) or cls.name == "abstract":
        raise ValueError("filter plugins need a unique kebab-case name")
    _REGISTRY[cls.name] = cls


def available_filters() -> dict[str, type[Filter]]:
    """Built-ins + packs + registered + pip-installed entry points."""
    for cls in _BUILT_INS:
        _REGISTRY.setdefault(cls.name, cls)
    from photoslop import geglpack, gmicpack

    gmicpack.register_all()
    geglpack.register_all()
    from importlib.metadata import entry_points

    for ep in entry_points(group="photoslop.filters"):
        if ep.name in _REGISTRY:
            continue
        try:
            register_filter(ep.load())
        except Exception:  # a broken plugin must not break the app
            continue
    return dict(_REGISTRY)


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
            raise ValueError(
                f"{cls.name}: expects {cls.params[0].key}=<text>")
        values[cls.params[0].key] = val
        return values
    for chunk in text.split(","):
        key, sep, num = chunk.partition("=")
        key = key.strip()
        if not sep or key not in specs:
            raise ValueError(
                f"{cls.name}: unknown parameter {key!r}; expects "
                + ", ".join(specs) if specs else
                f"{cls.name} takes no parameters")
        spec = specs[key]
        try:
            v = int(num) if spec.type == "int" else float(num)
        except ValueError as exc:
            raise ValueError(f"{cls.name}: {key}: {exc}") from exc
        if not spec.minimum <= v <= spec.maximum:
            raise ValueError(f"{cls.name}: {key} must be in "
                             f"{spec.minimum}..{spec.maximum}")
        values[key] = v
    return values
