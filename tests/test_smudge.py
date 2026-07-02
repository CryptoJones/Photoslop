# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(80, 40), 72.0, "sm", QColor(255, 255, 255))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(0, 0, 30, 40), QColor(255, 0, 0))  # red left half
    p.end()
    win.add_document(doc)
    win.options.size = 12
    win.options.opacity = 100
    return win


def drag(tool, doc, canvas, a: QPointF, b: QPointF):
    tool.press(doc, canvas, a, None)
    tool.move(doc, canvas, b, None)
    tool.release(doc, canvas, b, None)


def test_smudge_drags_colour_across_boundary(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc

    before = doc.active_layer.image.pixelColor(40, 20)
    assert before == QColor(255, 255, 255)

    drag(win.tools["smudge"], doc, editor.canvas, QPointF(25, 20), QPointF(45, 20))
    smeared = doc.active_layer.image.pixelColor(40, 20)
    assert smeared.red() == 255 and smeared.green() < 250  # red dragged rightward

    assert doc.undo_stack.command(0).text() == "Smudge"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(40, 20) == QColor(255, 255, 255)


def test_low_strength_smears_less(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc

    drag(win.tools["smudge"], doc, editor.canvas, QPointF(25, 20), QPointF(45, 20))
    strong = doc.active_layer.image.pixelColor(38, 20).green()
    doc.undo_stack.undo()

    win.options.opacity = 30
    drag(win.tools["smudge"], doc, editor.canvas, QPointF(25, 20), QPointF(45, 20))
    weak = doc.active_layer.image.pixelColor(38, 20).green()
    assert weak > strong  # weaker smudge leaves the white less reddened
