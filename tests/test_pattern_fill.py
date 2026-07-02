# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(64, 64), 72.0, "p", QColor(255, 255, 255))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(0, 0, 4, 4), QColor(255, 0, 0))  # checker cell
    p.fillRect(QRect(4, 4, 4, 4), QColor(255, 0, 0))
    p.end()
    win.add_document(doc)
    win.options.tolerance = 0
    win.options.opacity = 100
    return win


def test_define_pattern_needs_selection_then_captures(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    win.action_define_pattern()
    assert win.options.pattern is None  # refused without a selection

    path = QPainterPath()
    path.addRect(QRect(0, 0, 8, 8))
    doc.set_selection(path)
    win.action_define_pattern()
    assert win.options.pattern is not None
    assert win.options.pattern.size() == QSize(8, 8)
    assert win.options.pattern.pixelColor(1, 1) == QColor(255, 0, 0)


def test_bucket_tiles_pattern(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    path = QPainterPath()
    path.addRect(QRect(0, 0, 8, 8))
    doc.set_selection(path)
    win.action_define_pattern()
    doc.set_selection(None)

    win.options.fill_source = "pattern"
    tool = win.tools["bucket"]
    tool.press(doc, win.current_editor().canvas, QPointF(40, 40), None)  # white region

    img = doc.active_layer.image
    # the 8px checker tiles across the filled area (brush anchored at 0,0)
    assert img.pixelColor(41, 41) == QColor(255, 0, 0)  # tile coord (1,1): red cell
    assert img.pixelColor(45, 41) == QColor(255, 255, 255)  # tile coord (5,1): white
    assert doc.undo_stack.command(0).text() == "Paint Bucket"
    doc.undo_stack.undo()
    assert img.pixelColor(41, 41) == QColor(255, 255, 255)
