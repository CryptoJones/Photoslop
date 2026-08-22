# SPDX-License-Identifier: Apache-2.0
"""The layer list's own right-click menu. Its reason to exist is the import:
"New Layer from Image…" otherwise lives only under the Layer menu, which is
not where anyone looks while already pointing at the layer stack."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 30), 72.0, "c", QColor(255, 255, 255)))
    return win


def entries(panel) -> dict:
    return {a.text(): a for a in panel.context_menu().actions() if a.text()}


def test_context_menu_offers_the_stack_operations(qapp):
    win = make_window(qapp)
    assert list(entries(win.layer_panel)) == [
        "New Layer",
        "New Layer from Image…",
        "Duplicate Layer",
        "Delete Layer",
        "Merge Down",
    ]


def test_context_menu_import_reaches_the_window_action(qapp, monkeypatch):
    win = make_window(qapp)
    called = []
    monkeypatch.setattr(win, "action_import_layer", lambda: called.append("window"))
    win.layer_panel.importRequested.disconnect()
    win.layer_panel.importRequested.connect(win.action_import_layer)

    entries(win.layer_panel)["New Layer from Image…"].trigger()
    assert called == ["window"]


def test_destructive_entries_disable_on_a_single_layer_document(qapp):
    win = make_window(qapp)
    actions = entries(win.layer_panel)
    assert actions["Delete Layer"].isEnabled() is False  # the last layer stays
    assert actions["Merge Down"].isEnabled() is False  # nothing below it
    assert actions["Duplicate Layer"].isEnabled() is True

    win.layer_panel.add_layer()
    actions = entries(win.layer_panel)
    assert actions["Delete Layer"].isEnabled() is True
    assert actions["Merge Down"].isEnabled() is True


def test_new_layer_entry_actually_adds_a_layer(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    entries(win.layer_panel)["New Layer"].trigger()
    assert len(doc.layers) == 2


def test_context_menu_is_silent_without_a_document(qapp):
    panel = make_window(qapp).layer_panel
    panel.doc = None
    assert panel.context_menu() is None
