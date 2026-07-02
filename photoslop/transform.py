# SPDX-License-Identifier: Apache-2.0
"""Free Transform (Ctrl+T): scale / rotate / move the active layer with a
live preview. The layer's pixels are only resampled ONCE, on commit — the
preview is drawn through the painter transform, so dragging costs nothing."""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPen, QTransform, QUndoCommand

from photoslop.tools import Tool, ToolOptions


class TransformLayerCommand(QUndoCommand):
    def __init__(self, doc, layer, old_image: QImage, old_offset: QPoint,
                 new_image: QImage, new_offset: QPoint):
        super().__init__("Free Transform")
        self.doc, self.layer = doc, layer
        self.old_image, self.old_offset = old_image, QPoint(old_offset)
        self.new_image, self.new_offset = new_image, QPoint(new_offset)
        self._applied = True

    def _swap(self, image: QImage, offset: QPoint) -> None:
        dirty = self.layer.bounds()
        self.layer.image = QImage(image)
        self.layer.offset = QPoint(offset)
        self.doc.notify_pixels(dirty.united(self.layer.bounds()))

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        self._swap(self.new_image, self.new_offset)

    def undo(self) -> None:
        self._swap(self.old_image, self.old_offset)


class TransformSession:
    """Pending transform of one layer: rotation+scale about the base centre
    plus a translation, all in canvas coordinates."""

    def __init__(self, doc, layer) -> None:
        self.doc = doc
        self.layer = layer
        self.base_image = QImage(layer.image)  # COW reference
        self.base_offset = QPoint(layer.offset)
        self.scale_x = 1.0
        self.scale_y = 1.0
        self.rotation = 0.0  # degrees
        self.translation = QPointF(0.0, 0.0)

    @property
    def base_center(self) -> QPointF:
        return QPointF(self.base_offset.x() + self.base_image.width() / 2.0,
                       self.base_offset.y() + self.base_image.height() / 2.0)

    @property
    def center(self) -> QPointF:
        return self.base_center + self.translation

    def matrix(self) -> QTransform:
        return QTransform().rotate(self.rotation).scale(self.scale_x, self.scale_y)

    def corners(self) -> list[QPointF]:
        """Transformed corner positions in canvas coordinates (TL,TR,BR,BL)."""
        w, h = self.base_image.width(), self.base_image.height()
        m = self.matrix()
        c = self.center
        out = []
        for lx, ly in ((0, 0), (w, 0), (w, h), (0, h)):
            p = m.map(QPointF(lx - w / 2.0, ly - h / 2.0))
            out.append(QPointF(p.x() + c.x(), p.y() + c.y()))
        return out

    def to_local(self, pos: QPointF) -> QPointF:
        """Canvas point → unrotated, unscaled frame centred on the layer."""
        inverted, ok = self.matrix().inverted()
        if not ok:
            return QPointF(0, 0)
        d = pos - self.center
        return inverted.map(QPointF(d.x(), d.y()))

    def is_identity(self) -> bool:
        return (self.scale_x == 1.0 and self.scale_y == 1.0
                and self.rotation == 0.0 and self.translation.isNull())

    def commit(self) -> None:
        if self.is_identity():
            return
        new_image = self.base_image.transformed(
            self.matrix(), Qt.TransformationMode.SmoothTransformation)
        c = self.center
        new_offset = QPoint(round(c.x() - new_image.width() / 2.0),
                            round(c.y() - new_image.height() / 2.0))
        self.layer.image = new_image
        self.layer.offset = new_offset
        self.doc.undo_stack.push(TransformLayerCommand(
            self.doc, self.layer, self.base_image, self.base_offset,
            QImage(new_image), new_offset))

    def restore(self) -> None:
        self.layer.image = QImage(self.base_image)
        self.layer.offset = QPoint(self.base_offset)


_HANDLES = ("tl", "tr", "br", "bl", "t", "r", "b", "l")
_CORNER_LOCAL = {"tl": (-1, -1), "tr": (1, -1), "br": (1, 1), "bl": (-1, 1),
                 "t": (0, -1), "r": (1, 0), "b": (0, 1), "l": (-1, 0)}


class TransformTool(Tool):
    """Active while a Free Transform session runs. Inside = move, handles =
    scale (Shift = uniform), outside = rotate (Shift snaps to 15°)."""

    name = "transform"
    cursor = Qt.CursorShape.SizeAllCursor

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self.session: TransformSession | None = None
        self._mode: str | None = None
        self._press_pos = QPointF()
        self._press_state: tuple | None = None

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
            "tl": corners[0], "tr": corners[1], "br": corners[2], "bl": corners[3],
            "t": (corners[0] + corners[1]) / 2, "r": (corners[1] + corners[2]) / 2,
            "b": (corners[2] + corners[3]) / 2, "l": (corners[3] + corners[0]) / 2,
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

    def press(self, doc, canvas, pos, ev):
        if self.session is None:
            return
        self._mode = self._hit(canvas, pos)
        self._press_pos = pos
        s = self.session
        self._press_state = (s.scale_x, s.scale_y, s.rotation,
                             QPointF(s.translation))

    def move(self, doc, canvas, pos, ev):
        if self.session is None or self._mode is None:
            return
        s = self.session
        sx0, sy0, rot0, tr0 = self._press_state
        shift = ev is not None and bool(
            ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)

        if self._mode == "move":
            s.translation = tr0 + (pos - self._press_pos)
        elif self._mode == "rotate":
            c = s.base_center + tr0
            a0 = math.degrees(math.atan2(self._press_pos.y() - c.y(),
                                         self._press_pos.x() - c.x()))
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
        corners = [QPointF(p.x() * z, p.y() * z) for p in self.session.corners()]
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for color, style in ((QColor(255, 255, 255, 220), Qt.PenStyle.SolidLine),
                             (QColor(0, 0, 0, 220), Qt.PenStyle.DashLine)):
            painter.setPen(QPen(color, 1, style))
            for i in range(4):
                painter.drawLine(corners[i], corners[(i + 1) % 4])
        painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
        painter.setBrush(QColor(255, 255, 255, 230))
        mids = [(corners[i] + corners[(i + 1) % 4]) / 2 for i in range(4)]
        for p in corners + mids:
            painter.drawRect(QRectF(p.x() - 3, p.y() - 3, 6, 6))
