# SPDX-License-Identifier: Apache-2.0
"""Levels dialog: input black/white points, gamma, output range — live
preview against a pristine copy of the active layer, one undo step on OK."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QPushButton,
    QSpinBox,
)

from photoslop.adjust import apply_luts, levels_lut
from photoslop.commands import LayerRegionCommand
from photoslop.document import Document
from photoslop.npimage import view_u32


class LevelsDialog(QDialog):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Levels")
        self._doc = doc
        self._layer = doc.active_layer
        self._pristine = QImage(self._layer.image)  # COW reference

        self.in_black = QSpinBox()
        self.in_black.setRange(0, 253)
        self.in_black.setValue(0)
        self.in_white = QSpinBox()
        self.in_white.setRange(2, 255)
        self.in_white.setValue(255)
        self.gamma = QDoubleSpinBox()
        self.gamma.setRange(0.10, 9.99)
        self.gamma.setSingleStep(0.05)
        self.gamma.setValue(1.00)
        self.out_black = QSpinBox()
        self.out_black.setRange(0, 255)
        self.out_black.setValue(0)
        self.out_white = QSpinBox()
        self.out_white.setRange(0, 255)
        self.out_white.setValue(255)
        for w in (self.in_black, self.in_white, self.gamma,
                  self.out_black, self.out_white):
            w.valueChanged.connect(self._changed)

        auto = QPushButton("Auto")
        auto.clicked.connect(self.auto_levels)

        form = QFormLayout(self)
        form.addRow("Input black", self.in_black)
        form.addRow("Input white", self.in_white)
        form.addRow("Gamma", self.gamma)
        form.addRow("Output black", self.out_black)
        form.addRow("Output white", self.out_white)
        form.addRow(auto)
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

    # ----- machinery ---------------------------------------------------------

    def current_lut(self) -> np.ndarray:
        lut = levels_lut(self.in_black.value(), self.in_white.value(),
                         self.gamma.value(), self.out_black.value(),
                         self.out_white.value())
        return np.stack([lut, lut, lut])

    def _changed(self) -> None:
        if self.in_white.value() <= self.in_black.value():
            self.in_white.setValue(self.in_black.value() + 1)
        self._debounce.start()

    def _preview(self) -> None:
        img = QImage(self._pristine)
        apply_luts(img, self.current_lut())  # first write detaches the copy
        self._layer.image = img
        self._doc.notify_pixels(self._layer.bounds())

    def auto_levels(self) -> None:
        """0.1% percentile black/white points from a downsampled luminance
        histogram — cheap at any layer size."""
        sample = self._pristine.scaled(
            256, 256, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation)
        arr = view_u32(sample)
        r = (arr >> np.uint32(16)) & 0xFF
        g = (arr >> np.uint32(8)) & 0xFF
        b = arr & 0xFF
        luma = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8).ravel()
        lo, hi = np.percentile(luma, [0.1, 99.9])
        self.in_black.setValue(int(min(lo, 253)))
        self.in_white.setValue(int(max(hi, lo + 2)))

    # ----- outcome ------------------------------------------------------------

    def accept(self) -> None:
        self._debounce.stop()
        self._preview()
        if self._layer.image != self._pristine:
            self._doc.undo_stack.push(LayerRegionCommand(
                self._doc, self._layer, self._layer.image.rect(),
                QImage(self._pristine), QImage(self._layer.image),
                "Levels", applied=True,
            ))
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self._layer.image = QImage(self._pristine)
        self._doc.notify_pixels(self._layer.bounds())
        super().reject()
