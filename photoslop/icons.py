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


def magnetic_lasso_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        pen = QPen(_INK, 1.6, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(11, 10), 6.5, 5.0)
        p.setPen(QPen(_INK, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(7, 16), QPointF(7, 19))  # magnet legs
        p.drawLine(QPointF(11, 16), QPointF(11, 19))

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


def eraser_tool_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.save()
        p.translate(11, 11)
        p.rotate(-35)
        p.drawRect(QRectF(-6, -3.5, 12, 7))
        p.drawLine(QPointF(-2, -3.5), QPointF(-2, 3.5))  # ferrule line
        p.restore()
        p.setPen(QPen(_INK, 1.4))
        p.drawLine(QPointF(6, 18), QPointF(16, 18))  # rubbed-out streak

    return _make(draw)


def heal_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.save()
        p.translate(11, 11)
        p.rotate(-45)
        p.drawRoundedRect(QRectF(-8, -3, 16, 6), 3, 3)  # plaster
        p.drawLine(QPointF(-2.5, -3), QPointF(-2.5, 3))
        p.drawLine(QPointF(2.5, -3), QPointF(2.5, 3))
        p.restore()

    return _make(draw)


def patch_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        pen = QPen(_INK, 1.5, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(8, 8), 4.5, 4.5)
        p.setPen(QPen(_INK, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(11, 11), QPointF(17, 17))  # drag arrow
        p.drawLine(QPointF(17, 17), QPointF(13.5, 16.5))
        p.drawLine(QPointF(17, 17), QPointF(16.5, 13.5))

    return _make(draw)


def liquify_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(4, 12))
        path.cubicTo(QPointF(8, 6), QPointF(10, 18), QPointF(14, 10))
        path.cubicTo(QPointF(16, 7), QPointF(18, 9), QPointF(18.5, 8))
        p.drawPath(path)
        p.drawLine(QPointF(15.5, 5.5), QPointF(18.5, 8))
        p.drawLine(QPointF(15.8, 10.8), QPointF(18.5, 8))

    return _make(draw)


def text_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(5, 6), QPointF(17, 6))
        p.drawLine(QPointF(11, 6), QPointF(11, 17.5))
        p.drawLine(QPointF(8.5, 17.5), QPointF(13.5, 17.5))

    return _make(draw)


def spot_heal_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(11, 5), QPointF(11, 17))  # plaster cross
        p.drawLine(QPointF(5, 11), QPointF(17, 11))
        p.setPen(QPen(_INK, 1.2, Qt.PenStyle.DotLine))
        p.drawEllipse(QPointF(11, 11), 8, 8)

    return _make(draw)


def smudge_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath(QPointF(5, 16))
        path.cubicTo(QPointF(9, 16), QPointF(9, 8), QPointF(13, 8))
        path.cubicTo(QPointF(16, 8), QPointF(17, 5), QPointF(17.5, 4))
        p.drawPath(path)
        p.setPen(QPen(_INK, 1.2))
        p.drawLine(QPointF(5, 18.5), QPointF(11, 18.5))

    return _make(draw)


def dodge_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(11, 11), 4.0, 4.0)  # sun disc
        p.setPen(QPen(_INK, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            p.drawLine(QPointF(11 + dx * 6, 11 + dy * 6),
                       QPointF(11 + dx * 8.5, 11 + dy * 8.5))

    return _make(draw)


def burn_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.8))
        p.setBrush(QBrush(_INK))
        p.drawEllipse(QPointF(11, 11), 4.0, 4.0)  # filled = darkened disc
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(11, 11), 7.5, 7.5)

    return _make(draw)


def crop_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(7, 3), QPointF(7, 15))   # left crop mark
        p.drawLine(QPointF(7, 15), QPointF(19, 15))
        p.drawLine(QPointF(3, 7), QPointF(15, 7))   # top crop mark
        p.drawLine(QPointF(15, 7), QPointF(15, 19))

    return _make(draw)


def clone_stamp_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(11, 8), 4.5, 4.5)  # stamp head
        p.drawLine(QPointF(11, 12.5), QPointF(11, 15))  # handle
        p.drawLine(QPointF(5, 17.5), QPointF(17, 17.5))  # base

    return _make(draw)


def quick_select_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(_INK, 1.5, Qt.PenStyle.DashLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(10, 12), 6.5, 6.5)
        p.setPen(QPen(_INK, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(13.5, 8.5), QPointF(17.5, 4.5))

    return _make(draw)


TOOL_ICONS = {
    "brush": brush_icon,
    "pencil": pencil_icon,
    "eraser": eraser_tool_icon,
    "bucket": bucket_icon,
    "gradient": gradient_icon,
    "eyedropper": eyedropper_icon,
    "clone-stamp": clone_stamp_icon,
    "smudge": smudge_icon,
    "spot-heal": spot_heal_icon,
    "heal": heal_icon,
    "patch": patch_icon,
    "liquify": liquify_icon,
    "text": text_icon,
    "crop": crop_icon,
    "dodge": dodge_icon,
    "burn": burn_icon,
    "rect-select": rect_select_icon,
    "lasso": lasso_icon,
    "poly-lasso": poly_lasso_icon,
    "magnetic-lasso": magnetic_lasso_icon,
    "wand": wand_icon,
    "quick-select": quick_select_icon,
    "move": move_icon,
    "hand": hand_icon,
    "zoom": zoom_icon,
}
