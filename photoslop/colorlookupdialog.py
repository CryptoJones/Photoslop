# SPDX-License-Identifier: Apache-2.0
"""Color Lookup adjustment dialog: 3D LUT preset selection, external .cube / .3dl
file loading, intensity/opacity slider, and live preview via ScopedAdjustMixin."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
)

from photoslop.document import Document
from photoslop.lut3d import (
    LUT3D,
    PRESET_NAMES,
    apply_lut3d,
    get_preset_lut,
    load_lut,
)
from photoslop.scopedadjust import ScopedAdjustMixin


class ColorLookupDialog(ScopedAdjustMixin, QDialog):
    """3D LUT Color Lookup dialog supporting presets and external .cube/.3dl tables."""

    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Color Lookup")
        self._doc = doc
        self._layer = doc.active_layer

        self._current_lut: LUT3D = get_preset_lut(PRESET_NAMES[0])

        form = QFormLayout(self)

        # Preset selection
        self.preset_combo = QComboBox()
        for name in PRESET_NAMES:
            self.preset_combo.addItem(name)
        self.preset_combo.currentTextChanged.connect(self._preset_changed)

        self.load_btn = QPushButton("Load 3D LUT…")
        self.load_btn.clicked.connect(self._on_load_lut)

        preset_row = QHBoxLayout()
        preset_row.addWidget(self.preset_combo, stretch=1)
        preset_row.addWidget(self.load_btn)
        form.addRow("3D LUT:", preset_row)

        # Intensity / Opacity slider
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(0, 100)
        self.intensity_slider.setValue(100)
        self.intensity_slider.valueChanged.connect(self._intensity_changed)

        self.intensity_label = QLabel("100%")
        self.intensity_label.setMinimumWidth(40)
        self.intensity_label.setAlignment(Qt.AlignmentFlag.AlignRight)

        intensity_row = QHBoxLayout()
        intensity_row.addWidget(self.intensity_slider, stretch=1)
        intensity_row.addWidget(self.intensity_label)
        form.addRow("Intensity:", intensity_row)

        # Dialog buttons (OK / Cancel)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        self.init_scope(form)
        form.addRow(buttons)

        # Debounce timer for live preview
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._preview)

        # Initial live preview
        self._debounce.start()

    def _preset_changed(self, text: str) -> None:
        if not text:
            return
        if text.startswith("Custom: "):
            # Retain currently loaded custom LUT
            self._debounce.start()
            return
        try:
            self._current_lut = get_preset_lut(text)
            self._debounce.start()
        except ValueError:
            pass

    def _intensity_changed(self, val: int) -> None:
        self.intensity_label.setText(f"{val}%")
        self._debounce.start()

    def _on_load_lut(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Load 3D LUT",
            "",
            "3D LUT Files (*.cube *.3dl);;Adobe Cube (*.cube);;Autodesk 3DL (*.3dl);;All Files (*)",
        )
        if not path_str:
            return
        try:
            loaded = load_lut(path_str)
            self._current_lut = loaded
            label = f"Custom: {Path(path_str).name}"
            # Add or update custom item in combo
            existing_idx = self.preset_combo.findText(label)
            if existing_idx < 0:
                self.preset_combo.addItem(label)
                self.preset_combo.setCurrentIndex(self.preset_combo.count() - 1)
            else:
                self.preset_combo.setCurrentIndex(existing_idx)
            self._debounce.start()
        except Exception as exc:
            QMessageBox.warning(self, "Load 3D LUT Error", f"Failed to load LUT:\n{exc}")

    def transform(self, img: QImage) -> None:
        intensity = self.intensity_slider.value() / 100.0
        apply_lut3d(img, self._current_lut, intensity=intensity)

    def _preview(self) -> None:
        self.preview_scope()

    def accept(self) -> None:
        self._debounce.stop()
        self.accept_scope("Color Lookup")
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self.reject_scope()
        super().reject()
