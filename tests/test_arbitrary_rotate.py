# SPDX-License-Identifier: Apache-2.0
import math

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.commands import ArbitraryRotateCommand
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp, w=80, h=40) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(w, h), 72.0, "r", QColor(0, 128, 255)))
    return win


def test_rotate_90_via_arbitrary_swaps_dimensions(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    doc.add_guide("h", 10.0)

    doc.undo_stack.push(ArbitraryRotateCommand(doc, 90.0))
    assert doc.size == QSize(40, 80)
    assert doc.layers[0].image.size() == QSize(40, 80)
    assert doc.layers[0].offset.x() == 0 and doc.layers[0].offset.y() == 0
    assert doc.guides_h == [] and doc.guides_v == []
    assert doc.flatten().pixelColor(20, 40) == QColor(0, 128, 255)


def test_rotate_30_bounding_box_and_exact_undo(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    doc.add_guide("v", 33.0)
    before = doc.layers[0].image.copy()

    doc.undo_stack.push(ArbitraryRotateCommand(doc, 30.0))
    rad = math.radians(30.0)
    expected_w = round(80 * math.cos(rad) + 40 * math.sin(rad))
    expected_h = round(80 * math.sin(rad) + 40 * math.cos(rad))
    assert abs(doc.size.width() - expected_w) <= 1
    assert abs(doc.size.height() - expected_h) <= 1

    doc.undo_stack.undo()
    assert doc.size == QSize(80, 40)
    assert doc.layers[0].image == before  # ref-restore, no second resample
    assert doc.guides_v == [33.0]

    doc.undo_stack.redo()  # cached state reapplies without recompute
    assert abs(doc.size.width() - expected_w) <= 1
