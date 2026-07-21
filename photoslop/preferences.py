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
        allow_unsafe = (
            str(self._settings.value("security/allow_unsafe_plugins", "false")).lower() == "true"
        )
        for name, cls in sorted(available_adapters(allow_unsafe=allow_unsafe).items()):
            self.combo.addItem(cls.label, name)
        self.combo.setCurrentIndex(
            max(0, self.combo.findData(self._settings.value("model/adapter", "")))
        )
        self.url = QLineEdit(self._settings.value("model/http_url", ""))
        self.url.setPlaceholderText("http://localhost:8188/photoslop")
        self.insecure_http = QCheckBox("Allow unencrypted HTTP to non-local model servers")
        self.insecure_http.setChecked(
            str(self._settings.value("model/allow_insecure_http", "false")).lower() == "true"
        )
        form.addRow("&Adapter:", self.combo)
        form.addRow("HTTP &URL:", self.url)
        form.addRow(self.insecure_http)

    def apply(self) -> None:
        self._settings.setValue("model/adapter", self.combo.currentData())
        self._settings.setValue("model/http_url", self.url.text().strip())
        self._settings.setValue("model/allow_insecure_http", self.insecure_http.isChecked())


class SecurityPanel(QWidget):
    """Local-only opt-ins that deliberately widen a trust boundary."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = QSettings("CryptoJones", "Photoslop")
        form = QFormLayout(self)
        self.unsafe_plugins = QCheckBox(
            "Enable native and third-party filter plugins (restart required)"
        )
        self.unsafe_plugins.setToolTip(
            "These filters may launch G'MIC, GEGL, or GIMP, or execute "
            "third-party Python code. They are never exposed through MCP."
        )
        self.unsafe_plugins.setChecked(
            str(self._settings.value("security/allow_unsafe_plugins", "false")).lower() == "true"
        )
        self.large_documents = QCheckBox(
            "Allow trusted documents beyond the adaptive memory estimate"
        )
        self.large_documents.setToolTip(
            "Hard dimension, pixel-count, archive, and parser limits still apply."
        )
        self.large_documents.setChecked(
            str(self._settings.value("security/allow_large_documents", "false")).lower() == "true"
        )
        form.addRow(self.unsafe_plugins)
        form.addRow(self.large_documents)

    def apply(self) -> None:
        self._settings.setValue("security/allow_unsafe_plugins", self.unsafe_plugins.isChecked())
        self._settings.setValue("security/allow_large_documents", self.large_documents.isChecked())


class AccessibilityPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings = QSettings("CryptoJones", "Photoslop")
        form = QFormLayout(self)
        self.high_contrast = QCheckBox("Use high-contrast application palette")
        self.high_contrast.setChecked(
            str(self._settings.value("accessibility/high_contrast", "false")).lower() == "true"
        )
        self.reduced_motion = QCheckBox("Reduce selection and status animation")
        self.reduced_motion.setChecked(
            str(self._settings.value("accessibility/reduced_motion", "false")).lower() == "true"
        )
        self.scale = QComboBox()
        for value in (100, 125, 150, 200):
            self.scale.addItem(f"{value}%", value)
        self.scale.setCurrentIndex(
            max(
                0,
                self.scale.findData(int(self._settings.value("accessibility/control_scale", 100))),
            )
        )
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
        self.security_panel = SecurityPanel(self)
        self.tabs.addTab(self.model_panel, "Model Backend")
        self.tabs.addTab(self.color_panel, "Color")
        self.tabs.addTab(self.accessibility_panel, "Accessibility")
        self.tabs.addTab(self.security_panel, "Security")
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        self.model_panel.apply()
        self.color_panel.apply()
        self.accessibility_panel.apply()
        self.security_panel.apply()
        self.accept()
