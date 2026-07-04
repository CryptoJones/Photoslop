# SPDX-License-Identifier: Apache-2.0
"""GIMP bridge (#111c) — spawn-per-call per DD-006; skip-if-missing.
Each test spawns a real GIMP (~seconds), so the set stays small."""

import pytest
from PySide6.QtGui import QColor, QImage

from photoslop import cli, gimpbridge
from photoslop.filters import available_filters

HAVE_GIMP = gimpbridge.gimp_available()
needs_gimp = pytest.mark.skipif(not HAVE_GIMP, reason="no gimp binary on PATH")


@needs_gimp
def test_bridge_registers_when_available(qapp):
    reg = available_filters()
    for name in ("gimp-script", "gimp-oilify", "gimp-softglow", "gimp-cubism"):
        assert name in reg


def test_bridge_absent_is_silent(qapp, monkeypatch):
    monkeypatch.setattr(gimpbridge, "gimp_available", lambda: False)
    assert gimpbridge.register_all() is False
    img = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(1, 2, 3))
    with pytest.raises(ValueError):
        gimpbridge.run_gimp_script(img, "(gimp-drawable-invert drawable FALSE)")


@needs_gimp
def test_raw_script_deterministic_invert(qapp):
    img = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 60, 40))
    gimpbridge.GimpScript().apply(
        img, {"script": "(gimp-drawable-invert drawable FALSE)"})
    c = img.pixelColor(8, 8)
    assert (c.red(), c.green(), c.blue()) == (55, 195, 215)


@needs_gimp
def test_script_error_is_clean_and_empty_rejected(qapp):
    img = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(9, 9, 9))
    with pytest.raises(ValueError):
        gimpbridge.GimpScript().apply(img, {"script": ""})
    with pytest.raises(ValueError):
        gimpbridge.run_gimp_script(img, "(this-is-not-a-procedure 1)",
                                   timeout=45)


@needs_gimp
def test_cli_bridge_selection_aware(qapp, tmp_path):
    out = str(tmp_path / "inv.png")
    assert cli.main([
        "--new", "40x20", "--fill", "200,60,40",
        "--select", "0,0,20,20",
        "--filter", "gimp-script:script=(gimp-drawable-invert drawable FALSE)",
        "--deselect", "--output", out]) == 0
    img = QImage(out)
    left, right = img.pixelColor(5, 10), img.pixelColor(35, 10)
    assert (left.red(), left.green(), left.blue()) == (55, 195, 215)
    assert right == QColor(200, 60, 40)
