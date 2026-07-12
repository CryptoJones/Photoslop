# SPDX-License-Identifier: Apache-2.0
"""Contextual, high-contrast cursors for canvas tools.

Tools describe intent; this module owns rendering, hotspots, HiDPI scaling,
and the temporary Hand override.  Keeping cursor policy here prevents tools
and canvas event handlers from fighting over ``QWidget.setCursor``.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath, QPen, QPixmap


@dataclass(frozen=True)
class CursorContext:
    position: QPointF | None
    modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier
    dragging: bool = False
    zoom: float = 1.0


@dataclass(frozen=True)
class CursorIntent:
    """Declarative cursor request returned by an interactive tool."""

    kind: str
    badge: str = ""
    diameter: int = 0
    valid: bool = True


_PAINT_TOOLS = {
    "brush", "pencil", "eraser", "clone-stamp", "heal", "spot-heal",
    "smudge", "dodge", "burn", "liquify", "quick-select",
}
_SELECTION_TOOLS = {
    "rect-select", "ellipse-select", "lasso", "poly-lasso",
    "magnetic-lasso", "wand", "quick-select",
}


def default_intent(tool_name: str, context: CursorContext, brush_size: int = 16) -> CursorIntent:
    """Return the standard intent for a tool without special live state."""
    mods = context.modifiers
    badge = ""
    if tool_name in _SELECTION_TOOLS:
        if mods & Qt.KeyboardModifier.ShiftModifier and mods & Qt.KeyboardModifier.AltModifier:
            badge = "x"
        elif mods & Qt.KeyboardModifier.AltModifier:
            badge = "−"
        elif mods & Qt.KeyboardModifier.ShiftModifier:
            badge = "+"
    if tool_name in _PAINT_TOOLS:
        return CursorIntent("brush", badge, max(1, round(brush_size * context.zoom)))
    kinds = {
        "bucket": "bucket",
        "gradient": "gradient",
        "eyedropper": "eyedropper",
        "rect-select": "select-rect",
        "ellipse-select": "select-ellipse",
        "lasso": "lasso",
        "poly-lasso": "lasso",
        "magnetic-lasso": "magnetic",
        "wand": "wand",
        "patch": "patch",
        "perspective": "perspective",
        "puppet": "node",
        "text": "text",
        "shape": "shape",
        "pen": "pen",
        "crop": "crop",
        "move": "move",
        "hand": "hand-closed" if context.dragging else "hand-open",
        "zoom": "zoom-out" if mods & Qt.KeyboardModifier.AltModifier else "zoom-in",
    }
    return CursorIntent(kinds.get(tool_name, "cross"), badge)


class CursorRenderer:
    """Render and cache high-contrast custom cursors."""

    def __init__(self) -> None:
        self._cache: dict[tuple[CursorIntent, float], QCursor] = {}

    def cursor(self, intent: CursorIntent, dpr: float = 1.0) -> QCursor:
        builtin = {
            "text": Qt.CursorShape.IBeamCursor,
            "move": Qt.CursorShape.SizeAllCursor,
            "hand-open": Qt.CursorShape.OpenHandCursor,
            "hand-closed": Qt.CursorShape.ClosedHandCursor,
            "resize-h": Qt.CursorShape.SizeHorCursor,
            "resize-v": Qt.CursorShape.SizeVerCursor,
            "resize-fdiag": Qt.CursorShape.SizeFDiagCursor,
            "resize-bdiag": Qt.CursorShape.SizeBDiagCursor,
            "forbidden": Qt.CursorShape.ForbiddenCursor,
        }
        kind = "forbidden" if not intent.valid else intent.kind
        if kind in builtin and not intent.badge:
            return QCursor(builtin[kind])
        key = (CursorIntent(kind, intent.badge, intent.diameter, intent.valid), round(dpr, 2))
        if key not in self._cache:
            self._cache[key] = self._render(key[0], max(1.0, dpr))
        return self._cache[key]

    def _render(self, intent: CursorIntent, dpr: float) -> QCursor:
        # Native cursor sizes are limited on some platforms.  Large brushes use
        # the exact canvas overlay and retain a compact precision cursor.
        diameter = min(intent.diameter, 64) if intent.kind == "brush" else 0
        logical = max(32, diameter + 8)
        physical = round(logical * dpr)
        pm = QPixmap(physical, physical)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        c = logical / 2

        def stroke_path(path: QPainterPath, width: float = 1.4) -> None:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(255, 255, 255, 245), width + 2.2,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)
            p.setPen(QPen(QColor(15, 15, 15, 245), width,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                          Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)

        path = self._glyph(intent.kind, c, diameter)
        stroke_path(path)
        if intent.badge:
            r = QRectF(logical - 13, logical - 13, 12, 12)
            p.setPen(QPen(QColor(255, 255, 255), 3))
            p.setBrush(QColor(15, 15, 15))
            p.drawEllipse(r)
            p.setPen(QColor(255, 255, 255))
            font = p.font()
            font.setBold(True)
            font.setPixelSize(9)
            p.setFont(font)
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, intent.badge)
        p.end()
        return QCursor(pm, round(c), round(c))

    @staticmethod
    def _glyph(kind: str, c: float, diameter: int) -> QPainterPath:
        path = QPainterPath()
        if kind == "brush":
            r = max(2.0, diameter / 2.0)
            path.addEllipse(QPointF(c, c), r, r)
            path.moveTo(c - 3, c)
            path.lineTo(c + 3, c)
            path.moveTo(c, c - 3)
            path.lineTo(c, c + 3)
        elif kind.startswith("zoom"):
            path.addEllipse(QPointF(c - 2, c - 2), 6, 6)
            path.moveTo(c + 2, c + 2)
            path.lineTo(c + 8, c + 8)
            path.moveTo(c - 5, c - 2)
            path.lineTo(c + 1, c - 2)
            if kind == "zoom-in":
                path.moveTo(c - 2, c - 5)
                path.lineTo(c - 2, c + 1)
        elif kind == "rotate":
            path.arcMoveTo(QRectF(c - 8, c - 8, 16, 16), 40)
            path.arcTo(QRectF(c - 8, c - 8, 16, 16), 40, 275)
            path.moveTo(c + 7, c - 6)
            path.lineTo(c + 8, c)
            path.lineTo(c + 2, c - 2)
        elif kind == "eyedropper":
            path.moveTo(c - 7, c + 7)
            path.lineTo(c + 5, c - 5)
            path.addEllipse(QPointF(c + 6, c - 6), 3, 3)
        elif kind == "bucket":
            path.addRect(QRectF(c - 7, c - 6, 11, 11))
            path.moveTo(c + 4, c + 4)
            path.cubicTo(c + 9, c + 5, c + 9, c + 10, c + 5, c + 10)
        elif kind == "gradient":
            path.addRect(QRectF(c - 8, c - 6, 16, 12))
            path.moveTo(c - 5, c)
            path.lineTo(c + 5, c)
        elif kind in {"select-rect", "select-ellipse", "shape", "crop"}:
            if kind == "select-ellipse":
                path.addEllipse(QRectF(c - 8, c - 6, 16, 12))
            elif kind == "crop":
                path.moveTo(c - 8, c - 3)
                path.lineTo(c + 4, c - 3)
                path.moveTo(c - 3, c - 8)
                path.lineTo(c - 3, c + 4)
                path.moveTo(c + 3, c - 4)
                path.lineTo(c + 3, c + 8)
                path.moveTo(c - 4, c + 3)
                path.lineTo(c + 8, c + 3)
            else:
                path.addRect(QRectF(c - 8, c - 6, 16, 12))
        elif kind in {"lasso", "magnetic", "patch"}:
            path.moveTo(c - 7, c - 5)
            path.cubicTo(c - 11, c + 4, c + 2, c + 10, c + 8, c + 2)
            path.cubicTo(c + 10, c - 5, c, c - 9, c - 7, c - 5)
            if kind == "magnetic":
                path.moveTo(c - 4, c + 7)
                path.lineTo(c - 4, c + 11)
                path.moveTo(c, c + 7)
                path.lineTo(c, c + 11)
        elif kind in {"pen", "node", "perspective"}:
            path.moveTo(c, c - 9)
            path.lineTo(c + 7, c + 4)
            path.lineTo(c, c + 9)
            path.lineTo(c - 7, c + 4)
            path.closeSubpath()
            path.addEllipse(QPointF(c, c + 2), 2, 2)
        elif kind == "wand":
            path.moveTo(c - 6, c + 7)
            path.lineTo(c + 5, c - 4)
            for dx, dy in ((-6, -5), (0, -8), (7, 2)):
                path.moveTo(c + dx - 1, c + dy)
                path.lineTo(c + dx + 1, c + dy)
        else:
            path.moveTo(c - 7, c)
            path.lineTo(c + 7, c)
            path.moveTo(c, c - 7)
            path.lineTo(c, c + 7)
        return path


class CursorController:
    """Single owner for a canvas widget's cursor state."""

    def __init__(self, widget) -> None:
        self.widget = widget
        self.renderer = CursorRenderer()
        self.intent = CursorIntent("cross")

    def apply(self, intent: CursorIntent) -> None:
        self.intent = intent
        self.widget.setCursor(self.renderer.cursor(intent, self.widget.devicePixelRatioF()))
