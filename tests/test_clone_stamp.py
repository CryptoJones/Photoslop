# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


class _AltEv:
    def modifiers(self):
        return Qt.KeyboardModifier.AltModifier


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(100, 60), 72.0, "s", QColor(255, 255, 255))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(5, 5, 12, 12), QColor(255, 0, 0))  # distinctive source patch
    p.end()
    win.add_document(doc)
    win.options.size = 10
    win.options.opacity = 100
    return win


def stroke(tool, doc, canvas, at: QPointF):
    tool.press(doc, canvas, at, None)
    tool.release(doc, canvas, at, None)


def test_clone_copies_source_aligned(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["clone-stamp"]

    tool.press(doc, editor.canvas, QPointF(11, 11), _AltEv())  # set source in the patch
    assert doc.undo_stack.count() == 0  # Alt-click paints nothing

    stroke(tool, doc, editor.canvas, QPointF(60, 30))  # clone patch centre → (60, 30)
    img = doc.active_layer.image
    assert img.pixelColor(60, 30) == QColor(255, 0, 0)
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.command(0).text() == "Clone Stamp"

    # aligned mode: a second stroke +8px right samples source +8px right,
    # which is outside the 12px patch → white
    stroke(tool, doc, editor.canvas, QPointF(72, 30))
    assert img.pixelColor(72, 30) == QColor(255, 255, 255)

    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert img.pixelColor(60, 30) == QColor(255, 255, 255)


def test_no_source_is_noop(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["clone-stamp"]
    stroke(tool, doc, editor.canvas, QPointF(60, 30))
    assert doc.undo_stack.count() == 0
    assert doc.active_layer.image.pixelColor(60, 30) == QColor(255, 255, 255)
