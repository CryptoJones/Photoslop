# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop import npimage
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(80, 40), 72.0, "fe", QColor(200, 200, 200)))
    return win


def select_left_half(doc):
    path = QPainterPath()
    path.addRect(QRect(0, 0, 40, 40))
    doc.set_selection(path)


def darken(img, mask):
    import numpy as np

    from photoslop.npimage import view_u32

    arr = view_u32(img)
    dark = np.uint32(0xFF202020)
    if mask is None:
        arr[:] = dark
    else:
        arr[mask] = dark


def test_feathered_filter_blends_softly(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    select_left_half(doc)
    doc.selection_feather = 12.0

    win._run_filter("Darken", lambda img, m: darken(img, m))
    img = doc.active_layer.image
    deep_in = img.pixelColor(5, 20).red()
    near_edge_in = img.pixelColor(37, 20).red()
    near_edge_out = img.pixelColor(43, 20).red()
    deep_out = img.pixelColor(75, 20).red()
    assert deep_in < 60  # fully darkened well inside
    assert deep_out > 190  # untouched far outside
    assert deep_in < near_edge_in < near_edge_out < deep_out  # smooth ramp

    doc.undo_stack.undo()
    assert img.pixelColor(37, 20) == QColor(200, 200, 200)


def test_feather_resets_with_new_selection(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    select_left_half(doc)
    doc.selection_feather = 10.0
    select_left_half(doc)  # replacing the selection clears the feather
    assert doc.selection_feather == 0.0

    weights = npimage.feathered_weights(doc.selection, QSize(80, 40),
                                        doc.layers[0].offset, 8.0)
    assert weights[20, 5] > 0.95 and weights[20, 75] < 0.05
    assert 0.2 < weights[20, 40] < 0.8  # gradient at the boundary
