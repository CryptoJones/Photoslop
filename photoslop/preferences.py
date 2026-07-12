# SPDX-License-Identifier: Apache-2.0
"""Consolidated Preferences dialog (#131): one tabbed window for the app-level
settings — the generative model backend and colour management. Reachable as
Edit → Preferences… everywhere and, on macOS, the native Photoslop →
Preferences… (Cmd+,) slot, because the menu action carries PreferencesRole."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from photoslop.colordialog import ColorSettingsPanel


class ModelBackendPanel(QWidget):
    """Adapter + HTTP endpoint for the generative model routes. Reads and
    (on apply) writes the model/* keys in the shared QSettings."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from photoslop.modeladapter import available_adapters

        self._settings = QSettings("CryptoJones", "Photoslop")
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)  # sit flush inside a tab
        self.combo = QComboBox()
        self.combo.addItem("(none)", "")
        for name, cls in sorted(available_adapters().items()):
            self.combo.addItem(cls.label, name)
        self.combo.setCurrentIndex(max(0, self.combo.findData(
            self._settings.value("model/adapter", ""))))
        self.url = QLineEdit(self._settings.value("model/http_url", ""))
        self.url.setPlaceholderText("http://localhost:8188/photoslop")
        form.addRow("&Adapter:", self.combo)
        form.addRow("HTTP &URL:", self.url)

    def apply(self) -> None:
        self._settings.setValue("model/adapter", self.combo.currentData())
        self._settings.setValue("model/http_url", self.url.text().strip())


class AccessibilityPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = QSettings("CryptoJones", "Photoslop")
        form = QFormLayout(self)
        self.high_contrast = QCheckBox("Use high-contrast application palette")
        self.high_contrast.setChecked(
            str(self._settings.value(
                "accessibility/high_contrast", "false")).lower() == "true")
        self.reduced_motion = QCheckBox("Reduce selection and status animation")
        self.reduced_motion.setChecked(
            str(self._settings.value(
                "accessibility/reduced_motion", "false")).lower() == "true")
        self.scale = QComboBox()
        for value in (100, 125, 150, 200):
            self.scale.addItem(f"{value}%", value)
        self.scale.setCurrentIndex(max(0, self.scale.findData(
            int(self._settings.value("accessibility/control_scale", 100)))))
        form.addRow(self.high_contrast)
        form.addRow(self.reduced_motion)
        form.addRow("Control scale", self.scale)

    def apply(self) -> None:
        self._settings.setValue("accessibility/high_contrast", self.high_contrast.isChecked())
        self._settings.setValue("accessibility/reduced_motion", self.reduced_motion.isChecked())
        self._settings.setValue("accessibility/control_scale", self.scale.currentData())


class PreferencesDialog(QDialog):
    """Tabbed application preferences: Model Backend + Color. OK commits every
    panel; Cancel discards."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.model_panel = ModelBackendPanel(self)
        self.color_panel = ColorSettingsPanel(self)
        self.accessibility_panel = AccessibilityPanel(self)
        self.tabs.addTab(self.model_panel, "Model Backend")
        self.tabs.addTab(self.color_panel, "Color")
        self.tabs.addTab(self.accessibility_panel, "Accessibility")
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        self.model_panel.apply()
        self.color_panel.apply()
        self.accessibility_panel.apply()
        self.accept()
