# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


class _PlainEv:
    def modifiers(self):
        return Qt.KeyboardModifier.NoModifier


class _ShiftEv:
    def modifiers(self):
        return Qt.KeyboardModifier.ShiftModifier


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(200, 150), 72.0, "s", QColor(255, 255, 255))
    small = Layer.blank("chip", QSize(20, 20), QPoint(100, 60))
    small.image.fill(QColor(255, 0, 0))
    doc.layers.append(small)
    doc.active_index = 1
    win.add_document(doc)
    win.set_unit("px")
    return win


def test_snap_layer_to_guide_and_edges(qapp):
    win = make_window(qapp)
    win.snap_enabled = True
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    doc.add_guide("v", 50.0)

    # left edge within 6px of the guide → snaps to 50
    snapped = editor.snap_layer_offset(layer, QPoint(47, 60), _PlainEv().modifiers())
    assert snapped.x() == 50 and snapped.y() == 60
    # right edge near canvas right edge (200) → offset snaps to 180
    snapped = editor.snap_layer_offset(layer, QPoint(176, 60), _PlainEv().modifiers())
    assert snapped.x() == 180
    # top edge near canvas top
    snapped = editor.snap_layer_offset(layer, QPoint(100, 4), _PlainEv().modifiers())
    assert snapped.y() == 0
    # Shift disables
    snapped = editor.snap_layer_offset(layer, QPoint(47, 60), _ShiftEv().modifiers())
    assert snapped == QPoint(47, 60)
    # Snap off disables
    win.snap_enabled = False
    snapped = editor.snap_layer_offset(layer, QPoint(47, 60), _PlainEv().modifiers())
    assert snapped == QPoint(47, 60)


def test_move_tool_drag_snaps(qapp):
    win = make_window(qapp)
    win.snap_enabled = True
    editor = win.current_editor()
    doc = editor.doc
    doc.add_guide("v", 50.0)
    tool = win.tools["move"]

    tool.press(doc, editor.canvas, QPointF(110, 70), None)  # grab the chip layer
    tool.move(doc, editor.canvas, QPointF(58, 70), _PlainEv())  # left edge lands at 48
    assert doc.active_layer.offset.x() == 50  # snapped onto the guide
    tool.release(doc, editor.canvas, QPointF(58, 70), None)


def test_grid_toggle_and_render(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    win._grid_action.setChecked(True)
    assert win.show_grid is True
    win.show()
    qapp.processEvents()
    img = editor.canvas.grab().toImage()
    # grid line at x=20 (px minor tick) should darken the white canvas
    on_line = img.pixelColor(20, 5)
    off_line = img.pixelColor(10, 5)
    assert on_line != off_line
    win._grid_action.setChecked(False)
    assert win.show_grid is False
