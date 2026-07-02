# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    """A dark blemish on gray at left; clean gray at right to sample from."""
    win = MainWindow()
    doc = Document.new(QSize(120, 60), 72.0, "pt", QColor(170, 170, 170))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(20, 20, 12, 12), QColor(10, 10, 10))
    p.end()
    win.add_document(doc)
    return win


def select_rect(doc, x, y, w, h):
    path = QPainterPath()
    path.addRect(QRect(x, y, w, h))
    doc.set_selection(path)


def test_patch_drag_heals_selection(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["patch"]
    select_rect(doc, 16, 16, 20, 20)

    tool.press(doc, editor.canvas, QPointF(26, 26), None)
    tool.move(doc, editor.canvas, QPointF(86, 26), None)  # drag to clean area
    tool.release(doc, editor.canvas, QPointF(86, 26), None)

    healed = doc.active_layer.image.pixelColor(26, 26)
    assert healed.red() > 130  # blemish replaced with sampled-clean tone
    assert doc.undo_stack.command(0).text() == "Patch"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(26, 26) == QColor(10, 10, 10)


def test_patch_guards(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["patch"]

    tool.press(doc, editor.canvas, QPointF(26, 26), None)  # no selection: inert
    tool.release(doc, editor.canvas, QPointF(80, 26), None)
    assert doc.undo_stack.count() == 0

    select_rect(doc, 16, 16, 20, 20)
    tool.press(doc, editor.canvas, QPointF(60, 40), None)  # press outside selection
    tool.release(doc, editor.canvas, QPointF(90, 40), None)
    assert doc.undo_stack.count() == 0

    tool.press(doc, editor.canvas, QPointF(26, 26), None)  # sample out of bounds
    tool.release(doc, editor.canvas, QPointF(-40, 26), None)
    assert doc.undo_stack.count() == 0
