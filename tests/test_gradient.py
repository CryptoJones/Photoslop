# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(100, 50), 72.0, "g", QColor(255, 255, 255)))
    win.options.foreground = QColor(255, 0, 0)
    win.options.background = QColor(0, 0, 255)
    win.options.opacity = 100
    return win


def drag(tool, doc, canvas, a, b):
    tool.press(doc, canvas, QPointF(*a), None)
    tool.move(doc, canvas, QPointF(*b), None)
    tool.release(doc, canvas, QPointF(*b), None)


def test_linear_gradient_fills_layer(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    win.options.gradient_shape = "linear"
    drag(win.tools["gradient"], doc, editor.canvas, (0, 25), (99, 25))

    img = doc.active_layer.image
    left, mid, right = img.pixelColor(1, 25), img.pixelColor(50, 25), img.pixelColor(98, 25)
    assert left.red() > 240 and left.blue() < 20
    assert right.blue() > 240 and right.red() < 20
    assert 80 < mid.red() < 180 and 80 < mid.blue() < 180  # blended middle

    doc.undo_stack.undo()
    assert img.pixelColor(50, 25) == QColor(255, 255, 255)


def test_radial_gradient(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    win.options.gradient_shape = "radial"
    drag(win.tools["gradient"], doc, editor.canvas, (50, 25), (99, 25))

    img = doc.active_layer.image
    assert img.pixelColor(50, 25).red() > 240  # centre = foreground
    assert img.pixelColor(1, 25).blue() > 200  # far edge ≈ background


def test_gradient_respects_selection(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    path = QPainterPath()
    path.addRect(QRect(10, 10, 30, 20))
    doc.set_selection(path)
    win.options.gradient_shape = "linear"
    drag(win.tools["gradient"], doc, editor.canvas, (10, 20), (40, 20))

    img = doc.active_layer.image
    assert img.pixelColor(15, 15) != QColor(255, 255, 255)  # inside filled
    assert img.pixelColor(60, 30) == QColor(255, 255, 255)  # outside untouched


def test_tiny_drag_is_noop(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    drag(win.tools["gradient"], doc, editor.canvas, (30, 30), (30, 30))
    assert doc.undo_stack.count() == 0
    assert doc.active_layer.image.pixelColor(30, 30) == QColor(255, 255, 255)
