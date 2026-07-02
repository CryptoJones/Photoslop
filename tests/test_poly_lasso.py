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
