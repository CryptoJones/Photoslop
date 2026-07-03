# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QPainterPath
from PySide6.QtWidgets import QMessageBox

from photoslop.document import Document
from photoslop.mainwindow import CREDITS_TEXT, MainWindow


def test_fill_layer_fills_everything_and_undoes(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(30, 30), 72.0, "fl",
                                  QColor(255, 255, 255)))
    doc = win.current_doc()
    win.options.foreground = QColor(10, 40, 220)

    sel = QPainterPath()
    sel.addRect(QRectF(5, 5, 8, 8))
    doc.set_selection(sel)  # a selection must NOT confine Fill Layer

    win.action_fill_layer()
    layer = doc.active_layer
    assert layer.image.pixelColor(6, 6) == QColor(10, 40, 220)
    assert layer.image.pixelColor(25, 25) == QColor(10, 40, 220)  # outside sel
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert layer.image.pixelColor(25, 25) == QColor(255, 255, 255)


def test_about_has_credits_button_with_the_names(qapp):
    win = MainWindow()
    box = win._build_about()
    labels = [b.text().replace("&", "") for b in box.buttons()]
    assert "Credits" in labels
    assert any(b == QMessageBox.StandardButton.Ok
               for b in (box.standardButtons(),)) or "OK" in labels
    assert CREDITS_TEXT == "Programming: CryptoJones, GPT5.5, and Fable5"


def test_about_shows_le_basilisk(qapp):
    from photoslop.appicon import mascot_pixmap

    win = MainWindow()
    box = win._build_about()
    shown = box.iconPixmap()
    assert not shown.isNull()
    # it is the QPainter mascot, pixel for pixel — not some other art
    assert shown.toImage() == mascot_pixmap(128).toImage()
