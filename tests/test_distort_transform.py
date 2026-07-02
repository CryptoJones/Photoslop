# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


class _CtrlEv:
    def modifiers(self):
        return Qt.KeyboardModifier.ControlModifier


class _Ev:
    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(200, 160), 72.0, "d", QColor(0, 0, 0, 0))
    chip = Layer.blank("chip", QSize(40, 20), QPoint(80, 70))
    chip.image.fill(QColor(255, 0, 0))
    doc.layers.append(chip)
    doc.active_index = 1
    win.add_document(doc)
    return win


def test_ctrl_corner_distorts_and_commits(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    win.action_free_transform()
    tool = win.tools["transform"]

    # Ctrl+drag the BR corner from (120, 90) out to (140, 110)
    tool.press(doc, editor.canvas, QPointF(120, 90), _CtrlEv())
    assert tool._mode == "quad:br"
    tool.move(doc, editor.canvas, QPointF(140, 110), _CtrlEv())
    tool.release(doc, editor.canvas, QPointF(140, 110), _CtrlEv())
    assert tool.session.quad is not None

    tool.commit(editor.canvas)
    # bounding box: TL still (80,70), BR now (140,110)
    assert layer.offset == QPoint(80, 70)
    assert abs(layer.image.width() - 60) <= 1
    assert abs(layer.image.height() - 40) <= 1
    doc.undo_stack.undo()
    assert layer.image.size() == QSize(40, 20)
    assert layer.offset == QPoint(80, 70)


def test_ctrl_edge_skews(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    win.action_free_transform()
    tool = win.tools["transform"]

    # Ctrl+drag the top edge 10px right → parallelogram
    tool.press(doc, editor.canvas, QPointF(100, 70), _CtrlEv())
    assert tool._mode == "quad:t"
    tool.move(doc, editor.canvas, QPointF(110, 70), _CtrlEv())
    tool.release(doc, editor.canvas, QPointF(110, 70), _CtrlEv())
    quad = tool.session.quad
    assert quad[0] == QPointF(90, 70) and quad[1] == QPointF(130, 70)
    assert quad[3] == QPointF(80, 90)  # bottom edge unmoved

    tool.commit(editor.canvas)
    assert abs(layer.image.width() - 50) <= 1  # skew widens the bbox by 10
    assert abs(layer.image.height() - 20) <= 1
    # skewed content: bottom-left corner region opaque, top-left transparent
    assert layer.image.pixelColor(2, layer.image.height() - 3).alpha() > 0
    assert layer.image.pixelColor(2, 2).alpha() == 0


def test_quad_move_translates_whole_quad(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    win.action_free_transform()
    tool = win.tools["transform"]

    tool.press(doc, editor.canvas, QPointF(80, 70), _CtrlEv())  # TL: enter quad
    tool.release(doc, editor.canvas, QPointF(80, 70), _CtrlEv())
    tool.press(doc, editor.canvas, QPointF(100, 80), _Ev())  # inside: move
    assert tool._mode == "move"
    tool.move(doc, editor.canvas, QPointF(105, 85), _Ev())
    tool.release(doc, editor.canvas, QPointF(105, 85), _Ev())
    assert tool.session.quad[0] == QPointF(85, 75)

    tool.cancel(doc)
    win.end_transform()
    assert doc.active_layer.offset == QPoint(80, 70)
    assert doc.undo_stack.count() == 0
