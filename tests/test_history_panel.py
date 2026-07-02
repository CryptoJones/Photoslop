# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_history_panel_tracks_and_navigates(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(30, 30), 72.0, "h", QColor(255, 255, 255)))
    doc = win.current_doc()

    win.layer_panel.add_layer()
    win.layer_panel.add_layer()
    assert len(doc.layers) == 3

    # QUndoView renders the active stack of the group: empty label + 2 commands
    model = win.history_view.model()
    assert model.rowCount() == 3
    assert win.history_view.group() is win.undo_group
    assert win.undo_group.activeStack() is doc.undo_stack

    # jumping in history applies the state (what a click on the view does)
    doc.undo_stack.setIndex(1)
    assert len(doc.layers) == 2
    doc.undo_stack.setIndex(2)
    assert len(doc.layers) == 3
    doc.undo_stack.setIndex(0)
    assert len(doc.layers) == 1


def test_history_panel_follows_active_document(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "a", QColor(255, 255, 255)))
    win.layer_panel.add_layer()
    win.add_document(Document.new(QSize(20, 20), 72.0, "b", QColor(255, 255, 255)))

    # switching tabs re-targets the group and therefore the view
    assert win.undo_group.activeStack() is win.current_doc().undo_stack
    assert win.history_view.model().rowCount() == 1  # doc b: just the empty label
    win.tabs.setCurrentIndex(0)
    assert win.history_view.model().rowCount() == 2  # doc a: label + Add Layer
