# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import Layer, blank_image
from photoslop.mainwindow import MainWindow


def chip_image(size=16):
    img = blank_image(QSize(size, size))
    img.fill(QColor(0, 128, 255))
    return img


def test_stroke_outline_ring(qapp):
    outline = npimage.stroke_outline_image(chip_image(), QColor(255, 0, 0, 255), 3)
    assert outline.size() == QSize(16 + 6, 16 + 6)
    assert outline.pixelColor(11, 11).alpha() == 0  # inside the chip: empty
    assert outline.pixelColor(1, 11).alpha() == 255  # in the ring
    assert outline.pixelColor(1, 11).red() == 255
    # 8-neighbour dilation = Chebyshev metric: the diagonal corner is in reach
    assert outline.pixelColor(0, 0).alpha() == 255


def test_apply_stroke_inserts_below_and_undoes(qapp):
    win = MainWindow()
    doc = Document.new(QSize(60, 60), 72.0, "st", QColor(255, 255, 255))
    chip = Layer("chip", chip_image(), QPoint(20, 20))
    doc.layers.append(chip)
    doc.active_index = 1
    win.add_document(doc)

    win.apply_stroke_style(doc, chip, 3, QColor(255, 0, 0))
    assert [layer.name for layer in doc.layers] == [
        "Background", "chip stroke", "chip"]
    assert doc.layers[1].offset == QPoint(17, 17)
    flat = doc.flatten()
    assert flat.pixelColor(18, 28).red() > 200  # ring visible left of the chip
    assert flat.pixelColor(18, 28).green() < 100

    doc.undo_stack.undo()
    assert len(doc.layers) == 2
