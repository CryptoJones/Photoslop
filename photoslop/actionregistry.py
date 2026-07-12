# SPDX-License-Identifier: Apache-2.0
"""Central command metadata, prerequisite state, and searchable palette."""

from __future__ import annotations

import re
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


@dataclass(frozen=True)
class ActionSpec:
    command_id: str
    label: str
    shortcut: str
    help_text: str
    prerequisite: str = "always"


class ActionRegistry:
    def __init__(self, host) -> None:
        self.host = host
        self.entries: dict[str, tuple[ActionSpec, QAction]] = {}

    def register(self, action: QAction, label: str, shortcut: str | None,
                 slot, prerequisite: str | None = None) -> ActionSpec:
        base = getattr(slot, "__name__", "command").removeprefix("action_")
        command_id = re.sub(r"[^a-z0-9]+", ".", base.lower()).strip(".")
        if command_id in self.entries:
            command_id += "." + re.sub(r"[^a-z0-9]+", ".", label.lower()).strip(".")
        clean = label.replace("&", "").replace("…", "")
        required = prerequisite or self._infer(base)
        spec = ActionSpec(command_id, clean, shortcut or "", action.toolTip() or clean, required)
        action.setData(command_id)
        self.entries[command_id] = (spec, action)
        return spec

    @staticmethod
    def _infer(name: str) -> str:
        if any(token in name for token in ("new", "open", "about", "preferences",
                                           "quit", "workspace")):
            return "always"
        if any(token in name for token in ("paste",)):
            return "clipboard"
        if any(token in name for token in ("deselect", "feather", "refine",
                                           "content_aware_fill")):
            return "selection"
        return "document"

    def update(self) -> None:
        doc = self.host.current_doc()
        editor = self.host.current_editor()
        context = {
            "always": True,
            "document": doc is not None,
            "layer": doc is not None and doc.active_layer is not None,
            "selection": doc is not None and doc.selection is not None,
            "clipboard": bool(self.host.pixel_clip or self.host.layer_clip),
            "idle": not bool(getattr(editor, "task_active", False)),
        }
        for spec, action in self.entries.values():
            action.setEnabled(context.get(spec.prerequisite, True))

    def palette(self, parent=None) -> CommandPalette:
        self.update()
        return CommandPalette(self, parent)


class CommandPalette(QDialog):
    def __init__(self, registry: ActionRegistry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.setWindowTitle("Command Palette")
        self.resize(520, 420)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search commands…")
        self.search.setAccessibleName("Search commands")
        self.results = QListWidget()
        self.results.setAccessibleName("Matching commands")
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.search)
        layout.addWidget(self.results, 1)
        layout.addWidget(self.explanation)
        self.search.textChanged.connect(self.refresh)
        self.results.currentItemChanged.connect(self._describe)
        self.results.itemActivated.connect(self._activate)
        self.refresh()

    def refresh(self, query: str = "") -> None:
        needle = query.casefold().strip()
        self.results.clear()
        for spec, action in sorted(self.registry.entries.values(),
                                   key=lambda item: item[0].label):
            haystack = f"{spec.label} {spec.command_id} {spec.shortcut}".casefold()
            if needle and needle not in haystack:
                continue
            suffix = f"    {spec.shortcut}" if spec.shortcut else ""
            item = QListWidgetItem(spec.label + suffix)
            item.setData(Qt.ItemDataRole.UserRole, spec.command_id)
            if not action.isEnabled():
                item.setForeground(self.palette().color(self.palette().ColorGroup.Disabled,
                                                        self.palette().ColorRole.Text))
            self.results.addItem(item)
        if self.results.count():
            self.results.setCurrentRow(0)

    def _describe(self, item, _previous=None) -> None:
        if item is None:
            self.explanation.clear()
            return
        spec, action = self.registry.entries[item.data(Qt.ItemDataRole.UserRole)]
        state = "Available" if action.isEnabled() else f"Requires {spec.prerequisite}"
        self.explanation.setText(f"{state} — {spec.help_text}")

    def _activate(self, item) -> None:
        _spec, action = self.registry.entries[item.data(Qt.ItemDataRole.UserRole)]
        if action.isEnabled():
            action.trigger()
            self.accept()
