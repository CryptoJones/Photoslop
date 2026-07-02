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
    doc = Document.new(QSize(100, 60), 72.0, "q", QColor(255, 255, 255))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(10, 10, 30, 30), QColor(255, 0, 0))
    p.fillRect(QRect(40, 10, 30, 30), QColor(0, 0, 255))  # touching the red box
    p.end()
    win.add_document(doc)
    win.options.tolerance = 0
    win.options.size = 16
    return win


def test_drag_grows_across_regions(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["quick-select"]

    tool.press(doc, editor.canvas, QPointF(15, 20), None)
    assert doc.selection_bounds() == QRect(10, 10, 30, 30)  # red only

    tool.move(doc, editor.canvas, QPointF(50, 20), None)  # sweep into blue
    tool.release(doc, editor.canvas, QPointF(50, 20), None)
    assert doc.selection_bounds() == QRect(10, 10, 60, 30)  # both regions


def test_plain_drag_adds_alt_drag_subtracts(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["quick-select"]

    tool.press(doc, editor.canvas, QPointF(15, 20), None)
    tool.release(doc, editor.canvas, QPointF(15, 20), None)
    tool.press(doc, editor.canvas, QPointF(50, 20), None)  # second gesture adds
    tool.release(doc, editor.canvas, QPointF(50, 20), None)
    assert doc.selection_bounds() == QRect(10, 10, 60, 30)

    tool.press(doc, editor.canvas, QPointF(50, 20), _AltEv())  # subtract blue
    tool.release(doc, editor.canvas, QPointF(50, 20), _AltEv())
    assert doc.selection_bounds() == QRect(10, 10, 30, 30)


def test_out_of_layer_seed_is_noop(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["quick-select"]
    tool.press(doc, editor.canvas, QPointF(-10, -10), None)
    tool.release(doc, editor.canvas, QPointF(-10, -10), None)
    assert doc.selection is None
