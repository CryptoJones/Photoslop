# SPDX-License-Identifier: Apache-2.0
"""Hue/Saturation dialog — same live-preview session pattern as Levels."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSlider,
)

from photoslop.adjust import apply_hsl
from photoslop.document import Document
from photoslop.scopedadjust import ScopedAdjustMixin


class HueSatDialog(ScopedAdjustMixin, QDialog):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Hue/Saturation")
        self._doc = doc
        self._layer = doc.active_layer
        self._pristine = QImage(self._layer.image)  # COW reference

        self._sliders: dict[str, QSlider] = {}
        self._labels: dict[str, QLabel] = {}
        form = QFormLayout(self)
        for key, label, extent in (("hue", "Hue", 180),
                                   ("saturation", "Saturation", 100),
                                   ("lightness", "Lightness", 100)):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-extent, extent)
            slider.setValue(0)
            slider.valueChanged.connect(self._changed)
            value = QLabel("0")
            value.setMinimumWidth(36)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            form.addRow(label, slider)
            form.addRow("", value)
            self._sliders[key] = slider
            self._labels[key] = value

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
        self._debounce.timeout.connect(self._preview)

    def values(self) -> tuple[int, int, int]:
        return (self._sliders["hue"].value(),
                self._sliders["saturation"].value(),
                self._sliders["lightness"].value())

    def _changed(self) -> None:
        for key, slider in self._sliders.items():
            self._labels[key].setText(f"{slider.value():+d}")
        self._debounce.start()

    def transform(self, img: QImage) -> None:
        hue, sat, light = self.values()
        apply_hsl(img, hue, sat, light)

    def _preview(self) -> None:
        self.preview_scope()

    def accept(self) -> None:
        self._debounce.stop()
        self.accept_scope("Hue/Saturation")
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self.reject_scope()
        super().reject()
