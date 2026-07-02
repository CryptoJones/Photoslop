# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(100, 80), 72.0, "c", QColor(255, 255, 255)))
    return win


def drag(tool, doc, canvas, a: QPointF, b: QPointF):
    tool.press(doc, canvas, a, None)
    tool.move(doc, canvas, b, None)
    tool.release(doc, canvas, b, None)


def test_crop_commit_and_undo(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    drag(tool, doc, editor.canvas, QPointF(20, 10), QPointF(70, 60))
    assert tool.rect == QRect(20, 10, 50, 50)

    tool.commit(editor.canvas)
    assert doc.size == QSize(50, 50)
    assert doc.layers[0].offset == QPoint(-20, -10)  # shifted, not copied
    assert tool.rect is None
    assert doc.undo_stack.command(0).text() == "Crop"

    doc.undo_stack.undo()
    assert doc.size == QSize(100, 80)
    assert doc.layers[0].offset == QPoint(0, 0)


def test_crop_clamps_and_escape_clears(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    drag(tool, doc, editor.canvas, QPointF(80, 60), QPointF(200, 200))
    assert tool.rect == QRect(80, 60, 20, 20)  # clamped to canvas

    tool.cancel(doc)
    assert tool.rect is None
    tool.commit(editor.canvas)  # no rect: no-op
    assert doc.undo_stack.count() == 0

    drag(tool, doc, editor.canvas, QPointF(10, 10), QPointF(11, 11))
    assert tool.rect is None  # sub-2px drags are discarded
