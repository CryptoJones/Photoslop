# SPDX-License-Identifier: Apache-2.0
"""Auto-generated parameter dialog for filter plugins — one spinbox row
per ParamSpec, so a plugin gets a UI without writing any Qt."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
)

from photoslop.filters import Filter


class FilterParamsDialog(QDialog):
    def __init__(self, cls: type[Filter], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(cls.label)
        self._cls = cls
        self._boxes: dict[str, QSpinBox | QDoubleSpinBox | QLineEdit] = {}
        form = QFormLayout(self)
        for spec in cls.params:
            if spec.type == "str":
                box = QLineEdit(str(spec.default))
            elif spec.type == "int":
                box = QSpinBox()
                box.setRange(int(spec.minimum), int(spec.maximum))
                box.setValue(int(spec.default))
            else:
                box = QDoubleSpinBox()
                box.setRange(spec.minimum, spec.maximum)
                box.setValue(spec.default)
            form.addRow(spec.label, box)
            self._boxes[spec.key] = box
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> dict:
        return {key: (box.text() if isinstance(box, QLineEdit) else box.value())
                for key, box in self._boxes.items()}
