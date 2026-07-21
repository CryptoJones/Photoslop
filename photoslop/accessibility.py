# SPDX-License-Identifier: Apache-2.0
"""Cross-platform accessibility semantics, announcements, and preferences."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListView,
    QSlider,
    QSpinBox,
    QWidget,
)


class AccessibilityController(QObject):
    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def apply(self) -> None:
        settings = self.window.settings
        high_contrast = str(settings.value(
            "accessibility/high_contrast", "false")).lower() == "true"
        reduced_motion = str(settings.value(
            "accessibility/reduced_motion", "false")).lower() == "true"
        scale = max(100, min(200, int(settings.value(
            "accessibility/control_scale", 100))))
        self.window.setProperty("reducedMotion", reduced_motion)
        self.window.setProperty("highContrast", high_contrast)
        self.window.setProperty("controlScale", scale)
        self.window.setStyleSheet(self._stylesheet(high_contrast, scale))
        self._polish_subtree(self.window)
        for editor_index in range(self.window.tabs.count()):
            editor = self.window.tabs.widget(editor_index)
            editor.canvas.set_accessibility_preferences(
                high_contrast=high_contrast,
                reduced_motion=reduced_motion,
                scale=scale,
            )

    def eventFilter(self, obj, event) -> bool:
        if (event.type() in {QEvent.Type.Polish, QEvent.Type.Show}
                and isinstance(obj, QWidget)):
            self._polish_subtree(obj)
        return False

    def _polish_subtree(self, root: QWidget) -> None:
        self._polish_widget(root)
        for widget in root.findChildren(QWidget):
            self._polish_widget(widget)

    def _polish_widget(self, widget: QWidget) -> None:
        if not widget.accessibleName():
            name = self._inferred_name(widget)
            if name:
                widget.setAccessibleName(name)
        if not widget.accessibleDescription() and widget.toolTip():
            widget.setAccessibleDescription(widget.toolTip())

    @staticmethod
    def _inferred_name(widget: QWidget) -> str:
        name = widget.toolTip() or widget.windowTitle()
        if isinstance(widget, QAbstractButton):
            name = name or widget.text().replace("&", "")
        elif isinstance(widget, QLineEdit):
            name = name or widget.placeholderText()
        elif isinstance(widget, QLabel):
            name = name or widget.text().replace("&", "")
        if name:
            return name
        parent = widget.parentWidget()
        layout = parent.layout() if parent is not None else None
        if isinstance(layout, QFormLayout):
            label = layout.labelForField(widget)
            if isinstance(label, QLabel):
                return label.text().replace("&", "")
        if isinstance(widget, QComboBox):
            return "Options"
        if isinstance(widget, QSpinBox):
            return "Numeric value"
        if isinstance(widget, QSlider):
            return "Value"
        if isinstance(widget, QListView):
            return "Items"
        return ""

    @staticmethod
    def _stylesheet(high_contrast: bool, scale: int) -> str:
        factor = max(100, scale) / 100
        minimum = round(24 * factor)
        indicator = round(16 * factor)
        handle = round(16 * factor)
        base_font = QApplication.font().pointSizeF()
        font_size = max(9.0, base_font if base_font > 0 else 9.0) * factor
        rules = [
            f"QWidget {{ font-size: {font_size:.2f}pt; }}",
            "QToolButton, QPushButton, QComboBox, QSpinBox, QLineEdit "
            f"{{ min-height: {minimum}px; }}",
            f"QListView::item {{ min-height: {minimum}px; }}",
            "QCheckBox::indicator, QRadioButton::indicator "
            f"{{ width: {indicator}px; height: {indicator}px; }}",
            f"QSlider::handle:horizontal {{ width: {handle}px; margin: -6px 0; }}",
            f"QSlider::handle:vertical {{ height: {handle}px; margin: 0 -6px; }}",
        ]
        if high_contrast:
            rules.extend([
                "QWidget { color: #fff; background: #000; }",
                "QWidget:focus { border: 3px solid #ff0; }",
                "QToolButton:checked, QPushButton:checked { "
                "background: #06f; border: 3px double #fff; }",
                "QLineEdit, QComboBox, QSpinBox, QListView { "
                "selection-color: #000; selection-background-color: #ff0; }",
                "QToolTip { color: #000; background: #ff0; border: 2px solid #fff; }",
            ])
        return "\n".join(rules)

    def announce(self, message: str) -> None:
        if not message:
            return
        event = QAccessibleAnnouncementEvent(self.window.statusBar(), message)
        event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
        QAccessible.updateAccessibility(event)


def app_accessibility_active() -> bool:
    return QApplication.instance() is not None and QAccessible.isActive()
