# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop.commands import SetGroupPropsCommand
from photoslop.document import Document
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    """White background + a group of two OVERLAPPING opaque red chips."""
    win = MainWindow()
    doc = Document.new(QSize(80, 60), 72.0, "gc", QColor(255, 255, 255))
    for name, offset in (("a", QPoint(10, 10)), ("b", QPoint(25, 10))):
        layer = Layer.blank(name, QSize(30, 20), offset)
        layer.image.fill(QColor(255, 0, 0))
        layer.group = "Group 1"
        doc.layers.append(layer)
    doc.active_index = 2
    win.add_document(doc)
    return win


def test_group_opacity_blends_as_one_unit(qapp):
    win = make_window(qapp)
    doc = win.current_doc()

    doc.undo_stack.push(SetGroupPropsCommand(
        doc, "Group 1", {"opacity": 0.5, "blend_mode": "normal"}))
    flat = doc.flatten()
    # the overlap region (x 25..40) must blend ONCE at 50% — red over white
    # at half strength = (255, 128, 128), same as the non-overlap region
    overlap = flat.pixelColor(30, 20)
    single = flat.pixelColor(15, 20)
    assert abs(overlap.green() - 128) <= 3
    assert abs(single.green() - 128) <= 3
    assert overlap.green() == single.green()  # no double-blending in overlap
    assert doc.sample_color(30, 20).green() == overlap.green()

    doc.undo_stack.undo()
    assert doc.flatten().pixelColor(30, 20) == QColor(255, 0, 0)  # back to opaque


def test_defaults_return_to_fast_path(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    assert not doc.needs_offscreen()
    doc.undo_stack.push(SetGroupPropsCommand(
        doc, "Group 1", {"opacity": 0.7, "blend_mode": "normal"}))
    assert doc.needs_offscreen()
    doc.undo_stack.push(SetGroupPropsCommand(doc, "Group 1", None))
    assert not doc.needs_offscreen()
    assert doc.flatten().pixelColor(30, 20) == QColor(255, 0, 0)
