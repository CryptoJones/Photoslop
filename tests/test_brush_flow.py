# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(60, 60), 72.0, "f", QColor(255, 255, 255)))
    win.options.size = 14
    win.options.hardness = 100
    win.options.foreground = QColor(0, 0, 0)
    win.options.eraser = False
    return win


def scribble(tool, doc, canvas, center: QPointF, passes=6):
    tool.press(doc, canvas, center, None)
    for i in range(passes):
        tool.move(doc, canvas, center + QPointF(10 if i % 2 else -10, 0), None)
    tool.move(doc, canvas, center, None)
    tool.release(doc, canvas, center, None)


def test_opacity_is_a_stroke_ceiling(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    win.options.opacity = 50
    win.options.flow = 100

    scribble(win.tools["brush"], doc, canvas, QPointF(30, 30))
    # many overlapping stamps in ONE stroke must not exceed the 50% ceiling
    px = doc.active_layer.image.pixelColor(30, 30)
    assert 118 <= px.red() <= 138  # ~50% black over white, not darker


def test_flow_builds_up_within_a_stroke(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    win.options.opacity = 100
    win.options.flow = 30

    tool = win.tools["brush"]
    tool.press(doc, canvas, QPointF(30, 30), None)
    tool.release(doc, canvas, QPointF(30, 30), None)
    single = doc.active_layer.image.pixelColor(30, 30).red()
    doc.undo_stack.undo()

    scribble(tool, doc, canvas, QPointF(30, 30))
    built_up = doc.active_layer.image.pixelColor(30, 30).red()
    assert built_up < single  # repeated low-flow passes darken further

    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(30, 30) == QColor(255, 255, 255)


def test_eraser_ceiling(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    win.options.opacity = 50
    win.options.flow = 100

    scribble(win.tools["eraser"], doc, canvas, QPointF(30, 30))
    alpha = doc.active_layer.image.pixelColor(30, 30).alpha()
    assert 118 <= alpha <= 138  # one stroke erases to the 50% ceiling, no more


def test_cancel_restores_an_in_progress_brush_stroke(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    tool = win.tools["brush"]
    before = doc.active_layer.image.copy()

    tool.press(doc, canvas, QPointF(20, 20), None)
    tool.move(doc, canvas, QPointF(40, 20), None)
    assert doc.active_layer.image != before
    tool.cancel(doc)

    assert doc.active_layer.image == before
    assert doc.undo_stack.count() == 0
    assert not tool.has_active_interaction()
