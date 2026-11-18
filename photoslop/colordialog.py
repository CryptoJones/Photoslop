# SPDX-License-Identifier: Apache-2.0
"""Color management dialogs (#108): a profile picker (presets + .icc
browse), session Color Settings, and Color Swatch palette dialogs (#421)."""

from __future__ import annotations

from PySide6.QtGui import QColor, QColorSpace
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from photoslop import color
from photoslop.swatches import (
    SwatchesWidget,
)


class _ProfileRow(QHBoxLayout):
    """Combo of presets + (none) + Browse…; .space() yields the choice."""

    def __init__(self, allow_none: bool = True) -> None:
        super().__init__()
        self.combo = QComboBox()
        if allow_none:
            self.combo.addItem("(none)")
        for name in color.PRESETS:
            self.combo.addItem(name)
        self._file: str | None = None
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        self.addWidget(self.combo, 1)
        self.addWidget(browse)

    def _browse(self) -> None:
        path, _f = QFileDialog.getOpenFileName(
            None, "Choose ICC profile", "", "ICC profiles (*.icc *.icm)"
        )
        if path:
            self._file = path
            self.combo.addItem(path)
            self.combo.setCurrentIndex(self.combo.count() - 1)

    def space(self) -> QColorSpace | None:
        text = self.combo.currentText()
        if text == "(none)":
            return None
        return color.load_space(text)


class ProfilePickerDialog(QDialog):
    """Pick one profile (Assign / Convert)."""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        self.row = _ProfileRow(allow_none=False)
        form.addRow("Profile", self.row)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def space(self) -> QColorSpace | None:
        try:
            return self.row.space()
        except ValueError:
            return None


class ColorSettingsPanel(QWidget):
    """Session display/proof profile chooser — feeds photoslop.color.settings.
    Embeddable (Preferences tab) or wrapped in ColorSettingsDialog. Call
    apply() to commit the chosen profiles."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 0, 0, 0)  # sit flush inside a tab
        form.addRow(QLabel("Display transform and soft-proof apply to the viewport only (DD-004)."))
        self.display_row = _ProfileRow()
        self.proof_row = _ProfileRow()
        form.addRow("Monitor profile", self.display_row)
        form.addRow("Proof profile", self.proof_row)

    def apply(self) -> None:
        try:
            color.settings["display"] = self.display_row.space()
            color.settings["proof"] = self.proof_row.space()
        except ValueError:
            pass


class ColorSettingsDialog(QDialog):
    """Standalone Color Settings window wrapping ColorSettingsPanel."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Color Settings")
        layout = QVBoxLayout(self)
        self.panel = ColorSettingsPanel(self)
        layout.addWidget(self.panel)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        self.panel.apply()
        self.accept()


class ColorWithSwatchesDialog(QDialog):
    """Color picker dialog with tabbed palette swatches (#421)."""

    def __init__(
        self,
        initial_color: QColor | None = None,
        parent=None,
        title: str = "Color Picker",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(380, 440)
        self._color = initial_color or QColor(0, 0, 0)

        layout = QVBoxLayout(self)
        self.swatches_widget = SwatchesWidget(parent=self)
        self.swatches_widget.colorSelected.connect(self._on_swatch_selected)
        layout.addWidget(self.swatches_widget)

        # Custom color button
        btn_row = QHBoxLayout()
        self.custom_btn = QPushButton("Custom Color…")
        self.custom_btn.clicked.connect(self._pick_custom)
        btn_row.addWidget(self.custom_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_swatch_selected(self, color: QColor, is_foreground: bool) -> None:
        self._color = color

    def _pick_custom(self) -> None:
        chosen = QColorDialog.getColor(self._color, self, "Custom Color")
        if chosen.isValid():
            self._color = chosen

    def color(self) -> QColor:
        return self._color


def get_color_with_swatches(
    initial: QColor | None = None, parent=None, title: str = "Choose Color"
) -> QColor | None:
    dlg = ColorWithSwatchesDialog(initial, parent=parent, title=title)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.color()
    return None
