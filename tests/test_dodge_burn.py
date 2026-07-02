# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 40), 72.0, "d", QColor(120, 120, 120)))
    win.options.size = 12
    win.options.hardness = 100
    win.options.opacity = 100
    return win


def stroke(tool, doc, canvas, at: QPointF):
    tool.press(doc, canvas, at, None)
    tool.release(doc, canvas, at, None)


def test_dodge_lightens_and_burn_darkens(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc

    stroke(win.tools["dodge"], doc, editor.canvas, QPointF(10, 10))
    lightened = doc.active_layer.image.pixelColor(10, 10)
    assert lightened.red() > 120

    stroke(win.tools["burn"], doc, editor.canvas, QPointF(30, 30))
    darkened = doc.active_layer.image.pixelColor(30, 30)
    assert darkened.red() < 120

    assert doc.undo_stack.count() == 2
    assert doc.undo_stack.command(0).text() == "Dodge"
    assert doc.undo_stack.command(1).text() == "Burn"
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(10, 10) == QColor(120, 120, 120)
    assert doc.active_layer.image.pixelColor(30, 30) == QColor(120, 120, 120)


def test_strength_follows_opacity(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc

    stroke(win.tools["dodge"], doc, editor.canvas, QPointF(10, 10))
    strong = doc.active_layer.image.pixelColor(10, 10).red()

    win.options.opacity = 25
    stroke(win.tools["dodge"], doc, editor.canvas, QPointF(30, 30))
    weak = doc.active_layer.image.pixelColor(30, 30).red()
    assert 120 < weak < strong
