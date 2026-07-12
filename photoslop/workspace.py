# SPDX-License-Identifier: Apache-2.0
"""Saved dock/layout state and current-screen geometry validation."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QGuiApplication


class WorkspaceController:
    def __init__(self, window, settings) -> None:
        self.window = window
        self.settings = settings
        self.default_state = window.saveState()

    def restore_startup(self) -> None:
        state = self.settings.value("workspace/state")
        if state is not None:
            self.window.restoreState(state)
        geometry = self.settings.value("workspace/geometry")
        if geometry is not None:
            self.window.restoreGeometry(geometry)
        QTimer.singleShot(0, self.validate_geometry)

    def save(self) -> None:
        self.settings.setValue("workspace/state", self.window.saveState())
        self.settings.setValue("workspace/geometry", self.window.saveGeometry())

    def restore(self) -> bool:
        state = self.settings.value("workspace/state")
        if state is None:
            return False
        self.window.restoreState(state)
        self.validate_geometry()
        return True

    def reset(self) -> None:
        self.window.restoreState(self.default_state)

    def validate_geometry(self) -> None:
        frame = self.window.frameGeometry()
        if any(screen.availableGeometry().intersects(frame)
               for screen in QGuiApplication.screens()):
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.window.resize(min(1280, available.width()), min(800, available.height()))
        self.window.move(available.center() - self.window.rect().center())
