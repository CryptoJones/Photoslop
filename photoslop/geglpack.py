# SPDX-License-Identifier: Apache-2.0
"""GEGL filter pack (#111b) — GIMP's processing core on the filter API.

System-library gated per DD-001 and the tracker: Photoslop never bundles
the GEGL native stack. On Linux, `apt install python3-gi gir1.2-gegl-0.4`
is the whole setup — the pack finds a python interpreter that can import
Gegl (the venv's own if pygobject is installed, else the system python3)
and registers curated filters plus a raw **GEGL Operation** escape hatch
to all ~200 operations.

Every run is **spawn-per-call** (DD-006 discipline applied to GEGL too):
a short-lived worker process loads GEGL, applies one operation between
two temp PNGs, and dies. GEGL never enters Photoslop's resident memory —
the most literal reading of DD-001 available."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

from PySide6.QtGui import QImage

from photoslop.filters import Filter, ParamSpec, register_filter

_HELPER = os.path.join(os.path.dirname(__file__), "_gegl_helper.py")
_PROBE = "import gi; gi.require_version('Gegl', '0.4'); from gi.repository import Gegl"  # noqa: E501

_worker: str | None | bool = False  # False = not probed yet


def _find_worker() -> str | None:
    """Interpreter that can import Gegl: our own, else system python3."""
    global _worker
    if _worker is not False:
        return _worker
    candidates = []
    if importlib.util.find_spec("gi") is not None:
        candidates.append(sys.executable)
    # a venv shadows PATH with its own python3 — probe the system ones too
    for exe in (
        "/usr/bin/python3",
        "/usr/local/bin/python3",
        shutil.which("python3"),
        shutil.which("python"),
    ):
        if exe and os.path.exists(exe) and exe not in candidates and not exe.startswith(sys.prefix):
            candidates.append(exe)
    for exe in candidates:
        try:
            ok = (
                subprocess.run([exe, "-c", _PROBE], capture_output=True, timeout=30).returncode == 0
            )
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if ok:
            _worker = exe
            return exe
    _worker = None
    return None


def gegl_available() -> bool:
    return _find_worker() is not None


def run_gegl(image: QImage, operation: str, props: dict) -> None:
    """Apply one GEGL operation to a QImage in place (worker process)."""
    exe = _find_worker()
    if exe is None:
        raise ValueError("GEGL not available — apt install python3-gi gir1.2-gegl-0.4 (Linux)")
    with tempfile.TemporaryDirectory(prefix="photoslop-gegl-") as tmp:
        src = os.path.join(tmp, "in.png")
        dst = os.path.join(tmp, "out.png")
        image.save(src)
        proc = subprocess.run(
            [exe, _HELPER, src, dst, operation, json.dumps(props)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0 or not os.path.exists(dst):
            raise ValueError(f"GEGL: {proc.stderr.strip()[:200]}")
        out = QImage(dst)
        if out.isNull():
            raise ValueError("GEGL: worker produced an unreadable PNG")
    out = out.scaled(image.width(), image.height()) if out.size() != image.size() else out
    out = out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    from photoslop.npimage import view_u32

    view_u32(image)[...] = view_u32(out)


class _GeglFilter(Filter):
    operation = ""
    unsafe = True

    def apply(self, image: QImage, params: dict) -> None:
        run_gegl(image, self.operation, dict(params))


class GeglVignette(_GeglFilter):
    name = "gegl-vignette"
    label = "GEGL Vignette"
    operation = "gegl:vignette"
    params = (
        ParamSpec("radius", "Radius", "float", 0.0, 3.0, 1.2),
        ParamSpec("softness", "Softness", "float", 0.0, 2.0, 0.8),
    )


class GeglBloom(_GeglFilter):
    name = "gegl-bloom"
    label = "GEGL Bloom"
    operation = "gegl:bloom"
    params = (
        ParamSpec("strength", "Strength", "float", 0.0, 100.0, 50.0),
        ParamSpec("radius", "Radius", "float", 0.0, 100.0, 10.0),
    )


class GeglPixelize(_GeglFilter):
    name = "gegl-pixelize"
    label = "GEGL Pixelize"
    operation = "gegl:pixelize"
    params = (
        ParamSpec("size-x", "Block width", "int", 1, 128, 16),
        ParamSpec("size-y", "Block height", "int", 1, 128, 16),
    )


class GeglNewsprint(_GeglFilter):
    name = "gegl-newsprint"
    label = "GEGL Newsprint"
    operation = "gegl:newsprint"
    params = (ParamSpec("period", "Period", "float", 2.0, 50.0, 10.0),)


class GeglPosterize(_GeglFilter):
    name = "gegl-posterize"
    label = "GEGL Posterize"
    operation = "gegl:posterize"
    params = (ParamSpec("levels", "Levels", "int", 1, 64, 8),)


class GeglMotionBlur(_GeglFilter):
    name = "gegl-motion-blur"
    label = "GEGL Motion Blur"
    operation = "gegl:motion-blur-linear"
    params = (
        ParamSpec("length", "Length", "float", 0.0, 300.0, 20.0),
        ParamSpec("angle", "Angle", "float", -180.0, 180.0, 0.0),
    )


class GeglEdgeSobel(_GeglFilter):
    name = "gegl-edge-sobel"
    label = "GEGL Edge Detect (Sobel)"
    operation = "gegl:edge-sobel"
    params = ()


class GeglRaw(_GeglFilter):
    name = "gegl"
    label = "GEGL Operation"
    params = (
        ParamSpec("operation", "Operation + props", "str", 0, 0, "gegl:pixelize size-x=8,size-y=8"),
    )

    def apply(self, image: QImage, params: dict) -> None:
        text = str(params.get("operation", "")).strip()
        op, _sep, propstext = text.partition(" ")
        props: dict = {}
        if propstext.strip():
            for chunk in propstext.split(","):
                key, sep, val = chunk.partition("=")
                if not sep:
                    raise ValueError(f"gegl: expected key=val, got {chunk!r}")
                val = val.strip()
                try:
                    props[key.strip()] = int(val)
                except ValueError:
                    try:
                        props[key.strip()] = float(val)
                    except ValueError:
                        props[key.strip()] = val
        if not op:
            raise ValueError('gegl: operation name required, e.g. "gegl:vignette radius=1.2"')
        run_gegl(image, op, props)


CURATED: tuple[type[Filter], ...] = (
    GeglVignette,
    GeglBloom,
    GeglPixelize,
    GeglNewsprint,
    GeglPosterize,
    GeglMotionBlur,
    GeglEdgeSobel,
    GeglRaw,
)


def register_all() -> bool:
    """Register the pack when a GEGL-capable interpreter exists."""
    if not gegl_available():
        return False
    for cls in CURATED:
        register_filter(cls)
    return True
