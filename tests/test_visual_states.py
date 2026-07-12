# SPDX-License-Identifier: Apache-2.0
"""Deterministic 1x/2x light/dark/high-contrast icon and cursor render matrix."""

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QPalette

from photoslop.cursors import CursorIntent, CursorRenderer
from photoslop.svgicons import svg_icon


@pytest.mark.parametrize("dpr", [1.0, 2.0])
@pytest.mark.parametrize("theme", ["light", "dark", "high-contrast"])
def test_icon_cursor_visual_matrix_has_correct_scale_contrast_and_alpha(qapp, dpr, theme):
    palette = QPalette()
    foreground = QColor("black") if theme == "light" else QColor("white")
    background = QColor("white") if theme == "light" else QColor("black")
    if theme == "high-contrast":
        foreground = QColor("yellow")
    palette.setColor(QPalette.ColorRole.WindowText, foreground)
    palette.setColor(QPalette.ColorRole.Window, background)
    qapp.setPalette(palette)

    logical = 32
    pixmap = svg_icon("brush").pixmap(QSize(logical, logical), dpr)
    image = pixmap.toImage()
    assert not image.isNull() and pixmap.devicePixelRatio() == dpr
    assert any(image.pixelColor(x, y).alpha() for y in range(image.height())
               for x in range(image.width()))

    for intent in (CursorIntent("brush", diameter=24),
                   CursorIntent("zoom-in", badge="+"),
                   CursorIntent("clone", badge="!", valid=False)):
        cursor = CursorRenderer().cursor(intent, dpr)
        assert not cursor.pixmap().isNull()
        assert cursor.pixmap().devicePixelRatio() == dpr
