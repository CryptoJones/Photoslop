# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def edge_image(w=80, h=60):
    img = blank_image(QSize(w, h))
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    p.fillRect(QRect(40, 0, w - 40, h), QColor(255, 255, 255))
    p.end()
    return img


def edge_x(img, y) -> int:
    for x in range(img.width()):
        if img.pixelColor(x, y).red() > 127:
            return x
    return img.width()


def test_warp_push_bulges_edge(qapp):
    img = edge_image()
    dirty = npimage.warp_push(img, 40, 30, 14, 10, 0)  # push right at row 30
    assert not dirty.isEmpty()
    assert edge_x(img, 30) > 44  # edge bulged rightward at the push row
    assert edge_x(img, 5) == 40  # far row untouched
    assert edge_x(img, 55) == 40


def test_liquify_tool_stroke_and_undo(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 60), 72.0, "lq", QColor(0, 0, 0))
    doc.layers[0].image = edge_image()
    win.add_document(doc)
    editor = win.current_editor()
    tool = win.tools["liquify"]
    win.options.size = 24
    win.options.opacity = 100

    tool.press(doc, editor.canvas, QPointF(38, 30), None)
    tool.move(doc, editor.canvas, QPointF(50, 30), None)
    tool.release(doc, editor.canvas, QPointF(50, 30), None)

    img = doc.active_layer.image
    assert edge_x(img, 30) > 42  # pixels shoved right along the drag
    assert edge_x(img, 5) == 40
    assert doc.undo_stack.command(0).text() == "Liquify"
    doc.undo_stack.undo()
    assert edge_x(img, 30) == 40  # exact restore
