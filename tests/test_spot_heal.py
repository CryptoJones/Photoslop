# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(60, 60), 72.0, "h", QColor(180, 180, 180))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(28, 28, 5, 5), QColor(0, 0, 0))  # the blemish
    p.end()
    win.add_document(doc)
    win.options.size = 14
    return win


def test_inpaint_diffuse_fills_hole(qapp):
    win = make_window(qapp)
    img = win.current_doc().active_layer.image
    mask = np.zeros((60, 60), dtype=bool)
    mask[25:37, 25:37] = True

    dirty = npimage.inpaint_diffuse(img, mask)
    assert dirty.contains(QRect(25, 25, 12, 12))
    healed = img.pixelColor(30, 30)
    assert healed.red() > 150  # black spot replaced by surround-like gray
    assert img.pixelColor(5, 5) == QColor(180, 180, 180)  # untouched outside


def test_spot_heal_tool_stroke_and_undo(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["spot-heal"]

    assert doc.active_layer.image.pixelColor(30, 30) == QColor(0, 0, 0)
    tool.press(doc, editor.canvas, QPointF(30, 30), None)
    tool.release(doc, editor.canvas, QPointF(30, 30), None)

    healed = doc.active_layer.image.pixelColor(30, 30)
    assert healed.red() > 150
    assert doc.undo_stack.command(0).text() == "Spot Heal"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(30, 30) == QColor(0, 0, 0)
