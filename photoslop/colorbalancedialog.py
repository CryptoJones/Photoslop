# SPDX-License-Identifier: Apache-2.0
"""Color Balance dialog: shadows/midtones/highlights band selector with
cyan–red / magenta–green / yellow–blue sliders (nine values total), live
preview via the shared banded LUT engine."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSlider,
)

from photoslop.adjust import apply_luts, color_balance_luts
from photoslop.commands import LayerRegionCommand
from photoslop.document import Document

_BANDS = ("shadows", "midtones", "highlights")
_AXES = (("Cyan", "Red"), ("Magenta", "Green"), ("Yellow", "Blue"))


class ColorBalanceDialog(QDialog):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Color Balance")
        self._doc = doc
        self._layer = doc.active_layer
        self._pristine = QImage(self._layer.image)  # COW reference
        self._values = {band: [0.0, 0.0, 0.0] for band in _BANDS}
        self._band = "midtones"

        form = QFormLayout(self)
        band_row = QHBoxLayout()
        self._radios: dict[str, QRadioButton] = {}
        for band in _BANDS:
            radio = QRadioButton(band.capitalize())
            radio.setChecked(band == self._band)
            radio.toggled.connect(
                lambda on, b=band: self._switch_band(b) if on else None)
            band_row.addWidget(radio)
            self._radios[band] = radio
        form.addRow(band_row)

        self._sliders: list[QSlider] = []
        self._labels: list[QLabel] = []
        for left, right in _AXES:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-100, 100)
            slider.setValue(0)
            slider.valueChanged.connect(self._changed)
            value = QLabel("0")
            value.setMinimumWidth(36)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            form.addRow(f"{left} ↔ {right}", slider)
            form.addRow("", value)
            self._sliders.append(slider)
            self._labels.append(value)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._preview)

    def _switch_band(self, band: str) -> None:
        self._band = band
        for i, slider in enumerate(self._sliders):
            slider.blockSignals(True)
            slider.setValue(round(self._values[band][i]))
            slider.blockSignals(False)
            self._labels[i].setText(f"{slider.value():+d}")

    def _changed(self) -> None:
        for i, slider in enumerate(self._sliders):
            self._values[self._band][i] = float(slider.value())
            self._labels[i].setText(f"{slider.value():+d}")
        self._debounce.start()

    def balance_values(self) -> dict[str, tuple[float, float, float]]:
        return {band: tuple(vals) for band, vals in self._values.items()}

    def _preview(self) -> None:
        img = QImage(self._pristine)
        apply_luts(img, color_balance_luts(self.balance_values()))
        self._layer.image = img
        self._doc.notify_pixels(self._layer.bounds())

    def accept(self) -> None:
        self._debounce.stop()
        self._preview()
        if self._layer.image != self._pristine:
            self._doc.undo_stack.push(LayerRegionCommand(
                self._doc, self._layer, self._layer.image.rect(),
                QImage(self._pristine), QImage(self._layer.image),
                "Color Balance", applied=True,
            ))
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self._layer.image = QImage(self._pristine)
        self._doc.notify_pixels(self._layer.bounds())
        super().reject()
