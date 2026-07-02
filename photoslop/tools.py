# SPDX-License-Identifier: Apache-2.0
"""Interactive tools. Tools paint directly into layer buffers during the
gesture (live feedback), record touched tiles as they go, and push a single
undo command on release."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QLinearGradient,
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
        self.gradient_shape = "linear"  # or "radial"
        self.contiguous = True  # wand: connected region vs global colour range
        self.fill_source = "color"  # bucket: "color" or "pattern"
        self.spacing = 25  # stamp spacing, % of brush size
        self.pattern = None  # QImage tile from Edit > Define Pattern

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
    antialias = True

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
        cmd = self._recorder.finish(self._stroke_name())
        if cmd is not None:
            doc.undo_stack.push(cmd)
        self._recorder = None
        self._layer = None
        self._last = None

    def _stroke_name(self) -> str:
        return "Eraser" if self.opts.eraser else "Brush Stroke"

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
        p.setRenderHint(QPainter.RenderHint.Antialiasing, self.antialias)
        if self._clip is not None:
            p.setClipPath(self._clip)
        self._paint(p, la, lb, first)
        p.end()

        doc.notify_pixels(rect.translated(layer.offset))

    def _paint(self, p: QPainter, la: QPointF, lb: QPointF, first: bool) -> None:
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

    def _stamp_segment(self, p: QPainter, a: QPointF, b: QPointF, alpha: int,
                       first: bool, color: QColor | None = None):
        radius = max(0.5, self.opts.size / 2.0)
        spacing = max(1.0, self.opts.size * self.opts.spacing / 100.0)
        delta = b - a
        dist = math.hypot(delta.x(), delta.y())

        if color is not None:
            base = QColor(color)
            base.setAlpha(alpha)
        elif self.opts.eraser:
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


class PencilTool(BrushTool):
    """Hard-edged aliased strokes: every painted pixel is exactly the
    foreground colour at the shared opacity — no antialiasing, no hardness
    falloff. Paints with replace semantics (like the bucket), so overlapping
    segments within a stroke stay perfectly uniform."""

    name = "pencil"
    antialias = False

    def _stroke_name(self) -> str:
        return "Pencil Eraser" if self.opts.eraser else "Pencil"

    def _paint(self, p: QPainter, la: QPointF, lb: QPointF, first: bool) -> None:
        color = QColor(self.opts.foreground)
        color.setAlpha(round(self.opts.opacity * 2.55))
        if self.opts.eraser:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        else:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        self._pen_segment(p, la, lb, color, first)


class CropTool(Tool):
    """Drag a crop rectangle; Enter or double-click commits (offset-shift
    crop, no pixel copies), Escape clears. The overlay shields the discard
    area and shows a rule-of-thirds grid."""

    name = "crop"
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._start: QPointF | None = None
        self.rect: QRect | None = None

    def press(self, doc, canvas, pos, ev):
        self._start = pos
        self.rect = None

    def move(self, doc, canvas, pos, ev):
        if self._start is None:
            return
        rect = QRectF(self._start, pos).normalized().toAlignedRect()
        self.rect = rect.intersected(doc.canvas_rect())
        canvas.update()

    def release(self, doc, canvas, pos, ev):
        self._start = None
        if self.rect is not None and (self.rect.width() < 2 or self.rect.height() < 2):
            self.rect = None
        if canvas is not None:
            canvas.update()

    def double_click(self, doc, canvas, pos, ev):
        self.commit(canvas)

    def cancel(self, doc=None) -> None:
        self._start = None
        self.rect = None

    def commit(self, canvas) -> None:
        from photoslop.commands import ResizeCanvasCommand

        rect = self.rect
        if canvas is None or rect is None or rect.isEmpty():
            return
        doc = canvas.doc
        doc.undo_stack.push(
            ResizeCanvasCommand(doc, rect.size(), -rect.topLeft(), "Crop"))
        self.rect = None
        canvas.update()

    def overlay(self, doc, painter, canvas):
        rect = self.rect
        if rect is None:
            return
        z = canvas.zoom
        r = QRectF(rect.x() * z, rect.y() * z, rect.width() * z, rect.height() * z)
        full = QRectF(0, 0, doc.size.width() * z, doc.size.height() * z)
        shield = QPainterPath()
        shield.addRect(full)
        inner = QPainterPath()
        inner.addRect(r)
        painter.fillPath(shield.subtracted(inner), QColor(0, 0, 0, 110))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 230), 1))
        painter.drawRect(r)
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
        for i in (1, 2):  # rule-of-thirds guides
            x = r.left() + r.width() * i / 3
            y = r.top() + r.height() * i / 3
            painter.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
            painter.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))


class EraserTool(BrushTool):
    """A first-class eraser: always erases, whatever the eraser checkbox
    says. Hard 100% strokes clear outright; soft/partial strokes fade
    alpha via DestinationOut stamps."""

    name = "eraser"

    def _stroke_name(self) -> str:
        return "Eraser"

    def _paint(self, p: QPainter, la: QPointF, lb: QPointF, first: bool) -> None:
        alpha = round(self.opts.opacity * 2.55)
        if self.opts.hardness >= 100 and self.opts.opacity >= 100:
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            self._pen_segment(p, la, lb, QColor(0, 0, 0), first)
        else:
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut)
            self._stamp_segment(p, la, lb, alpha, first, QColor(0, 0, 0))


class DodgeTool(BrushTool):
    """Lighten as you paint: soft-light white stamps, strength = opacity."""

    name = "dodge"
    _tone = QColor(255, 255, 255)

    def _stroke_name(self) -> str:
        return self.name.capitalize()

    def _paint(self, p: QPainter, la: QPointF, lb: QPointF, first: bool) -> None:
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SoftLight)
        alpha = round(self.opts.opacity * 2.55)
        self._stamp_segment(p, la, lb, alpha, first, self._tone)


class BurnTool(DodgeTool):
    """Darken as you paint: soft-light black stamps."""

    name = "burn"
    _tone = QColor(0, 0, 0)


class CloneStampTool(BrushTool):
    """Alt+click sets the clone source; painting copies pixels from the
    source, offset-locked on the first stroke (aligned mode)."""

    name = "clone-stamp"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._source: QPointF | None = None  # doc coords
        self._clone_offset: QPointF | None = None  # dest - source, aligned

    def press(self, doc, canvas, pos, ev):
        if ev is not None and ev.modifiers() & Qt.KeyboardModifier.AltModifier:
            self._source = QPointF(pos)
            self._clone_offset = None  # next stroke re-locks the alignment
            return
        if self._source is None:
            return  # no source set
        if self._clone_offset is None:
            self._clone_offset = pos - self._source
        super().press(doc, canvas, pos, ev)

    def _stroke_name(self) -> str:
        return "Clone Stamp"

    def _paint(self, p: QPainter, la: QPointF, lb: QPointF, first: bool) -> None:
        layer = self._layer
        offset = self._clone_offset
        radius = max(0.5, self.opts.size / 2.0)
        spacing = max(1.0, self.opts.size * self.opts.spacing / 100.0)
        pad = int(radius) + 1
        p.setOpacity(self.opts.opacity / 100.0)

        def stamp(center: QPointF) -> None:
            src_center = center - offset
            src_rect = QRect(round(src_center.x()) - pad, round(src_center.y()) - pad,
                             2 * pad, 2 * pad)
            chunk = layer.image.copy(src_rect)  # snapshot: source may overlap dest
            path = QPainterPath()
            path.addEllipse(center, radius, radius)
            p.save()
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            p.drawImage(QPointF(center.x() - pad, center.y() - pad), chunk)
            p.restore()

        delta = lb - la
        dist = math.hypot(delta.x(), delta.y())
        if first or dist == 0:
            stamp(la)
        if dist > 0:
            steps = int(dist / spacing)
            for i in range(1, steps + 1):
                t = (i * spacing) / dist
                stamp(QPointF(la.x() + delta.x() * t, la.y() + delta.y() * t))

    def overlay(self, doc, painter, canvas):
        z = canvas.zoom
        if self._source is not None:
            c = QPointF(self._source.x() * z, self._source.y() * z)
            painter.setPen(QPen(QColor(255, 80, 255, 220), 1))
            painter.drawLine(QPointF(c.x() - 6, c.y()), QPointF(c.x() + 6, c.y()))
            painter.drawLine(QPointF(c.x(), c.y() - 6), QPointF(c.x(), c.y() + 6))
        if canvas.hover_pos is not None:
            center = QPointF(canvas.hover_pos.x() * z, canvas.hover_pos.y() * z)
            r = max(2.0, self.opts.size / 2.0 * z)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
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

        # Shared handle to the pre-fill pixels; the fill's first write detaches.
        before_full = QImage(img)
        if self.opts.fill_source == "pattern" and self.opts.pattern is not None:
            result = npimage.flood_mask(img, lx, ly, self.opts.tolerance, sel_mask)
            if result is None:
                return
            mask, dirty = result
            path = npimage.mask_to_path(mask)
            p = QPainter(img)
            p.setOpacity(self.opts.opacity / 100.0)
            p.fillPath(path, QBrush(self.opts.pattern))
            p.end()
        else:
            c = self.opts.foreground
            color = npimage.premultiplied_u32(c.red(), c.green(), c.blue(),
                                              round(self.opts.opacity * 2.55))
            dirty = npimage.flood_fill(img, lx, ly, color, self.opts.tolerance,
                                       sel_mask)
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


class GradientTool(Tool):
    """Drag start→end, release to fill the active layer (or selection) with
    a foreground→background gradient, linear or radial."""

    name = "gradient"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._start: QPointF | None = None
        self._end: QPointF | None = None
        self._layer = None

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        self._layer = layer
        self._start = pos
        self._end = pos

    def move(self, doc, canvas, pos, ev):
        if self._start is not None:
            self._end = pos
            canvas.update()

    def cancel(self, doc=None) -> None:
        self._start = self._end = None
        self._layer = None

    def release(self, doc, canvas, pos, ev):
        if self._start is None or self._layer is None:
            return
        self._end = pos
        layer = self._layer
        try:
            if (self._end - self._start).manhattanLength() < 2:
                return
            if doc.selection is not None:
                region = doc.selection_bounds()
                region = region.intersected(layer.bounds()) if region is not None else None
                if region is None or region.isEmpty():
                    return
            else:
                region = layer.bounds()
            local = region.translated(-layer.offset)
            before = layer.image.copy(local)

            off = QPointF(layer.offset)
            start_l, end_l = self._start - off, self._end - off
            if self.opts.gradient_shape == "radial":
                delta = end_l - start_l
                radius = max(math.hypot(delta.x(), delta.y()), 0.001)
                grad = QRadialGradient(start_l, radius)
            else:
                grad = QLinearGradient(start_l, end_l)
            grad.setColorAt(0.0, QColor(self.opts.foreground))
            grad.setColorAt(1.0, QColor(self.opts.background))

            p = QPainter(layer.image)
            p.setOpacity(self.opts.opacity / 100.0)
            if doc.selection is not None:
                p.setClipPath(doc.selection.translated(-layer.offset.x(),
                                                       -layer.offset.y()))
            p.fillRect(local, QBrush(grad))
            p.end()

            after = layer.image.copy(local)
            doc.undo_stack.push(LayerRegionCommand(
                doc, layer, local, before, after, "Gradient"))
            doc.notify_pixels(region)
        finally:
            self.cancel()

    def overlay(self, doc, painter, canvas):
        if self._start is None or self._end is None or self._start == self._end:
            return
        z = canvas.zoom
        a = QPointF(self._start.x() * z, self._start.y() * z)
        b = QPointF(self._end.x() * z, self._end.y() * z)
        painter.setPen(QPen(QColor(255, 255, 255, 200), 1))
        painter.drawLine(a, b)
        painter.setPen(QPen(QColor(0, 0, 0, 200), 1, Qt.PenStyle.DashLine))
        painter.drawLine(a, b)


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
        finder = npimage.flood_mask if self.opts.contiguous else npimage.global_mask
        result = finder(img, lx, ly, self.opts.tolerance)
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


class QuickSelectTool(Tool):
    """Paint a selection: every brush seed floods its contiguous colour
    region (shared tolerance) and unions into the selection live. Plain drag
    adds to the existing selection; Alt-drag subtracts."""

    name = "quick-select"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._layer = None
        self._mask = None
        self._base_path: QPainterPath | None = None
        self._subtract = False
        self._last_seed: QPointF | None = None

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        self._layer = layer
        self._mask = np.zeros(
            (layer.image.height(), layer.image.width()), dtype=bool)
        self._subtract = ev is not None and bool(
            ev.modifiers() & Qt.KeyboardModifier.AltModifier)
        self._base_path = doc.selection
        self._last_seed = None
        self._seed(doc, pos)

    def move(self, doc, canvas, pos, ev):
        if self._mask is None:
            return
        step = max(2.0, self.opts.size / 4.0)
        if (self._last_seed is not None
                and (pos - self._last_seed).manhattanLength() < step):
            return
        self._seed(doc, pos)

    def release(self, doc, canvas, pos, ev):
        self._layer = None
        self._mask = None
        self._base_path = None
        self._last_seed = None

    def cancel(self, doc=None) -> None:
        self.release(doc, None, None, None)

    def _seed(self, doc, pos: QPointF) -> None:
        layer = self._layer
        lx = int(pos.x() - layer.offset.x())
        ly = int(pos.y() - layer.offset.y())
        img = layer.image
        if not (0 <= lx < img.width() and 0 <= ly < img.height()):
            return
        self._last_seed = pos
        if self._mask[ly, lx]:
            return  # already captured by an earlier seed
        result = npimage.flood_mask(img, lx, ly, self.opts.tolerance)
        if result is None:
            return
        self._mask |= result[0]
        path = npimage.mask_to_path(self._mask, layer.offset)
        if self._base_path is not None:
            path = (self._base_path.subtracted(path) if self._subtract
                    else self._base_path.united(path))
        elif self._subtract:
            path = QPainterPath()
        doc.set_selection(path)

    def overlay(self, doc, painter, canvas):
        if canvas.hover_pos is None:
            return
        z = canvas.zoom
        center = QPointF(canvas.hover_pos.x() * z, canvas.hover_pos.y() * z)
        r = max(2.0, self.opts.size / 2.0 * z)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
        painter.drawEllipse(center, r, r)
        painter.setPen(QPen(QColor(0, 0, 0, 180), 1, Qt.PenStyle.DotLine))
        painter.drawEllipse(center, r, r)


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
