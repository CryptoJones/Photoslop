# SPDX-License-Identifier: Apache-2.0
"""Camera-raw import via rawpy (optional dependency: photoslop[raw]).

Raw decoding is memory-heavy by nature (a 45MP sensor demosaics to a
~135MB RGB array); the array is handed straight to QImage and the
intermediate dropped, so the cost is one transient copy."""

from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

RAW_EXTENSIONS = (".arw", ".cr2", ".cr3", ".dng", ".nef", ".nrw", ".orf",
                  ".pef", ".raf", ".rw2", ".srw")


class RawSupportError(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "Camera-raw support is not installed — pip install photoslop[raw] "
            "(or: uv pip install rawpy)")


def is_raw_path(path: str) -> bool:
    return path.lower().endswith(RAW_EXTENSIONS)


def probe_raw(path: str) -> None:
    """Open-and-close to validate a raw file (raises on junk) — lets the
    GUI fail gracefully BEFORE showing the develop dialog."""
    try:
        import rawpy
    except ImportError as exc:
        raise RawSupportError() from exc
    with rawpy.imread(path):
        pass


def load_raw(path: str) -> QImage:
    """Decode a camera raw file to a premultiplied ARGB32 QImage."""
    try:
        import rawpy
    except ImportError as exc:
        raise RawSupportError() from exc
    with rawpy.imread(path) as raw:
        rgb = raw.postprocess(use_camera_wb=True, output_bps=8)
    rgb = np.ascontiguousarray(rgb)
    h, w, _ = rgb.shape
    img = QImage(rgb.data, w, h, w * 3, QImage.Format.Format_RGB888)
    # copy out of the numpy buffer before it goes away, into our format
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)


DEVELOP_FIELDS = {
    # key: (min, max, default) — exposure in EV; temp 0 = camera WB
    "exposure": (-2.0, 3.0, 0.0),
    "temp": (0.0, 12000.0, 0.0),
    "tint": (-100.0, 100.0, 0.0),
    "highlights": (-100.0, 100.0, 0.0),
    "shadows": (-100.0, 100.0, 0.0),
}


def _kelvin_rgb(kelvin: float) -> tuple[float, float, float]:
    """Approximate RGB of a black-body at `kelvin` (Tanner Helland fit)."""
    t = max(1000.0, min(40000.0, kelvin)) / 100.0
    r = 255.0 if t <= 66 else 329.7 * ((t - 60.0) ** -0.1332)
    g = (99.47 * np.log(t) - 161.12 if t <= 66
         else 288.12 * ((t - 60.0) ** -0.0755))
    b = (255.0 if t >= 66 else
         0.0 if t <= 19 else 138.52 * np.log(t - 10.0) - 305.04)
    return (float(np.clip(r, 1, 255)), float(np.clip(g, 1, 255)),
            float(np.clip(b, 1, 255)))


def wb_multipliers(temp: float, tint: float) -> list[float]:
    """rawpy user_wb multipliers that render `temp` kelvin light neutral;
    tint biases green<->magenta. Setting temp above the scene's actual
    temperature warms the render (the Lightroom convention)."""
    r, g, b = _kelvin_rgb(temp)
    muls = [g / r, 1.0, g / b]
    muls[1] *= 1.0 / (1.0 + tint / 200.0)
    lo = min(muls)
    return [m / lo for m in muls] + [muls[1] / lo]


def tone_map(f: np.ndarray, highlights: float, shadows: float
             ) -> np.ndarray:
    """Float [0,1] RGB tone adjustment: highlights weight ~ luma^2,
    shadows weight ~ (1-luma)^2 — monotone and bounded."""
    if not highlights and not shadows:
        return f
    luma = (0.299 * f[..., 0] + 0.587 * f[..., 1]
            + 0.114 * f[..., 2])[..., None]
    factor = (1.0 + (highlights / 100.0) * luma ** 2
              + (shadows / 100.0) * (1.0 - luma) ** 2)
    return np.clip(f * factor, 0.0, 1.0)


def develop_raw(path: str, exposure: float = 0.0, temp: float = 0.0,
                tint: float = 0.0, highlights: float = 0.0,
                shadows: float = 0.0, half_size: bool = False) -> QImage:
    """Raw develop stage (DD-007): rawpy decodes at 16 bits, exposure/WB
    happen in the demosaic, tone work happens in float — all transient —
    and the returned layer content is 8-bit."""
    try:
        import rawpy
    except ImportError as exc:
        raise RawSupportError() from exc
    kwargs: dict = {"output_bps": 16, "half_size": half_size}
    if exposure:
        kwargs["exp_shift"] = float(np.clip(2.0 ** exposure, 0.25, 8.0))
        kwargs["no_auto_bright"] = True
    if temp > 0:
        kwargs["user_wb"] = wb_multipliers(temp, tint)
    else:
        kwargs["use_camera_wb"] = True
    with rawpy.imread(path) as raw:
        rgb16 = raw.postprocess(**kwargs)  # transient 16-bit (DD-007)
    f = rgb16.astype(np.float32) / 65535.0
    f = tone_map(f, highlights, shadows)
    rgb8 = np.ascontiguousarray((f * 255.0 + 0.5).astype(np.uint8))
    h, w, _ = rgb8.shape
    img = QImage(rgb8.data, w, h, w * 3, QImage.Format.Format_RGB888)
    return img.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
