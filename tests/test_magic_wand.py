# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


class _Mods:
    def __init__(self, mods):
        self._m = mods

    def modifiers(self):
        return self._m


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(100, 80), 72.0, "w", QColor(255, 255, 255))
    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(10, 10, 30, 20), QColor(255, 0, 0))
    p.fillRect(QRect(60, 40, 20, 20), QColor(255, 0, 0))
    p.end()
    win.add_document(doc)
    return win


def test_mask_to_path_runs(qapp):
    mask = np.zeros((6, 6), dtype=bool)
    mask[1:3, 1:5] = True
    path = npimage.mask_to_path(mask, QPoint(10, 20))
    assert path.boundingRect().toAlignedRect() == QRect(11, 21, 4, 2)


def test_wand_selects_contiguous_region(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["wand"]
    win.options.tolerance = 0

    tool.press(doc, editor.canvas, QPointF(15, 15), None)
    assert doc.selection_bounds() == QRect(10, 10, 30, 20)  # only the first box

    # delete-selection integration: clears just the selected region
    win.action_delete_selection()
    img = doc.active_layer.image
    assert img.pixelColor(15, 15).alpha() == 0
    assert img.pixelColor(65, 45) == QColor(255, 0, 0)  # second box untouched


def test_wand_shift_adds_alt_subtracts(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["wand"]
    win.options.tolerance = 0

    tool.press(doc, editor.canvas, QPointF(15, 15), None)
    tool.press(doc, editor.canvas, QPointF(65, 45),
               _Mods(Qt.KeyboardModifier.ShiftModifier))
    bounds = doc.selection_bounds()
    assert bounds == QRect(10, 10, 70, 50)  # union spans both boxes

    tool.press(doc, editor.canvas, QPointF(65, 45),
               _Mods(Qt.KeyboardModifier.AltModifier))
    assert doc.selection_bounds() == QRect(10, 10, 30, 20)  # back to box one


def test_flood_fill_still_fills_after_refactor(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    img = doc.active_layer.image
    dirty = npimage.flood_fill(img, 15, 15, npimage.premultiplied_u32(0, 0, 255, 255), 0)
    assert dirty == QRect(10, 10, 30, 20)
    assert img.pixelColor(15, 15) == QColor(0, 0, 255)
