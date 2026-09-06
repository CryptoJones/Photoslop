# SPDX-License-Identifier: Apache-2.0
"""Edit ▸ Fill Selection (#393).

The desktop half of the operator's iPhone report. Fill Layer deliberately
ignores the selection (`test_fill_layer_credits`) and the bucket floods a
region of similar colour from a click; neither one paints a lasso shape flat.
"""

from PySide6.QtCore import QRectF, QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def _window(qapp, size=None):
    win = MainWindow()
    win.add_document(Document.new(size or QSize(40, 40), 72.0, "fs", QColor(255, 255, 255)))
    win.options.foreground = QColor(10, 40, 220)
    return win, win.current_doc()


def _select(doc, x, y, w, h):
    path = QPainterPath()
    path.addRect(QRectF(x, y, w, h))
    doc.set_selection(path)


def test_fill_selection_paints_the_selection_and_leaves_the_rest(qapp):
    win, doc = _window(qapp)
    _select(doc, 5, 5, 10, 10)

    win.action_fill_selection()

    layer = doc.active_layer
    assert layer.image.pixelColor(6, 6) == QColor(10, 40, 220)
    assert layer.image.pixelColor(14, 14) == QColor(10, 40, 220)  # the far corner
    assert layer.image.pixelColor(25, 25) == QColor(255, 255, 255)  # outside stays
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert layer.image.pixelColor(6, 6) == QColor(255, 255, 255)


def test_fill_selection_without_a_selection_does_nothing(qapp):
    win, doc = _window(qapp)
    win.action_fill_selection()
    assert doc.undo_stack.count() == 0
    assert doc.active_layer.image.pixelColor(6, 6) == QColor(255, 255, 255)


def test_fill_selection_fades_over_a_feathered_edge(qapp):
    win, doc = _window(qapp, QSize(64, 64))
    win.options.foreground = QColor(0, 0, 0)
    _select(doc, 20, 20, 24, 24)
    doc.selection_feather = 6

    win.action_fill_selection()

    image = doc.active_layer.image
    middle = image.pixelColor(32, 32).red()
    edge = image.pixelColor(20, 32).red()
    assert middle < 15, "the middle of a feathered selection still fills"
    assert middle < edge < 255, f"the ramp neither filled nor skipped: {edge}"
    assert image.pixelColor(2, 2) == QColor(255, 255, 255), "beyond the ramp is untouched"
