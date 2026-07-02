# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def checker_image(w=60, h=80):
    img = blank_image(QSize(w, h))
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            if (x // 4 + y // 4) % 2 == 0:
                p.fillRect(QRect(x, y, 4, 4), QColor(0, 0, 0))
    p.end()
    return img


def row_contrast(img, y) -> int:
    values = [img.pixelColor(x, y).red() for x in range(4, img.width() - 4)]
    return max(values) - min(values)


def test_tilt_shift_keeps_band_sharp_blurs_far(qapp):
    win = MainWindow()
    doc = Document.new(QSize(60, 80), 72.0, "ts", QColor(255, 255, 255))
    doc.layers[0].image = checker_image()
    win.add_document(doc)
    layer = doc.active_layer

    win.apply_tilt_shift(doc, layer, centre=40, band=20, transition=10, radius=10)
    img = layer.image
    assert row_contrast(img, 40) == 255  # sharp in the band
    assert row_contrast(img, 38) == 255  # still inside band
    assert row_contrast(img, 5) < 120  # heavily blurred far above
    assert row_contrast(img, 75) < 120  # and far below
    mid = row_contrast(img, 52)  # inside the transition
    assert row_contrast(img, 5) < mid < 255

    assert doc.undo_stack.command(0).text() == "Tilt-Shift"
    doc.undo_stack.undo()
    assert row_contrast(layer.image, 5) == 255  # exact restore
