# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


class _Ev:
    def __init__(self, mods=Qt.KeyboardModifier.NoModifier):
        self._m = mods

    def modifiers(self):
        return self._m


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(200, 160), 72.0, "t", QColor(0, 0, 0, 0))
    chip = Layer.blank("chip", QSize(40, 20), QPoint(80, 70))  # centre (100, 80)
    chip.image.fill(QColor(255, 0, 0))
    doc.layers.append(chip)
    doc.active_index = 1
    win.add_document(doc)
    return win


def test_scale_via_handle_and_commit(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer

    win.action_free_transform()
    assert win.active_tool.name == "transform"
    tool = win.tools["transform"]

    # drag the right edge handle from x=100+20 to x=100+40 → sx = 2
    tool.press(doc, editor.canvas, QPointF(120, 80), _Ev())
    assert tool._mode == "r"
    tool.move(doc, editor.canvas, QPointF(140, 80), _Ev())
    tool.release(doc, editor.canvas, QPointF(140, 80), _Ev())
    tool.commit(editor.canvas)

    assert layer.image.size() == QSize(80, 20)  # doubled width
    assert layer.offset == QPoint(60, 70)  # centre preserved at (100, 80)
    assert win.active_tool.name != "transform"  # tool restored
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert layer.image.size() == QSize(40, 20)
    assert layer.offset == QPoint(80, 70)


def test_rotate_90_and_move(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    win.action_free_transform()
    tool = win.tools["transform"]

    tool.session.rotation = 90.0  # set directly; drag math tested via hit zones
    tool.session.translation = QPointF(10, -5)
    tool.commit(editor.canvas)

    assert layer.image.size() == QSize(20, 40)  # W/H swapped
    assert layer.offset == QPoint(100, 55)  # centre moved to (110, 75)


def test_escape_cancels_exactly(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    before = layer.image.copy()

    win.action_free_transform()
    tool = win.tools["transform"]
    tool.session.scale_x = 3.0
    tool.session.rotation = 45.0
    tool.cancel(doc)
    win.end_transform()

    assert layer.image == before
    assert layer.offset == QPoint(80, 70)
    assert doc.undo_stack.count() == 0
    assert win.active_tool.name != "transform"


def test_hit_zones(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    win.action_free_transform()
    tool = win.tools["transform"]
    assert tool._hit(editor.canvas, QPointF(100, 80)) == "move"  # centre
    assert tool._hit(editor.canvas, QPointF(80, 70)) == "tl"
    assert tool._hit(editor.canvas, QPointF(120, 90)) == "br"
    assert tool._hit(editor.canvas, QPointF(100, 70)) == "t"
    assert tool._hit(editor.canvas, QPointF(170, 20)) == "rotate"  # far outside
    tool.cancel(editor.doc)
    win.end_transform()


def test_identity_commit_pushes_nothing(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    win.action_free_transform()
    win.tools["transform"].commit(editor.canvas)
    assert doc.undo_stack.count() == 0
