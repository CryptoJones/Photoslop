# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.npimage import view_u32


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(60, 60), 72.0, "n", QColor(0, 0, 0, 0)))
    win.options.foreground = QColor(200, 30, 90)
    win.options.size = 3
    win.options.opacity = 100
    win.options.eraser = False
    return win


def stroke(tool, doc, canvas, a, b):
    tool.press(doc, canvas, QPointF(*a), None)
    tool.move(doc, canvas, QPointF(*b), None)
    tool.release(doc, canvas, QPointF(*b), None)


def test_pencil_is_aliased(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    stroke(win.tools["pencil"], doc, editor.canvas, (10, 10), (50, 45))

    arr = view_u32(doc.active_layer.image)
    fg = (255 << 24) | (200 << 16) | (30 << 8) | 90
    values = set(arr.flatten().tolist())
    assert values == {0, fg}  # aliased: every painted pixel is exactly fg
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.command(0).text() == "Pencil"


def test_brush_antialiases_but_pencil_does_not(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    stroke(win.tools["brush"], doc, editor.canvas, (10, 40), (50, 12))

    arr = view_u32(doc.active_layer.image)
    fg = (255 << 24) | (200 << 16) | (30 << 8) | 90
    values = set(arr.flatten().tolist())
    assert len(values - {0, fg}) > 0  # antialiased edge pixels exist


def test_pencil_translucent_is_uniform(qapp):
    win = make_window(qapp)
    win.options.opacity = 50
    editor = win.current_editor()
    doc = editor.doc
    stroke(win.tools["pencil"], doc, editor.canvas, (5, 30), (55, 30))

    px = doc.active_layer.image.pixelColor(30, 30)
    assert px.alpha() in (127, 128)  # exactly the shared opacity, everywhere
    arr = view_u32(doc.active_layer.image)
    assert len(set(arr.flatten().tolist())) == 2  # transparent + one value
