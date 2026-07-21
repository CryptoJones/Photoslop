# SPDX-License-Identifier: Apache-2.0
"""Contextual cursor mapping, rendering, and temporary-pan restoration."""

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.cursors import CursorContext, CursorIntent, CursorRenderer, default_intent
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def _window(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(200, 160), 72.0, "cursor", QColor("white")))
    return win


def test_brush_cursor_tracks_effective_zoomed_diameter():
    intent = default_intent("brush", CursorContext(QPointF(), zoom=2.5), 20)
    assert intent == CursorIntent("brush", diameter=50)


def test_modifier_and_operation_states_are_declarative():
    shift = Qt.KeyboardModifier.ShiftModifier
    alt = Qt.KeyboardModifier.AltModifier
    assert default_intent("rect-select", CursorContext(None, shift)).badge == "+"
    assert default_intent("rect-select", CursorContext(None, alt)).badge == "−"
    assert default_intent("rect-select", CursorContext(None, shift | alt)).badge == "x"
    assert default_intent("zoom", CursorContext(None, alt)).kind == "zoom-out"
    assert default_intent("zoom", CursorContext(None)).kind == "zoom-in"


def test_custom_cursor_renders_at_hidpi_with_center_hotspot(qapp):
    cursor = CursorRenderer().cursor(CursorIntent("brush", diameter=24), 2.0)
    pm = cursor.pixmap()
    assert not pm.isNull()
    assert pm.devicePixelRatio() == 2.0
    assert cursor.hotSpot().x() == cursor.hotSpot().y() == 16


def test_every_toolbar_tool_has_a_nonempty_cursor_intent(qapp):
    win = _window(qapp)
    canvas = win.current_editor().canvas
    for name, tool in win.tools.items():
        intent = tool.cursor_intent(canvas.doc, canvas, QPointF(20, 20))
        assert intent.kind and intent.kind != "tool", name


def test_clone_cursor_reports_source_required_and_source_set(qapp):
    win = _window(qapp)
    canvas = win.current_editor().canvas
    tool = win.tools["clone-stamp"]
    missing = tool.cursor_intent(canvas.doc, canvas, QPointF(20, 20))
    assert missing.valid is False and missing.badge == "!"
    tool._source = QPointF(5, 5)
    assert tool.cursor_intent(canvas.doc, canvas, QPointF(20, 20)).valid is True
    sampling = tool.cursor_intent(
        canvas.doc, canvas, QPointF(20, 20), Qt.KeyboardModifier.AltModifier
    )
    assert sampling.badge == "S"


def test_transform_cursor_hit_tests_handles_body_and_outside(qapp):
    win = _window(qapp)
    canvas = win.current_editor().canvas
    tool = win.tools["transform"]
    tool.begin(canvas.doc, canvas.doc.active_layer)
    assert tool.cursor_intent(canvas.doc, canvas, QPointF(0, 0)).kind == "resize-fdiag"
    assert tool.cursor_intent(canvas.doc, canvas, QPointF(100, 80)).kind == "move"
    assert tool.cursor_intent(canvas.doc, canvas, QPointF(230, 190)).kind == "rotate"


def test_space_pan_restores_exact_contextual_cursor(qapp):
    win = _window(qapp)
    win._set_tool("zoom")
    canvas = win.current_editor().canvas
    canvas.hover_pos = QPointF(10, 10)
    canvas._cursor_modifiers = Qt.KeyboardModifier.AltModifier
    canvas.refresh_cursor()
    before = canvas.cursor_controller.intent
    assert before.kind == "zoom-out"

    canvas._space_pan = True
    canvas.refresh_cursor()
    assert canvas.cursor_controller.intent.kind == "hand-open"
    canvas._pan_last = QPointF(1, 1)
    canvas.refresh_cursor(dragging=True)
    assert canvas.cursor_controller.intent.kind == "hand-closed"

    canvas._space_pan = False
    canvas._pan_last = None
    canvas.refresh_cursor()
    assert canvas.cursor_controller.intent == before
