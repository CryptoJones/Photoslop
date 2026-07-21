# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def striped_image(w=80, h=40):
    """Flat gray field with one high-contrast vertical feature stripe."""
    img = blank_image(QSize(w, h))
    img.fill(QColor(128, 128, 128))
    p = QPainter(img)
    p.fillRect(QRect(60, 0, 6, h), QColor(255, 0, 0))  # the detail to keep
    p.end()
    return img


def count_red_columns(img) -> int:
    return sum(
        1
        for x in range(img.width())
        if img.pixelColor(x, img.height() // 2).red() > 200
        and img.pixelColor(x, img.height() // 2).green() < 60
    )


def test_seam_carve_shrinks_and_keeps_detail(qapp):
    img = striped_image()
    carved = npimage.seam_carve(img, 50, 40)
    assert carved.width() == 50 and carved.height() == 40
    assert count_red_columns(carved) >= 5  # the red stripe survived 30 seams

    both = npimage.seam_carve(striped_image(), 60, 30)
    assert both.width() == 60 and both.height() == 30


def test_apply_content_aware_scale_undo(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 40), 72.0, "cas", QColor(128, 128, 128))
    doc.layers[0].image = striped_image()
    win.add_document(doc)
    layer = doc.active_layer

    win.apply_content_aware_scale(doc, layer, 56, 40)
    assert layer.image.size() == QSize(56, 40)
    assert doc.undo_stack.command(0).text() == "Content-Aware Scale"

    doc.undo_stack.undo()
    assert layer.image.size() == QSize(80, 40)
    assert count_red_columns(layer.image) == 6  # byte-exact restore


def test_seam_insert_grows_and_keeps_detail(qapp):
    img = striped_image()
    grown = npimage.seam_carve(img, 100, 40)  # +20 columns
    assert grown.width() == 100 and grown.height() == 40
    assert count_red_columns(grown) >= 6  # the stripe survives intact

    both = npimage.seam_carve(striped_image(), 96, 50)  # grow both axes
    assert both.width() == 96 and both.height() == 50

    # flat field grows without artefacts: still uniform gray
    flat = blank_image(QSize(30, 20))
    flat.fill(QColor(128, 128, 128))
    bigger = npimage.seam_carve(flat, 45, 20)
    assert bigger.width() == 45
    assert bigger.pixelColor(22, 10) == QColor(128, 128, 128)
