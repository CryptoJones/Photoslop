# SPDX-License-Identifier: Apache-2.0
"""Dirty tracking, stable identities, and async revision guards."""

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import Layer
from photoslop.layerpanel import LayerPanel
from photoslop.propertiespanel import PropertiesPanel


def _document() -> Document:
    return Document.new(QSize(40, 30), 72.0, "integrity", QColor("white"))


def test_properties_panel_edits_are_dirty_mergeable_and_undoable(qapp):
    doc = _document()
    panel = PropertiesPanel()
    panel.set_document(doc)

    panel.opacity.setValue(60)
    panel.opacity.setValue(40)

    assert doc.active_layer.opacity == 0.4
    assert doc.is_dirty()
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.active_layer.opacity == 1.0
    assert not doc.is_dirty()
    doc.undo_stack.redo()
    assert doc.active_layer.opacity == 0.4


def test_layer_panel_visibility_and_name_use_undo_stack(qapp):
    doc = _document()
    panel = LayerPanel()
    panel.set_document(doc)
    item = panel.list.item(0)

    item.setCheckState(Qt.CheckState.Unchecked)
    assert not doc.active_layer.visible
    assert doc.is_dirty()
    doc.undo_stack.undo()
    assert doc.active_layer.visible

    item = panel.list.item(0)
    item.setText("Renamed")
    assert doc.active_layer.name == "Renamed"
    doc.undo_stack.undo()
    assert doc.active_layer.name == "Background"


def test_document_revision_rejects_every_relevant_stale_state(qapp):
    doc = _document()
    layer = doc.active_layer
    current = doc.capture_revision()
    assert doc.accepts_revision(current, layer)

    doc.notify_pixels(QRect(0, 0, 1, 1))
    assert not doc.accepts_revision(current, layer)

    current = doc.capture_revision()
    doc.notify_structure()
    assert not doc.accepts_revision(current, layer)

    current = doc.capture_revision()
    doc.set_selection(None)
    assert not doc.accepts_revision(current, layer)

    current = doc.capture_revision()
    detached = Layer.blank("Detached", QSize(2, 2))
    assert not doc.accepts_revision(current, detached)

    doc.close()
    assert not doc.accepts_revision(doc.capture_revision(), layer)


def test_layer_identity_round_trips_and_snapshot_clone_can_preserve_it(qapp, tmp_path):
    doc = _document()
    layer_id = doc.active_layer.id
    assert doc.active_layer.clone().id != layer_id
    assert doc.active_layer.clone(preserve_id=True).id == layer_id

    path = str(tmp_path / "identity.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.active_layer.id == layer_id
