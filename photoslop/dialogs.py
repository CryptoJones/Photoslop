# SPDX-License-Identifier: Apache-2.0
"""New-document, image-resize, and canvas-size dialogs."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
)

from photoslop import units
from photoslop.units import PAPER_SIZES  # noqa: F401 — re-export; canonical home is units

_BACKGROUNDS = (
    ("White", QColor(255, 255, 255)),
    ("Transparent", None),
    ("Black", QColor(0, 0, 0)),
)


class NewDocumentDialog(QDialog):
    def __init__(self, parent=None, initial_size: QSize | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Image")

        self.name = QLineEdit("Untitled")
        self.width = QDoubleSpinBox()
        self.height = QDoubleSpinBox()
        for spin in (self.width, self.height):
            spin.setRange(0.001, 65535)
            spin.setDecimals(3)
        self.width.setValue(800)
        self.height.setValue(600)

        self.unit = QComboBox()
        self.unit.addItems(list(units.UNITS))
        self._last_unit = "px"
        self.unit.currentTextChanged.connect(self._convert_unit)

        self.dpi = QSpinBox()
        self.dpi.setRange(1, 2400)
        self.dpi.setValue(72)

        self.background = QComboBox()
        self.background.addItems([label for label, _c in _BACKGROUNDS])

        presets = QGroupBox("Preset")
        preset_lay = QVBoxLayout(presets)
        self.custom_radio = QRadioButton("Custom")
        self.custom_radio.setChecked(True)
        preset_lay.addWidget(self.custom_radio)
        self.preset_radios = {}
        for name, wmm, hmm, metric, inches in PAPER_SIZES:
            radio = QRadioButton(f"{name} — {metric} ({inches})")
            radio.toggled.connect(lambda on, w=wmm, h=hmm: on and self._apply_preset(w, h))
            preset_lay.addWidget(radio)
            self.preset_radios[name] = radio
        self._applying_preset = False
        for spin in (self.width, self.height):
            spin.valueChanged.connect(self._size_edited)

        form = QFormLayout(self)
        form.addRow("Name", self.name)
        form.addRow(presets)
        form.addRow("Width", self.width)
        form.addRow("Height", self.height)
        form.addRow("Unit", self.unit)
        form.addRow("Resolution (DPI)", self.dpi)
        form.addRow("Background", self.background)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        if initial_size is not None:  # e.g. the clipboard image's size
            self.unit.setCurrentText("px")
            self._applying_preset = True
            self.width.setValue(initial_size.width())
            self.height.setValue(initial_size.height())
            self._applying_preset = False

    def _apply_preset(self, wmm: float, hmm: float) -> None:
        self._applying_preset = True
        self.unit.setCurrentText("mm")
        self.width.setValue(wmm)
        self.height.setValue(hmm)
        self._applying_preset = False

    def _size_edited(self) -> None:
        # hand-editing the size means it is no longer the chosen preset
        if not self._applying_preset and not self.custom_radio.isChecked():
            self.custom_radio.setChecked(True)

    def _convert_unit(self, unit: str) -> None:
        # converting units preserves the physical size, so it must not kick
        # the preset radio back to Custom
        guard, self._applying_preset = self._applying_preset, True
        dpi = float(self.dpi.value())
        for spin in (self.width, self.height):
            px = units.unit_to_px(spin.value(), self._last_unit, dpi)
            spin.setValue(units.px_to_unit(px, unit, dpi))
        self._last_unit = unit
        for spin in (self.width, self.height):
            spin.setDecimals(0 if unit == "px" else 3)
        self._applying_preset = guard

    def values(self) -> tuple[str, QSize, float, QColor | None]:
        dpi = float(self.dpi.value())
        unit = self.unit.currentText()
        w = max(1, round(units.unit_to_px(self.width.value(), unit, dpi)))
        h = max(1, round(units.unit_to_px(self.height.value(), unit, dpi)))
        color = _BACKGROUNDS[self.background.currentIndex()][1]
        return self.name.text().strip() or "Untitled", QSize(w, h), dpi, color


class ResizeImageDialog(QDialog):
    def __init__(self, current: QSize, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Image Size")
        self._ratio = current.width() / max(1, current.height())
        self._guard = False

        self.width = QSpinBox()
        self.height = QSpinBox()
        for spin in (self.width, self.height):
            spin.setRange(1, 65535)
        self.width.setValue(current.width())
        self.height.setValue(current.height())
        self.constrain = QCheckBox("Constrain proportions")
        self.constrain.setChecked(True)

        self.width.valueChanged.connect(lambda v: self._linked(self.height, v / self._ratio))
        self.height.valueChanged.connect(lambda v: self._linked(self.width, v * self._ratio))

        form = QFormLayout(self)
        form.addRow("Width (px)", self.width)
        form.addRow("Height (px)", self.height)
        form.addRow(self.constrain)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _linked(self, other: QSpinBox, value: float) -> None:
        if self.constrain.isChecked() and not self._guard:
            self._guard = True
            other.setValue(max(1, round(value)))
            self._guard = False

    def value(self) -> QSize:
        return QSize(self.width.value(), self.height.value())


class CanvasSizeDialog(QDialog):
    """New canvas extent plus a 9-way anchor for where the old content sits."""

    def __init__(self, current: QSize, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Canvas Size")
        self._current = QSize(current)

        self.width = QSpinBox()
        self.height = QSpinBox()
        for spin in (self.width, self.height):
            spin.setRange(1, 65535)
        self.width.setValue(current.width())
        self.height.setValue(current.height())

        anchor_box = QGroupBox("Anchor")
        grid = QGridLayout(anchor_box)
        self._anchor = (0.5, 0.5)
        self._anchor_buttons = {}
        from PySide6.QtWidgets import QToolButton

        for row, ay in enumerate((0.0, 0.5, 1.0)):
            for col, ax in enumerate((0.0, 0.5, 1.0)):
                btn = QToolButton()
                btn.setCheckable(True)
                btn.setText("·")
                btn.setFixedSize(28, 28)
                grid.addWidget(btn, row, col)
                self._anchor_buttons[(ax, ay)] = btn
                btn.clicked.connect(lambda _=False, a=(ax, ay): self._set_anchor(a))
        self._set_anchor((0.5, 0.5))

        form = QFormLayout()
        form.addRow("Width (px)", self.width)
        form.addRow("Height (px)", self.height)

        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(anchor_box, alignment=Qt.AlignmentFlag.AlignHCenter)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box.addWidget(buttons)

    def _set_anchor(self, anchor: tuple[float, float]) -> None:
        self._anchor = anchor
        for key, btn in self._anchor_buttons.items():
            btn.setChecked(key == anchor)
            btn.setText("●" if key == anchor else "·")

    def value(self) -> tuple[QSize, QPoint]:
        new = QSize(self.width.value(), self.height.value())
        ax, ay = self._anchor
        delta = QPoint(
            round((new.width() - self._current.width()) * ax),
            round((new.height() - self._current.height()) * ay),
        )
        return new, delta
