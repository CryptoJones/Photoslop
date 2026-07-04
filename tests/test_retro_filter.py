# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop import npimage
from photoslop.filters import RetroConsoleFilter, available_filters
from photoslop.layer import blank_image


def _gradient(w=32, h=32):
    img = blank_image(QSize(w, h))
    for y in range(h):
        for x in range(w):
            img.setPixelColor(x, y, QColor((x * 8) % 256, (y * 8) % 256, 120))
    return img


def test_retro_is_registered(qapp):
    assert available_filters().get("retro-console") is RetroConsoleFilter


def test_retro_crushes_colour_depth(qapp):
    img = _gradient()
    RetroConsoleFilter().apply(img, {"size": 4, "levels": 3, "dither": 0})
    arr = npimage.view_u32(img)
    reds = {int((v >> 16) & 0xFF) for v in arr.flatten().tolist()}
    greens = {int((v >> 8) & 0xFF) for v in arr.flatten().tolist()}
    assert len(reds) <= 3  # 3 levels/channel → at most 3 distinct reds
    assert len(greens) <= 3


def test_retro_pixelates_into_blocks(qapp):
    img = _gradient()
    RetroConsoleFilter().apply(img, {"size": 4, "levels": 8, "dither": 0})
    # a 4x4 block maps back to a single source pixel → uniform colour
    top_left = img.pixelColor(0, 0)
    assert img.pixelColor(1, 1) == top_left
    assert img.pixelColor(3, 3) == top_left


def test_retro_preserves_opacity(qapp):
    img = _gradient()
    RetroConsoleFilter().apply(img, {"size": 4, "levels": 4, "dither": 1})
    assert img.pixelColor(10, 10).alpha() == 255
