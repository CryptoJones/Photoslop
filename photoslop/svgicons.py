# SPDX-License-Identifier: Apache-2.0
# ruff: noqa: E501, I001
"""Palette-aware SVG icons based on Tabler Icons v3.44.0 (MIT)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


PATHS = {
    "arrows-move": '<path d="M18 9l3 3l-3 3M15 12h6M6 9l-3 3l3 3M3 12h6M9 18l3 3l3-3M12 15v6M15 6l-3-3l-3 3M12 3v6"/>',
    "bandage": '<path d="M14 12v.01M10 12v.01M12 10v.01M12 14v.01M4.5 12.5l8-8a4.94 4.94 0 017 7l-8 8a4.94 4.94 0 01-7-7"/>',
    "brush": '<path d="M3 21v-4a4 4 0 114 4H3M21 3A16 16 0 008.2 13.2M21 3a16 16 0 01-10.2 12.8M10.6 9a9 9 0 014.4 4.4"/>',
    "bucket-droplet": '<path d="M5 16l1.465 1.638a2 2 0 11-3.015.099L5 16M13.737 9.737c2.299-2.3 3.23-5.095 2.081-6.245-1.15-1.15-3.945-.217-6.244 2.082-2.3 2.299-3.231 5.095-2.082 6.244 1.15 1.15 3.946.218 6.245-2.081M7.492 11.818c.362.362.768.676 1.208.934l6.895 4.047c1.078.557 2.255-.075 3.692-1.512s2.07-2.614 1.512-3.692L16.752 4.7a6.015 6.015 0 00-.934-1.208"/>',
    "color-picker": '<path d="M11 7l6 6M4 16L15.7 4.3a1 1 0 011.4 0l2.6 2.6a1 1 0 010 1.4L8 20H4v-4"/>',
    "crop": '<path d="M8 5v10a1 1 0 001 1h10M5 8h10a1 1 0 011 1v10"/>',
    "eraser": '<path d="M19 20H8.5l-4.21-4.3a1 1 0 010-1.41l10-10a1 1 0 011.41 0l5 5a1 1 0 010 1.41L11.5 20M18 13.3L11.7 7"/>',
    "lasso": '<path d="M4.028 13.252A5.76 5.76 0 013 10c0-3.866 4.03-7 9-7s9 3.134 9 7-4.03 7-9 7a12 12 0 01-5.144-1.255M3 15a2 2 0 104 0 2 2 0 10-4 0M5 17c0 1.42.316 2.805 1 4"/>',
    "pencil": '<path d="M4 20h4L18.5 9.5a2.828 2.828 0 10-4-4L4 16v4M13.5 6.5l4 4"/>',
    "text-size": '<path d="M3 7V5h13v2M10 5v14M12 19H8M15 13v-1h6v1M18 12v7M17 19h2"/>',
    "transform": '<path d="M3 6a3 3 0 106 0 3 3 0 00-6 0M21 11V8a2 2 0 00-2-2h-6l3 3m0-6l-3 3M3 13v3a2 2 0 002 2h6l-3-3m0 6l3-3M15 18a3 3 0 106 0 3 3 0 00-6 0"/>',
    "vector-bezier": '<path d="M3 15a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 01-1 1H4a1 1 0 01-1-1v-2M17 15a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 01-1 1h-2a1 1 0 01-1-1v-2M10 7a1 1 0 011-1h2a1 1 0 011 1v2a1 1 0 01-1 1h-2a1 1 0 01-1-1V7M10 8.5A6 6 0 005 14M14 8.5a6 6 0 015 5.5M10 8H4M20 8h-6M2 8a1 1 0 102 0 1 1 0 10-2 0M20 8a1 1 0 102 0 1 1 0 10-2 0"/>',
    "wand": '<path d="M6 21L21 6l-3-3L3 18l3 3M15 6l3 3M9 3a2 2 0 002 2 2 2 0 00-2 2 2 2 0 00-2-2 2 2 0 002-2M19 13a2 2 0 002 2 2 2 0 00-2 2 2 2 0 00-2-2 2 2 0 002-2"/>',
    "zoom-in": '<path d="M3 10a7 7 0 1014 0 7 7 0 10-14 0M7 10h6M10 7v6M21 21l-6-6"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "copy": '<path d="M8 8h11a1 1 0 011 1v10a1 1 0 01-1 1H9a1 1 0 01-1-1V8M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M5 7l1 14h12l1-14M9 7V4h6v3"/>',
    "arrow-up": '<path d="M12 5v14M6 11l6-6 6 6"/>',
    "arrow-down": '<path d="M12 5v14M6 13l6 6 6-6"/>',
}


def _svg(name: str, color: QColor) -> QByteArray:
    # SVG/CSS eight-digit colors are #RRGGBBAA, while QColor.HexArgb emits
    # #AARRGGBB. Keep the color and opacity separate so every Qt SVG backend
    # renders palette icons visibly and consistently.
    ink = color.name(QColor.NameFormat.HexRgb)
    source = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
        f'fill="none" stroke="{ink}" stroke-opacity="{color.alphaF():.3f}" '
        f'stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{PATHS[name]}</svg>'
    )
    return QByteArray(source.encode())


def svg_icon(name: str) -> QIcon:
    """Build normal/active/disabled palette states at common logical sizes."""
    palette = QApplication.palette()
    icon = QIcon()
    colors = {
        QIcon.Mode.Normal: palette.color(palette.ColorRole.ButtonText),
        QIcon.Mode.Active: palette.color(palette.ColorRole.Highlight),
        QIcon.Mode.Selected: palette.color(palette.ColorRole.HighlightedText),
        QIcon.Mode.Disabled: palette.color(
            palette.ColorGroup.Disabled, palette.ColorRole.ButtonText
        ),
    }
    for mode, color in colors.items():
        renderer = QSvgRenderer(_svg(name, color))
        for size in (16, 20, 24, 32):
            pm = QPixmap(size * 2, size * 2)
            pm.setDevicePixelRatio(2.0)
            pm.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pm)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
            icon.addPixmap(pm, mode)
    return icon
