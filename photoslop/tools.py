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
        self.color = QColor(0, 0, 0)
        self.size = 16
        self.hardness = 100  # percent
        self.opacity = 100  # percent
        self.eraser = False
        self.tolerance = 32  # 0..255


class Tool:
    name = "tool"
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, options: ToolOptions) -> None:
        self.opts = options

    def press(self, doc, canvas, pos: QPointF, ev) -> None: ...

    def move(self, doc, canvas, pos: QPointF, ev) -> None: ...

    def release(self, doc, canvas, pos: QPointF, ev) -> None: ...

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
            self._pen_segment(p, la, lb, self.opts.color, first)
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
            base = QColor(self.opts.color)
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

        c = self.opts.color
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
            layer.offset = orig + (pos - start).toPoint()
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
