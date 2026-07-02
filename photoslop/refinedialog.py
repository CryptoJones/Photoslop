# SPDX-License-Identifier: Apache-2.0
"""Refine Selection dialog: smooth + expand/contract with a live
marching-ants preview — the working core of Select and Mask."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QSpinBox,
)

from photoslop import npimage
from photoslop.document import Document


class RefineSelectionDialog(QDialog):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Refine Selection")
        self._doc = doc
        self._original = doc.selection  # QPainterPath (immutable by copy)
        self._base_mask = npimage.selection_mask(
            self._original, doc.size, QPoint(0, 0))

        form = QFormLayout(self)
        self.smooth = QSpinBox()
        self.smooth.setRange(0, 20)
        self.smooth.setSuffix(" px")
        self.expand = QSpinBox()
        self.expand.setRange(-50, 50)
        self.expand.setSuffix(" px")
        self.expand.setToolTip("Positive expands, negative contracts")
        form.addRow("Smooth", self.smooth)
        form.addRow("Expand/Contract", self.expand)
        self.smooth.valueChanged.connect(self._changed)
        self.expand.valueChanged.connect(self._changed)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(150)
        self._debounce.timeout.connect(self._preview)

    def _changed(self) -> None:
        self._debounce.start()

    def _preview(self) -> None:
        mask = npimage.refine_mask(
            self._base_mask, self.smooth.value(), self.expand.value())
        if mask.any():
            self._doc.set_selection(npimage.mask_to_path(mask))
        else:
            self._doc.set_selection(None)

    def accept(self) -> None:
        self._debounce.stop()
        self._preview()
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self._doc.set_selection(self._original)
        super().reject()
