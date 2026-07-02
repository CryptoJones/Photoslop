# SPDX-License-Identifier: Apache-2.0
"""The canvas widget and the per-document editor view (rulers + scroll area).

CanvasView composites layers directly in paintEvent, clipped to the exposed
rect — the viewport is the only thing ever rendered, and there is no cached
flattened image anywhere.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QScrollArea, QToolButton, QWidget

from photoslop import units
from photoslop.commands import SetLayerOffsetCommand
from photoslop.document import Document
from photoslop.rulers import Ruler

ZOOM_LEVELS = (0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0)

_GUIDE_COLOR = QColor(0, 200, 255)
_TEMP_GUIDE_COLOR = QColor(255, 0, 200)


def _checker_pixmap() -> QPixmap:
    pm = QPixmap(16, 16)
    pm.fill(QColor(200, 200, 200))
    p = QPainter(pm)
    p.fillRect(0, 0, 8, 8, QColor(230, 230, 230))
    p.fillRect(8, 8, 8, 8, QColor(230, 230, 230))
    p.end()
    return pm


class CanvasView(QWidget):
    mousePos = Signal(object)  # QPointF in canvas coords, or None on leave

    def __init__(self, doc: Document, editor: EditorView) -> None:
        super().__init__()
        self.doc = doc
        self.editor = editor
        self.zoom = 1.0
        self.hover_pos: QPointF | None = None
        self.temp_guide: tuple[str, float] | None = None
        # (orient, canvas value, anchor in widget coords) while a guide is dragged
        self.guide_label: tuple[str, float, QPointF] | None = None
        self._ants_offset = 0.0
        self._ants = QTimer(self)
        self._ants.setInterval(120)
        self._ants.timeout.connect(self._advance_ants)
        self._checker = QBrush(_checker_pixmap())

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        doc.pixelsChanged.connect(self._on_pixels)
        doc.structureChanged.connect(self._on_structure)
        doc.selectionChanged.connect(self._on_selection)
        doc.guidesChanged.connect(self.update)
        self._resize_to_zoom()

    # -- geometry --

    def _resize_to_zoom(self) -> None:
        self.setFixedSize(
            max(1, math.ceil(self.doc.size.width() * self.zoom)),
            max(1, math.ceil(self.doc.size.height() * self.zoom)),
        )

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(ZOOM_LEVELS[0], min(zoom, ZOOM_LEVELS[-1]))
        self._resize_to_zoom()
        self.update()
        self.editor.sync_rulers()

    def _canvas_to_widget(self, rect: QRect) -> QRect:
        z = self.zoom
        return QRect(
            math.floor(rect.x() * z) - 2,
            math.floor(rect.y() * z) - 2,
            math.ceil(rect.width() * z) + 4,
            math.ceil(rect.height() * z) + 4,
        )

    # -- document signals --

    def _on_pixels(self, rect: QRect) -> None:
        self.update(self._canvas_to_widget(rect))

    def _on_structure(self) -> None:
        self._resize_to_zoom()
        self.update()
        self.editor.sync_rulers()

    def _on_selection(self) -> None:
        if self.doc.selection is None:
            self._ants.stop()
        elif not self._ants.isActive():
            self._ants.start()
        self.update()

    def _advance_ants(self) -> None:
        self._ants_offset = (self._ants_offset + 1.0) % 8.0
        sel = self.doc.selection
        if sel is not None:
            self.update(self._canvas_to_widget(sel.boundingRect().toAlignedRect()))

    # -- painting --

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        exposed = ev.rect()
        p.fillRect(exposed, self._checker)

        z = self.zoom
        p.save()
        p.scale(z, z)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, z < 1.0)
        clip = QRectF(exposed).adjusted(-1, -1, 1, 1)
        p.setClipRect(QRectF(clip.x() / z, clip.y() / z, clip.width() / z, clip.height() / z))
        for layer in self.doc.layers:
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.drawImage(QPointF(layer.offset), layer.image)
        p.restore()
        p.setOpacity(1.0)

        self._paint_guides(p)
        self._paint_selection(p)
        self._paint_guide_label(p)
        tool = self.editor.active_tool()
        if tool is not None:
            tool.overlay(self.doc, p, self)
        p.end()

    def _paint_guides(self, p: QPainter) -> None:
        z = self.zoom
        p.setPen(QPen(_GUIDE_COLOR, 1))
        for y in self.doc.guides_h:
            wy = round(y * z)
            p.drawLine(0, wy, self.width(), wy)
        for x in self.doc.guides_v:
            wx = round(x * z)
            p.drawLine(wx, 0, wx, self.height())
        if self.temp_guide is not None:
            p.setPen(QPen(_TEMP_GUIDE_COLOR, 1, Qt.PenStyle.DashLine))
            orient, pos = self.temp_guide
            w = round(pos * z)
            if orient == "h":
                p.drawLine(0, w, self.width(), w)
            else:
                p.drawLine(w, 0, w, self.height())

    def _paint_guide_label(self, p: QPainter) -> None:
        if self.guide_label is None:
            return
        orient, value, anchor = self.guide_label
        axis = "Y" if orient == "h" else "X"
        text = f"{axis}: {units.format_value_precise(value, self.editor.host.unit, self.doc.dpi)}"
        rect = p.fontMetrics().boundingRect(text).adjusted(-5, -3, 5, 3)
        rect.moveTo(int(anchor.x()) + 14, int(anchor.y()) - rect.height() - 8)
        if rect.right() > self.width() - 2:
            rect.moveRight(self.width() - 2)
        if rect.left() < 2:
            rect.moveLeft(2)
        if rect.top() < 2:
            rect.moveTop(int(anchor.y()) + 16)
        if rect.bottom() > self.height() - 2:
            rect.moveBottom(self.height() - 2)
        p.setPen(QPen(QColor(70, 70, 70), 1))
        p.setBrush(QColor(255, 255, 245, 235))
        p.drawRoundedRect(rect, 3, 3)
        p.setPen(QColor(20, 20, 20))
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_selection(self, p: QPainter) -> None:
        sel = self.doc.selection
        if sel is None:
            return
        p.save()
        p.scale(self.zoom, self.zoom)
        p.setBrush(Qt.BrushStyle.NoBrush)
        white = QPen(QColor(255, 255, 255), 0)
        white.setCosmetic(True)
        p.setPen(white)
        p.drawPath(sel)
        ants = QPen(QColor(0, 0, 0), 0, Qt.PenStyle.CustomDashLine)
        ants.setCosmetic(True)
        ants.setDashPattern([4.0, 4.0])
        ants.setDashOffset(self._ants_offset)
        p.setPen(ants)
        p.drawPath(sel)
        p.restore()

    # -- input --

    def _canvas_pos(self, ev) -> QPointF:
        wp = ev.position()
        return QPointF(wp.x() / self.zoom, wp.y() / self.zoom)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            tool = self.editor.active_tool()
            if tool is not None:
                tool.press(self.doc, self, self._canvas_pos(ev), ev)

    def mouseMoveEvent(self, ev) -> None:
        pos = self._canvas_pos(ev)
        self.hover_pos = pos
        self.mousePos.emit(pos)
        if ev.buttons() & Qt.MouseButton.LeftButton:
            tool = self.editor.active_tool()
            if tool is not None:
                tool.move(self.doc, self, pos, ev)
        else:
            self.update()  # brush outline follows the cursor

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            tool = self.editor.active_tool()
            if tool is not None:
                tool.release(self.doc, self, self._canvas_pos(ev), ev)

    def leaveEvent(self, ev) -> None:
        self.hover_pos = None
        self.mousePos.emit(None)
        self.update()

    def wheelEvent(self, ev) -> None:
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.editor.zoom_step(1 if ev.angleDelta().y() > 0 else -1, ev.position())
            ev.accept()
        else:
            ev.ignore()

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        if key == Qt.Key.Key_Escape:
            self.doc.set_selection(None)
            return
        nudges = {
            Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
            Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
        }
        tool = self.editor.active_tool()
        if key in nudges and tool is not None and tool.name == "move":
            layer = self.doc.active_layer
            if layer is not None:
                dx, dy = nudges[key]
                if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    dx, dy = dx * 10, dy * 10
                old = QPoint(layer.offset)
                layer.offset = old + QPoint(dx, dy)
                self.doc.notify_pixels(layer.bounds().united(
                    QRect(old, layer.image.size())))
                self.doc.undo_stack.push(
                    SetLayerOffsetCommand(self.doc, layer, old, layer.offset))
            return
        super().keyPressEvent(ev)


class EditorView(QWidget):
    """One open document: corner unit button, two rulers, scrollable canvas."""

    def __init__(self, doc: Document, host) -> None:
        super().__init__()
        self.doc = doc
        self.host = host  # MainWindow-ish: provides active_tool(), unit, set_unit()

        self.canvas = CanvasView(doc, self)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.viewport().setBackgroundRole(self.scroll.backgroundRole())

        self.hruler = Ruler(Qt.Orientation.Horizontal)
        self.vruler = Ruler(Qt.Orientation.Vertical)
        self.corner = QToolButton()
        self.corner.setToolTip("Cycle ruler units")
        self.corner.setAutoRaise(True)
        self.corner.clicked.connect(self._cycle_unit)

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(0)
        grid.addWidget(self.corner, 0, 0)
        grid.addWidget(self.hruler, 0, 1)
        grid.addWidget(self.vruler, 1, 0)
        grid.addWidget(self.scroll, 1, 1)

        self.scroll.horizontalScrollBar().valueChanged.connect(self.sync_rulers)
        self.scroll.verticalScrollBar().valueChanged.connect(self.sync_rulers)
        self.scroll.viewport().installEventFilter(self)

        self.canvas.mousePos.connect(self._on_mouse_pos)
        self.hruler.guideDragged.connect(lambda g: self._guide_drag("h", g))
        self.hruler.guideDropped.connect(lambda g: self._guide_drop("h", g))
        self.vruler.guideDragged.connect(lambda g: self._guide_drag("v", g))
        self.vruler.guideDropped.connect(lambda g: self._guide_drop("v", g))

        self.sync_rulers()

    def active_tool(self):
        return self.host.active_tool

    def eventFilter(self, obj, ev) -> bool:
        if obj is self.scroll.viewport() and ev.type() == QEvent.Type.Resize:
            self.sync_rulers()
        return False

    # -- rulers --

    def sync_rulers(self) -> None:
        origin = self.canvas.mapTo(self.scroll.viewport(), QPoint(0, 0))
        unit = self.host.unit
        zoom = self.canvas.zoom
        self.hruler.configure(origin.x(), zoom, self.doc.dpi, unit, self.doc.size.width())
        self.vruler.configure(origin.y(), zoom, self.doc.dpi, unit, self.doc.size.height())
        self.corner.setText(unit)

    def _cycle_unit(self) -> None:
        current = units.UNITS.index(self.host.unit)
        self.host.set_unit(units.UNITS[(current + 1) % len(units.UNITS)])

    def _on_mouse_pos(self, pos) -> None:
        self.hruler.set_marker(None if pos is None else pos.x())
        self.vruler.set_marker(None if pos is None else pos.y())
        self.host.show_mouse_pos(self.doc, pos)

    # -- zoom --

    def set_zoom(self, zoom: float, anchor: QPointF | None = None) -> None:
        old_zoom = self.canvas.zoom
        if anchor is None:
            vp = self.scroll.viewport()
            anchor = QPointF(vp.width() / 2, vp.height() / 2)
            origin = self.canvas.mapTo(vp, QPoint(0, 0))
            canvas_anchor = QPointF(
                (anchor.x() - origin.x()) / old_zoom, (anchor.y() - origin.y()) / old_zoom
            )
        else:
            canvas_anchor = QPointF(anchor.x() / old_zoom, anchor.y() / old_zoom)
            anchor = self.canvas.mapTo(self.scroll.viewport(), anchor.toPoint())
            anchor = QPointF(anchor)

        self.canvas.set_zoom(zoom)
        new_zoom = self.canvas.zoom
        # keep the anchor point stationary in the viewport
        hbar = self.scroll.horizontalScrollBar()
        vbar = self.scroll.verticalScrollBar()
        hbar.setValue(round(canvas_anchor.x() * new_zoom - anchor.x()))
        vbar.setValue(round(canvas_anchor.y() * new_zoom - anchor.y()))
        self.sync_rulers()
        self.host.show_zoom(new_zoom)

    def zoom_step(self, direction: int, anchor: QPointF | None = None) -> None:
        z = self.canvas.zoom
        if direction > 0:
            nxt = next((lv for lv in ZOOM_LEVELS if lv > z * 1.001), ZOOM_LEVELS[-1])
        else:
            nxt = next((lv for lv in reversed(ZOOM_LEVELS) if lv < z * 0.999), ZOOM_LEVELS[0])
        self.set_zoom(nxt, anchor)

    def zoom_fit(self) -> None:
        vp = self.scroll.viewport()
        margin = 20
        zw = (vp.width() - margin) / max(1, self.doc.size.width())
        zh = (vp.height() - margin) / max(1, self.doc.size.height())
        self.set_zoom(max(ZOOM_LEVELS[0], min(zw, zh)))

    # -- guides --

    def _guide_pos(self, orient: str, global_pos: QPoint) -> float:
        local = self.canvas.mapFromGlobal(global_pos)
        z = self.canvas.zoom
        return (local.y() if orient == "h" else local.x()) / z

    def show_guide_feedback(self, orient: str, pos: float,
                            anchor: QPointF | None = None) -> None:
        """Live drag feedback: marker on the matching ruler, floating X/Y
        readout on the canvas, echo in the status bar."""
        ruler = self.vruler if orient == "h" else self.hruler
        other = self.hruler if orient == "h" else self.vruler
        ruler.set_guide_marker(pos)
        other.set_guide_marker(None)
        if anchor is None:
            hp = self.canvas.hover_pos
            z = self.canvas.zoom
            anchor = QPointF(hp.x() * z, hp.y() * z) if hp is not None else QPointF(8, 8)
        self.canvas.guide_label = (orient, pos, anchor)
        self.canvas.update()
        self.host.show_guide_value(orient, pos, self.doc.dpi)

    def clear_guide_feedback(self) -> None:
        self.hruler.set_guide_marker(None)
        self.vruler.set_guide_marker(None)
        self.canvas.guide_label = None
        self.canvas.update()

    def _guide_drag(self, orient: str, global_pos: QPoint) -> None:
        pos = self._guide_pos(orient, global_pos)
        self.canvas.temp_guide = (orient, pos)
        self.show_guide_feedback(orient, pos, QPointF(self.canvas.mapFromGlobal(global_pos)))

    def _guide_drop(self, orient: str, global_pos: QPoint) -> None:
        self.canvas.temp_guide = None
        self.clear_guide_feedback()
        local = self.canvas.mapFromGlobal(global_pos)
        if self.canvas.rect().contains(local):
            self.doc.add_guide(orient, self._guide_pos(orient, global_pos))
        self.canvas.update()
