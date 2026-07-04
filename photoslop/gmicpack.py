# SPDX-License-Identifier: Apache-2.0
"""G'MIC filter pack (#111a) — the first pack on the filter plugin API.

Feature-detected per DD-001: install `photoslop[gmic]` (the gmic-py wheel)
and a curated set of G'MIC filters appears in the Filter menu and the CLI,
plus a raw **G'MIC Command** escape hatch that reaches the whole library
(hundreds of commands, including the community `fx_*` set bundled with
gmic-py 3.6+). Without the wheel, a `gmic` CLI binary on PATH works as a
subprocess fallback; with neither, nothing registers and Photoslop is
unchanged.

Memory (DD-008): libgmic computes in float — each run costs a transient
~4x copy of ONE layer, released on return. Accepted and documented; the
resident footprint is zero (this module stores classes, not pixels)."""

from __future__ import annotations

import importlib.util
import shutil

import numpy as np
from PySide6.QtGui import QImage

from photoslop.filters import Filter, ParamSpec, register_filter


def gmic_available() -> bool:
    return (importlib.util.find_spec("gmic") is not None
            or shutil.which("gmic") is not None)


def _to_rgba(image: QImage) -> np.ndarray:
    src = image.convertToFormat(QImage.Format.Format_RGBA8888)  # unpremultiplies
    h, w = src.height(), src.width()
    return np.frombuffer(src.constBits(), dtype=np.uint8).reshape(h, w, 4).copy()


def _write_back(image: QImage, rgba: np.ndarray) -> None:
    h, w = image.height(), image.width()
    out = QImage(rgba.tobytes(), w, h, w * 4, QImage.Format.Format_RGBA8888)
    out = out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    from photoslop.npimage import view_u32

    view_u32(image)[...] = view_u32(out)


def _restore_shape(res: np.ndarray, alpha: np.ndarray,
                   w: int, h: int) -> np.ndarray:
    """gmic output (h', w', spectrum, depth) -> (h, w, 4) uint8."""
    res = res[..., 0] if res.ndim == 4 else res          # drop depth
    if res.ndim == 2:
        res = res[..., None]
    spectrum = res.shape[2]
    if spectrum == 1:
        rgb = np.repeat(res, 3, axis=2)
        a = alpha
    elif spectrum == 3:
        rgb, a = res, alpha
    else:
        rgb, a = res[..., :3], res[..., 3:4]
    rgba = np.concatenate([rgb, a if a.shape[:2] == rgb.shape[:2]
                           else np.full((*rgb.shape[:2], 1), 255.0)], axis=2)
    rgba = np.clip(rgba, 0, 255).astype(np.uint8)
    if rgba.shape[:2] != (h, w):  # a command that resized: scale back
        img = QImage(rgba.tobytes(), rgba.shape[1], rgba.shape[0],
                     rgba.shape[1] * 4, QImage.Format.Format_RGBA8888)
        img = img.scaled(w, h)
        rgba = np.frombuffer(img.constBits(), dtype=np.uint8
                             ).reshape(h, w, 4).copy()
    return rgba


def run_gmic(image: QImage, command: str) -> None:
    """Run a G'MIC command on a QImage in place (gmic-py, else CLI).

    Only RGB goes to G'MIC — alpha is kept aside and reattached, so
    commands like negate/blur can't corrupt transparency."""
    rgba = _to_rgba(image)
    h, w = rgba.shape[:2]
    alpha = rgba[..., 3:4].astype(np.float32)
    if importlib.util.find_spec("gmic") is not None:
        import gmic

        img = gmic.Image()
        img.assign_ndarray(np.ascontiguousarray(
            rgba[..., :3]).astype(np.float32))
        lst = gmic.ImageList([img])
        try:
            gmic.run(command, lst)
        except gmic.GmicException as exc:
            raise ValueError(f"G'MIC: {exc}") from exc
        res = lst[0].to_numpy()
    else:
        res = _run_gmic_cli(rgba, command)
    _write_back(image, _restore_shape(res.astype(np.float32), alpha, w, h))


def _run_gmic_cli(rgba: np.ndarray, command: str) -> np.ndarray:
    import os
    import subprocess
    import tempfile

    h, w = rgba.shape[:2]
    with tempfile.TemporaryDirectory(prefix="photoslop-gmic-") as tmp:
        src = os.path.join(tmp, "in.png")
        dst = os.path.join(tmp, "out.png")
        rgb = np.ascontiguousarray(rgba[..., :3])
        img = QImage(rgb.tobytes(), w, h, w * 3,
                     QImage.Format.Format_RGB888)
        img.save(src)
        proc = subprocess.run(["gmic", src, *command.split(),
                               "output", dst],
                              capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or not os.path.exists(dst):
            raise ValueError(f"G'MIC CLI: {proc.stderr.strip()[:200]}")
        out = QImage(dst).convertToFormat(QImage.Format.Format_RGB888)
        oh, ow = out.height(), out.width()
        arr = np.frombuffer(out.constBits(), dtype=np.uint8)
        # RGB888 rows are 32-bit aligned: slice off the padding per row
        arr = arr.reshape(oh, out.bytesPerLine())[:, :ow * 3]
        return arr.reshape(oh, ow, 3).copy()


class _GmicFilter(Filter):
    """Curated G'MIC filter: a command template formatted from params."""

    template = ""

    def apply(self, image: QImage, params: dict) -> None:
        run_gmic(image, self.template.format(**params))


class GmicCartoon(_GmicFilter):
    name = "gmic-cartoon"
    label = "G'MIC Cartoon"
    template = "cartoon {smoothness},50,80,0.25,{colors},8"
    params = (ParamSpec("smoothness", "Smoothness", "float", 0, 10, 3),
              ParamSpec("colors", "Color richness", "float", 0.5, 3, 1.5))


class GmicOldPhoto(_GmicFilter):
    name = "gmic-old-photo"
    label = "G'MIC Old Photo"
    template = "old_photo"
    params = ()


class GmicDrawing(_GmicFilter):
    name = "gmic-drawing"
    label = "G'MIC Drawing"
    template = "drawing {amplitude}"
    params = (ParamSpec("amplitude", "Amplitude", "int", 1, 300, 100),)


class GmicStencil(_GmicFilter):
    name = "gmic-stencil"
    label = "G'MIC Stencil (B&W)"
    template = "stencilbw {radius},{smoothness}"
    params = (ParamSpec("radius", "Radius", "float", 0.5, 10, 2),
              ParamSpec("smoothness", "Smoothness", "int", 1, 30, 10))


class GmicSpread(_GmicFilter):
    name = "gmic-spread"
    label = "G'MIC Spread"
    template = "spread {dx},{dy}"
    params = (ParamSpec("dx", "Horizontal", "int", 0, 32, 3),
              ParamSpec("dy", "Vertical", "int", 0, 32, 3))


class GmicSolarize(_GmicFilter):
    name = "gmic-solarize"
    label = "G'MIC Solarize"
    template = "solarize {threshold}"
    params = (ParamSpec("threshold", "Threshold", "int", 0, 255, 128),)


class GmicSmooth(_GmicFilter):
    name = "gmic-smooth"
    label = "G'MIC Smooth (anisotropic)"
    template = "smooth {amplitude},0.7,0.3,1,1"
    params = (ParamSpec("amplitude", "Amplitude", "int", 1, 500, 60),)


class GmicRaw(_GmicFilter):
    name = "gmic"
    label = "G'MIC Command"
    params = (ParamSpec("command", "Command", "str", 0, 0, "blur 3"),)

    def apply(self, image: QImage, params: dict) -> None:
        run_gmic(image, str(params.get("command", "")).strip() or "blur 0")


CURATED: tuple[type[Filter], ...] = (
    GmicCartoon, GmicOldPhoto, GmicDrawing, GmicStencil, GmicSpread,
    GmicSolarize, GmicSmooth, GmicRaw,
)


def register_all() -> bool:
    """Register the pack when a G'MIC runtime is present. Idempotent."""
    if not gmic_available():
        return False
    for cls in CURATED:
        register_filter(cls)
    return True
