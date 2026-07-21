# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import Layer, blank_image
from photoslop.mainwindow import MainWindow


def chip_image(size=20):
    img = blank_image(QSize(size, size))
    img.fill(QColor(255, 0, 0))
    return img


def test_drop_shadow_image_blurs_silhouette(qapp):
    shadow = npimage.drop_shadow_image(chip_image(), QColor(0, 0, 0, 153), 8)
    assert shadow.width() == 20 + 16 and shadow.height() == 20 + 16
    centre = shadow.pixelColor(18, 18)
    assert centre.alpha() > 100  # solid under the chip
    edge = shadow.pixelColor(3, 18)
    assert 0 < edge.alpha() < centre.alpha()  # soft falloff at the fringe
    assert shadow.pixelColor(0, 0).alpha() < 25  # corner nearly transparent

    hard = npimage.drop_shadow_image(chip_image(), QColor(0, 0, 0, 255), 0)
    assert hard.size() == QSize(20, 20)
    assert hard.pixelColor(10, 10).alpha() == 255


def test_apply_drop_shadow_inserts_below_and_undoes(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 60), 72.0, "ds", QColor(255, 255, 255))
    chip = Layer("chip", chip_image(), QPoint(30, 20))
    doc.layers.append(chip)
    doc.active_index = 1
    win.add_document(doc)

    win.apply_drop_shadow(doc, chip, 6, 6, 8, 60)
    assert [layer.name for layer in doc.layers] == ["Background", "chip shadow", "chip"]
    shadow = doc.layers[1]
    assert shadow.offset == QPoint(30 + 6 - 8, 20 + 6 - 8)  # offset minus pad
    # shadow visible just outside the chip's lower-right edge
    flat = doc.flatten()
    px = flat.pixelColor(53, 43)
    assert px.red() < 250  # darkened by the shadow

    doc.undo_stack.undo()
    assert [layer.name for layer in doc.layers] == ["Background", "chip"]
