# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.commands import (
    InsertLayerCommand,
    MergeDownCommand,
    MoveLayerStackCommand,
    RemoveLayerCommand,
)
from photoslop.document import Document
from photoslop.layer import Layer


def make_doc(qapp) -> Document:
    return Document.new(QSize(64, 48), 72.0, "t", QColor(255, 0, 0))


def test_new_document(qapp):
    doc = make_doc(qapp)
    assert doc.size == QSize(64, 48)
    assert len(doc.layers) == 1
    assert doc.active_layer is doc.layers[0]
    assert doc.flatten().pixelColor(10, 10) == QColor(255, 0, 0)


def test_layer_commands_undo(qapp):
    doc = make_doc(qapp)
    layer = Layer.blank("L2", doc.size)
    doc.undo_stack.push(InsertLayerCommand(doc, 1, layer))
    assert len(doc.layers) == 2
    doc.undo_stack.undo()
    assert len(doc.layers) == 1
    doc.undo_stack.redo()

    doc.undo_stack.push(MoveLayerStackCommand(doc, 1, 0))
    assert doc.layers[0] is layer
    doc.undo_stack.undo()
    assert doc.layers[1] is layer

    doc.undo_stack.push(RemoveLayerCommand(doc, 1))
    assert len(doc.layers) == 1
    doc.undo_stack.undo()
    assert doc.layers[1] is layer


def test_merge_down(qapp):
    doc = make_doc(qapp)
    top = Layer.blank("top", doc.size)
    top.image.fill(QColor(0, 0, 255))
    doc.undo_stack.push(InsertLayerCommand(doc, 1, top))
    doc.undo_stack.push(MergeDownCommand(doc, 1))
    assert len(doc.layers) == 1
    assert doc.flatten().pixelColor(5, 5) == QColor(0, 0, 255)
    doc.undo_stack.undo()
    assert len(doc.layers) == 2
    assert doc.layers[0].image.pixelColor(5, 5) == QColor(255, 0, 0)


def test_memory_accounting(qapp):
    doc = make_doc(qapp)
    base = doc.memory_bytes()
    assert base == 64 * 48 * 4
    doc.undo_stack.push(InsertLayerCommand(doc, 1, Layer.blank("L2", doc.size)))
    assert doc.memory_bytes() == base * 2
