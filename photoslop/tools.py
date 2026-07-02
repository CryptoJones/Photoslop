# SPDX-License-Identifier: Apache-2.0
"""Interactive tools. Tools paint directly into layer buffers during the
gesture (live feedback), record touched tiles as they go, and push a single
undo command on release."""

from __future__ import annotations

import math
import random

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
    QPolygonF,
    QRadialGradient,
    QTransform,
)

from photoslop import npimage
from photoslop.commands import LayerRegionCommand, SetLayerOffsetCommand, TileRecorder
from photoslop.layer import Layer, blank_image


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
        self.shape = "rect"  # or "ellipse" / "line"
        self.contiguous = True  # wand: connected region vs global colour range
        self.fill_source = "color"  # bucket: "color" or "pattern"
        self.spacing = 25  # stamp spacing, % of brush size
        self.flow = 100  # per-stamp paint amount; opacity is the stroke ceiling
        self.scatter = 0  # random stamp offset, % of brush size
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
    # Soft/partial strokes paint into a per-stroke scratch buffer at `flow`
    # strength and composite at `opacity` — so opacity is a true stroke
    # ceiling (PS semantics). Subclasses that paint directly opt out.
    scratch_stroke = True

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._layer = None
        self._recorder: TileRecorder | None = None
        self._last: QPointF | None = None
        self._residual = 0.0
        self._clip: QPainterPath | None = None
        self._scratch: QImage | None = None
        self._orig: QImage | None = None
        self._rng = random.Random(0)

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
        self._rng = random.Random(round(pos.x() * 7919) ^ round(pos.y() * 104729))
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
        self._scratch = None
        self._orig = None

    def _stroke_name(self) -> str:
        return "Eraser" if self.opts.eraser else "Brush Stroke"

    # -- painting --

    def _segment(self, doc, a: QPointF, b: QPointF, first: bool = False) -> None:
        layer = self._layer
        assert layer is not None and self._recorder is not None
        off = QPointF(layer.offset)
        la, lb = a - off, b - off
        radius = self.opts.size / 2.0
        pad = int(radius + self.opts.scatter / 100.0 * self.opts.size) + 2
        rect = QRectF(la, lb).normalized().adjusted(-pad, -pad, pad, pad).toAlignedRect()
        self._recorder.will_change(rect)

        fast = (self.opts.hardness >= 100 and self.opts.opacity >= 100
                and self.opts.flow >= 100)
        if not self.scratch_stroke or fast:
            p = QPainter(layer.image)
            p.setRenderHint(QPainter.RenderHint.Antialiasing, self.antialias)
            if self._clip is not None:
                p.setClipPath(self._clip)
            self._paint(p, la, lb, first)
            p.end()
        else:
            if self._scratch is None:
                self._orig = QImage(layer.image)  # COW reference
                self._scratch = blank_image(layer.image.size())
            sp = QPainter(self._scratch)
            sp.setRenderHint(QPainter.RenderHint.Antialiasing, self.antialias)
            if self._clip is not None:
                sp.setClipPath(self._clip)
            self._stamp_segment(sp, la, lb, round(self.opts.flow * 2.55),
                                first, self._stroke_color())
            sp.end()
            # rebuild the dirty rect: original pixels + stroke at opacity
            p = QPainter(layer.image)
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.drawImage(rect.topLeft(), self._orig, rect)
            p.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_DestinationOut
                if self._erases()
                else QPainter.CompositionMode.CompositionMode_SourceOver)
            p.setOpacity(self.opts.opacity / 100.0)
            p.drawImage(rect.topLeft(), self._scratch, rect)
            p.end()

        doc.notify_pixels(rect.translated(layer.offset))

    def _erases(self) -> bool:
        return self.opts.eraser

    def _stroke_color(self) -> QColor:
        return QColor(0, 0, 0) if self._erases() else QColor(self.opts.foreground)

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

        scatter = self.opts.scatter / 100.0 * self.opts.size

        def stamp(center: QPointF) -> None:
            if scatter:
                center = QPointF(
                    center.x() + self._rng.uniform(-scatter, scatter),
                    center.y() + self._rng.uniform(-scatter, scatter))
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
    scratch_stroke = False
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
    alpha via the scratch stroke at flow/opacity."""

    name = "eraser"

    def _erases(self) -> bool:
        return True

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


class PatchTool(Tool):
    """Patch: make a selection first, then drag from inside it to the area
    to sample — on release the selection heals with the sampled texture,
    tone-matched to its surroundings."""

    name = "patch"
    cursor = Qt.CursorShape.OpenHandCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._start: QPointF | None = None
        self._delta = QPointF(0, 0)

    def press(self, doc, canvas, pos, ev):
        if doc.selection is None or not doc.selection.contains(pos):
            return
        self._start = pos
        self._delta = QPointF(0, 0)

    def move(self, doc, canvas, pos, ev):
        if self._start is None:
            return
        self._delta = pos - self._start
        canvas.update()

    def release(self, doc, canvas, pos, ev):
        if self._start is None:
            return
        delta = pos - self._start
        self._start = None
        self._delta = QPointF(0, 0)
        layer = doc.active_layer
        if layer is None or (abs(delta.x()) < 1 and abs(delta.y()) < 1):
            if canvas is not None:
                canvas.update()
            return
        mask = npimage.selection_mask(doc.selection, layer.image.size(),
                                      layer.offset)
        if not mask.any():
            return
        before = QImage(layer.image)  # COW; patch_heal's write detaches
        dirty = npimage.patch_heal(layer.image, mask,
                                   round(delta.x()), round(delta.y()))
        if dirty.isEmpty():
            return  # sample window out of bounds
        doc.undo_stack.push(LayerRegionCommand(
            doc, layer, dirty, before.copy(dirty), layer.image.copy(dirty),
            "Patch", applied=True))
        doc.notify_pixels(dirty.translated(layer.offset))
        if canvas is not None:
            canvas.update()

    def cancel(self, doc=None) -> None:
        self._start = None
        self._delta = QPointF(0, 0)

    def overlay(self, doc, painter, canvas):
        if self._start is None or doc.selection is None:
            return
        z = canvas.zoom
        ghost = doc.selection.translated(self._delta.x(), self._delta.y())
        painter.save()
        painter.scale(z, z)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(120, 220, 255, 220), 1.5 / max(z, 0.01)))
        painter.drawPath(ghost)
        painter.restore()


class LiquifyTool(Tool):
    """Liquify push (Y): drag to shove pixels along the stroke with a smooth
    falloff — the classic forward-warp brush."""

    name = "liquify"
    cursor = Qt.CursorShape.SizeAllCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._layer = None
        self._recorder: TileRecorder | None = None
        self._last: QPointF | None = None

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        self._layer = layer
        self._recorder = TileRecorder(doc, layer)
        self._last = pos

    def move(self, doc, canvas, pos, ev):
        if self._recorder is None or self._last is None:
            return
        layer = self._layer
        delta = pos - self._last
        strength = self.opts.opacity / 100.0
        radius = max(2.0, self.opts.size / 2.0)
        local = self._last - QPointF(layer.offset)
        pad = int(radius + delta.manhattanLength()) + 2
        rect = QRect(int(local.x()) - pad, int(local.y()) - pad,
                     2 * pad, 2 * pad)
        self._recorder.will_change(rect)
        dirty = npimage.warp_push(layer.image, local.x(), local.y(), radius,
                                  delta.x() * strength, delta.y() * strength)
        self._last = pos
        if not dirty.isEmpty():
            doc.notify_pixels(dirty.translated(layer.offset))

    def release(self, doc, canvas, pos, ev):
        if self._recorder is None:
            return
        cmd = self._recorder.finish("Liquify")
        if cmd is not None:
            doc.undo_stack.push(cmd)
        self._recorder = None
        self._layer = None
        self._last = None

    def overlay(self, doc, painter, canvas):
        if canvas.hover_pos is None:
            return
        z = canvas.zoom
        center = QPointF(canvas.hover_pos.x() * z, canvas.hover_pos.y() * z)
        r = max(2.0, self.opts.size / 2.0 * z)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 180, 80, 200), 1))
        painter.drawEllipse(center, r, r)


class PerspectiveTool(Tool):
    """Perspective Warp (Shift+P): click four corners to define the source
    plane, then drag them to their rectified positions — the whole layer
    warps by that homography. Enter commits, Escape cancels."""

    name = "perspective"
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._layer = None
        self._doc = None
        self._base: QImage | None = None
        self._base_offset: QPoint | None = None
        self.src: list[QPointF] = []  # layer-local plane corners
        self.dst: list[QPointF] = []
        self._drag: int | None = None

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        if self._base is None:
            self._layer = layer
            self._doc = doc
            self._base = QImage(layer.image)
            self._base_offset = QPoint(layer.offset)
            self.src = []
            self.dst = []
        local = pos - QPointF(layer.offset if not self.dst else self._base_offset)
        if len(self.src) < 4:
            self.src.append(QPointF(local))
            if len(self.src) == 4:
                self.dst = [QPointF(p) for p in self.src]
            canvas.update()
            return
        tol = 10.0 / max(canvas.zoom, 0.01)
        best, best_d = None, tol * tol
        for i, pt in enumerate(self.dst):
            d = (pt.x() - local.x()) ** 2 + (pt.y() - local.y()) ** 2
            if d <= best_d:
                best, best_d = i, d
        self._drag = best

    def move(self, doc, canvas, pos, ev):
        if self._drag is None or self._base is None:
            return
        local = pos - QPointF(self._base_offset)
        self.dst[self._drag] = QPointF(local)
        self._rewarp(doc)
        canvas.update()

    def release(self, doc, canvas, pos, ev):
        self._drag = None

    def _homography(self) -> QTransform:
        m = QTransform()
        QTransform.quadToQuad(QPolygonF(self.src), QPolygonF(self.dst), m)
        return m

    def _rewarp(self, doc) -> None:
        from PySide6.QtCore import QRectF

        from photoslop.layer import blank_image

        layer = self._layer
        h = self._homography()
        bw, bh = self._base.width(), self._base.height()
        # projective transforms can shoot past the vanishing line: clamp the
        # output window to a sane multiple of the layer instead of trusting
        # mapRect (QImage.transformed would try to allocate the horizon)
        sane = QRectF(-2.0 * bw, -2.0 * bh, 5.0 * bw, 5.0 * bh)
        bounds = h.mapRect(QRectF(0, 0, bw, bh)).intersected(sane)
        if bounds.width() < 1 or bounds.height() < 1:
            return
        from PySide6.QtCore import QSize

        warped = blank_image(QSize(round(bounds.width()), round(bounds.height())))
        p = QPainter(warped)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.translate(-bounds.topLeft())
        p.setTransform(h, True)
        p.drawImage(QPointF(0, 0), self._base)
        p.end()
        layer.image = warped
        layer.offset = self._base_offset + QPoint(round(bounds.left()),
                                                  round(bounds.top()))
        doc.notify_pixels(doc.canvas_rect())

    def commit(self, canvas) -> None:
        if self._base is None or self._layer is None:
            return
        from photoslop.transform import TransformLayerCommand

        layer, doc = self._layer, self._doc
        if layer.image != self._base or layer.offset != self._base_offset:
            command = TransformLayerCommand(
                doc, layer, self._base, self._base_offset,
                QImage(layer.image), QPoint(layer.offset))
            command.setText("Perspective Warp")
            doc.undo_stack.push(command)
        self._reset()
        if canvas is not None:
            canvas.update()

    def cancel(self, doc=None) -> None:
        if self._base is not None and self._layer is not None:
            self._layer.image = QImage(self._base)
            self._layer.offset = QPoint(self._base_offset)
            self._doc.notify_pixels(self._doc.canvas_rect())
        self._reset()

    def _reset(self) -> None:
        self._layer = None
        self._doc = None
        self._base = None
        self._base_offset = None
        self.src = []
        self.dst = []
        self._drag = None

    def overlay(self, doc, painter, canvas):
        if self._base is None:
            return
        z = canvas.zoom
        off = QPointF(self._base_offset)

        def to_widget(pt: QPointF) -> QPointF:
            return QPointF((pt.x() + off.x()) * z, (pt.y() + off.y()) * z)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        if len(self.src) >= 2:
            painter.setPen(QPen(QColor(160, 160, 160, 200), 1, Qt.PenStyle.DashLine))
            pts = [to_widget(p) for p in self.src]
            for i in range(len(pts) - (0 if len(pts) == 4 else 1)):
                painter.drawLine(pts[i], pts[(i + 1) % len(pts)])
        if self.dst:
            painter.setPen(QPen(QColor(120, 220, 255, 230), 1))
            pts = [to_widget(p) for p in self.dst]
            for i in range(4):
                painter.drawLine(pts[i], pts[(i + 1) % 4])
            painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
            painter.setBrush(QColor(255, 255, 255, 230))
            for pt in pts:
                painter.drawRect(QRectF(pt.x() - 3.5, pt.y() - 3.5, 7, 7))
        elif self.src:
            painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
            painter.setBrush(QColor(255, 255, 255, 230))
            for p in self.src:
                w = to_widget(p)
                painter.drawRect(QRectF(w.x() - 3.5, w.y() - 3.5, 7, 7))


class PuppetTool(Tool):
    """Puppet Warp (Shift+Y): click to drop pins, drag a pin and the image
    bends around the others. Enter commits, Escape cancels."""

    name = "puppet"
    cursor = Qt.CursorShape.PointingHandCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._layer = None
        self._doc = None
        self._base: QImage | None = None
        self.pins: list[list[QPointF]] = []  # [source, target] in layer coords
        self._drag: int | None = None

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        if self._base is None:
            self._layer = layer
            self._doc = doc
            self._base = QImage(layer.image)
            self.pins = []
        local = pos - QPointF(layer.offset)
        tol = 8.0 / max(canvas.zoom, 0.01)
        for i, (_src, tgt) in enumerate(self.pins):
            if (tgt - local).manhattanLength() <= tol:
                self._drag = i
                return
        self.pins.append([QPointF(local), QPointF(local)])
        self._drag = None
        canvas.update()

    def move(self, doc, canvas, pos, ev):
        if self._drag is None or self._layer is None:
            return
        local = pos - QPointF(self._layer.offset)
        self.pins[self._drag][1] = QPointF(local)
        self._rewarp(doc)
        canvas.update()

    def release(self, doc, canvas, pos, ev):
        self._drag = None

    def _rewarp(self, doc) -> None:
        layer = self._layer
        pin_pairs = [((p[0].x(), p[0].y()), (p[1].x(), p[1].y()))
                     for p in self.pins]
        layer.image = npimage.puppet_warp(self._base, pin_pairs)
        doc.notify_pixels(layer.bounds())

    def commit(self, canvas) -> None:
        if self._base is None or self._layer is None:
            return
        from photoslop.transform import TransformLayerCommand

        layer, doc = self._layer, self._doc
        if layer.image != self._base:
            doc.undo_stack.push(TransformLayerCommand(
                doc, layer, self._base, layer.offset,
                QImage(layer.image), layer.offset))
            doc.undo_stack.command(doc.undo_stack.count() - 1).setText(
                "Puppet Warp")
        self._reset()
        if canvas is not None:
            canvas.update()

    def cancel(self, doc=None) -> None:
        if self._base is not None and self._layer is not None:
            self._layer.image = QImage(self._base)
            self._doc.notify_pixels(self._layer.bounds())
        self._reset()

    def _reset(self) -> None:
        self._layer = None
        self._doc = None
        self._base = None
        self.pins = []
        self._drag = None

    def overlay(self, doc, painter, canvas):
        if self._layer is None:
            return
        z = canvas.zoom
        off = QPointF(self._layer.offset)
        painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
        for i, (_src, tgt) in enumerate(self.pins):
            centre = QPointF((tgt.x() + off.x()) * z, (tgt.y() + off.y()) * z)
            painter.setBrush(QColor(255, 210, 60, 230) if i != self._drag
                             else QColor(255, 80, 80, 230))
            painter.drawEllipse(centre, 5, 5)


class ShapeTool(Tool):
    """Shape (U): drag to draw a rectangle, ellipse, or line onto a NEW
    layer (foreground fill; the line's width is the brush size). Shift+U
    cycles the shape. The layer is bounded to the shape, not the canvas."""

    name = "shape"
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._start: QPointF | None = None
        self._end: QPointF | None = None

    def press(self, doc, canvas, pos, ev):
        self._start = pos
        self._end = pos

    def move(self, doc, canvas, pos, ev):
        if self._start is None:
            return
        self._end = pos
        canvas.update()

    def overlay(self, doc, painter, canvas):
        if self._start is None or self._end is None:
            return
        z = canvas.zoom
        painter.setPen(QPen(QColor(30, 144, 255), 1, Qt.PenStyle.DashLine))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        a = QPointF(self._start.x() * z, self._start.y() * z)
        b = QPointF(self._end.x() * z, self._end.y() * z)
        if self.opts.shape == "line":
            painter.drawLine(a, b)
        elif self.opts.shape == "ellipse":
            painter.drawEllipse(QRectF(a, b).normalized())
        else:
            painter.drawRect(QRectF(a, b).normalized())

    def release(self, doc, canvas, pos, ev):
        from photoslop.commands import InsertLayerCommand

        start, end = self._start, self._end
        self._start = self._end = None
        if canvas is not None:
            canvas.update()
        if start is None or end is None:
            return
        raw = QRectF(start, end).normalized()
        if raw.width() < 2 and raw.height() < 2:
            return  # a click, not a drag
        margin = max(2, self.opts.size) if self.opts.shape == "line" else 2
        bounds = (raw.toAlignedRect()
                  .adjusted(-margin, -margin, margin, margin)
                  .intersected(doc.canvas_rect().adjusted(-margin, -margin,
                                                          margin, margin)))
        layer = Layer.blank(f"Shape {len(doc.layers)}", bounds.size(),
                            bounds.topLeft())
        p = QPainter(layer.image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(-bounds.topLeft())
        color = self.opts.foreground
        if self.opts.shape == "line":
            pen = QPen(color, max(1, self.opts.size))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(start, end)
        else:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            rect = QRectF(start, end).normalized()
            if self.opts.shape == "ellipse":
                p.drawEllipse(rect)
            else:
                p.drawRect(rect)
        p.end()
        doc.undo_stack.push(InsertLayerCommand(
            doc, len(doc.layers), layer, "Add Shape"))


class TextTool(Tool):
    """Text (T): click to place text — a dialog takes the content and font,
    and the text rasterises onto a new layer at the click point."""

    name = "text"
    cursor = Qt.CursorShape.IBeamCursor

    def press(self, doc, canvas, pos, ev):
        from photoslop.commands import InsertLayerCommand
        from photoslop.textdialog import TextDialog, render_text_layer

        dialog = TextDialog(self.opts.foreground, canvas.window())
        if not dialog.exec():
            return
        layer = render_text_layer(dialog.text(), dialog.chosen_font(),
                                  dialog.color, pos.toPoint())
        if layer is None:
            return
        doc.undo_stack.push(InsertLayerCommand(
            doc, len(doc.layers), layer, "Add Text"))


class SpotHealTool(Tool):
    """Spot Healing (J): paint over a blemish; on release the covered region
    fills by diffusion from its boundary and blends in."""

    name = "spot-heal"
    cursor = Qt.CursorShape.CrossCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._layer = None
        self._mask = None
        self._trail: list[QPointF] = []

    def press(self, doc, canvas, pos, ev):
        layer = doc.active_layer
        if layer is None:
            return
        self._layer = layer
        self._mask = np.zeros(
            (layer.image.height(), layer.image.width()), dtype=bool)
        self._trail = []
        self._stamp(pos)
        canvas.update()

    def move(self, doc, canvas, pos, ev):
        if self._mask is None:
            return
        self._stamp(pos)
        canvas.update()

    def _stamp(self, pos: QPointF) -> None:
        layer = self._layer
        radius = max(1, int(self.opts.size / 2))
        cx = int(pos.x() - layer.offset.x())
        cy = int(pos.y() - layer.offset.y())
        h, w = self._mask.shape
        y0, y1 = max(0, cy - radius), min(h, cy + radius + 1)
        x0, x1 = max(0, cx - radius), min(w, cx + radius + 1)
        if y0 >= y1 or x0 >= x1:
            return
        yy, xx = np.ogrid[y0:y1, x0:x1]
        self._mask[y0:y1, x0:x1] |= ((yy - cy) ** 2 + (xx - cx) ** 2
                                     <= radius * radius)
        self._trail.append(QPointF(pos))

    def release(self, doc, canvas, pos, ev):
        layer, mask = self._layer, self._mask
        self._layer = None
        self._mask = None
        self._trail = []
        if layer is None or mask is None or not mask.any():
            return
        recorder = TileRecorder(doc, layer)
        ys, xs = np.nonzero(mask)
        pad = 2
        rect = QRect(int(xs.min()) - pad, int(ys.min()) - pad,
                     int(xs.max() - xs.min()) + 1 + 2 * pad,
                     int(ys.max() - ys.min()) + 1 + 2 * pad)
        recorder.will_change(rect)
        dirty = npimage.inpaint_diffuse(layer.image, mask)
        cmd = recorder.finish("Spot Heal")
        if cmd is not None:
            doc.undo_stack.push(cmd)
        doc.notify_pixels(dirty.translated(layer.offset))
        if canvas is not None:
            canvas.update()

    def cancel(self, doc=None) -> None:
        self._layer = None
        self._mask = None
        self._trail = []

    def overlay(self, doc, painter, canvas):
        z = canvas.zoom
        r = max(2.0, self.opts.size / 2.0 * z)
        painter.setBrush(QColor(120, 200, 255, 70))
        painter.setPen(Qt.PenStyle.NoPen)
        for pos in self._trail:
            painter.drawEllipse(QPointF(pos.x() * z, pos.y() * z), r, r)
        if canvas.hover_pos is not None:
            center = QPointF(canvas.hover_pos.x() * z, canvas.hover_pos.y() * z)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 180), 1))
            painter.drawEllipse(center, r, r)


class SmudgeTool(BrushTool):
    """Mixer/smudge brush: each stamp deposits the paint carried from the
    previous stamp (strength = opacity slider), then picks up what's now
    under the brush — dragging colour along the stroke."""

    name = "smudge"
    scratch_stroke = False

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._pickup: QImage | None = None

    def press(self, doc, canvas, pos, ev):
        self._pickup = None
        super().press(doc, canvas, pos, ev)

    def _stroke_name(self) -> str:
        return "Smudge"

    def _segment(self, doc, a: QPointF, b: QPointF, first: bool = False) -> None:
        layer = self._layer
        assert layer is not None and self._recorder is not None
        off = QPointF(layer.offset)
        la, lb = a - off, b - off
        radius = max(1.0, self.opts.size / 2.0)
        pad = int(radius) + 2
        rect = QRectF(la, lb).normalized().adjusted(-pad, -pad, pad, pad).toAlignedRect()
        self._recorder.will_change(rect)

        strength = self.opts.opacity / 100.0
        side = int(radius) + 1

        def stamp(center: QPointF) -> None:
            region = QRect(round(center.x()) - side, round(center.y()) - side,
                           2 * side, 2 * side)
            if self._pickup is not None:
                p = QPainter(layer.image)
                p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                path = QPainterPath()
                path.addEllipse(center, radius, radius)
                if self._clip is not None:
                    path = path.intersected(self._clip)
                p.setClipPath(path)
                p.setOpacity(strength)
                p.drawImage(region.topLeft(), self._pickup)
                p.end()
            self._pickup = layer.image.copy(region)

        spacing = max(1.0, radius * 0.35)  # smudge needs a dense trail
        delta = lb - la
        dist = math.hypot(delta.x(), delta.y())
        if first or dist == 0:
            stamp(la)
        if dist > 0:
            steps = int(dist / spacing)
            for i in range(1, steps + 1):
                t = (i * spacing) / dist
                stamp(QPointF(la.x() + delta.x() * t, la.y() + delta.y() * t))

        doc.notify_pixels(rect.translated(layer.offset))


class DodgeTool(BrushTool):
    scratch_stroke = False
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
    scratch_stroke = False
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


class HealBrushTool(CloneStampTool):
    """Sampled Healing Brush: Alt+click a source like the clone stamp, but
    stamps transplant the source's texture onto the destination's tone."""

    name = "heal"

    def _stroke_name(self) -> str:
        return "Healing Brush"

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
            dst_rect = QRect(round(center.x()) - pad, round(center.y()) - pad,
                             2 * pad, 2 * pad)
            src_chunk = layer.image.copy(src_rect)
            dst_chunk = layer.image.copy(dst_rect)
            healed = npimage.heal_patch(src_chunk, dst_chunk)
            path = QPainterPath()
            path.addEllipse(center, radius, radius)
            p.save()
            p.setClipPath(path, Qt.ClipOperation.IntersectClip)
            p.drawImage(QPointF(dst_rect.x(), dst_rect.y()), healed)
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


class MagneticLassoTool(PolyLassoTool):
    """Poly lasso whose segments hug edges: each anchor-to-cursor stretch is
    a livewire (minimum-cost path along strong gradients)."""

    name = "magnetic-lasso"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self._doc = None

    def press(self, doc, canvas, pos, ev):
        self._doc = doc
        super().press(doc, canvas, pos, ev)

    def _wire(self, a: QPointF, b: QPointF) -> list[QPointF]:
        doc = self._doc
        layer = doc.active_layer if doc is not None else None
        if layer is None:
            return [b]
        off = layer.offset
        points = npimage.livewire_path(
            layer.image,
            (a.x() - off.x(), a.y() - off.y()),
            (b.x() - off.x(), b.y() - off.y()))
        return [QPointF(x + off.x() + 0.5, y + off.y() + 0.5)
                for x, y in points[1:]]

    def _path(self) -> QPainterPath:
        path = QPainterPath(self._points[0])
        prev = self._points[0]
        for pt in self._points[1:]:
            for wp in self._wire(prev, pt):
                path.lineTo(wp)
            prev = pt
        if self._hover is not None:
            for wp in self._wire(prev, self._hover):
                path.lineTo(wp)
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
            members = ([lyr for lyr in doc.layers if lyr.group == layer.group]
                       if layer.group else [layer])
            origins = [QPoint(lyr.offset) for lyr in members]
            self._mode = ("layer", layer, QPoint(layer.offset), pos,
                          members, origins)

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
            _, layer, orig, start, members, origins = self._mode
            proposed = orig + (pos - start).toPoint()
            snapped = canvas.editor.snap_layer_offset(
                layer, proposed, ev.modifiers() if ev else None)
            delta = snapped - orig
            dirty = QRect()
            for member, member_orig in zip(members, origins, strict=True):
                dirty = dirty.united(member.bounds())
                member.offset = member_orig + delta
                dirty = dirty.united(member.bounds())
            doc.notify_pixels(dirty)

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
            _, layer, orig, _start, members, origins = self._mode
            delta = layer.offset - orig
            if not delta.isNull():
                if len(members) > 1:
                    from photoslop.commands import MoveGroupCommand

                    # offsets already sit at their final positions; the
                    # command's skip-first-redo pattern records them as-is
                    doc.undo_stack.push(MoveGroupCommand(doc, members, delta))
                else:
                    doc.undo_stack.push(
                        SetLayerOffsetCommand(doc, layer, orig, layer.offset))
        self._mode = None
