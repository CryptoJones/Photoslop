# SPDX-License-Identifier: Apache-2.0
"""The canvas widget and the per-document editor view (rulers + scroll area).

CanvasView composites layers directly in paintEvent, clipped to the exposed
rect — the viewport is the only thing ever rendered, and there is no cached
flattened image anywhere.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QGridLayout, QScrollArea, QToolButton, QWidget

from photoslop import units
from photoslop.commands import SetLayerOffsetCommand
from photoslop.cursors import CursorController, CursorIntent
from photoslop.document import Document, draw_layer, render_region
from photoslop.layer import BLEND_MODES
from photoslop.rulers import Ruler

# extends down to 1/32 so zoom-fit can hold 100MP-class frames
# (Fuji GFX 11648px) inside an ordinary viewport
ZOOM_LEVELS = (0.03125, 0.0625, 0.125, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0,
               3.0, 4.0, 6.0, 8.0, 12.0, 16.0)

_GUIDE_COLOR = QColor(0, 200, 255)
_TEMP_GUIDE_COLOR = QColor(255, 0, 200)


def _event_modifiers(ev) -> Qt.KeyboardModifier:
    getter = getattr(ev, "modifiers", None)
    return getter() if getter is not None else Qt.KeyboardModifier.NoModifier


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
        self._space_pan = False  # Space held: temporary hand tool
        self._pan_last: QPointF | None = None
        self._cursor_modifiers = Qt.KeyboardModifier.NoModifier
        self.cursor_controller = CursorController(self)
        self._ants_offset = 0.0
        self._ants = QTimer(self)
        self._ants.setInterval(120)
        self._ants.timeout.connect(self._advance_ants)
        self._checker = QBrush(_checker_pixmap())

        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Image canvas")
        self.setAccessibleDescription(
            "Editable document canvas. Arrow keys operate the active keyboard-capable tool.")

        doc.pixelsChanged.connect(self._on_pixels)
        doc.structureChanged.connect(self._on_structure)
        doc.selectionChanged.connect(self._on_selection)
        doc.guidesChanged.connect(self.update)
        self.view_rotation = 0  # view-only, 90-degree steps
        self._resize_to_zoom()
        self.refresh_cursor()

    # -- geometry --

    def _resize_to_zoom(self) -> None:
        w = max(1, math.ceil(self.doc.size.width() * self.zoom))
        h = max(1, math.ceil(self.doc.size.height() * self.zoom))
        if self.view_rotation % 180:
            w, h = h, w
        self.setFixedSize(w, h)

    def rotate_view(self, delta_deg: int) -> None:
        self.view_rotation = (self.view_rotation + delta_deg) % 360
        self._resize_to_zoom()
        self.update()
        self.editor.sync_rulers()

    def _view_transform(self) -> QTransform:
        """Widget <- content transform for the view rotation (identity at 0)."""
        t = QTransform()
        if self.view_rotation:
            t.translate(self.width() / 2.0, self.height() / 2.0)
            t.rotate(self.view_rotation)
            cw = self.doc.size.width() * self.zoom
            ch = self.doc.size.height() * self.zoom
            t.translate(-cw / 2.0, -ch / 2.0)
        return t

    def set_zoom(self, zoom: float) -> None:
        self.zoom = max(ZOOM_LEVELS[0], min(zoom, ZOOM_LEVELS[-1]))
        self._resize_to_zoom()
        self.update()
        self.editor.sync_rulers()
        self.refresh_cursor()

    def refresh_cursor(self, dragging: bool = False) -> None:
        """Resolve the active tool's live cursor through the single controller."""
        if self._space_pan:
            self.cursor_controller.apply(CursorIntent(
                "hand-closed" if self._pan_last is not None else "hand-open"))
            return
        tool = self.editor.active_tool()
        if tool is None:
            self.cursor_controller.apply(CursorIntent("cross"))
            return
        intent = tool.cursor_intent(
            self.doc, self, self.hover_pos, self._cursor_modifiers, dragging)
        self.cursor_controller.apply(intent)

    def _transform_session(self):
        tool = self.editor.active_tool()
        if tool is not None and tool.name == "transform":
            session = tool.session
            if session is not None and session.doc is self.doc:
                return session
        return None

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
        if self.view_rotation:
            view_t = self._view_transform()
            p.setTransform(view_t)
            inverse, _ok = view_t.inverted()
            exposed = inverse.mapRect(QRectF(exposed)).toAlignedRect()

        z = self.zoom
        p.save()
        p.scale(z, z)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, z < 1.0)
        clip = QRectF(exposed).adjusted(-1, -1, 1, 1)
        p.setClipRect(QRectF(clip.x() / z, clip.y() / z, clip.width() / z, clip.height() / z))
        clip_canvas = QRect(
            int(clip.x() / z), int(clip.y() / z),
            int(clip.width() / z) + 2, int(clip.height() / z) + 2)
        from photoslop import color

        transform_session = self._transform_session()
        cms = color.viewport_active()
        if self.doc.needs_offscreen() or cms:
            region = clip_canvas.intersected(self.doc.canvas_rect())
            if not region.isEmpty():
                exclude = (transform_session.layer
                           if transform_session is not None else None)
                rendered = render_region(self.doc, region, exclude)
                if cms:  # DD-004: one viewport-region transform, only here
                    rendered = color.apply_viewport(rendered, self.doc)
                p.drawImage(region.topLeft(), rendered)
                if transform_session is not None:
                    transform_session.draw_preview(p)
            layers_to_paint = ()
        else:
            layers_to_paint = self.doc.layers
        for layer in layers_to_paint:
            if not layer.visible:
                continue
            p.setOpacity(layer.opacity)
            p.setCompositionMode(BLEND_MODES[layer.blend_mode])
            if transform_session is not None and layer is transform_session.layer:
                # live transform preview: painter transforms, no resampling
                transform_session.draw_preview(p)
            else:
                draw_layer(p, self.doc, layer, clip_canvas)
        p.restore()
        p.setOpacity(1.0)

        if self.doc.artboards:
            self._paint_artboards(p)
        if getattr(self.editor.host, "show_grid", False):
            self._paint_grid(p)
        self._paint_guides(p)
        self._paint_selection(p)
        self._paint_guide_label(p)
        tool = self.editor.active_tool()
        if tool is not None:
            tool.overlay(self.doc, p, self)
        p.end()

    def _paint_artboards(self, p: QPainter) -> None:
        z = self.zoom
        p.setPen(QPen(QColor(80, 160, 255, 200), 1, Qt.PenStyle.DashDotLine))
        p.setBrush(Qt.BrushStyle.NoBrush)
        font = p.font()
        font.setPointSizeF(8.0)
        p.setFont(font)
        for name, rect in self.doc.artboards:
            wr = QRectF(rect.x() * z, rect.y() * z,
                        rect.width() * z, rect.height() * z)
            p.drawRect(wr)
            p.drawText(QPointF(wr.x() + 3, max(10.0, wr.y() - 3)), name)

    def _paint_grid(self, p: QPainter) -> None:
        host = self.editor.host
        step = (units.minor_tick_step(host.unit, self.doc.dpi, self.zoom)
                * units.px_per_unit(host.unit, self.doc.dpi))
        if step * self.zoom < 4:  # too dense to be useful
            return
        p.setPen(QPen(QColor(128, 128, 128, 70), 1))
        x = step
        while x < self.doc.size.width():
            wx = round(x * self.zoom)
            p.drawLine(wx, 0, wx, self.height())
            x += step
        y = step
        while y < self.doc.size.height():
            wy = round(y * self.zoom)
            p.drawLine(0, wy, self.width(), wy)
            y += step

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
        if self.view_rotation:
            inverse, _ok = self._view_transform().inverted()
            wp = inverse.map(wp)
        return QPointF(wp.x() / self.zoom, wp.y() / self.zoom)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self._cursor_modifiers = _event_modifiers(ev)
            if self._space_pan:
                self._pan_last = ev.globalPosition()
                self.refresh_cursor(dragging=True)
                return
            tool = self.editor.active_tool()
            if tool is not None:
                tool.press(self.doc, self, self._canvas_pos(ev), ev)
                self.refresh_cursor(dragging=True)

    def mouseMoveEvent(self, ev) -> None:
        self._cursor_modifiers = _event_modifiers(ev)
        if self._pan_last is not None:
            current = ev.globalPosition()
            self.editor.pan_by(current.x() - self._pan_last.x(),
                               current.y() - self._pan_last.y())
            self._pan_last = current
            self.refresh_cursor(dragging=True)
            return
        pos = self._canvas_pos(ev)
        self.hover_pos = pos
        self.mousePos.emit(pos)
        if ev.buttons() & Qt.MouseButton.LeftButton:
            tool = self.editor.active_tool()
            if tool is not None:
                tool.move(self.doc, self, pos, ev)
            self.refresh_cursor(dragging=True)
        else:
            tool = self.editor.active_tool()
            if tool is not None:
                tool.hover(self.doc, self, pos)
            self.refresh_cursor()
            self.update()  # brush outline / previews follow the cursor

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            if self._pan_last is not None:
                self._pan_last = None
                self.refresh_cursor()
                return
            tool = self.editor.active_tool()
            if tool is not None:
                tool.release(self.doc, self, self._canvas_pos(ev), ev)
            self._cursor_modifiers = _event_modifiers(ev)
            self.refresh_cursor()

    def mouseDoubleClickEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            tool = self.editor.active_tool()
            if tool is not None:
                tool.double_click(self.doc, self, self._canvas_pos(ev), ev)

    def leaveEvent(self, ev) -> None:
        self.hover_pos = None
        self.mousePos.emit(None)
        self.refresh_cursor()
        self.update()

    def wheelEvent(self, ev) -> None:
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.editor.zoom_step(1 if ev.angleDelta().y() > 0 else -1, ev.position())
            ev.accept()
        else:
            ev.ignore()

    def keyPressEvent(self, ev) -> None:
        key = ev.key()
        self._cursor_modifiers = _event_modifiers(ev)
        if key == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space_pan = True
            self.refresh_cursor()
            return
        tool = self.editor.active_tool()
        if (key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and tool is not None and hasattr(tool, "commit")):
            tool.commit(self)
            return
        if key == Qt.Key.Key_Escape:
            if tool is not None:
                tool.cancel(self.doc)
                if tool.name == "transform":
                    self.editor.host.end_transform()
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
        if key in (Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Control, Qt.Key.Key_Meta):
            self.refresh_cursor()
        super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev) -> None:
        self._cursor_modifiers = _event_modifiers(ev)
        if ev.key() == Qt.Key.Key_Space and not ev.isAutoRepeat():
            self._space_pan = False
            self._pan_last = None
            self.refresh_cursor()
            return
        if ev.key() in (Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Control, Qt.Key.Key_Meta):
            self.refresh_cursor()
        super().keyReleaseEvent(ev)


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
        self.hruler.setAccessibleName("Horizontal ruler")
        self.vruler.setAccessibleName("Vertical ruler")
        self.corner = QToolButton()
        self.corner.setToolTip("Cycle ruler units")
        self.corner.setAccessibleName("Cycle ruler units")
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
        # Map the canvas origin into each RULER's own coordinate space (via
        # global coords) — the viewport is inset by the scroll-area frame, so
        # viewport-relative origins draw everything a frame-width off.
        origin_global = self.canvas.mapToGlobal(QPoint(0, 0))
        origin_x = self.hruler.mapFromGlobal(origin_global).x()
        origin_y = self.vruler.mapFromGlobal(origin_global).y()
        unit = self.host.unit
        zoom = self.canvas.zoom
        self.hruler.configure(origin_x, zoom, self.doc.dpi, unit, self.doc.size.width())
        self.vruler.configure(origin_y, zoom, self.doc.dpi, unit, self.doc.size.height())
        self.corner.setText(unit)

    def _cycle_unit(self) -> None:
        current = units.UNITS.index(self.host.unit)
        self.host.set_unit(units.UNITS[(current + 1) % len(units.UNITS)])

    def _on_mouse_pos(self, pos) -> None:
        self.hruler.set_marker(None if pos is None else pos.x())
        self.vruler.set_marker(None if pos is None else pos.y())
        self.host.show_mouse_pos(self.doc, pos)

    def pan_by(self, dx: float, dy: float) -> None:
        hbar = self.scroll.horizontalScrollBar()
        vbar = self.scroll.verticalScrollBar()
        hbar.setValue(hbar.value() - round(dx))
        vbar.setValue(vbar.value() - round(dy))

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

    def snap_layer_offset(self, layer, proposed: QPoint, modifiers=None) -> QPoint:
        """Snap a dragged layer's edges to guides and canvas edges (View →
        Snap; Shift overrides)."""
        host = self.host
        if not getattr(host, "snap_enabled", False):
            return proposed
        if modifiers is None:
            from PySide6.QtGui import QGuiApplication

            modifiers = QGuiApplication.queryKeyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return proposed
        tol = 6.0 / max(self.canvas.zoom, 0.01)
        doc = self.doc

        def best_shift(edges: list[float], targets: list[float]) -> float:
            distance, shift = tol + 1.0, 0.0
            for edge in edges:
                for target in targets:
                    d = target - edge
                    if abs(d) < distance:
                        distance, shift = abs(d), d
            return shift if distance <= tol else 0.0

        w, h = layer.image.width(), layer.image.height()
        sx = best_shift([float(proposed.x()), float(proposed.x() + w)],
                        [0.0, float(doc.size.width()), *doc.guides_v])
        sy = best_shift([float(proposed.y()), float(proposed.y() + h)],
                        [0.0, float(doc.size.height()), *doc.guides_h])
        return QPoint(proposed.x() + round(sx), proposed.y() + round(sy))

    def snap_guide(self, value: float, modifiers=None) -> float:
        """Snap a guide position to the visible minor ruler ticks. Hold Shift
        for free positioning. `modifiers=None` means 'query the keyboard'."""
        if modifiers is None:
            from PySide6.QtGui import QGuiApplication

            modifiers = QGuiApplication.queryKeyboardModifiers()
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            return value
        return units.snap_px(value, self.host.unit, self.doc.dpi, self.canvas.zoom)

    def _guide_pos(self, orient: str, global_pos: QPoint) -> float:
        local = self.canvas.mapFromGlobal(global_pos)
        z = self.canvas.zoom
        return self.snap_guide((local.y() if orient == "h" else local.x()) / z)

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
