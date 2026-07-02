# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(20, 20), 72.0, "m", QColor(200, 200, 200))
    hidden = Layer.blank("hidden", QSize(20, 20))
    hidden.image.fill(QColor(0, 255, 0))
    hidden.visible = False
    doc.layers.append(hidden)
    top = Layer.blank("top", QSize(20, 20))
    top.image.fill(QColor(128, 128, 128))
    top.blend_mode = "multiply"
    doc.layers.append(top)
    doc.active_index = 2
    win.add_document(doc)
    return win


def test_merge_visible_keeps_hidden_and_composites(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    names_before = [layer.name for layer in doc.layers]

    win.action_merge_visible()
    assert [layer.name for layer in doc.layers] == ["Merged", "hidden"]
    merged = doc.layers[0]
    expected = 200 * 128 // 255  # multiply baked in
    assert abs(merged.image.pixelColor(5, 5).red() - expected) <= 2
    assert merged.blend_mode == "normal" and merged.opacity == 1.0

    doc.undo_stack.undo()
    assert [layer.name for layer in doc.layers] == names_before
    assert doc.layers[1].visible is False
    doc.undo_stack.redo()
    assert len(doc.layers) == 2


def test_merge_visible_needs_two(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(10, 10), 72.0, "one", QColor(255, 0, 0)))
    doc = win.current_doc()
    win.action_merge_visible()
    assert doc.undo_stack.count() == 0  # refused, nothing pushed


def test_stamp_visible_adds_composite_on_top(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    win.action_stamp_visible()

    assert len(doc.layers) == 4
    stamp = doc.layers[-1]
    assert stamp.name == "Stamp"
    expected = 200 * 128 // 255
    assert abs(stamp.image.pixelColor(5, 5).red() - expected) <= 2
    # originals untouched
    assert [layer.name for layer in doc.layers[:3]] == ["Background", "hidden", "top"]

    doc.undo_stack.undo()
    assert len(doc.layers) == 3
