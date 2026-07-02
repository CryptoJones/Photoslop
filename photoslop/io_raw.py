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
