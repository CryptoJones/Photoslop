# SPDX-License-Identifier: Apache-2.0
"""Auto-generated parameter dialog for filter plugins — one spinbox row
per ParamSpec, so a plugin gets a UI without writing any Qt.

Filters with a lot of knobs (Node Machine has seventeen) would otherwise
generate a form taller than the screen, so past a threshold the rows go
inside a scroll area capped to a fraction of the available screen height.
Short dialogs are laid out exactly as before — Sepia's single row must not
grow a scrollbar."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from photoslop.filters import Filter

# Row count past which the form is worth scrolling rather than stretching.
_SCROLL_THRESHOLD = 8
# Never let the dialog claim more than this share of the screen.
_MAX_SCREEN_FRACTION = 0.7


class FilterParamsDialog(QDialog):
    def __init__(self, cls: type[Filter], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(cls.label)
        self._cls = cls
        self._boxes: dict[str, QSpinBox | QDoubleSpinBox | QLineEdit | QComboBox] = {}
        rows = QWidget(self)
        form = QFormLayout(rows)
        for spec in cls.params:
            if spec.type == "choice":
                box = QComboBox()
                box.addItems(list(spec.choices))
                box.setCurrentText(str(spec.default))
            elif spec.type == "str":
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

        outer = QVBoxLayout(self)
        if len(cls.params) > _SCROLL_THRESHOLD:
            scroll = QScrollArea(self)
            scroll.setWidgetResizable(True)
            scroll.setWidget(rows)
            outer.addWidget(scroll)
            self.setMaximumHeight(self._screen_cap())
        else:
            outer.addWidget(rows)
        # Buttons live outside the scroll area so OK is always reachable.
        outer.addWidget(buttons)

    def _screen_cap(self) -> int:
        """Height budget for a scrolling dialog; falls back to a sane
        constant when there is no screen (offscreen test runs)."""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return 600
        return int(screen.availableGeometry().height() * _MAX_SCREEN_FRACTION)

    def values(self) -> dict:
        return {
            key: (
                box.currentText()
                if isinstance(box, QComboBox)
                else box.text()
                if isinstance(box, QLineEdit)
                else box.value()
            )
            for key, box in self._boxes.items()
        }
