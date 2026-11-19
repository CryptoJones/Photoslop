# SPDX-License-Identifier: Apache-2.0
"""Gaussian Blur dialog with live preview, slider and spinbox up to 250px."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from photoslop import npimage
from photoslop.document import Document
from photoslop.services import FilterService


class GaussianBlurDialog(QDialog):
    """Gaussian Blur dialog with slider, spinbox up to 250px, and live preview (#418)."""

    def __init__(self, doc: Document, parent=None, initial_radius: int = 8) -> None:
        super().__init__(parent)
        self.setWindowTitle("Gaussian Blur")
        self._doc = doc
        self._layer = doc.active_layer
        self._pristine = QImage(self._layer.image)  # COW copy

        # Precompute selection mask and feathered weights
        self._mask = None
        self._weights = None
        if doc.selection is not None:
            if doc.selection_feather > 0:
                self._weights = npimage.feathered_weights(
                    doc.selection,
                    self._layer.image.size(),
                    self._layer.offset,
                    doc.selection_feather,
                )
            else:
                m = npimage.selection_mask(
                    doc.selection, self._layer.image.size(), self._layer.offset
                )
                if m.any():
                    self._mask = m

        outer = QVBoxLayout(self)
        form = QFormLayout()

        # Radius controls: slider and spinbox linked together (1..250)
        row = QHBoxLayout()
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setRange(1, 250)
        self._slider.setValue(max(1, min(250, initial_radius)))

        self._spin = QSpinBox()
        self._spin.setRange(1, 250)
        self._spin.setValue(self._slider.value())
        self._spin.setSuffix(" px")

        self._slider.valueChanged.connect(self._spin.setValue)
        self._spin.valueChanged.connect(self._slider.setValue)
        self._slider.valueChanged.connect(self._on_radius_changed)

        row.addWidget(self._slider)
        row.addWidget(self._spin)
        form.addRow("Radius:", row)

        self._preview_cb = QCheckBox("Preview")
        self._preview_cb.setChecked(True)
        self._preview_cb.toggled.connect(self._on_preview_toggled)
        form.addRow("", self._preview_cb)

        outer.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        # Debounce timer for responsive preview without event flooding
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(40)
        self._debounce.timeout.connect(self._update_preview)

        # Trigger initial preview if enabled
        if self._preview_cb.isChecked():
            self._update_preview()

    def radius(self) -> int:
        return self._spin.value()

    def set_radius(self, val: int) -> None:
        self._spin.setValue(max(1, min(250, int(val))))

    def _on_radius_changed(self, _val: int) -> None:
        if self._preview_cb.isChecked():
            self._debounce.start()

    def _on_preview_toggled(self, checked: bool) -> None:
        if checked:
            self._update_preview()
        else:
            self._debounce.stop()
            self._restore_pristine()

    def _update_preview(self) -> None:
        if not self._preview_cb.isChecked():
            return
        radius = self.radius()
        blurred = FilterService.apply(
            self._pristine,
            lambda img, m: npimage.fast_blur(img, radius, m),
            self._mask,
            self._weights,
        )
        self._layer.image = blurred
        self._doc.notify_pixels(self._layer.bounds())

    def _restore_pristine(self) -> None:
        self._layer.image = QImage(self._pristine)
        self._doc.notify_pixels(self._layer.bounds())

    def accept(self) -> None:
        self._debounce.stop()
        self._restore_pristine()
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self._restore_pristine()
        super().reject()
