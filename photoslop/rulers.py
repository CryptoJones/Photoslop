# SPDX-License-Identifier: Apache-2.0
"""Rulers in pixels, inches, millimetres, or picas — and the origin of
guides: press on a ruler and drag into the canvas to place one."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from photoslop import units

THICKNESS = 24


class Ruler(QWidget):
    guideDragged = Signal(QPoint)  # global pos
    guideDropped = Signal(QPoint)  # global pos

    def __init__(self, orientation: Qt.Orientation, parent=None) -> None:
        super().__init__(parent)
        self.orientation = orientation
        self.origin = 0.0  # widget px where canvas coordinate 0 sits
        self.zoom = 1.0
        self.dpi = 72.0
        self.unit = "px"
        self.length = 0  # canvas extent in canvas px
        self.marker: float | None = None  # canvas coords
        self._dragging = False
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(THICKNESS)
        else:
            self.setFixedWidth(THICKNESS)
        self.setMouseTracking(True)

    def configure(self, origin: float, zoom: float, dpi: float, unit: str, length: int) -> None:
        self.origin = origin
        self.zoom = zoom
        self.dpi = dpi
        self.unit = unit
        self.length = length
        self.update()

    def set_marker(self, canvas_pos: float | None) -> None:
        self.marker = canvas_pos
        self.update()

    # -- guide creation ------------------------------------------------------

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._dragging = True

    def mouseMoveEvent(self, ev) -> None:
        if self._dragging:
            self.guideDragged.emit(ev.globalPosition().toPoint())

    def mouseReleaseEvent(self, ev) -> None:
        if self._dragging:
            self._dragging = False
            self.guideDropped.emit(ev.globalPosition().toPoint())

    # -- painting --------------------------------------------------------------

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        bg = self.palette().window().color().darker(104)
        p.fillRect(self.rect(), bg)
        fg = self.palette().windowText().color()
        dim = QColor(fg)
        dim.setAlpha(140)

        horizontal = self.orientation == Qt.Orientation.Horizontal
        edge = self.height() - 1 if horizontal else self.width() - 1
        p.setPen(QPen(dim, 1))
        if horizontal:
            p.drawLine(0, edge, self.width(), edge)
        else:
            p.drawLine(edge, 0, edge, self.height())

        ppu = units.px_per_unit(self.unit, self.dpi) * self.zoom  # screen px per unit
        step = units.pick_tick_step(self.unit, self.dpi, self.zoom)
        minor = step / 5.0 if step * ppu >= 30.0 else step / 2.0

        font = p.font()
        font.setPointSizeF(7.5)
        p.setFont(font)

        length_units = self.length / units.px_per_unit(self.unit, self.dpi)

        # minor ticks
        p.setPen(QPen(dim, 1))
        value = 0.0
        while value <= length_units + 1e-9:
            w = self.origin + value * ppu
            if -2 <= w <= (self.width() if horizontal else self.height()) + 2:
                self._tick(p, w, edge, 5)
            value += minor

        # major ticks + labels
        p.setPen(QPen(fg, 1))
        value = 0.0
        while value <= length_units + 1e-9:
            w = self.origin + value * ppu
            if -60 <= w <= (self.width() if horizontal else self.height()) + 60:
                self._tick(p, w, edge, 11)
                label = units.format_tick(value)
                if horizontal:
                    p.drawText(QRectF(w + 2, 0, 56, self.height() - 8),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
                else:
                    p.save()
                    p.translate(0, w - 2)
                    p.rotate(-90)
                    p.drawText(QRectF(2, 0, 56, self.width() - 8),
                               Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, label)
                    p.restore()
            value += step

        # cursor marker
        if self.marker is not None:
            w = self.origin + self.marker * self.zoom
            p.setPen(QPen(QColor(220, 60, 60), 1))
            if horizontal:
                p.drawLine(QPointF(w, 0), QPointF(w, self.height()))
            else:
                p.drawLine(QPointF(0, w), QPointF(self.width(), w))
        p.end()

    def _tick(self, p: QPainter, w: float, edge: int, length: int) -> None:
        if self.orientation == Qt.Orientation.Horizontal:
            p.drawLine(QPointF(w, edge - length), QPointF(w, edge))
        else:
            p.drawLine(QPointF(edge - length, w), QPointF(edge, w))
