# SPDX-License-Identifier: Apache-2.0
"""Lens corrections (#112) — distortion + vignetting via lensfunpy, with
the camera/lens identified from the source file's EXIF (exifread). Ships
as the optional `photoslop[lens]` extra, feature-detected per DD-001; the
correction is one transient remap of one layer."""

from __future__ import annotations

import importlib.util

import numpy as np
from PySide6.QtGui import QImage


def lens_available() -> bool:
    return (importlib.util.find_spec("lensfunpy") is not None
            and importlib.util.find_spec("exifread") is not None)


def read_exif(path: str) -> dict:
    import exifread

    with open(path, "rb") as fh:
        tags = exifread.process_file(fh, details=False)

    def _s(key: str) -> str:
        return str(tags[key]).strip() if key in tags else ""

    def _f(key: str) -> float:
        try:
            v = tags[key].values[0]
            return float(v.num) / float(v.den) if hasattr(v, "num") \
                else float(v)
        except (KeyError, IndexError, ZeroDivisionError, AttributeError):
            return 0.0

    return {"maker": _s("Image Make"), "model": _s("Image Model"),
            "lens": _s("EXIF LensModel"),
            "focal": _f("EXIF FocalLength"),
            "aperture": _f("EXIF FNumber")}


def correct_lens(image: QImage, source_path: str) -> QImage:
    """Distortion + vignetting corrected copy, or ValueError with a clear
    reason (missing extra, no EXIF, camera/lens not in the lensfun db)."""
    if not lens_available():
        raise ValueError("lens corrections need the optional extra — "
                         'install with `pip install "photoslop[lens]"`')
    import lensfunpy

    exif = read_exif(source_path)
    if not exif["model"]:
        raise ValueError(f"no camera EXIF in {source_path}")
    db = lensfunpy.Database()
    cams = db.find_cameras(exif["maker"], exif["model"])
    if not cams:
        raise ValueError(f"camera not in lensfun db: {exif['maker']} "
                         f"{exif['model']}")
    lenses = db.find_lenses(cams[0], None, exif["lens"] or None)
    if not lenses:
        raise ValueError(f"lens not in lensfun db: {exif['lens'] or '(none)'}")
    focal = exif["focal"] or lenses[0].min_focal
    aperture = exif["aperture"] or 4.0

    src = image.convertToFormat(QImage.Format.Format_ARGB32)
    h, w = src.height(), src.width()
    arr = np.frombuffer(src.constBits(), np.uint8).reshape(h, w, 4).copy()

    mod = lensfunpy.Modifier(lenses[0], cams[0].crop_factor, w, h)
    mod.initialize(focal, aperture, distance=10.0)

    # vignetting first (multiplicative, in place on float RGB)
    rgbf = arr[..., :3].astype(np.float64)
    if mod.apply_color_modification(rgbf):
        arr[..., :3] = np.clip(rgbf, 0, 255).astype(np.uint8)
    # geometry: nearest-neighbour remap through the undistort coordinates
    coords = mod.apply_geometry_distortion()
    if coords is not None:
        xs = np.clip(np.rint(coords[..., 0]).astype(np.int32), 0, w - 1)
        ys = np.clip(np.rint(coords[..., 1]).astype(np.int32), 0, h - 1)
        arr = arr[ys, xs]

    out = QImage(np.ascontiguousarray(arr).tobytes(), w, h, w * 4,
                 QImage.Format.Format_ARGB32)
    return out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
