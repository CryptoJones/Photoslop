# SPDX-License-Identifier: Apache-2.0
"""Cross-platform accessibility naming, announcements, and visual preferences."""

from __future__ import annotations

from PySide6.QtGui import QAccessible, QAccessibleAnnouncementEvent
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget


class AccessibilityController:
    def __init__(self, window) -> None:
        self.window = window

    def apply(self) -> None:
        settings = self.window.settings
        high_contrast = str(settings.value(
            "accessibility/high_contrast", "false")).lower() == "true"
        reduced_motion = str(settings.value(
            "accessibility/reduced_motion", "false")).lower() == "true"
        scale = int(settings.value("accessibility/control_scale", 100))
        self.window.setProperty("reducedMotion", reduced_motion)
        self.window.setStyleSheet(self._stylesheet(high_contrast, scale))
        for widget in self.window.findChildren(QWidget):
            if not widget.accessibleName():
                name = widget.toolTip() or widget.windowTitle()
                if isinstance(widget, QAbstractButton):
                    name = name or widget.text().replace("&", "")
                if name:
                    widget.setAccessibleName(name)
        for editor_index in range(self.window.tabs.count()):
            editor = self.window.tabs.widget(editor_index)
            editor.canvas._ants.setInterval(1000 if reduced_motion else 120)

    @staticmethod
    def _stylesheet(high_contrast: bool, scale: int) -> str:
        minimum = round(24 * max(100, scale) / 100)
        rules = [f"QToolButton, QPushButton, QComboBox, QSpinBox {{ min-height: {minimum}px; }}"]
        if high_contrast:
            rules.append(
                "QWidget { color: #fff; background: #000; } "
                "QWidget:focus { border: 3px solid #ff0; } "
                "QToolButton:checked, QPushButton:checked { background: #06f; }"
            )
        return "\n".join(rules)

    def announce(self, message: str) -> None:
        if not message:
            return
        event = QAccessibleAnnouncementEvent(self.window.statusBar(), message)
        event.setPoliteness(QAccessible.AnnouncementPoliteness.Polite)
        QAccessible.updateAccessibility(event)


def app_accessibility_active() -> bool:
    return QApplication.instance() is not None and QAccessible.isActive()
