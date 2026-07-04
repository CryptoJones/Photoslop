# SPDX-License-Identifier: Apache-2.0
"""Auto-generated parameter dialog for filter plugins — one spinbox row
per ParamSpec, so a plugin gets a UI without writing any Qt."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
)

from photoslop.filters import Filter


class FilterParamsDialog(QDialog):
    def __init__(self, cls: type[Filter], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(cls.label)
        self._cls = cls
        self._boxes: dict[str, QSpinBox | QDoubleSpinBox] = {}
        form = QFormLayout(self)
        for spec in cls.params:
            box = QSpinBox() if spec.type == "int" else QDoubleSpinBox()
            box.setRange(int(spec.minimum) if spec.type == "int" else spec.minimum,
                         int(spec.maximum) if spec.type == "int" else spec.maximum)
            box.setValue(int(spec.default) if spec.type == "int" else spec.default)
            form.addRow(spec.label, box)
            self._boxes[spec.key] = box
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {key: box.value() for key, box in self._boxes.items()}
