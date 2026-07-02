# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.adjust import apply_hsl
from photoslop.document import Document
from photoslop.huesatdialog import HueSatDialog
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def red_image(size=4):
    img = blank_image(QSize(size, size))
    img.fill(QColor(255, 0, 0))
    return img


def test_hue_rotation_moves_red_toward_green(qapp):
    img = red_image()
    apply_hsl(img, 120, 0, 0)
    px = img.pixelColor(1, 1)
    assert px.green() > px.red() and px.green() > px.blue()


def test_saturation_and_lightness(qapp):
    img = red_image()
    apply_hsl(img, 0, -100, 0)
    px = img.pixelColor(1, 1)
    assert abs(px.red() - px.green()) <= 2 and abs(px.green() - px.blue()) <= 2

    img = red_image()
    apply_hsl(img, 0, 0, 100)
    assert img.pixelColor(1, 1) == QColor(255, 255, 255)

    img = red_image()
    apply_hsl(img, 0, 0, -100)
    assert img.pixelColor(1, 1) == QColor(0, 0, 0)


def test_identity_is_noop_and_alpha_kept(qapp):
    img = blank_image(QSize(4, 4))
    img.fill(QColor(10, 200, 60, 128))
    before = img.copy()
    apply_hsl(img, 0, 0, 0)
    assert img == before
    apply_hsl(img, 30, 20, 10)
    assert img.pixelColor(0, 0).alpha() == 128


def test_dialog_ok_undo_cancel(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "h", QColor(255, 0, 0)))
    doc = win.current_doc()

    dialog = HueSatDialog(doc, win)
    dialog._sliders["hue"].setValue(120)
    dialog._debounce.stop()
    dialog._preview()
    assert doc.active_layer.image.pixelColor(5, 5).green() > 100
    dialog.accept()
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.command(0).text() == "Hue/Saturation"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(255, 0, 0)

    dialog = HueSatDialog(doc, win)
    dialog._sliders["lightness"].setValue(-50)
    dialog._debounce.stop()
    dialog._preview()
    dialog.reject()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(255, 0, 0)
    assert doc.undo_stack.count() == 1  # unchanged by cancel
