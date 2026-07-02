# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop.commands import (
    FlipImageCommand,
    FlipLayerCommand,
    RotateImageCommand,
    RotateLayerCommand,
)
from photoslop.document import Document


def make_doc(qapp) -> Document:
    doc = Document.new(QSize(40, 30), 72.0, "r", QColor(255, 255, 255))
    doc.active_layer.image.setPixelColor(3, 5, QColor(255, 0, 0))
    return doc


def test_rotate_image_90_cw(qapp):
    doc = make_doc(qapp)
    doc.add_guide("h", 10.0)
    doc.add_guide("v", 4.0)
    doc.undo_stack.push(RotateImageCommand(doc, 90))

    assert doc.size == QSize(30, 40)  # W/H swapped
    # pixel (3,5) → (H-1-5, 3) = (24, 3)
    assert doc.flatten().pixelColor(24, 3) == QColor(255, 0, 0)
    # h-guide y=10 → v-guide x=30-10=20; v-guide x=4 → h-guide y=4
    assert doc.guides_v == [20.0] and doc.guides_h == [4.0]

    doc.undo_stack.undo()
    assert doc.size == QSize(40, 30)
    assert doc.flatten().pixelColor(3, 5) == QColor(255, 0, 0)
    assert doc.guides_h == [10.0] and doc.guides_v == [4.0]


def test_rotate_image_180_and_ccw(qapp):
    doc = make_doc(qapp)
    doc.undo_stack.push(RotateImageCommand(doc, 180))
    assert doc.size == QSize(40, 30)
    assert doc.flatten().pixelColor(36, 24) == QColor(255, 0, 0)  # (W-1-3, H-1-5)
    doc.undo_stack.undo()

    doc.undo_stack.push(RotateImageCommand(doc, 270))
    assert doc.size == QSize(30, 40)
    assert doc.flatten().pixelColor(5, 36) == QColor(255, 0, 0)  # (y, W-1-x)


def test_flip_image(qapp):
    doc = make_doc(qapp)
    doc.add_guide("v", 4.0)
    doc.undo_stack.push(FlipImageCommand(doc, True))
    assert doc.flatten().pixelColor(36, 5) == QColor(255, 0, 0)
    assert doc.guides_v == [36.0]
    doc.undo_stack.undo()  # involution
    assert doc.flatten().pixelColor(3, 5) == QColor(255, 0, 0)
    assert doc.guides_v == [4.0]

    doc.undo_stack.push(FlipImageCommand(doc, False))
    assert doc.flatten().pixelColor(3, 24) == QColor(255, 0, 0)


def test_rotate_layer_keeps_centre_and_undo_exact(qapp):
    doc = Document.new(QSize(60, 60), 72.0, "L", QColor(0, 0, 0, 0))
    layer = doc.active_layer
    layer.image = layer.image.copy(0, 0, 20, 10)  # 20x10 layer
    layer.offset = QPoint(7, 13)
    layer.image.fill(QColor(0, 255, 0))
    layer.image.setPixelColor(0, 0, QColor(255, 0, 0))

    doc.undo_stack.push(RotateLayerCommand(doc, layer, 90))
    assert layer.image.size() == QSize(10, 20)
    # centre stays at (17, 18): new offset = (17-5, 18-10) = (12, 8)
    assert layer.offset == QPoint(12, 8)
    # top-left pixel → top-right after CW rotation
    assert layer.image.pixelColor(9, 0) == QColor(255, 0, 0)

    doc.undo_stack.undo()
    assert layer.image.size() == QSize(20, 10)
    assert layer.offset == QPoint(7, 13)
    assert layer.image.pixelColor(0, 0) == QColor(255, 0, 0)


def test_flip_layer(qapp):
    doc = Document.new(QSize(20, 20), 72.0, "F", QColor(0, 0, 0, 0))
    layer = doc.active_layer
    layer.image.setPixelColor(2, 3, QColor(255, 0, 0))
    doc.undo_stack.push(FlipLayerCommand(doc, layer, True))
    assert layer.image.pixelColor(17, 3) == QColor(255, 0, 0)
    doc.undo_stack.undo()
    assert layer.image.pixelColor(2, 3) == QColor(255, 0, 0)
