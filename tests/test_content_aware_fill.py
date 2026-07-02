# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(60, 60), 72.0, "caf", QColor(200, 200, 200))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(25, 25, 10, 10), QColor(0, 0, 0))  # object to remove
    p.end()
    win.add_document(doc)
    return win


def test_content_aware_fill_removes_selection(qapp):
    win = make_window(qapp)
    doc = win.current_doc()

    win.action_content_aware_fill()  # no selection: refused
    assert doc.undo_stack.count() == 0

    path = QPainterPath()
    path.addRect(QRect(22, 22, 16, 16))
    doc.set_selection(path)
    win.action_content_aware_fill()

    healed = doc.active_layer.image.pixelColor(30, 30)
    assert healed.red() > 170  # black object replaced by surround-like gray
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(200, 200, 200)
    assert doc.undo_stack.command(0).text() == "Content-Aware Fill"

    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(30, 30) == QColor(0, 0, 0)
    doc.undo_stack.redo()
    assert doc.active_layer.image.pixelColor(30, 30).red() > 170
