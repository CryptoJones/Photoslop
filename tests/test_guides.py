# SPDX-License-Identifier: Apache-2.0
"""Guide-drag feedback: ruler markers, the floating X/Y label, status echo."""

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop import units
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(200, 150), 72.0, "g", QColor(255, 255, 255)))
    return win


def test_format_value_precise():
    assert units.format_value_precise(90.0, "px", 72) == "90.0 px"
    assert units.format_value_precise(72.0, "in", 72) == "1.00 in"
    assert units.format_value_precise(72.0, "pc", 72) == "6.00 pc"
    assert units.format_value_precise(25.4, "mm", 25.4) == "25.40 mm"


def test_show_guide_feedback_sets_ruler_and_label(qapp):
    win = make_window(qapp)
    editor = win.current_editor()

    editor.show_guide_feedback("h", 90.0)
    assert editor.vruler.guide_marker == 90.0  # y lives on the vertical ruler
    assert editor.hruler.guide_marker is None
    orient, value, _anchor = editor.canvas.guide_label
    assert orient == "h" and value == 90.0

    editor.show_guide_feedback("v", 40.0)
    assert editor.hruler.guide_marker == 40.0
    assert editor.vruler.guide_marker is None

    editor.clear_guide_feedback()
    assert editor.hruler.guide_marker is None
    assert editor.vruler.guide_marker is None
    assert editor.canvas.guide_label is None


def test_move_tool_guide_drag_updates_feedback(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    doc.add_guide("h", 50.0)

    tool = win.tools["move"]
    tool.press(doc, editor.canvas, QPointF(30, 50), None)
    tool.move(doc, editor.canvas, QPointF(30, 72.5), None)
    assert doc.guides_h[0] == 72.5
    assert editor.vruler.guide_marker == 72.5
    assert editor.canvas.guide_label[1] == 72.5

    tool.release(doc, editor.canvas, QPointF(30, 72.5), None)
    assert editor.vruler.guide_marker is None
    assert editor.canvas.guide_label is None
    assert doc.guides_h == [72.5]  # dropped inside the canvas: guide stays


def test_guide_drag_off_canvas_still_removes(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    doc.add_guide("v", 60.0)

    tool = win.tools["move"]
    tool.press(doc, editor.canvas, QPointF(60, 40), None)
    tool.move(doc, editor.canvas, QPointF(-30, 40), None)
    tool.release(doc, editor.canvas, QPointF(-30, 40), None)
    assert doc.guides_v == []
    assert editor.canvas.guide_label is None
