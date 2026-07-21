# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(100, 80), 72.0, "sh", QColor(255, 255, 255)))
    win.options.foreground = QColor(200, 30, 30)
    win.options.size = 6
    return win


def drag(win, tool, a, b):
    doc, canvas = win.current_doc(), win.current_editor().canvas
    tool.press(doc, canvas, QPointF(*a), None)
    tool.move(doc, canvas, QPointF(*b), None)
    tool.release(doc, canvas, QPointF(*b), None)


def test_rect_shape_lands_on_new_bounded_layer(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    tool = win.tools["shape"]

    drag(win, tool, (20, 20), (60, 50))
    assert len(doc.layers) == 2
    layer = doc.layers[1]
    assert layer.name.startswith("Shape")
    assert layer.offset == QPoint(18, 18)  # bounded to the shape, not canvas
    assert layer.image.width() <= 46 and layer.image.height() <= 36
    flat = doc.flatten()
    assert flat.pixelColor(40, 35) == QColor(200, 30, 30)  # inside
    assert flat.pixelColor(10, 10) == QColor(255, 255, 255)  # outside

    doc.undo_stack.undo()
    assert len(doc.layers) == 1  # one undo removes the whole shape


def test_ellipse_line_and_cycle(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    tool = win.tools["shape"]

    win.options.shape = "ellipse"
    drag(win, tool, (10, 10), (50, 40))
    flat = doc.flatten()
    assert flat.pixelColor(30, 25) == QColor(200, 30, 30)  # centre filled
    corner = flat.pixelColor(12, 12)
    assert corner.green() > 200  # ellipse leaves the corner white

    win.options.shape = "line"
    drag(win, tool, (20, 60), (80, 60))
    assert doc.flatten().pixelColor(50, 60) == QColor(200, 30, 30)

    win.options.shape = "rect"
    win._cycle_shape()
    assert win.options.shape == "ellipse"
    assert win._active_tool_name == "shape"
    win._cycle_shape()
    win._cycle_shape()
    assert win.options.shape == "rect"

    tiny = win.tools["shape"]  # sub-3px drags are ignored
    drag(win, tiny, (5, 5), (6, 6))
    assert len(doc.layers) == 3
