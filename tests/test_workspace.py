# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "w", QColor(255, 255, 255)))
    return win


def test_workspace_save_restore_reset(qapp):
    win = make_window(qapp)
    win.settings.remove("workspace/state")

    default = bytes(win._default_workspace)
    win._history_dock.raise_()  # mutate the layout: History tab on top
    mutated = bytes(win.saveState())
    assert mutated != default

    win.save_workspace()
    assert win.settings.value("workspace/state") is not None

    win.reset_workspace()
    assert bytes(win.saveState()) == default

    win.restore_workspace()
    assert bytes(win.saveState()) == mutated

    win.settings.remove("workspace/state")
    win.settings.remove("workspace/geometry")


def test_saved_workspace_applies_at_startup(qapp):
    first = make_window(qapp)
    first.settings.remove("workspace/state")
    first._adjust_dock.raise_()
    first.save_workspace()
    layout = bytes(first.saveState())

    second = make_window(qapp)  # fresh window picks up the saved layout
    assert bytes(second.saveState()) == layout

    second.settings.remove("workspace/state")
    second.settings.remove("workspace/geometry")
