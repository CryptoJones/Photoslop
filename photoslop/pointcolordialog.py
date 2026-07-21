# SPDX-License-Identifier: Apache-2.0
"""Point Color — targeted hue-band HSL with a click-to-sample preview.

Click anywhere on the thumbnail to pick the target hue straight from the
composite (the tracker's "click a color in the canvas" flow, self-contained
in the dialog); the swatch shows what's targeted. The Skin Tones preset
loads the classic skin band; Uniformity pulls in-band hues toward the
centre to even skin out."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
)

from photoslop.adjust import apply_point_color
from photoslop.document import Document
from photoslop.scopedadjust import ScopedAdjustMixin

_THUMB = 200


class _SampleLabel(QLabel):
    """Thumbnail that reports clicks in image coordinates."""

    def __init__(self, image: QImage, on_pick) -> None:
        super().__init__()
        self._image = image
        self._on_pick = on_pick
        self._pm = QPixmap.fromImage(
            image.scaled(
                _THUMB,
                _THUMB,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.setPixmap(self._pm)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setToolTip("Click to sample the target color")

    def mousePressEvent(self, event) -> None:
        sx = self._image.width() / self._pm.width()
        sy = self._image.height() / self._pm.height()
        x = int(event.position().x() * sx)
        y = int(event.position().y() * sy)
        if 0 <= x < self._image.width() and 0 <= y < self._image.height():
            self._on_pick(self._image.pixelColor(x, y))


class PointColorDialog(ScopedAdjustMixin, QDialog):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Point Color")
        self._doc = doc
        self._layer = doc.active_layer
        self._pristine = QImage(self._layer.image)

        form = QFormLayout(self)

        self.sample = _SampleLabel(doc.flatten(), self._picked)
        self.swatch = QLabel()
        self.swatch.setFixedSize(48, 24)
        self.swatch.setAutoFillBackground(True)
        pick_row = QHBoxLayout()
        pick_row.addWidget(self.sample)
        form.addRow(pick_row)

        self._sliders: dict[str, QSlider] = {}
        self._labels: dict[str, QLabel] = {}
        for key, label, lo, hi, start in (
            ("hue", "Hue", 0, 359, 20),
            ("range", "Range", 5, 120, 30),
            ("dh", "Hue shift", -90, 90, 0),
            ("ds", "Saturation", -100, 100, 0),
            ("dl", "Lightness", -100, 100, 0),
            ("uniform", "Uniformity", 0, 100, 0),
        ):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(lo, hi)
            slider.setValue(start)
            slider.valueChanged.connect(self._changed)
            value = QLabel(str(start))
            value.setMinimumWidth(36)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            form.addRow(label, slider)
            form.addRow("", value)
            self._sliders[key] = slider
            self._labels[key] = value

        skin = QPushButton("Skin Tones preset")
        skin.clicked.connect(self._skin_preset)
        row = QHBoxLayout()
        row.addWidget(skin)
        row.addWidget(QLabel("Target:"))
        row.addWidget(self.swatch)
        row.addStretch(1)
        form.addRow(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.init_scope(form)
        form.addRow(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self.preview_scope)
        self._update_swatch()

    def values(self) -> dict[str, float]:
        return {key: float(s.value()) for key, s in self._sliders.items()}

    def _picked(self, color: QColor) -> None:
        if color.alpha() == 0:
            return
        self._sliders["hue"].setValue(max(0, color.hsvHue()))

    def _skin_preset(self) -> None:
        for key, val in (("hue", 20), ("range", 28), ("dh", 0), ("ds", 0), ("dl", 0)):
            self._sliders[key].setValue(val)

    def _update_swatch(self) -> None:
        c = QColor.fromHsv(self._sliders["hue"].value() % 360, 200, 220)
        self.swatch.setStyleSheet(f"background:{c.name()}; border:1px solid #444;")

    def _changed(self) -> None:
        for key, slider in self._sliders.items():
            self._labels[key].setText(str(slider.value()))
        self._update_swatch()
        self._debounce.start()

    def transform(self, img: QImage) -> None:
        v = self.values()
        apply_point_color(img, v["hue"], v["range"], v["dh"], v["ds"], v["dl"], v["uniform"])

    def accept(self) -> None:
        self._debounce.stop()
        self.accept_scope("Point Color")
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self.reject_scope()
        super().reject()
