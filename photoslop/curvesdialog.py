# SPDX-License-Identifier: Apache-2.0
"""Curves dialog (Ctrl+M): a monotone-spline curve per channel (RGB master +
R/G/B), draggable control points, live preview via the shared LUT engine."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from photoslop.adjust import apply_luts, curve_lut, curves_luts
from photoslop.document import Document
from photoslop.scopedadjust import ScopedAdjustMixin

IDENTITY = [(0.0, 0.0), (255.0, 255.0)]


class CurveWidget(QWidget):
    """256-value curve editor: click to add a point, drag to move it,
    right-click to remove (endpoints stay)."""

    curveChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.points: list[tuple[float, float]] = list(IDENTITY)
        self._drag: int | None = None
        self.setMinimumSize(QSize(260, 260))

    # value space (0..255, y up) <-> widget space
    def _to_widget(self, x: float, y: float) -> QPointF:
        w, h = self.width() - 1, self.height() - 1
        return QPointF(x / 255.0 * w, h - y / 255.0 * h)

    def _to_value(self, pos: QPointF) -> tuple[float, float]:
        w, h = self.width() - 1, self.height() - 1
        return (
            max(0.0, min(255.0, pos.x() / w * 255.0)),
            max(0.0, min(255.0, (h - pos.y()) / h * 255.0)),
        )

    def _hit(self, pos: QPointF) -> int | None:
        for i, (x, y) in enumerate(self.points):
            p = self._to_widget(x, y)
            if abs(p.x() - pos.x()) <= 6 and abs(p.y() - pos.y()) <= 6:
                return i
        return None

    def set_points(self, points: list[tuple[float, float]]) -> None:
        self.points = list(points)
        self.update()

    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        hit = self._hit(pos)
        if ev.button() == Qt.MouseButton.RightButton:
            if hit is not None and 0 < hit < len(self.points) - 1:
                self.points.pop(hit)
                self.update()
                self.curveChanged.emit()
            return
        if hit is None:
            x, y = self._to_value(pos)
            self.points.append((x, y))
            self.points.sort()
            hit = self.points.index((x, y))
        self._drag = hit

    def mouseMoveEvent(self, ev) -> None:
        if self._drag is None:
            return
        x, y = self._to_value(ev.position())
        i = self._drag
        if i == 0:
            x = 0.0
        elif i == len(self.points) - 1:
            x = 255.0
        else:  # keep strictly between neighbours
            x = max(self.points[i - 1][0] + 1, min(self.points[i + 1][0] - 1, x))
        self.points[i] = (x, y)
        self.update()
        self.curveChanged.emit()

    def mouseReleaseEvent(self, ev) -> None:
        self._drag = None

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(32, 32, 32))
        p.setPen(QPen(QColor(70, 70, 70), 1))
        for i in (1, 2, 3):  # quarter grid
            p.drawLine(self._to_widget(i * 64, 0), self._to_widget(i * 64, 255))
            p.drawLine(self._to_widget(0, i * 64), self._to_widget(255, i * 64))
        p.drawLine(self._to_widget(0, 0), self._to_widget(255, 255))

        lut = curve_lut(self.points)
        p.setPen(QPen(QColor(230, 230, 230), 2))
        prev = self._to_widget(0, float(lut[0]))
        for x in range(1, 256, 2):
            cur = self._to_widget(x, float(lut[x]))
            p.drawLine(prev, cur)
            prev = cur
        p.setPen(QPen(QColor(0, 0, 0), 1))
        p.setBrush(QColor(255, 255, 255))
        for x, y in self.points:
            c = self._to_widget(x, y)
            p.drawEllipse(c, 4, 4)
        p.end()


class CurvesDialog(ScopedAdjustMixin, QDialog):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Curves")
        self._doc = doc
        self._layer = doc.active_layer
        self._pristine = QImage(self._layer.image)  # COW reference
        self.channel_points: dict[str, list[tuple[float, float]]] = {
            key: list(IDENTITY) for key in ("rgb", "r", "g", "b")
        }
        self._channel = "rgb"

        self.curve = CurveWidget()
        self.curve.curveChanged.connect(self._changed)

        self.channel_box = QComboBox()
        self.channel_box.addItems(["RGB", "Red", "Green", "Blue"])
        self.channel_box.currentIndexChanged.connect(self._switch_channel)
        reset = QPushButton("Reset Channel")
        reset.clicked.connect(self._reset_channel)
        top = QHBoxLayout()
        top.addWidget(self.channel_box)
        top.addWidget(reset)
        top.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        from PySide6.QtWidgets import QFormLayout

        scope_row = QFormLayout()
        box = QVBoxLayout(self)
        box.addLayout(top)
        box.addWidget(self.curve, 1)
        self.init_scope(scope_row)
        box.addLayout(scope_row)
        box.addWidget(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._preview)

    def _switch_channel(self, index: int) -> None:
        self._channel = ("rgb", "r", "g", "b")[index]
        self.curve.set_points(self.channel_points[self._channel])

    def _reset_channel(self) -> None:
        self.channel_points[self._channel] = list(IDENTITY)
        self.curve.set_points(IDENTITY)
        self._debounce.start()

    def _changed(self) -> None:
        self.channel_points[self._channel] = list(self.curve.points)
        self._debounce.start()

    def transform(self, img: QImage) -> None:
        apply_luts(img, curves_luts(self.channel_points))

    def _preview(self) -> None:
        self.preview_scope()

    def accept(self) -> None:
        self._debounce.stop()
        self.accept_scope("Curves")
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self.reject_scope()
        super().reject()
