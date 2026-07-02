# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    """A 40×20 chip at (30, 20): white with a red horizontal stripe at y=10."""
    win = MainWindow()
    doc = Document.new(QSize(120, 80), 72.0, "wm", QColor(0, 0, 0, 0))
    chip = Layer.blank("chip", QSize(40, 20), QPoint(30, 20))
    chip.image.fill(QColor(255, 255, 255))
    p = QPainter(chip.image)
    p.fillRect(QRect(0, 9, 40, 2), QColor(255, 0, 0))
    p.end()
    doc.layers.append(chip)
    doc.active_index = 1
    win.add_document(doc)
    return win


def stripe_y(img, x) -> int:
    for y in range(img.height()):
        c = img.pixelColor(x, y)
        if c.red() > 200 and c.green() < 80:
            return y
    return -1


def test_warp_grid_initialises_and_identity_commits_nothing(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    win.action_warp()
    tool = win.tools["transform"]
    grid = tool.session.warp_grid
    assert grid is not None and len(grid) == 9
    assert grid[0] == QPointF(30, 20) and grid[8] == QPointF(70, 40)
    assert grid[4] == QPointF(50, 30)  # centre

    tool.commit(win.current_editor().canvas)  # untouched grid: no-op
    assert doc.undo_stack.count() == 0
    assert win.active_tool.name != "transform"


def test_warp_centre_drag_bends_stripe(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    layer = doc.active_layer
    win.action_warp()
    tool = win.tools["transform"]

    tool.press(doc, editor.canvas, QPointF(50, 30), None)  # grab centre point
    assert tool._mode == "warp:4"
    tool.move(doc, editor.canvas, QPointF(50, 38), None)  # pull it down 8px
    tool.release(doc, editor.canvas, QPointF(50, 38), None)
    tool.commit(editor.canvas)

    img = layer.image
    mid_x = img.width() // 2
    y_mid = stripe_y(img, mid_x)
    y_edge = stripe_y(img, 2)
    assert y_mid >= 0 and y_edge >= 0
    assert y_mid > y_edge + 3  # stripe bends downward at the pulled centre
    assert doc.undo_stack.command(0).text() == "Free Transform"

    doc.undo_stack.undo()
    assert layer.image.size() == QSize(40, 20)
    assert stripe_y(layer.image, 20) == 9  # byte-exact restore


def test_warp_escape_cancels(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    win.action_warp()
    tool = win.tools["transform"]
    tool.session.warp_grid[4] = QPointF(55, 45)
    tool.cancel(doc)
    win.end_transform()
    assert doc.active_layer.image.size() == QSize(40, 20)
    assert doc.undo_stack.count() == 0
