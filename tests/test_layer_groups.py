# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(100, 80), 72.0, "g", QColor(255, 255, 255))
    for name, offset in (("a", QPoint(10, 10)), ("b", QPoint(40, 30))):
        layer = Layer.blank(name, QSize(20, 20), offset)
        layer.image.fill(QColor(255, 0, 0))
        doc.layers.append(layer)
    doc.active_index = 2  # "b"
    win.add_document(doc)
    return win


def test_group_ungroup_undo(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    a, b = doc.layers[1], doc.layers[2]

    win.action_group_layer()  # groups b with a
    assert a.group == b.group == "Group 1"

    doc.undo_stack.undo()
    assert a.group is None and b.group is None
    doc.undo_stack.redo()
    assert a.group == "Group 1"

    win.action_ungroup_layer()  # b leaves
    assert b.group is None and a.group == "Group 1"


def test_move_tool_drags_group_together(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    a, b = doc.layers[1], doc.layers[2]
    win.action_group_layer()
    win.snap_enabled = False

    tool = win.tools["move"]
    tool.press(doc, editor.canvas, QPointF(50, 40), None)  # inside b
    tool.move(doc, editor.canvas, QPointF(57, 45), None)
    tool.release(doc, editor.canvas, QPointF(57, 45), None)

    assert b.offset == QPoint(47, 35)
    assert a.offset == QPoint(17, 15)  # a came along
    doc.undo_stack.undo()  # undo the group move (one step)
    assert b.offset == QPoint(40, 30) and a.offset == QPoint(10, 10)


def test_group_round_trips_ora(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()
    win.action_group_layer()

    path = str(tmp_path / "grouped.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert [layer.group for layer in loaded.layers] == [None, "Group 1", "Group 1"]
    assert loaded.layers[1].clone().group == "Group 1"
