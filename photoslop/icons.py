# SPDX-License-Identifier: Apache-2.0
"""Tiny programmatic tool icons — no asset files to ship or load."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

SIZE = 22
_INK = QColor(70, 70, 70)


def _make(draw) -> QIcon:
    pm = QPixmap(SIZE, SIZE)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    draw(p)
    p.end()
    return QIcon(pm)


def brush_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(5, 17), QPointF(13, 9))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_INK))
        p.drawEllipse(QPointF(15.5, 6.5), 2.6, 2.6)

    return _make(draw)


def bucket_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.save()
        p.translate(10, 12)
        p.rotate(45)
        p.drawRect(QRectF(-4, -4, 8, 8))
        p.restore()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_INK))
        p.drawEllipse(QPointF(17, 15), 2.0, 2.6)

    return _make(draw)


def rect_select_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        pen = QPen(_INK, 1.6, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(4, 6, 14, 10))

    return _make(draw)


def lasso_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        pen = QPen(_INK, 1.6, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(6, 8))
        path.cubicTo(QPointF(4, 14), QPointF(12, 18), QPointF(16, 14))
        path.cubicTo(QPointF(19, 11), QPointF(15, 5), QPointF(10, 6))
        path.closeSubpath()
        p.drawPath(path)

    return _make(draw)


def move_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c = QPointF(11, 11)
        for dx, dy in ((7, 0), (-7, 0), (0, 7), (0, -7)):
            tip = QPointF(c.x() + dx, c.y() + dy)
            p.drawLine(c, tip)
            ux, uy = (dx / 7, dy / 7)
            p.drawLine(tip, QPointF(tip.x() - 3 * ux + 2 * uy, tip.y() - 3 * uy + 2 * ux))
            p.drawLine(tip, QPointF(tip.x() - 3 * ux - 2 * uy, tip.y() - 3 * uy - 2 * ux))

    return _make(draw)


def eyedropper_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(15, 7), QPointF(8, 14))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_INK))
        p.drawEllipse(QPointF(16.5, 5.5), 2.8, 2.8)  # bulb
        path = QPainterPath(QPointF(8, 14))  # tip
        path.lineTo(QPointF(5, 15.5))
        path.lineTo(QPointF(6.5, 17))
        path.closeSubpath()
        p.drawPath(path)

    return _make(draw)


def hand_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        palm = QPainterPath()
        palm.addRoundedRect(QRectF(6.5, 9, 9, 8), 3, 3)
        p.drawPath(palm)
        for i, x in enumerate((8.2, 10.6, 13.0, 15.2)):
            p.drawLine(QPointF(x, 9), QPointF(x, 5.5 if i in (1, 2) else 6.5))

    return _make(draw)


def zoom_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(9.5, 9.5), 5.2, 5.2)
        p.setPen(QPen(_INK, 2.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(13.6, 13.6), QPointF(17.5, 17.5))
        p.setPen(QPen(_INK, 1.4))
        p.drawLine(QPointF(7.2, 9.5), QPointF(11.8, 9.5))
        p.drawLine(QPointF(9.5, 7.2), QPointF(9.5, 11.8))

    return _make(draw)


def poly_lasso_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        pen = QPen(_INK, 1.6, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(5, 9))
        path.lineTo(QPointF(12, 5))
        path.lineTo(QPointF(18, 9))
        path.lineTo(QPointF(15, 16))
        path.lineTo(QPointF(7, 15))
        path.closeSubpath()
        p.drawPath(path)

    return _make(draw)


def wand_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(8, 14), QPointF(16, 6))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(_INK))
        for cx, cy, r in ((6, 7, 1.2), (11, 4, 1.0), (17.5, 12, 1.2), (5.5, 17, 1.0)):
            p.drawEllipse(QPointF(cx, cy), r, r)

    return _make(draw)


def gradient_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        from PySide6.QtGui import QLinearGradient

        grad = QLinearGradient(QPointF(5, 11), QPointF(17, 11))
        grad.setColorAt(0.0, _INK)
        faded = QColor(_INK)
        faded.setAlpha(20)
        grad.setColorAt(1.0, faded)
        p.setPen(QPen(_INK, 1.4))
        p.setBrush(QBrush(grad))
        p.drawRect(QRectF(4.5, 6.5, 13, 9))

    return _make(draw)


def pencil_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.save()
        p.translate(11, 11)
        p.rotate(45)
        p.drawRect(QRectF(-2.5, -8, 5, 12))
        tip = QPainterPath(QPointF(-2.5, 4))
        tip.lineTo(QPointF(0, 8.5))
        tip.lineTo(QPointF(2.5, 4))
        p.drawPath(tip)
        p.restore()

    return _make(draw)


TOOL_ICONS = {
    "brush": brush_icon,
    "pencil": pencil_icon,
    "bucket": bucket_icon,
    "gradient": gradient_icon,
    "eyedropper": eyedropper_icon,
    "rect-select": rect_select_icon,
    "lasso": lasso_icon,
    "poly-lasso": poly_lasso_icon,
    "wand": wand_icon,
    "move": move_icon,
    "hand": hand_icon,
    "zoom": zoom_icon,
}
