# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


class _ShiftEv:
    def modifiers(self):
        return Qt.KeyboardModifier.ShiftModifier


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(30, 30), 72.0, "e", QColor(200, 200, 200))
    top = Layer.blank("half-red", QSize(30, 30))
    top.image.fill(QColor(255, 0, 0))
    top.opacity = 0.5
    doc.layers.append(top)
    doc.active_index = 1
    win.add_document(doc)
    return win


def test_sample_color_composites(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    c = doc.sample_color(10, 10)
    # 50% red over gray → r > g == b, definitely blended, fully opaque
    assert c.alpha() == 255
    assert c.red() > 200 and c.green() < 120
    assert doc.sample_color(-1, 5) is None  # outside canvas


def test_eyedropper_sets_foreground_and_background(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    editor = win.current_editor()
    tool = win.tools["eyedropper"]

    tool.press(doc, editor.canvas, QPointF(10, 10), None)
    fg = win.options.foreground
    assert fg.red() > 200 and fg.alpha() == 255

    tool.press(doc, editor.canvas, QPointF(10, 10), _ShiftEv())
    assert win.options.background == fg  # Shift-click samples into background


def test_swap_and_reset_colors(qapp):
    win = make_window(qapp)
    win.options.foreground = QColor(10, 20, 30)
    win.options.background = QColor(240, 230, 220)
    win.action_swap_colors()
    assert win.options.foreground == QColor(240, 230, 220)
    assert win.options.background == QColor(10, 20, 30)
    win.action_reset_colors()
    assert win.options.foreground == QColor(0, 0, 0)
    assert win.options.background == QColor(255, 255, 255)
