# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QFont

from photoslop.commands import InsertLayerCommand
from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.textdialog import render_text_layer


def test_render_text_layer(qapp):
    font = QFont()
    font.setPointSize(24)
    layer = render_text_layer("Hi", font, QColor(255, 0, 0), QPoint(30, 20))
    assert layer is not None
    assert layer.offset == QPoint(30, 20)
    assert layer.image.width() > 10 and layer.image.height() > 10
    # some rendered pixels are red-ish
    found = any(
        layer.image.pixelColor(x, y).red() > 100
        and layer.image.pixelColor(x, y).alpha() > 100
        for x in range(layer.image.width())
        for y in range(layer.image.height())
    )
    assert found

    multi = render_text_layer("a\nb\nc", font, QColor(0, 0, 0), QPoint(0, 0))
    assert multi.image.height() > layer.image.height()  # three lines taller

    assert render_text_layer("   \n", font, QColor(0, 0, 0), QPoint(0, 0)) is None


def test_text_layer_insert_undo(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(200, 100), 72.0, "t", QColor(255, 255, 255)))
    doc = win.current_doc()

    font = QFont()
    font.setPointSize(18)
    layer = render_text_layer("Photoslop", font, QColor(0, 0, 255), QPoint(10, 10))
    doc.undo_stack.push(InsertLayerCommand(doc, len(doc.layers), layer, "Add Text"))

    assert len(doc.layers) == 2
    assert doc.layers[1].name.startswith("Photoslop")
    doc.undo_stack.undo()
    assert len(doc.layers) == 1
