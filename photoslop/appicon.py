# SPDX-License-Identifier: Apache-2.0
"""The Photoslop application icon, drawn in code (no asset files):
a doofy green tentacled basilisk in a French beret, mustachioed,
paintbrush in one tentacle and palette in another."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

BODY = QColor("#58b848")
BODY_LIGHT = QColor("#8ede7c")
BODY_DARK = QColor("#2e7d32")
BERET = QColor("#d32f2f")
BERET_DARK = QColor("#9a1b1b")
INK = QColor("#33221b")
HANDLE = QColor("#8d6e63")
FERRULE = QColor("#b0bec5")
BRISTLES = QColor("#4e342e")
PALETTE = QColor("#d7a86e")
PALETTE_DARK = QColor("#a9805b")


def _tentacle(p: QPainter, path: QPainterPath) -> None:
    outline = QPen(BODY_DARK, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
    p.setPen(outline)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)
    inner = QPen(BODY, 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                 Qt.PenJoinStyle.RoundJoin)
    p.setPen(inner)
    p.drawPath(path)


def draw_mascot(p: QPainter) -> None:
    """Draw into a 256x256 logical space."""
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    # --- tentacles (behind the body) ---------------------------------------
    t1 = QPainterPath(QPointF(92, 150))  # far left, rises to hold the brush
    t1.cubicTo(QPointF(58, 175), QPointF(38, 160), QPointF(44, 122))
    _tentacle(p, t1)

    t2 = QPainterPath(QPointF(105, 160))
    t2.cubicTo(QPointF(95, 205), QPointF(72, 218), QPointF(62, 198))
    _tentacle(p, t2)

    t3 = QPainterPath(QPointF(128, 163))
    t3.cubicTo(QPointF(126, 208), QPointF(140, 220), QPointF(152, 206))
    _tentacle(p, t3)

    t4 = QPainterPath(QPointF(152, 158))
    t4.cubicTo(QPointF(170, 198), QPointF(188, 205), QPointF(194, 186))
    _tentacle(p, t4)

    t5 = QPainterPath(QPointF(166, 148))  # far right, holds the palette
    t5.cubicTo(QPointF(198, 168), QPointF(212, 162), QPointF(208, 140))
    _tentacle(p, t5)

    # --- body ----------------------------------------------------------------
    grad = QRadialGradient(QPointF(112, 92), 95)
    grad.setColorAt(0.0, BODY_LIGHT)
    grad.setColorAt(1.0, BODY)
    p.setBrush(QBrush(grad))
    p.setPen(QPen(BODY_DARK, 4))
    p.drawEllipse(QPointF(128, 116), 60, 54)

    # --- eyes (slightly mismatched = doofy) -----------------------------------
    p.setBrush(QBrush(QColor("white")))
    p.setPen(QPen(INK, 2.5))
    p.drawEllipse(QPointF(104, 99), 17, 19)
    p.drawEllipse(QPointF(153, 99), 16, 18)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(INK))
    p.drawEllipse(QPointF(109, 104), 6.5, 6.5)  # looks down-right
    p.drawEllipse(QPointF(149, 97), 6.0, 6.0)  # looks up-left
    p.setBrush(QBrush(QColor(255, 255, 255, 230)))
    p.drawEllipse(QPointF(111.5, 101.5), 2.0, 2.0)
    p.drawEllipse(QPointF(151.5, 94.5), 1.8, 1.8)

    # --- mustache (handlebar) --------------------------------------------------
    p.setBrush(Qt.BrushStyle.NoBrush)
    pen = QPen(INK, 7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    left = QPainterPath(QPointF(128, 137))
    left.cubicTo(QPointF(114, 147), QPointF(99, 147), QPointF(92, 136))
    left.cubicTo(QPointF(90, 131), QPointF(94, 127), QPointF(98, 130))
    p.drawPath(left)
    right = QPainterPath(QPointF(128, 137))
    right.cubicTo(QPointF(142, 147), QPointF(157, 147), QPointF(164, 136))
    right.cubicTo(QPointF(166, 131), QPointF(162, 127), QPointF(158, 130))
    p.drawPath(right)

    # --- beret (tilted, with a stem) -------------------------------------------
    p.save()
    p.translate(120, 58)
    p.rotate(-10)
    p.setBrush(QBrush(BERET))
    p.setPen(QPen(BERET_DARK, 3))
    p.drawEllipse(QPointF(0, 0), 45, 16)
    p.setBrush(QBrush(BERET_DARK))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(2, -14), 4.5, 4.5)  # stem nub
    p.restore()

    # --- paintbrush in tentacle t1 ----------------------------------------------
    p.setPen(QPen(HANDLE, 8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(36, 152), QPointF(52, 96))
    p.setPen(QPen(FERRULE, 10, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    p.drawLine(QPointF(52, 96), QPointF(55, 85))
    p.setPen(QPen(BRISTLES, 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawLine(QPointF(55, 85), QPointF(58, 74))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(QColor("#1e88e5")))
    p.drawEllipse(QPointF(59.5, 69), 5.5, 5.5)  # fresh blue paint

    # --- palette in tentacle t5 ---------------------------------------------------
    p.save()
    p.translate(210, 136)
    p.rotate(20)
    p.setBrush(QBrush(PALETTE))
    p.setPen(QPen(PALETTE_DARK, 3))
    p.drawEllipse(QPointF(0, 0), 27, 19)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(PALETTE_DARK))
    p.drawEllipse(QPointF(-14, 7), 4.5, 4.5)  # thumb hole
    for color, (dx, dy) in (
        ("#e53935", (-12, -8)), ("#fdd835", (-2, -11)),
        ("#1e88e5", (8, -8)), ("#fafafa", (15, 0)),
    ):
        p.setBrush(QBrush(QColor(color)))
        p.drawEllipse(QPointF(dx, dy), 4.0, 4.0)
    p.restore()


def mascot_pixmap(size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.scale(size / 256.0, size / 256.0)
    draw_mascot(p)
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (32, 64, 128, 256):
        icon.addPixmap(mascot_pixmap(size))
    return icon


__all__ = ["app_icon", "draw_mascot", "mascot_pixmap"]
