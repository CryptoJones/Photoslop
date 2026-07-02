# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "k", QColor(255, 255, 255)))
    return win


def test_bracket_size_steps(qapp):
    win = make_window(qapp)
    win._size_spin.setValue(5)
    win._step_brush_size(+1)
    assert win.options.size == 6  # <10 → ±1
    win._size_spin.setValue(10)
    win._step_brush_size(+1)
    assert win.options.size == 15  # ≥10 → ±5
    win._step_brush_size(-1)
    assert win.options.size == 10
    win._step_brush_size(-1)
    assert win.options.size == 9  # at 10 going down → ±1
    win._size_spin.setValue(60)
    win._step_brush_size(+1)
    assert win.options.size == 70  # ≥50 → ±10
    win._size_spin.setValue(1)
    win._step_brush_size(-1)
    assert win.options.size == 1  # clamped

    # spinbox stays in sync (it drives options)
    assert win._size_spin.value() == win.options.size


def test_bracket_hardness_steps(qapp):
    win = make_window(qapp)
    win._hardness_spin.setValue(100)
    win._step_brush_hardness(-1)
    assert win.options.hardness == 75
    win._step_brush_hardness(-1)
    win._step_brush_hardness(-1)
    win._step_brush_hardness(-1)
    assert win.options.hardness == 0
    win._step_brush_hardness(-1)
    assert win.options.hardness == 0  # clamped
    win._step_brush_hardness(+1)
    assert win.options.hardness == 25
