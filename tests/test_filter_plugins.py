# SPDX-License-Identifier: Apache-2.0
"""Filter plugin framework (#109): registry, params, GUI, CLI, smart replay."""

import numpy as np
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop import cli, filters
from photoslop.document import Document
from photoslop.filters import (
    Filter,
    ParamSpec,
    available_filters,
    parse_params,
    register_filter,
)
from photoslop.npimage import view_u32


def test_built_ins_discovered(qapp):
    reg = available_filters()
    assert "sepia" in reg and "pixelate" in reg


def test_register_rejects_anonymous(qapp):
    class Nameless(Filter):
        pass

    with pytest.raises(ValueError):
        register_filter(Nameless)


def test_parse_params_defaults_validation_and_errors(qapp):
    cls = available_filters()["sepia"]
    assert parse_params(cls, "") == {"amount": 80}
    assert parse_params(cls, "amount=25") == {"amount": 25}
    with pytest.raises(ValueError):
        parse_params(cls, "amount=200")      # out of range
    with pytest.raises(ValueError):
        parse_params(cls, "strength=5")      # unknown key


def test_sepia_desaturates_toward_brown(qapp):
    img = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(30, 90, 220))            # a blue
    filters.SepiaFilter().apply(img, {"amount": 100})
    c = img.pixelColor(1, 1)
    assert c.red() > c.blue()                 # warm tone


def test_pixelate_makes_blocks(qapp):
    img = QImage(16, 16, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(16):
        for y in range(16):
            img.setPixelColor(x, y, QColor(x * 16, y * 16, 0))
    filters.PixelateFilter().apply(img, {"size": 8})
    assert img.pixelColor(1, 1) == img.pixelColor(6, 6)   # same block
    assert img.pixelColor(1, 1) != img.pixelColor(14, 14)  # different block


def test_cli_filter_op_and_unknown_name(qapp, tmp_path):
    out = str(tmp_path / "sepia.png")
    assert cli.main(["--new", "20x20", "--fill", "30,90,220",
                     "--filter", "sepia:amount=100", "--output", out]) == 0
    c = QImage(out).pixelColor(10, 10)
    assert c.red() > c.blue()
    with pytest.raises(SystemExit) as exc:
        cli.main(["--new", "8x8", "--filter", "nope", "--output",
                  str(tmp_path / "x.png")])
    assert exc.value.code == 2


def test_cli_filter_selection_aware(qapp, tmp_path):
    out = str(tmp_path / "half.png")
    assert cli.main(["--new", "40x20", "--fill", "30,90,220",
                     "--select", "0,0,20,20", "--filter", "sepia:amount=100",
                     "--deselect", "--output", out]) == 0
    img = QImage(out)
    left, right = img.pixelColor(5, 10), img.pixelColor(35, 10)
    assert left.red() > left.blue()
    assert right == QColor(30, 90, 220)


def test_filter_menu_autopopulates(qapp):
    from photoslop.mainwindow import MainWindow

    win = MainWindow()
    # resolve texts while the wrappers are alive (shiboken GC trap)
    for act in win.menuBar().actions():
        if act.text() == "Fi&lter":
            texts = [a.text().replace("&", "")
                     for a in act.menu().actions() if a.text()]
            break
    else:
        raise AssertionError("no Filter menu")
    assert "Sepia…" in texts and "Pixelate…" in texts


def test_params_dialog_generated_from_specs(qapp):
    from photoslop.filterdialog import FilterParamsDialog

    dlg = FilterParamsDialog(filters.SepiaFilter)
    assert dlg.values() == {"amount": 80}
    dlg._boxes["amount"].setValue(33)
    assert dlg.values() == {"amount": 33}


def test_smart_filter_replay_includes_plugins(qapp):
    from photoslop.mainwindow import MainWindow

    win = MainWindow()
    doc = Document.new(QSize(20, 20), 72.0, "sf", QColor(30, 90, 220))
    win.add_document(doc)
    layer = doc.active_layer
    win.action_convert_smart()
    win.apply_plugin_filter("sepia", {"amount": 100})
    assert ("filter", "sepia", (("amount", 100),)) in layer.smart_filters
    toned = QImage(layer.image)
    win.action_reapply_smart_filters()
    assert layer.image == toned  # restore + replay reproduces the result


def test_third_party_registration_flows_everywhere(qapp, tmp_path):
    class Redshift(Filter):
        name = "redshift-test"
        label = "Redshift"
        params = (ParamSpec("boost", "Boost", "int", 0, 100, 50),)

        def apply(self, image: QImage, params: dict) -> None:
            arr = view_u32(image)
            r = ((arr >> np.uint32(16)) & 0xFF).astype(np.uint32)
            r = np.minimum(255, r + int(params["boost"]))
            arr &= ~np.uint32(np.uint32(0xFF) << np.uint32(16))
            arr |= r << np.uint32(16)

    register_filter(Redshift)
    try:
        out = str(tmp_path / "red.png")
        assert cli.main(["--new", "8x8", "--fill", "10,10,10",
                         "--filter", "redshift-test:boost=90",
                         "--output", out]) == 0
        assert QImage(out).pixelColor(4, 4).red() == 100
    finally:
        filters._REGISTRY.pop("redshift-test", None)
