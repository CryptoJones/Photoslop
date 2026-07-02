# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize

from photoslop.appicon import app_icon, mascot_pixmap


def test_app_icon_has_sizes(qapp):
    icon = app_icon()
    assert not icon.isNull()
    sizes = icon.availableSizes()
    assert QSize(256, 256) in sizes and QSize(32, 32) in sizes


def test_mascot_is_green_and_bereted(qapp):
    img = mascot_pixmap(256).toImage()
    body = img.pixelColor(128, 120)  # body centre: green dominates
    assert body.green() > body.red() and body.green() > body.blue()
    beret = img.pixelColor(120, 58)  # beret: red dominates
    assert beret.red() > beret.green() and beret.red() > beret.blue()
    corner = img.pixelColor(4, 4)  # background stays transparent
    assert corner.alpha() == 0
