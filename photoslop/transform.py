# SPDX-License-Identifier: Apache-2.0
"""Free Transform (Ctrl+T): scale / rotate / move the active layer with a
live preview. The layer's pixels are only resampled ONCE, on commit — the
preview is drawn through the painter transform, so dragging costs nothing."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPen,
    QPolygonF,
    QTransform,
    QUndoCommand,
)

from photoslop.cursors import CursorIntent
from photoslop.layer import mask_to_alpha
from photoslop.tools import Tool, ToolOptions


class TransformLayerCommand(QUndoCommand):
    def __init__(
        self,
        doc,
        layer,
        old_image: QImage,
        old_offset: QPoint,
        new_image: QImage,
        new_offset: QPoint,
        old_mask: QImage | None = None,
        new_mask: QImage | None = None,
        old_text_data: dict | None = None,
        new_text_data: dict | None = None,
    ):
        super().__init__("Free Transform")
        self.doc, self.layer = doc, layer
        self.old_image, self.old_offset = old_image, QPoint(old_offset)
        self.new_image, self.new_offset = new_image, QPoint(new_offset)
        self.old_mask = old_mask
        self.new_mask = new_mask
        # A re-rendered text layer's size travels with its pixels: undoing the
        # transform must also restore the type's stored size, or the next edit
        # would re-render at the new size in the old box.
        self.old_text_data = old_text_data
        self.new_text_data = new_text_data
        self._applied = True

    def _swap(
        self, image: QImage, offset: QPoint, mask: QImage | None, text_data: dict | None
    ) -> None:
        dirty = self.layer.bounds()
        self.layer.image = QImage(image)
        self.layer.offset = QPoint(offset)
        self.layer.mask = QImage(mask) if mask is not None else None
        if text_data is not None or self.old_text_data is not None:
            self.layer.text_data = dict(text_data) if text_data is not None else None
        self.doc.notify_pixels(dirty.united(self.layer.bounds()))

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        self._swap(self.new_image, self.new_offset, self.new_mask, self.new_text_data)

    def undo(self) -> None:
        self._swap(self.old_image, self.old_offset, self.old_mask, self.old_text_data)


class TransformSession:
    """Pending transform of one layer: rotation+scale about the base centre
    plus a translation, all in canvas coordinates."""

    def __init__(self, doc, layer) -> None:
        self.doc = doc
        self.layer = layer
        self.base_image = QImage(layer.image)  # COW reference
        self.base_offset = QPoint(layer.offset)
        self.base_mask = QImage(layer.mask) if layer.mask is not None else None
        self.base_text_data = dict(layer.text_data) if layer.text_data else None
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.rotation = 0.0  # degrees
        self.translation = QPointF(0.0, 0.0)
        # Free-quad mode (distort/skew/perspective): once set, the quad IS
        # the transform and rot/scale/translation are baked into it.
        self.quad: list[QPointF] | None = None
        # Warp mode: a 3x3 control grid; the image renders as four
        # projective patches (quarter -> warped quad).
        self.warp_grid: list[QPointF] | None = None

    @property
    def base_center(self) -> QPointF:
        return QPointF(
            self.base_offset.x() + self.base_image.width() / 2.0,
            self.base_offset.y() + self.base_image.height() / 2.0,
        )

    @property
    def center(self) -> QPointF:
        return self.base_center + self.translation

    def matrix(self) -> QTransform:
        return QTransform().rotate(self.rotation).scale(self.scale_x, self.scale_y)

    def full_matrix(self) -> QTransform:
        """Image-local (0,0 at top-left) → canvas coordinates, whatever the
        mode. The preview painter and the commit both use this."""
        w, h = self.base_image.width(), self.base_image.height()
        if self.quad is not None:
            src = QPolygonF([QPointF(0, 0), QPointF(w, 0), QPointF(w, h), QPointF(0, h)])
            m = QTransform()
            QTransform.quadToQuad(src, QPolygonF(self.quad), m)
            return m
        c = self.center
        m = QTransform()
        m.translate(c.x(), c.y())
        m.rotate(self.rotation)
        m.scale(self.scale_x, self.scale_y)
        m.translate(-w / 2.0, -h / 2.0)
        return m

    def corners(self) -> list[QPointF]:
        """Transformed corner positions in canvas coordinates (TL,TR,BR,BL)."""
        if self.quad is not None:
            return [QPointF(p) for p in self.quad]
        w, h = self.base_image.width(), self.base_image.height()
        m = self.matrix()
        c = self.center
        out = []
        for lx, ly in ((0, 0), (w, 0), (w, h), (0, h)):
            p = m.map(QPointF(lx - w / 2.0, ly - h / 2.0))
            out.append(QPointF(p.x() + c.x(), p.y() + c.y()))
        return out

    def enter_quad(self) -> None:
        if self.quad is None:
            self.quad = self.corners()

    def enter_warp(self) -> None:
        if self.warp_grid is not None:
            return
        w = self.base_image.width()
        h = self.base_image.height()
        off = self.base_offset
        self.warp_grid = [
            QPointF(off.x() + w * col / 2.0, off.y() + h * row / 2.0)
            for row in range(3)
            for col in range(3)
        ]

    def warp_patches(self):
        """Yield (source_rect_in_image_coords, image->canvas QTransform) for
        the four grid patches."""
        w = self.base_image.width()
        h = self.base_image.height()
        grid = self.warp_grid
        for row in range(2):
            for col in range(2):
                sx0, sy0 = w * col / 2.0, h * row / 2.0
                sx1, sy1 = w * (col + 1) / 2.0, h * (row + 1) / 2.0
                src = QPolygonF(
                    [QPointF(sx0, sy0), QPointF(sx1, sy0), QPointF(sx1, sy1), QPointF(sx0, sy1)]
                )
                i = row * 3 + col
                dst = QPolygonF([grid[i], grid[i + 1], grid[i + 4], grid[i + 3]])
                m = QTransform()
                QTransform.quadToQuad(src, dst, m)
                yield QRectF(sx0, sy0, sx1 - sx0, sy1 - sy0), m

    def draw_preview(self, p) -> None:
        """Paint the live transform preview through the painter (canvas
        coordinate space) — handles warp, quad, and rot/scale uniformly."""
        if self.warp_grid is not None:
            for src, m in self.warp_patches():
                p.save()
                p.setTransform(m, True)
                p.drawImage(src.topLeft(), self.base_image, src)
                p.restore()
            return
        p.save()
        p.setTransform(self.full_matrix(), True)
        p.drawImage(QPointF(0, 0), self.base_image)
        p.restore()

    def to_local(self, pos: QPointF) -> QPointF:
        """Canvas point → unrotated, unscaled frame centred on the layer."""
        inverted, ok = self.matrix().inverted()
        if not ok:
            return QPointF(0, 0)
        d = pos - self.center
        return inverted.map(QPointF(d.x(), d.y()))

    def is_identity(self) -> bool:
        if self.warp_grid is not None:
            w = self.base_image.width()
            h = self.base_image.height()
            off = self.base_offset
            for row in range(3):
                for col in range(3):
                    expected = QPointF(off.x() + w * col / 2.0, off.y() + h * row / 2.0)
                    if self.warp_grid[row * 3 + col] != expected:
                        return False
            return True
        return (
            self.quad is None
            and self.scale_x == 1.0
            and self.scale_y == 1.0
            and self.rotation == 0.0
            and self.translation.isNull()
        )

    def commit(self) -> None:
        if self.is_identity():
            return
        if self.warp_grid is not None:
            xs = [pt.x() for pt in self.warp_grid]
            ys = [pt.y() for pt in self.warp_grid]
            bounds = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            from PySide6.QtCore import QSize

            from photoslop.layer import blank_image

            new_image = blank_image(
                QSize(max(1, round(bounds.width())), max(1, round(bounds.height())))
            )
            p = QPainter(new_image)
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            p.translate(-bounds.topLeft())
            for src, m in self.warp_patches():
                p.save()
                p.setTransform(m, True)
                p.drawImage(src.topLeft(), self.base_image, src)
                p.restore()
            p.end()
            new_mask = self._warp_mask(bounds)
            self._push(new_image, QPoint(round(bounds.left()), round(bounds.top())), new_mask)
            return
        if self.quad is not None:
            m = self.full_matrix()
            w, h = self.base_image.width(), self.base_image.height()
            new_image = self.base_image.transformed(m, Qt.TransformationMode.SmoothTransformation)
            new_mask = self._transform_mask(m)
            bounds = m.mapRect(QRectF(0, 0, w, h))
            new_offset = QPoint(round(bounds.left()), round(bounds.top()))
            self._push(new_image, new_offset, new_mask)
            return
        rendered = self._rerendered_text()
        if rendered is not None:
            new_image = rendered.image
            c = self.center
            new_offset = QPoint(
                round(c.x() - new_image.width() / 2.0), round(c.y() - new_image.height() / 2.0)
            )
            self._push(new_image, new_offset, None, rendered.text_data)
            return
        new_image = self.base_image.transformed(
            self.matrix(), Qt.TransformationMode.SmoothTransformation
        )
        new_mask = self._transform_mask(self.matrix())
        c = self.center
        new_offset = QPoint(
            round(c.x() - new_image.width() / 2.0), round(c.y() - new_image.height() / 2.0)
        )
        self._push(new_image, new_offset, new_mask)

    def _transform_mask(self, matrix: QTransform) -> QImage | None:
        """Apply a single QTransform to the base mask, preserving Grayscale8.

        ``QImage.transformed()`` on a Grayscale8 mask at a non-90° angle
        converts to ARGB32_Premultiplied internally.  A naive
        ``convertToFormat(Grayscale8)`` would read premultiplied RGB luminance,
        which is wrong at edges where alpha < 255.  Instead we route through
        Alpha8 (mask_to_alpha): the grey value *is* the alpha, so it is
        interpolated in the alpha channel, and we read the transformed alpha
        back as Grayscale8.
        """
        if self.base_mask is None:
            return None
        alpha = mask_to_alpha(self.base_mask)
        rotated = alpha.transformed(matrix, Qt.TransformationMode.SmoothTransformation)

        fmt = rotated.format()
        if fmt == QImage.Format.Format_Alpha8:
            return QImage(
                rotated.constBits(),
                rotated.width(),
                rotated.height(),
                rotated.bytesPerLine(),
                QImage.Format.Format_Grayscale8,
            ).copy()
        if fmt == QImage.Format.Format_Grayscale8:
            return rotated

        # ARGB32_Premultiplied: extract the alpha channel via numpy.
        from photoslop.npimage import view_u32

        arr = view_u32(rotated)
        alpha_bytes = (arr >> np.uint32(24)).astype(np.uint8)
        result = QImage(rotated.width(), rotated.height(), QImage.Format.Format_Grayscale8)
        out_bpl = result.bytesPerLine()
        out_arr = np.frombuffer(
            result.bits(),
            dtype=np.uint8,
            count=rotated.height() * out_bpl,
        ).reshape(rotated.height(), out_bpl)
        for y in range(rotated.height()):
            out_arr[y, : rotated.width()] = alpha_bytes[y, :]
        return result

    def _warp_mask(self, bounds: QRectF) -> QImage | None:
        """Warp the base mask through the same patch grid as the image."""
        if self.base_mask is None:
            return None
        from PySide6.QtCore import QSize

        new_mask = QImage(
            QSize(max(1, round(bounds.width())), max(1, round(bounds.height()))),
            self.base_mask.format(),
        )
        new_mask.fill(0)
        mp = QPainter(new_mask)
        mp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        mp.translate(-bounds.topLeft())
        for src, m in self.warp_patches():
            mp.save()
            mp.setTransform(m, True)
            mp.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            mp.drawImage(src.topLeft(), self.base_mask, src)
            mp.restore()
        mp.end()
        return new_mask

    def _rerendered_text(self):
        """The layer re-rendered at its transformed size, or None when the
        transform is not one type can absorb.

        A uniformly scaled text layer used to be resampled like any raster and
        went soft (#294); its `text_data` knows better. Only the pure uniform
        scale qualifies: rotation, stretch, quad and warp fall through to the
        raster path, whose result they genuinely are, and a masked layer keeps
        the raster path so the mask stays in register with the pixels.
        """
        data = self.layer.text_data
        if not data:
            return None
        if self.quad is not None or self.warp_grid is not None:
            return None
        if self.rotation != 0 or self.base_mask is not None:
            return None
        if self.scale_x <= 0 or abs(self.scale_x - self.scale_y) > 0.01:
            return None
        scale = self.scale_x
        if abs(scale - 1.0) < 1e-6:
            return None
        from photoslop.textdialog import render_text_document, render_text_layer

        if data.get("html"):
            from PySide6.QtGui import QTextCursor, QTextDocument

            document = QTextDocument()
            document.setHtml(data["html"])
            base = document.defaultFont()
            if base.pointSizeF() > 0:
                base.setPointSizeF(base.pointSizeF() * scale)
                document.setDefaultFont(base)
            # Every explicit per-letter size scales too; fragments without one
            # follow the default font scaled above.
            cursor = QTextCursor(document)
            block = document.begin()
            while block.isValid():
                fragment_iter = block.begin()
                while not fragment_iter.atEnd():
                    fragment = fragment_iter.fragment()
                    fmt = fragment.charFormat()
                    size = fmt.fontPointSize()
                    if size > 0:
                        fmt.setFontPointSize(size * scale)
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(
                            fragment.position() + fragment.length(), QTextCursor.MoveMode.KeepAnchor
                        )
                        cursor.setCharFormat(fmt)
                    fragment_iter += 1
                block = block.next()
            return render_text_document(document, QPoint(0, 0))

        font = QFont(data.get("family") or "")
        size = data.get("size") or 12
        font.setPointSizeF(max(1.0, float(size) * scale))
        color_values = data.get("color") or [0, 0, 0, 255]
        rendered = render_text_layer(
            data.get("text", ""), font, QColor(*color_values), QPoint(0, 0)
        )
        return rendered

    def _push(
        self,
        new_image: QImage,
        new_offset: QPoint,
        new_mask: QImage | None = None,
        new_text_data: dict | None = None,
    ) -> None:
        self.layer.image = new_image
        self.layer.offset = new_offset
        self.layer.mask = QImage(new_mask) if new_mask is not None else None
        self.doc.undo_stack.push(
            TransformLayerCommand(
                self.doc,
                self.layer,
                self.base_image,
                self.base_offset,
                QImage(new_image),
                new_offset,
                QImage(self.base_mask) if self.base_mask is not None else None,
                QImage(new_mask) if new_mask is not None else None,
                dict(self.base_text_data) if self.base_text_data else None,
                dict(new_text_data) if new_text_data else None,
            )
        )
        if new_text_data is not None:
            self.layer.text_data = dict(new_text_data)
        elif self.base_text_data:
            # A transform type cannot absorb (rotate, stretch, quad, warp)
            # rasterises the layer: stale text_data would let a later edit
            # silently re-render without the transform, so it is dropped —
            # and restored by undo.
            self.layer.text_data = None

    def restore(self) -> None:
        self.layer.image = QImage(self.base_image)
        self.layer.offset = QPoint(self.base_offset)
        self.layer.mask = QImage(self.base_mask) if self.base_mask is not None else None


_HANDLES = ("tl", "tr", "br", "bl", "t", "r", "b", "l")
_CORNER_LOCAL = {
    "tl": (-1, -1),
    "tr": (1, -1),
    "br": (1, 1),
    "bl": (-1, 1),
    "t": (0, -1),
    "r": (1, 0),
    "b": (0, 1),
    "l": (-1, 0),
}


class TransformTool(Tool):
    """Active while a Free Transform session runs. Inside = move, handles =
    scale (Shift = uniform), outside = rotate (Shift snaps to 15°)."""

    name = "transform"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self.session: TransformSession | None = None
        self._mode: str | None = None
        self._press_pos = QPointF()
        self._press_state: tuple | None = None
        self._press_quad: list[QPointF] | None = None

    # -- session control --

    def begin(self, doc, layer) -> None:
        self.session = TransformSession(doc, layer)

    def commit(self, canvas=None) -> None:
        if self.session is not None:
            self.session.commit()
            self.session = None
            self._mode = None
            if canvas is not None:
                canvas.editor.host.end_transform()

    def cancel(self, doc=None) -> None:
        if self.session is not None:
            session = self.session
            dirty = session.layer.bounds()
            session.restore()
            session.doc.notify_pixels(dirty.united(session.layer.bounds()))
            session.doc.notify_structure()
            self.session = None
            self._mode = None

    # -- interaction --

    def _hit(self, canvas, pos: QPointF) -> str:
        session = self.session
        tol = 8.0 / max(canvas.zoom, 0.01)
        corners = session.corners()
        centers = {
            "tl": corners[0],
            "tr": corners[1],
            "br": corners[2],
            "bl": corners[3],
            "t": (corners[0] + corners[1]) / 2,
            "r": (corners[1] + corners[2]) / 2,
            "b": (corners[2] + corners[3]) / 2,
            "l": (corners[3] + corners[0]) / 2,
        }
        for name in _HANDLES:
            p = centers[name]
            if abs(pos.x() - p.x()) <= tol and abs(pos.y() - p.y()) <= tol:
                return name
        local = session.to_local(pos)
        w, h = session.base_image.width(), session.base_image.height()
        if abs(local.x()) <= w / 2.0 and abs(local.y()) <= h / 2.0:
            return "move"
        return "rotate"

    def cursor_intent(
        self, doc, canvas, pos, modifiers=Qt.KeyboardModifier.NoModifier, dragging=False
    ):
        if self.session is None or pos is None:
            return CursorIntent("forbidden", valid=False)
        if self.session.warp_grid is not None:
            tol = 10.0 / max(canvas.zoom, 0.01)
            if any(
                (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2 <= tol * tol
                for pt in self.session.warp_grid
            ):
                return CursorIntent("node")
            return CursorIntent("forbidden", valid=False)
        hit = self._hit(canvas, pos)
        if hit == "move":
            return CursorIntent("move")
        if hit == "rotate":
            return CursorIntent("rotate")
        if hit in {"l", "r"}:
            return CursorIntent("resize-h")
        if hit in {"t", "b"}:
            return CursorIntent("resize-v")
        if hit in {"tl", "br"}:
            return CursorIntent("resize-fdiag")
        return CursorIntent("resize-bdiag")

    def press(self, doc, canvas, pos, ev):
        if self.session is None:
            return
        if self.session.warp_grid is not None:
            tol = 10.0 / max(canvas.zoom, 0.01)
            best, best_d = None, tol * tol
            for i, pt in enumerate(self.session.warp_grid):
                d = (pt.x() - pos.x()) ** 2 + (pt.y() - pos.y()) ** 2
                if d <= best_d:
                    best, best_d = i, d
            self._mode = f"warp:{best}" if best is not None else None
            self._press_pos = pos
            self._press_state = (
                self.session.scale_x,
                self.session.scale_y,
                self.session.rotation,
                QPointF(self.session.translation),
            )
            return
        self._mode = self._hit(canvas, pos)
        self._press_pos = pos
        s = self.session
        ctrl = ev is not None and bool(ev.modifiers() & Qt.KeyboardModifier.ControlModifier)
        if s.quad is not None or (ctrl and self._mode in _HANDLES):
            if self._mode in _HANDLES:
                s.enter_quad()
                self._mode = "quad:" + self._mode
            elif self._mode == "rotate":
                self._mode = "move"  # rotation is baked once distorting
        self._press_quad = [QPointF(p) for p in s.quad] if s.quad is not None else None
        self._press_state = (s.scale_x, s.scale_y, s.rotation, QPointF(s.translation))

    def move(self, doc, canvas, pos, ev):
        if self.session is None or self._mode is None:
            return
        s = self.session
        sx0, sy0, rot0, tr0 = self._press_state
        shift = ev is not None and bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if self._mode.startswith("warp:"):
            index = int(self._mode[5:])
            s.warp_grid[index] = QPointF(pos)
            doc.notify_structure()
            canvas.update()
            return
        if self._mode.startswith("quad:"):
            handle = self._mode[5:]
            delta = pos - self._press_pos
            quad = [QPointF(p) for p in self._press_quad]
            corner_of = {
                "tl": (0,),
                "tr": (1,),
                "br": (2,),
                "bl": (3,),
                "t": (0, 1),
                "r": (1, 2),
                "b": (2, 3),
                "l": (3, 0),
            }
            for i in corner_of[handle]:
                if handle in ("tl", "tr", "br", "bl"):
                    quad[i] = QPointF(pos)  # corner follows the cursor
                else:
                    quad[i] = self._press_quad[i] + delta  # edge skews
            s.quad = quad
        elif self._mode == "move":
            if s.quad is not None:
                delta = pos - self._press_pos
                s.quad = [p + delta for p in self._press_quad]
            else:
                s.translation = tr0 + (pos - self._press_pos)
        elif self._mode == "rotate":
            c = s.base_center + tr0
            a0 = math.degrees(math.atan2(self._press_pos.y() - c.y(), self._press_pos.x() - c.x()))
            a1 = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))
            angle = rot0 + (a1 - a0)
            if shift:
                angle = round(angle / 15.0) * 15.0
            s.rotation = angle
        else:  # scale via a handle
            w, h = s.base_image.width(), s.base_image.height()
            # local frame at press-state (undo current drag's scale changes)
            inverted, _ok = (QTransform().rotate(rot0)).inverted()
            d = pos - (s.base_center + tr0)
            local = inverted.map(QPointF(d.x(), d.y()))
            hx, hy = _CORNER_LOCAL[self._mode]
            sx, sy = sx0, sy0
            if hx != 0:
                sx = local.x() / (w / 2.0 * hx)  # negative = flipped
                sx = math.copysign(max(abs(sx), 0.02), sx)
            if hy != 0:
                sy = local.y() / (h / 2.0 * hy)
                sy = math.copysign(max(abs(sy), 0.02), sy)
            if shift and hx != 0 and hy != 0:
                uniform = max(abs(sx), abs(sy))
                sx = math.copysign(uniform, sx)
                sy = math.copysign(uniform, sy)
            s.scale_x, s.scale_y = sx, sy

        doc.notify_structure()
        canvas.update()

    def release(self, doc, canvas, pos, ev):
        self._mode = None

    def double_click(self, doc, canvas, pos, ev):
        self.commit(canvas)

    def overlay(self, doc, painter, canvas):
        if self.session is None:
            return
        z = canvas.zoom
        if self.session.warp_grid is not None:
            grid = [QPointF(pt.x() * z, pt.y() * z) for pt in self.session.warp_grid]
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(120, 220, 255, 200), 1))
            for row in range(3):  # grid lines
                painter.drawLine(grid[row * 3], grid[row * 3 + 1])
                painter.drawLine(grid[row * 3 + 1], grid[row * 3 + 2])
                painter.drawLine(grid[row], grid[row + 3])
                painter.drawLine(grid[row + 3], grid[row + 6])
            painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
            painter.setBrush(QColor(255, 255, 255, 230))
            for pt in grid:
                painter.drawRect(QRectF(pt.x() - 3.5, pt.y() - 3.5, 7, 7))
            return
        corners = [QPointF(p.x() * z, p.y() * z) for p in self.session.corners()]
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for color, style in (
            (QColor(255, 255, 255, 220), Qt.PenStyle.SolidLine),
            (QColor(0, 0, 0, 220), Qt.PenStyle.DashLine),
        ):
            painter.setPen(QPen(color, 1, style))
            for i in range(4):
                painter.drawLine(corners[i], corners[(i + 1) % 4])
        painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
        painter.setBrush(QColor(255, 255, 255, 230))
        mids = [(corners[i] + corners[(i + 1) % 4]) / 2 for i in range(4)]
        for p in corners + mids:
            painter.drawRect(QRectF(p.x() - 3, p.y() - 3, 6, 6))
