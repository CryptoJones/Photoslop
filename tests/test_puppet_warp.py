# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def stripe_image(w=80, h=80):
    img = blank_image(QSize(w, h))
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.fillRect(QRect(38, 0, 4, h), QColor(255, 0, 0))  # vertical red stripe
    p.end()
    return img


def stripe_x(img, y) -> int:
    for x in range(img.width()):
        c = img.pixelColor(x, y)
        if c.red() > 200 and c.green() < 80:
            return x
    return -1


def test_puppet_warp_bends_around_anchors(qapp):
    img = stripe_image()
    pins = [((40, 5), (40, 5)),  # anchor top
            ((40, 75), (40, 75)),  # anchor bottom
            ((40, 40), (55, 40))]  # middle pulled right
    warped = npimage.puppet_warp(img, pins)
    assert stripe_x(warped, 40) > 46  # middle bent right
    assert abs(stripe_x(warped, 5) - 38) <= 3  # anchored ends stay put
    assert abs(stripe_x(warped, 75) - 38) <= 3


def test_puppet_tool_session_commit_cancel(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 80), 72.0, "pw", QColor(255, 255, 255))
    doc.layers[0].image = stripe_image()
    win.add_document(doc)
    editor = win.current_editor()
    tool = win.tools["puppet"]

    tool.press(doc, editor.canvas, QPointF(40, 5), None)  # anchor
    tool.press(doc, editor.canvas, QPointF(40, 75), None)  # anchor
    tool.press(doc, editor.canvas, QPointF(40, 40), None)  # pin to drag
    tool.press(doc, editor.canvas, QPointF(40, 40), None)  # grab it
    assert tool._drag == 2
    tool.move(doc, editor.canvas, QPointF(55, 40), None)
    tool.release(doc, editor.canvas, QPointF(55, 40), None)

    assert stripe_x(doc.active_layer.image, 40) > 46  # live warp applied
    tool.commit(editor.canvas)
    assert doc.undo_stack.command(0).text() == "Puppet Warp"
    doc.undo_stack.undo()
    assert stripe_x(doc.active_layer.image, 40) == 38  # exact restore

    tool.press(doc, editor.canvas, QPointF(40, 40), None)  # new session
    tool.press(doc, editor.canvas, QPointF(40, 40), None)
    tool.move(doc, editor.canvas, QPointF(60, 40), None)
    tool.cancel(doc)
    assert stripe_x(doc.active_layer.image, 40) == 38
    assert doc.undo_stack.count() == 1  # cancel pushed nothing new
