# SPDX-License-Identifier: Apache-2.0
"""GEGL filter pack (#111b) — skip-if-missing; worker is spawn-per-call."""

import pytest
from PySide6.QtGui import QColor, QImage

from photoslop import cli, geglpack
from photoslop.filters import available_filters, parse_params

HAVE_GEGL = geglpack.gegl_available()
needs_gegl = pytest.mark.skipif(
    not HAVE_GEGL, reason="no GEGL-capable python (python3-gi + gir1.2-gegl)"
)


def _grad(n=48):
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(n):
        for y in range(n):
            img.setPixelColor(x, y, QColor((x * 5) % 256, 128, (y * 5) % 256))
    return img


@needs_gegl
def test_pack_registers_when_available(qapp):
    reg = available_filters(allow_unsafe=True)
    for name in (
        "gegl",
        "gegl-vignette",
        "gegl-bloom",
        "gegl-pixelize",
        "gegl-newsprint",
        "gegl-posterize",
        "gegl-motion-blur",
        "gegl-edge-sobel",
    ):
        assert name in reg


def test_pack_absent_is_silent(qapp, monkeypatch):
    monkeypatch.setattr(geglpack, "gegl_available", lambda: False)
    assert geglpack.register_all() is False


@needs_gegl
def test_posterize_reduces_levels(qapp):
    img = _grad()
    geglpack.GeglPosterize().apply(img, {"levels": 2})
    vals = {img.pixelColor(p, p).red() for p in range(0, 48, 4)}
    assert len(vals) <= 4


@needs_gegl
def test_every_curated_filter_produces_output(qapp):
    reg = available_filters(allow_unsafe=True)
    for cls in geglpack.CURATED:
        img = _grad()
        cls().apply(img, parse_params(reg[cls.name], ""))
        assert img.width() == 48  # ran and wrote back at original size


@needs_gegl
def test_raw_operation_with_props_and_errors(qapp):
    img = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(30, 200, 90))
    geglpack.GeglRaw().apply(img, {"operation": "gegl:pixelize size-x=8,size-y=8"})
    assert img.pixelColor(16, 16).green() == 200  # flat stays flat
    with pytest.raises(ValueError):
        geglpack.GeglRaw().apply(img, {"operation": ""})
    with pytest.raises(ValueError):
        geglpack.run_gegl(img, "gegl:not-a-real-op", {})


@needs_gegl
def test_cli_gegl_selection_aware(qapp, tmp_path):
    out = str(tmp_path / "post.png")
    assert (
        cli.main(
            [
                "--allow-unsafe-plugins",
                "--new",
                "40x20",
                "--fill",
                "97,140,203",
                "--select",
                "0,0,20,20",
                "--filter",
                "gegl-posterize:levels=2",
                "--deselect",
                "--output",
                out,
            ]
        )
        == 0
    )
    img = QImage(out)
    assert img.pixelColor(35, 10) == QColor(97, 140, 203)  # untouched half
    assert img.pixelColor(5, 10) != QColor(97, 140, 203)  # posterized half


def test_worker_probe_handles_no_interpreter(qapp, monkeypatch):
    import photoslop.geglpack as gp

    monkeypatch.setattr(gp, "_worker", None)
    img = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(1, 2, 3))
    with pytest.raises(ValueError):
        gp.run_gegl(img, "gegl:posterize", {"levels": 2})
