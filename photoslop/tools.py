# SPDX-License-Identifier: Apache-2.0
"""Interactive tools. Tools paint directly into layer buffers during the
gesture (live feedback), record touched tiles as they go, and push a single
undo command on release."""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)

from photoslop import npimage
from photoslop.commands import LayerRegionCommand, SetLayerOffsetCommand, TileRecorder


class ToolOptions:
    """Shared, toolbar-backed options."""

    def __init__(self) -> None:
        self.foreground = QColor(0, 0, 0)
        self.background = QColor(255, 255, 255)
        self.size = 16
        self.hardness = 100  # percent
        self.opacity = 100  # percent
        self.eraser = False
        self.tolerance = 32  # 0..255

    def swap_colors(self) -> None:
        self.foreground, self.background = self.background, self.foreground

    def reset_colors(self) -> None:
        self.foreground = QColor(0, 0, 0)
        self.background = QColor(255, 255, 255)


class Tool:
    name = "tool"
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, options: ToolOptions) -> None:
        self.opts = options

    def press(self, doc, canvas, pos: QPointF, ev) -> None: ...

    def move(self, doc, canvas, pos: QPointF, ev) -> None: ...

    def release(self, doc, canvas, pos: QPointF, ev) -> None: ...

    def hover(self, doc, canvas, pos: QPointF) -> None:
        """Mouse moved with no button held."""

    def double_click(self, doc, canvas, pos: QPointF, ev) -> None: ...

    def cancel(self, doc=None) -> None:
        """Escape pressed — abandon any in-progress gesture."""

    def overlay(self, doc, painter: QPainter, canvas) -> None:
        """Draw tool feedback. Painter is in widget coords (unscaled)."""


class BrushTool(Tool):
    name = "brush"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._layer = None
        self._recorder: TileRecorder | None = None
        self._last: QPointF | None = None
        self._residual = 0.0
        self._clip: QPainterPath | None = None

    # -- stroke lifecycle --

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        self._layer = layer
        self._recorder = TileRecorder(doc, layer)
        self._clip = None
        if doc.selection is not None:
            self._clip = doc.selection.translated(-layer.offset.x(), -layer.offset.y())
        self._residual = 0.0
        self._last = pos
        self._segment(doc, pos, pos, first=True)

    def move(self, doc, canvas, pos, ev):
        if self._recorder is None or self._last is None:
            return
        self._segment(doc, self._last, pos)
        self._last = pos

    def release(self, doc, canvas, pos, ev):
        if self._recorder is None:
            return
        cmd = self._recorder.finish("Eraser" if self.opts.eraser else "Brush Stroke")
        if cmd is not None:
            doc.undo_stack.push(cmd)
        self._recorder = None
        self._layer = None
        self._last = None

    # -- painting --

    def _segment(self, doc, a: QPointF, b: QPointF, first: bool = False) -> None:
        layer = self._layer
        assert layer is not None and self._recorder is not None
        off = QPointF(layer.offset)
        la, lb = a - off, b - off
        radius = self.opts.size / 2.0
        pad = int(radius) + 2
        rect = QRectF(la, lb).normalized().adjusted(-pad, -pad, pad, pad).toAlignedRect()
        self._recorder.will_change(rect)

        p = QPainter(layer.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._clip is not None:
            p.setClipPath(self._clip)

        hard = self.opts.hardness >= 100
        opaque = self.opts.opacity >= 100
        alpha = round(self.opts.opacity * 2.55)

        if self.opts.eraser and hard:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            self._pen_segment(p, la, lb, QColor(0, 0, 0), first)
        elif not self.opts.eraser and hard and opaque:
            self._pen_segment(p, la, lb, self.opts.foreground, first)
        else:
            self._stamp_segment(p, la, lb, alpha, first)
        p.end()

        doc.notify_pixels(rect.translated(layer.offset))

    def _pen_segment(self, p: QPainter, a: QPointF, b: QPointF, color: QColor, first: bool):
        radius = self.opts.size / 2.0
        if first or a == b:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(color))
            p.drawEllipse(a, radius, radius)
        if a != b:
            pen = QPen(color, self.opts.size)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.drawLine(a, b)

    def _stamp_segment(self, p: QPainter, a: QPointF, b: QPointF, alpha: int, first: bool):
        radius = max(0.5, self.opts.size / 2.0)
        spacing = max(1.0, self.opts.size * 0.25)
        delta = b - a
        dist = math.hypot(delta.x(), delta.y())

        if self.opts.eraser:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOut)
            base = QColor(0, 0, 0, alpha)
        else:
            base = QColor(self.opts.foreground)
            base.setAlpha(alpha)

        grad_stop = max(0.0, min(self.opts.hardness / 100.0, 0.999))
        p.setPen(Qt.PenStyle.NoPen)

        def stamp(center: QPointF) -> None:
            grad = QRadialGradient(center, radius)
            grad.setColorAt(0.0, base)
            grad.setColorAt(grad_stop, base)
            faded = QColor(base)
            faded.setAlpha(0)
            grad.setColorAt(1.0, faded)
            p.setBrush(QBrush(grad))
            p.drawEllipse(center, radius, radius)

        if first:
            stamp(a)
            self._residual = spacing
            if dist == 0:
                return
        if dist == 0:
            return
        t = self._residual
        while t <= dist:
            stamp(a + delta * (t / dist))
            t += spacing
        self._residual = t - dist

    def overlay(self, doc, painter, canvas):
        if canvas.hover_pos is None:
            return
        z = canvas.zoom
        center = QPointF(canvas.hover_pos.x() * z, canvas.hover_pos.y() * z)
        r = max(1.0, self.opts.size / 2.0 * z)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        painter.drawEllipse(center, r, r)
        painter.setPen(QPen(QColor(0, 0, 0, 180), 1, Qt.PenStyle.DashLine))
        painter.drawEllipse(center, r, r)


class BucketTool(Tool):
    name = "bucket"

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        img = layer.image
        lx = int(pos.x() - layer.offset.x())
        ly = int(pos.y() - layer.offset.y())
        if not (0 <= lx < img.width() and 0 <= ly < img.height()):
            return

        sel_mask = None
        if doc.selection is not None:
            sel_mask = npimage.selection_mask(doc.selection, img.size(), layer.offset)

        c = self.opts.foreground
        color = npimage.premultiplied_u32(c.red(), c.green(), c.blue(),
                                          round(self.opts.opacity * 2.55))
        # Shared handle to the pre-fill pixels; the fill's first write detaches.
        before_full = QImage(img)
        dirty = npimage.flood_fill(img, lx, ly, color, self.opts.tolerance, sel_mask)
        if dirty is None:
            return
        cmd = LayerRegionCommand(
            doc, layer, dirty,
            before_full.copy(dirty), img.copy(dirty),
            "Paint Bucket",
        )
        doc.undo_stack.push(cmd)
        doc.notify_pixels(dirty.translated(layer.offset))


class EyedropperTool(Tool):
    name = "eyedropper"

    def press(self, doc, canvas, pos, ev):
        self._sample(doc, canvas, pos, ev)

    def move(self, doc, canvas, pos, ev):
        self._sample(doc, canvas, pos, ev)  # live sampling while dragging

    def _sample(self, doc, canvas, pos, ev) -> None:
        color = doc.sample_color(int(pos.x()), int(pos.y()))
        if color is None or color.alpha() == 0:
            return
        color = QColor(color.red(), color.green(), color.blue())
        shift = ev is not None and bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if shift:
            self.opts.background = color
        else:
            self.opts.foreground = color
        canvas.editor.host.refresh_swatches()


class HandTool(Tool):
    name = "hand"
    cursor = Qt.CursorShape.OpenHandCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._last: QPointF | None = None

    def press(self, doc, canvas, pos, ev):
        if ev is not None:
            self._last = ev.globalPosition()
            canvas.setCursor(Qt.CursorShape.ClosedHandCursor)

    def move(self, doc, canvas, pos, ev):
        if self._last is None or ev is None:
            return
        current = ev.globalPosition()
        canvas.editor.pan_by(current.x() - self._last.x(), current.y() - self._last.y())
        self._last = current

    def release(self, doc, canvas, pos, ev):
        self._last = None
        canvas.setCursor(self.cursor)


class ZoomTool(Tool):
    name = "zoom"

    def press(self, doc, canvas, pos, ev):
        alt = ev is not None and bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
        anchor = QPointF(pos.x() * canvas.zoom, pos.y() * canvas.zoom)
        canvas.editor.zoom_step(-1 if alt else 1, anchor)


class RectSelectTool(Tool):
    name = "rect-select"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._anchor: QPointF | None = None

    def press(self, doc, canvas, pos, ev):
        self._anchor = pos
        doc.set_selection(None)

    def move(self, doc, canvas, pos, ev):
        if self._anchor is None:
            return
        path = QPainterPath()
        path.addRect(QRectF(self._anchor, pos).normalized())
        doc.set_selection(path)

    def release(self, doc, canvas, pos, ev):
        if self._anchor is None:
            return
        rect = QRectF(self._anchor, pos).normalized()
        if rect.width() < 2 and rect.height() < 2:
            doc.set_selection(None)
        self._anchor = None


class LassoTool(Tool):
    name = "lasso"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._points: list[QPointF] = []

    def press(self, doc, canvas, pos, ev):
        self._points = [pos]
        doc.set_selection(None)

    def move(self, doc, canvas, pos, ev):
        if not self._points:
            return
        last = self._points[-1]
        if (pos - last).manhattanLength() >= 1.0:
            self._points.append(pos)
            doc.set_selection(self._path(close=True))

    def release(self, doc, canvas, pos, ev):
        if len(self._points) >= 3:
            doc.set_selection(self._path(close=True))
        else:
            doc.set_selection(None)
        self._points = []

    def _path(self, close: bool) -> QPainterPath:
        path = QPainterPath(self._points[0])
        for pt in self._points[1:]:
            path.lineTo(pt)
        if close:
            path.closeSubpath()
        return path


class MagicWandTool(Tool):
    """Select the contiguous color region under the click, within the shared
    tolerance. Shift-click adds to the selection, Alt-click subtracts."""

    name = "wand"

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        img = layer.image
        lx = int(pos.x() - layer.offset.x())
        ly = int(pos.y() - layer.offset.y())
        if not (0 <= lx < img.width() and 0 <= ly < img.height()):
            return
        result = npimage.flood_mask(img, lx, ly, self.opts.tolerance)
        if result is None:
            return
        mask, _bbox = result
        path = npimage.mask_to_path(mask, layer.offset)
        mods = ev.modifiers() if ev is not None else Qt.KeyboardModifier.NoModifier
        if doc.selection is not None and mods & Qt.KeyboardModifier.ShiftModifier:
            path = doc.selection.united(path)
        elif doc.selection is not None and mods & Qt.KeyboardModifier.AltModifier:
            path = doc.selection.subtracted(path)
        doc.set_selection(path)


class PolyLassoTool(Tool):
    """Click to place vertices; close by clicking the first vertex or
    double-clicking. Escape cancels."""

    name = "poly-lasso"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._points: list[QPointF] = []
        self._hover: QPointF | None = None

    def press(self, doc, canvas, pos, ev):
        if not self._points:
            doc.set_selection(None)
            self._points = [pos]
            return
        close_tol = 8.0 / max(canvas.zoom, 0.01)
        if len(self._points) >= 3 and (pos - self._points[0]).manhattanLength() <= close_tol:
            self._close(doc)
            return
        self._points.append(pos)
        self._preview(doc)

    def hover(self, doc, canvas, pos):
        if self._points:
            self._hover = pos
            self._preview(doc)

    def double_click(self, doc, canvas, pos, ev):
        if len(self._points) >= 3:
            self._close(doc)
        else:
            self.cancel(doc)

    def cancel(self, doc=None) -> None:
        self._points = []
        self._hover = None

    def _path(self) -> QPainterPath:
        path = QPainterPath(self._points[0])
        for pt in self._points[1:]:
            path.lineTo(pt)
        if self._hover is not None:
            path.lineTo(self._hover)
        path.closeSubpath()
        return path

    def _preview(self, doc) -> None:
        if len(self._points) + (1 if self._hover is not None else 0) >= 2:
            doc.set_selection(self._path())

    def _close(self, doc) -> None:
        self._hover = None
        doc.set_selection(self._path())
        self._points = []

    def overlay(self, doc, painter, canvas):
        if not self._points:
            return
        z = canvas.zoom
        painter.setPen(QPen(QColor(0, 0, 0, 200), 1))
        painter.setBrush(QBrush(QColor(255, 255, 255, 220)))
        for pt in self._points:
            painter.drawRect(QRectF(pt.x() * z - 2, pt.y() * z - 2, 4, 4))


class MoveTool(Tool):
    name = "move"
    cursor = Qt.CursorShape.SizeAllCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._mode: tuple | None = None

    def press(self, doc, canvas, pos, ev):
        tol = 5.0 / max(canvas.zoom, 0.01)
        for i, y in enumerate(doc.guides_h):
            if abs(pos.y() - y) <= tol:
                self._mode = ("gh", i)
                return
        for i, x in enumerate(doc.guides_v):
            if abs(pos.x() - x) <= tol:
                self._mode = ("gv", i)
                return
        layer = doc.active_layer
        if layer is not None:
            self._mode = ("layer", layer, QPoint(layer.offset), pos)

    def move(self, doc, canvas, pos, ev):
        if self._mode is None:
            return
        kind = self._mode[0]
        if kind == "gh":
            snapped = canvas.editor.snap_guide(pos.y(), ev.modifiers() if ev else None)
            doc.guides_h[self._mode[1]] = snapped
            doc.guidesChanged.emit()
            canvas.editor.show_guide_feedback("h", snapped)
        elif kind == "gv":
            snapped = canvas.editor.snap_guide(pos.x(), ev.modifiers() if ev else None)
            doc.guides_v[self._mode[1]] = snapped
            doc.guidesChanged.emit()
            canvas.editor.show_guide_feedback("v", snapped)
        else:
            _, layer, orig, start = self._mode
            old_bounds = layer.bounds()
            proposed = orig + (pos - start).toPoint()
            layer.offset = canvas.editor.snap_layer_offset(
                layer, proposed, ev.modifiers() if ev else None)
            doc.notify_pixels(old_bounds.united(layer.bounds()))

    def release(self, doc, canvas, pos, ev):
        if self._mode is None:
            return
        kind = self._mode[0]
        if kind in ("gh", "gv"):
            canvas.editor.clear_guide_feedback()
            # Dropping a guide outside the canvas removes it.
            extent = QRectF(QPointF(0, 0), QPointF(doc.size.width(), doc.size.height()))
            if not extent.contains(pos):
                guides = doc.guides_h if kind == "gh" else doc.guides_v
                guides.pop(self._mode[1])
                doc.guidesChanged.emit()
        else:
            _, layer, orig, _start = self._mode
            if layer.offset != orig:
                doc.undo_stack.push(SetLayerOffsetCommand(doc, layer, orig, layer.offset))
        self._mode = None
