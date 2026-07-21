# SPDX-License-Identifier: Apache-2.0
"""Action prerequisites, command search, Properties, and responsive options."""

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def _window(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(80, 60), 72, "actions", QColor("white")))
    return win


def test_registry_drives_document_prerequisites(qapp):
    win = MainWindow()
    win.action_registry.update()
    document_actions = [
        action
        for spec, action in win.action_registry.entries.values()
        if spec.prerequisite == "document"
    ]
    assert document_actions and all(not action.isEnabled() for action in document_actions)
    win.add_document(Document.new(QSize(20, 20), 72, "doc", QColor("white")))
    assert all(action.isEnabled() for action in document_actions)


def test_command_palette_searches_metadata_and_explains_state(qapp):
    win = MainWindow()
    palette = win.action_registry.palette(win)
    palette.refresh("preferences")
    assert palette.results.count() == 1
    assert "Preferences" in palette.results.item(0).text()
    assert "Available" in palette.explanation.text()
    palette.refresh("crop")
    assert palette.results.count() >= 1
    assert "Requires document" in palette.explanation.text()


def test_properties_panel_tracks_and_edits_active_layer(qapp):
    win = _window(qapp)
    panel = win.properties_panel
    layer = win.current_doc().active_layer
    assert panel.name.text() == layer.name
    panel.name.setText("Renamed")
    panel.opacity.setValue(55)
    panel.apply()
    assert layer.name == "Renamed"
    assert layer.opacity == 0.55


def test_contextual_options_have_labels_units_and_reset(qapp):
    win = _window(qapp)
    assert win._tool_name_label.text() == "Brush"
    assert win._size_spin.accessibleName() == "Size in pixels"
    win._size_spin.setValue(91)
    win._reset_tool_options()
    assert win._size_spin.value() == 16


def test_workspace_geometry_recovery_uses_current_screen(qapp):
    win = MainWindow()
    win.setGeometry(QRect(100000, 100000, 400, 300))
    win._validate_workspace_geometry()
    assert any(
        screen.availableGeometry().intersects(win.frameGeometry()) for screen in qapp.screens()
    )


def test_registered_shortcuts_are_unique_and_keep_escape_for_canvas(qapp):
    win = _window(qapp)
    shortcuts: dict[str, list[str]] = {}
    for spec, _action in win.action_registry.entries.values():
        if spec.shortcut:
            shortcuts.setdefault(spec.shortcut, []).append(spec.command_id)
    assert {key: commands for key, commands in shortcuts.items() if len(commands) > 1} == {}
    assert win.action_registry.entries["export"][0].shortcut == "Ctrl+Alt+Shift+S"
    assert win.action_registry.entries["cancel.tasks"][0].shortcut == "Ctrl+Esc"
    assert "Esc" not in shortcuts
