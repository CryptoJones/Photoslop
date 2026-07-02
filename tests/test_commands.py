# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop.commands import (
    ResizeCanvasCommand,
    ResizeImageCommand,
    SetLayerOffsetCommand,
    TileRecorder,
)
from photoslop.document import Document


def make_doc(qapp):
    return Document.new(QSize(100, 80), 72.0, "t", QColor(255, 255, 255))


def test_tile_recorder_undo_redo(qapp):
    doc = make_doc(qapp)
    layer = doc.active_layer
    recorder = TileRecorder(doc, layer)
    rect = QRect(10, 10, 20, 20)
    recorder.will_change(rect)
    p = QPainter(layer.image)
    p.fillRect(rect, QColor(0, 0, 0))
    p.end()
    cmd = recorder.finish("stroke")
    assert cmd is not None
    doc.undo_stack.push(cmd)

    assert layer.image.pixelColor(15, 15) == QColor(0, 0, 0)
    doc.undo_stack.undo()
    assert layer.image.pixelColor(15, 15) == QColor(255, 255, 255)
    doc.undo_stack.redo()
    assert layer.image.pixelColor(15, 15) == QColor(0, 0, 0)


def test_tile_recorder_skips_untouched(qapp):
    doc = make_doc(qapp)
    recorder = TileRecorder(doc, doc.active_layer)
    recorder.will_change(QRect(0, 0, 50, 50))
    assert recorder.finish("noop") is None  # nothing changed → no command


def test_move_command_merges(qapp):
    doc = make_doc(qapp)
    layer = doc.active_layer
    layer.offset = QPoint(5, 0)
    doc.undo_stack.push(SetLayerOffsetCommand(doc, layer, QPoint(0, 0), QPoint(5, 0)))
    layer.offset = QPoint(9, 3)
    doc.undo_stack.push(SetLayerOffsetCommand(doc, layer, QPoint(5, 0), QPoint(9, 3)))
    assert doc.undo_stack.count() == 1  # merged
    doc.undo_stack.undo()
    assert layer.offset == QPoint(0, 0)


def test_resize_image(qapp):
    doc = make_doc(qapp)
    doc.undo_stack.push(ResizeImageCommand(doc, QSize(50, 40)))
    assert doc.size == QSize(50, 40)
    assert doc.active_layer.image.width() == 50
    doc.undo_stack.undo()
    assert doc.size == QSize(100, 80)
    assert doc.active_layer.image.width() == 100


def test_canvas_resize_and_crop(qapp):
    doc = make_doc(qapp)
    layer = doc.active_layer
    # crop to (20,10)-(60,50): canvas shrinks, layer shifts, pixels survive
    doc.undo_stack.push(ResizeCanvasCommand(doc, QSize(40, 40), QPoint(-20, -10), "Crop"))
    assert doc.size == QSize(40, 40)
    assert layer.offset == QPoint(-20, -10)
    assert doc.flatten().pixelColor(0, 0) == QColor(255, 255, 255)
    doc.undo_stack.undo()
    assert doc.size == QSize(100, 80)
    assert layer.offset == QPoint(0, 0)
