# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(100, 80), 72.0, "w", QColor(255, 255, 255))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(10, 10, 20, 20), QColor(255, 0, 0))
    p.fillRect(QRect(60, 40, 20, 20), QColor(255, 0, 0))
    p.end()
    win.add_document(doc)
    win.options.tolerance = 0
    return win


def test_global_mask_finds_disconnected_regions(qapp):
    win = make_window(qapp)
    img = win.current_doc().active_layer.image
    result = npimage.global_mask(img, 15, 15, 0)
    assert result is not None
    mask, bbox = result
    assert bool(mask[15, 15]) and bool(mask[45, 65])  # both boxes ([y, x])
    assert bbox == QRect(10, 10, 70, 50)
    assert npimage.global_mask(img, -5, 0, 0) is None  # out of bounds


def test_wand_contiguous_toggle(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["wand"]

    win.options.contiguous = True
    tool.press(doc, editor.canvas, QPointF(15, 15), None)
    assert doc.selection_bounds() == QRect(10, 10, 20, 20)

    win.options.contiguous = False
    tool.press(doc, editor.canvas, QPointF(15, 15), None)
    assert doc.selection_bounds() == QRect(10, 10, 70, 50)  # both boxes
