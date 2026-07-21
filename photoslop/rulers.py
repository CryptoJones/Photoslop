# SPDX-License-Identifier: Apache-2.0
"""Rulers in pixels, inches, millimetres, or picas — and the origin of
guides: press on a ruler and drag into the canvas to place one."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF
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
        self.marker: float | None = None  # canvas coords (cursor)
        self.guide_marker: float | None = None  # canvas coords (guide being dragged)
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
        axis = ("Horizontal" if self.orientation == Qt.Orientation.Horizontal
                else "Vertical")
        self.setAccessibleDescription(
            f"{axis} ruler, {length} pixels, units {units.unit_label(unit)}, "
            "drag to create a guide; keyboard guide commands are available in View.")
        self.update()

    def set_marker(self, canvas_pos: float | None) -> None:
        self.marker = canvas_pos
        self.update()

    def set_guide_marker(self, canvas_pos: float | None) -> None:
        self.guide_marker = canvas_pos
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
        minor = units.minor_tick_step(self.unit, self.dpi, self.zoom)

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
        end_w = self.origin + length_units * ppu
        p.setPen(QPen(fg, 1))
        value = 0.0
        while value <= length_units + 1e-9:
            w = self.origin + value * ppu
            if -60 <= w <= (self.width() if horizontal else self.height()) + 60:
                self._tick(p, w, edge, 11)
                # the exact-extent end label owns the last stretch of ruler
                if end_w - w < 52:
                    value += step
                    continue
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

        # end-of-image marker: a full-height tick + the exact extent, so the
        # scale always reads to the true edge (8192, 11648, ...) even when the
        # image size isn't a round multiple of the tick step
        extent = self.width() if horizontal else self.height()
        if -60 <= end_w <= extent + 60:
            self._tick(p, end_w, edge, edge)
            label = units.format_tick(length_units)
            if horizontal:
                p.drawText(QRectF(end_w - 58, 0, 56, self.height() - 8),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
                           label)
            else:
                p.save()
                p.translate(0, end_w + 2)
                p.rotate(-90)
                p.drawText(QRectF(0, 0, 56, self.width() - 8),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
                           label)
                p.restore()

        # cursor marker (round exactly like the canvas draws guides, so the
        # hairline and a guide under the cursor form one continuous line)
        if self.marker is not None:
            w = self.origin + round(self.marker * self.zoom)
            p.setPen(QPen(QColor(220, 60, 60), 1))
            if horizontal:
                p.drawLine(QPointF(w, 0), QPointF(w, self.height()))
            else:
                p.drawLine(QPointF(0, w), QPointF(self.width(), w))

        # guide-drag marker: full line + a triangle at the canvas-adjacent edge
        if self.guide_marker is not None:
            w = self.origin + round(self.guide_marker * self.zoom)
            color = QColor(255, 0, 200)
            p.setPen(QPen(color, 1))
            tri = QPolygonF()
            if horizontal:
                p.drawLine(QPointF(w, 0), QPointF(w, self.height()))
                tri.append(QPointF(w - 4, edge - 6))
                tri.append(QPointF(w + 4, edge - 6))
                tri.append(QPointF(w, edge))
            else:
                p.drawLine(QPointF(0, w), QPointF(self.width(), w))
                tri.append(QPointF(edge - 6, w - 4))
                tri.append(QPointF(edge - 6, w + 4))
                tri.append(QPointF(edge, w))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawPolygon(tri)
        p.end()

    def _tick(self, p: QPainter, w: float, edge: int, length: int) -> None:
        if self.orientation == Qt.Orientation.Horizontal:
            p.drawLine(QPointF(w, edge - length), QPointF(w, edge))
        else:
            p.drawLine(QPointF(edge - length, w), QPointF(edge, w))
