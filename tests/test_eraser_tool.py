# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 40), 72.0, "e", QColor(255, 0, 0)))
    win.options.size = 12
    win.options.hardness = 100
    win.options.opacity = 100
    win.options.eraser = False  # tool must erase regardless of the checkbox
    return win


def stroke(tool, doc, canvas, at: QPointF):
    tool.press(doc, canvas, at, None)
    tool.release(doc, canvas, at, None)


def test_hard_eraser_clears(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc

    stroke(win.tools["eraser"], doc, editor.canvas, QPointF(20, 20))
    assert doc.active_layer.image.pixelColor(20, 20).alpha() == 0
    assert doc.undo_stack.command(0).text() == "Eraser"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(20, 20) == QColor(255, 0, 0)


def test_partial_opacity_fades_alpha(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    win.options.opacity = 40

    stroke(win.tools["eraser"], doc, editor.canvas, QPointF(20, 20))
    remaining = doc.active_layer.image.pixelColor(20, 20).alpha()
    assert 0 < remaining < 255
