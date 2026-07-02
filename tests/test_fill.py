# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop import npimage
from photoslop.layer import blank_image


def _color_u32(r, g, b, a=255):
    return npimage.premultiplied_u32(r, g, b, a)


def test_fill_bounded_region(qapp):
    img = blank_image(QSize(32, 32))
    img.fill(QColor(255, 255, 255))
    # draw a black border box 8..23
    for i in range(8, 24):
        img.setPixelColor(i, 8, QColor(0, 0, 0))
        img.setPixelColor(i, 23, QColor(0, 0, 0))
        img.setPixelColor(8, i, QColor(0, 0, 0))
        img.setPixelColor(23, i, QColor(0, 0, 0))

    dirty = npimage.flood_fill(img, 15, 15, _color_u32(0, 255, 0), 0)
    assert dirty is not None
    assert img.pixelColor(15, 15) == QColor(0, 255, 0)
    assert img.pixelColor(9, 9) == QColor(0, 255, 0)  # inside the box
    assert img.pixelColor(4, 4) == QColor(255, 255, 255)  # outside stays
    assert img.pixelColor(8, 8) == QColor(0, 0, 0)  # border stays
    assert dirty.width() == 14 and dirty.height() == 14


def test_fill_tolerance(qapp):
    img = blank_image(QSize(8, 8))
    img.fill(QColor(100, 100, 100))
    img.setPixelColor(4, 4, QColor(110, 110, 110))  # within tolerance 20
    npimage.flood_fill(img, 0, 0, _color_u32(255, 0, 0), 20)
    assert img.pixelColor(4, 4) == QColor(255, 0, 0)

    img2 = blank_image(QSize(8, 8))
    img2.fill(QColor(100, 100, 100))
    img2.setPixelColor(4, 4, QColor(180, 180, 180))  # outside tolerance
    npimage.flood_fill(img2, 0, 0, _color_u32(255, 0, 0), 20)
    assert img2.pixelColor(4, 4) == QColor(180, 180, 180)


def test_fill_respects_selection(qapp):
    from PySide6.QtCore import QPoint

    img = blank_image(QSize(16, 16))
    img.fill(QColor(255, 255, 255))
    path = QPainterPath()
    path.addRect(0, 0, 8, 16)
    mask = npimage.selection_mask(path, img.size(), QPoint(0, 0))
    npimage.flood_fill(img, 2, 2, _color_u32(0, 0, 255), 0, mask)
    assert img.pixelColor(2, 2) == QColor(0, 0, 255)
    assert img.pixelColor(12, 2) == QColor(255, 255, 255)


def test_fill_noop_outside(qapp):
    img = blank_image(QSize(8, 8))
    assert npimage.flood_fill(img, 20, 20, _color_u32(1, 2, 3), 0) is None
