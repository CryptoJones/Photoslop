# SPDX-License-Identifier: Apache-2.0
"""G'MIC filter pack (#111a) — skip-if-missing per DD-001."""

import pytest
from PySide6.QtGui import QColor, QImage

from photoslop import cli, gmicpack
from photoslop.filters import available_filters, parse_params

HAVE_GMIC = gmicpack.gmic_available()
needs_gmic = pytest.mark.skipif(not HAVE_GMIC, reason="photoslop[gmic] not installed")


def _grad(n=48):
    img = QImage(n, n, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(n):
        for y in range(n):
            img.setPixelColor(x, y, QColor((x * 5) % 256, 128, (y * 5) % 256))
    return img


@needs_gmic
def test_pack_registers_when_available(qapp):
    reg = available_filters(allow_unsafe=True)
    for name in ("gmic", "gmic-cartoon", "gmic-old-photo", "gmic-drawing",
                 "gmic-stencil", "gmic-spread", "gmic-solarize", "gmic-smooth"):
        assert name in reg


def test_pack_absent_is_silent(qapp, monkeypatch):
    monkeypatch.setattr(gmicpack, "gmic_available", lambda: False)
    assert gmicpack.register_all() is False


@needs_gmic
def test_raw_command_deterministic_and_alpha_safe(qapp):
    img = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 60, 40))
    gmicpack.run_gmic(img, "add 10")
    c = img.pixelColor(8, 8)
    assert (c.red(), c.green(), c.blue(), c.alpha()) == (210, 70, 50, 255)
    semi = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    semi.fill(QColor(100, 50, 25, 128))
    gmicpack.run_gmic(semi, "solarize 60")
    assert abs(semi.pixelColor(4, 4).alpha() - 128) <= 1


@needs_gmic
def test_every_curated_filter_produces_output(qapp):
    reg = available_filters(allow_unsafe=True)
    for cls in gmicpack.CURATED:
        img = _grad()
        cls().apply(img, parse_params(reg[cls.name], ""))
        vals = {img.pixelColor(p, p).red() for p in (8, 20, 32, 44)}
        assert vals != {0}, f"{cls.name} produced black output"


@needs_gmic
def test_gmic_error_is_a_clean_usage_error(qapp):
    img = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(1, 2, 3))
    with pytest.raises(ValueError):
        gmicpack.run_gmic(img, "definitely_not_a_command_xyz")


@needs_gmic
def test_cli_gmic_raw_with_commas(qapp, tmp_path):
    # the single-str-param parse keeps commas: "command=add 10" style
    out = str(tmp_path / "g.png")
    assert cli.main(["--allow-unsafe-plugins", "--new", "20x20", "--fill", "10,20,30",
                     "--filter", "gmic:command=add 40", "--output", out]) == 0
    c = QImage(out).pixelColor(10, 10)
    assert (c.red(), c.green(), c.blue()) == (50, 60, 70)


@needs_gmic
def test_cli_curated_selection_aware(qapp, tmp_path):
    out = str(tmp_path / "sol.png")
    assert cli.main(["--allow-unsafe-plugins", "--new", "40x20", "--fill", "200,200,200",
                     "--select", "0,0,20,20",
                     "--filter", "gmic-solarize:threshold=128",
                     "--deselect", "--output", out]) == 0
    img = QImage(out)
    assert img.pixelColor(35, 10) == QColor(200, 200, 200)  # outside untouched
    assert img.pixelColor(5, 10) != QColor(200, 200, 200)   # inside solarized


@needs_gmic
def test_str_param_dialog_uses_line_edit(qapp):
    from PySide6.QtWidgets import QLineEdit

    from photoslop.filterdialog import FilterParamsDialog

    dlg = FilterParamsDialog(gmicpack.GmicRaw)
    assert isinstance(dlg._boxes["command"], QLineEdit)
    dlg._boxes["command"].setText("blur 2,1")
    assert dlg.values() == {"command": "blur 2,1"}
