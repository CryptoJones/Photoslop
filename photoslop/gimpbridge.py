# SPDX-License-Identifier: Apache-2.0
"""GIMP bridge (#111c) — the escape hatch to everything GIMP can run.

**Spawn-per-call ONLY, per DD-006**: each filter run launches `gimp -i`,
loads one PNG, executes one Script-Fu wrapper, exports, and the process
dies. A resident headless GIMP (200-500 MB RSS) is rejected by design;
if spawn latency (~2-5 s) makes this useless for a workflow, the answer
is "don't use the bridge for that", never "keep GIMP warm".

Curated filters use GIMP 3's drawable-filter API (`gegl:oilify` etc. —
GIMP ships GEGL operations Debian's bare gegl package doesn't). The raw
**GIMP Script-Fu** filter binds `image` and `drawable` and runs whatever
you write — any plug-in, any PDB call, the literal long tail."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from PySide6.QtGui import QImage

from photoslop.filters import Filter, ParamSpec, register_filter

_available: bool | None = None


def gimp_available() -> bool:
    global _available
    if _available is None:
        exe = shutil.which("gimp")
        if exe is None:
            _available = False
        else:
            try:
                out = subprocess.run([exe, "--version"], capture_output=True,
                                     text=True, timeout=30).stdout
                _available = "version 3" in out or "version 2.10" in out
            except (OSError, subprocess.TimeoutExpired):
                _available = False
    return _available


_HARNESS = """(let* ((image (car (gimp-file-load RUN-NONINTERACTIVE "{src}")))
       (drawable (vector-ref (car (gimp-image-get-layers image)) 0)))
  {body}
  (gimp-image-flatten image)
  (gimp-file-save RUN-NONINTERACTIVE image "{dst}")
  (gimp-quit 0))"""


def run_gimp_script(image: QImage, body: str, timeout: int = 180) -> None:
    """Run a Script-Fu body (with `image`/`drawable` bound) on a QImage,
    in place, in a fresh GIMP process that exits when done."""
    if not gimp_available():
        raise ValueError("GIMP bridge: no gimp 3.x/2.10 binary on PATH")
    with tempfile.TemporaryDirectory(prefix="photoslop-gimp-") as tmp:
        src = os.path.join(tmp, "in.png")
        dst = os.path.join(tmp, "out.png")
        image.save(src)
        script = _HARNESS.format(src=src, dst=dst, body=body)
        try:
            # the trailing quit batch is the safety terminator: if the body
            # errors, the harness quit never runs and GIMP would sit forever
            proc = subprocess.run(
                ["gimp", "-i", "-n", "-f", "-d", "-s",
                 "--batch-interpreter=plug-in-script-fu-eval",
                 "-b", script, "-b", "(gimp-quit 1)"],
                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            raise ValueError(
                f"GIMP bridge: timed out after {timeout}s") from exc
        if not os.path.exists(dst):
            err = (proc.stderr or proc.stdout).strip()
            tail = [ln for ln in err.splitlines() if "rror" in ln][-1:] \
                or err.splitlines()[-1:]
            raise ValueError(f"GIMP bridge: {' '.join(tail)[:200]}")
        out = QImage(dst)
    if out.isNull():
        raise ValueError("GIMP bridge: unreadable output")
    if out.size() != image.size():
        out = out.scaled(image.width(), image.height())
    out = out.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    from photoslop.npimage import view_u32

    view_u32(image)[...] = view_u32(out)


def _merge_op(operation: str) -> str:
    return (f'(let ((f (car (gimp-drawable-filter-new drawable '
            f'"{operation}" "")))) (gimp-drawable-merge-filter drawable f))')


class GimpOilify(Filter):
    unsafe = True
    name = "gimp-oilify"
    label = "GIMP Oilify"
    params = ()

    def apply(self, image: QImage, params: dict) -> None:
        run_gimp_script(image, _merge_op("gegl:oilify"))


class GimpSoftglow(Filter):
    unsafe = True
    name = "gimp-softglow"
    label = "GIMP Softglow"
    params = ()

    def apply(self, image: QImage, params: dict) -> None:
        run_gimp_script(image, _merge_op("gegl:softglow"))


class GimpCubism(Filter):
    unsafe = True
    name = "gimp-cubism"
    label = "GIMP Cubism"
    params = ()

    def apply(self, image: QImage, params: dict) -> None:
        run_gimp_script(image, _merge_op("gegl:cubism"))


class GimpScript(Filter):
    unsafe = True
    name = "gimp-script"
    label = "GIMP Script-Fu"
    params = (ParamSpec(
        "script", "Script-Fu body (image/drawable bound)", "str", 0, 0,
        "(gimp-drawable-invert drawable FALSE)"),)

    def apply(self, image: QImage, params: dict) -> None:
        body = str(params.get("script", "")).strip()
        if not body:
            raise ValueError("gimp-script: a Script-Fu body is required")
        run_gimp_script(image, body)


CURATED: tuple[type[Filter], ...] = (
    GimpOilify, GimpSoftglow, GimpCubism, GimpScript,
)


def register_all() -> bool:
    if not gimp_available():
        return False
    for cls in CURATED:
        register_filter(cls)
    return True
