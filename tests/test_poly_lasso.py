# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(100, 80), 72.0, "p", QColor(255, 255, 255)))
    return win


def test_poly_lasso_click_to_close(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["poly-lasso"]

    tool.press(doc, editor.canvas, QPointF(10, 10), None)
    tool.press(doc, editor.canvas, QPointF(60, 10), None)
    tool.press(doc, editor.canvas, QPointF(60, 50), None)
    tool.press(doc, editor.canvas, QPointF(10, 50), None)
    tool.press(doc, editor.canvas, QPointF(11, 11), None)  # near start → close

    assert doc.selection is not None
    assert tool._points == []  # gesture finished
    assert doc.selection_bounds() == QRect(10, 10, 50, 40)


def test_poly_lasso_double_click_close_and_hover_preview(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["poly-lasso"]

    tool.press(doc, editor.canvas, QPointF(20, 20), None)
    tool.hover(doc, editor.canvas, QPointF(70, 20))
    assert doc.selection is not None  # live preview with the hover vertex

    tool.press(doc, editor.canvas, QPointF(70, 20), None)
    tool.press(doc, editor.canvas, QPointF(70, 60), None)
    tool.double_click(doc, editor.canvas, QPointF(70, 60), None)
    assert tool._points == []
    bounds = doc.selection_bounds()
    assert bounds.width() == 50 and bounds.height() == 40


def test_poly_lasso_enter_commits(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["poly-lasso"]

    tool.press(doc, editor.canvas, QPointF(10, 10), None)
    tool.press(doc, editor.canvas, QPointF(60, 10), None)
    tool.press(doc, editor.canvas, QPointF(60, 50), None)
    tool.commit(editor.canvas)  # what canvas.keyPressEvent runs on Enter

    assert tool._points == []
    assert doc.selection is not None
    assert doc.selection_bounds() == QRect(10, 10, 50, 40)

    # Enter with too few vertices just abandons the gesture
    tool.press(doc, editor.canvas, QPointF(5, 5), None)
    tool.commit(editor.canvas)
    assert tool._points == []


def test_ellipse_select_drag(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["ellipse-select"]

    tool.press(doc, editor.canvas, QPointF(10, 10), None)
    tool.move(doc, editor.canvas, QPointF(70, 50), None)
    tool.release(doc, editor.canvas, QPointF(70, 50), None)

    sel = doc.selection
    assert sel is not None
    assert doc.selection_bounds() == QRect(10, 10, 60, 40)
    assert sel.contains(QPointF(40, 30))  # centre is inside
    assert not sel.contains(QPointF(12, 12))  # bounding-box corner is not


class _ShiftEv:
    def modifiers(self):
        from PySide6.QtCore import Qt
        return Qt.KeyboardModifier.ShiftModifier


def test_ellipse_select_shift_is_a_circle(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["ellipse-select"]

    ev = _ShiftEv()
    tool.press(doc, editor.canvas, QPointF(10, 10), ev)
    tool.move(doc, editor.canvas, QPointF(70, 30), ev)
    tool.release(doc, editor.canvas, QPointF(70, 30), ev)

    bounds = doc.selection_bounds()
    assert bounds.width() == bounds.height() == 60


def test_poly_lasso_escape_cancels(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["poly-lasso"]

    tool.press(doc, editor.canvas, QPointF(10, 10), None)
    tool.press(doc, editor.canvas, QPointF(40, 10), None)
    tool.cancel(doc)
    assert tool._points == []
    # a fresh gesture starts clean
    tool.press(doc, editor.canvas, QPointF(5, 5), None)
    assert tool._points == [QPointF(5, 5)]
