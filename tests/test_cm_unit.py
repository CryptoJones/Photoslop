# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop import units
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_cm_conversions(qapp):
    assert units.px_per_unit("cm", 254.0) == 100.0  # 254 dpi -> 100 px/cm
    assert units.px_to_unit(100.0, "cm", 254.0) == 1.0
    assert units.unit_to_px(2.5, "cm", 254.0) == 250.0
    assert units.format_value_precise(127.0, "cm", 254.0) == "1.27 cm"
    assert units.unit_label("cm") == "centimetres"
    assert 10 * units.px_per_unit("mm", 300.0) == units.px_per_unit("cm", 300.0) * 1


def test_cm_selectable_and_rulers_follow(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(50, 50), 72.0, "u", QColor(255, 255, 255)))
    win.show()
    assert "cm" in units.UNITS
    assert "cm" in win._unit_actions  # View/Options → Rulers menu offers it

    win.set_unit("cm")
    editor = win.current_editor()
    win.repaint()
    assert editor.hruler.unit == "cm"
    assert editor.corner.text() == "cm"
    win.set_unit("mm")  # and straight back — the metric switch CJ asked for
    assert editor.hruler.unit == "mm"
    win.close()
