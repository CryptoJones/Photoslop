# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def square_image(w=80, h=80):
    img = blank_image(QSize(w, h))
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.fillRect(QRect(20, 20, 30, 30), QColor(255, 0, 0))
    p.end()
    return img


def red_at(img, x, y) -> bool:
    if not (0 <= x < img.width() and 0 <= y < img.height()):
        return False
    c = img.pixelColor(x, y)
    return c.red() > 180 and c.green() < 90


def test_perspective_session_warps_commits_and_cancels(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 80), 72.0, "pw", QColor(255, 255, 255))
    doc.layers[0].image = square_image()
    win.add_document(doc)
    editor = win.current_editor()
    tool = win.tools["perspective"]

    # phase 1: define the plane as the red square's corners
    for corner in ((20, 20), (50, 20), (50, 50), (20, 50)):
        tool.press(doc, editor.canvas, QPointF(*corner), None)
        tool.release(doc, editor.canvas, QPointF(*corner), None)
    assert len(tool.dst) == 4

    # phase 2: drag the bottom-right corner outward
    tool.press(doc, editor.canvas, QPointF(50, 50), None)
    assert tool._drag == 2
    tool.move(doc, editor.canvas, QPointF(70, 60), None)
    tool.release(doc, editor.canvas, QPointF(70, 60), None)

    layer = doc.active_layer
    assert red_at(layer.image, 67 - layer.offset.x(), 57 - layer.offset.y())
    tool.commit(editor.canvas)
    assert doc.undo_stack.command(0).text() == "Perspective Warp"

    doc.undo_stack.undo()
    assert layer.image.size() == QSize(80, 80)
    assert layer.offset == QPoint(0, 0)
    assert red_at(layer.image, 35, 35)  # exact restore

    # cancel path: new session, deform, escape
    for corner in ((20, 20), (50, 20), (50, 50), (20, 50)):
        tool.press(doc, editor.canvas, QPointF(*corner), None)
        tool.release(doc, editor.canvas, QPointF(*corner), None)
    tool.press(doc, editor.canvas, QPointF(20, 20), None)
    tool.move(doc, editor.canvas, QPointF(5, 5), None)
    tool.release(doc, editor.canvas, QPointF(5, 5), None)
    tool.cancel(doc)
    assert layer.image.size() == QSize(80, 80)
    assert layer.offset == QPoint(0, 0)
    assert doc.undo_stack.count() == 1
