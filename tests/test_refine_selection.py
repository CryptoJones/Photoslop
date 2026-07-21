# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop import npimage
from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.refinedialog import RefineSelectionDialog


def rect_mask(w=60, h=40, rect=(20, 10, 20, 20)):
    mask = np.zeros((h, w), dtype=bool)
    x, y, rw, rh = rect
    mask[y : y + rh, x : x + rw] = True
    return mask


def test_expand_and_contract_are_exact(qapp):
    grown = npimage.refine_mask(rect_mask(), expand=3)
    ys, xs = np.nonzero(grown)
    assert (xs.min(), ys.min(), xs.max(), ys.max()) == (17, 7, 42, 32)

    shrunk = npimage.refine_mask(rect_mask(), expand=-2)
    ys, xs = np.nonzero(shrunk)
    assert (xs.min(), ys.min(), xs.max(), ys.max()) == (22, 12, 37, 27)


def test_smooth_fills_notch(qapp):
    mask = rect_mask()
    mask[10:16, 28:32] = False  # a notch cut into the top edge
    smoothed = npimage.refine_mask(mask, smooth=4)
    assert smoothed[12, 30]  # notch healed
    # and the overall extent stays put
    ys, xs = np.nonzero(smoothed)
    assert xs.min() >= 19 and xs.max() <= 40


def test_dialog_ok_applies_cancel_restores(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(60, 40), 72.0, "r", QColor(255, 255, 255)))
    doc = win.current_doc()
    path = QPainterPath()
    path.addRect(QRect(20, 10, 20, 20))
    doc.set_selection(path)

    dialog = RefineSelectionDialog(doc, win)
    dialog.expand.setValue(5)
    dialog._debounce.stop()
    dialog.accept()
    assert doc.selection_bounds() == QRect(15, 5, 30, 30)

    original = doc.selection
    dialog = RefineSelectionDialog(doc, win)
    dialog.expand.setValue(-40)  # collapses to nothing in preview
    dialog._debounce.stop()
    dialog._preview()
    assert doc.selection is None
    dialog.reject()
    assert doc.selection is original  # cancel restores the exact path
