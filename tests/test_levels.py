# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.adjust import apply_luts, levels_lut
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.levelsdialog import LevelsDialog
from photoslop.mainwindow import MainWindow


def test_levels_lut_math(qapp):
    identity = levels_lut(0, 255, 1.0)
    assert (identity == np.arange(256)).all()

    stretched = levels_lut(50, 200, 1.0)
    assert stretched[50] == 0 and stretched[200] == 255
    assert stretched[125] == 128  # midpoint maps to middle

    bright = levels_lut(0, 255, 2.0)
    assert bright[64] > 64  # gamma > 1 lifts midtones
    assert (np.diff(bright.astype(int)) >= 0).all()

    squeezed = levels_lut(0, 255, 1.0, 64, 191)
    assert squeezed[0] == 64 and squeezed[255] == 191


def test_apply_luts_preserves_alpha(qapp):
    img = blank_image(QSize(4, 4))
    img.fill(QColor(100, 100, 100, 128))
    lut = np.stack([levels_lut(0, 200, 1.0)] * 3)
    apply_luts(img, lut)
    assert img.pixelColor(0, 0).alpha() == 128
    assert img.pixelColor(0, 0).red() > 100  # stretched brighter


def test_levels_dialog_preview_ok_undo(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "l", QColor(100, 100, 100)))
    doc = win.current_doc()
    dialog = LevelsDialog(doc, win)

    dialog.in_white.setValue(150)  # stretch: 100 → ~170
    dialog._debounce.stop()
    dialog._preview()
    assert doc.active_layer.image.pixelColor(5, 5).red() > 150

    dialog.accept()
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.command(0).text() == "Levels"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(100, 100, 100)


def test_levels_dialog_cancel_restores(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "c", QColor(80, 80, 80)))
    doc = win.current_doc()
    dialog = LevelsDialog(doc, win)
    dialog.gamma.setValue(3.0)
    dialog._debounce.stop()
    dialog._preview()
    assert doc.active_layer.image.pixelColor(5, 5) != QColor(80, 80, 80)
    dialog.reject()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(80, 80, 80)
    assert doc.undo_stack.count() == 0


def test_auto_levels_finds_range(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 40), 72.0, "a", QColor(60, 60, 60)))
    doc = win.current_doc()
    # paint a bright region so the histogram spans 60..220
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainter

    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(0, 0, 40, 20), QColor(220, 220, 220))
    p.end()
    dialog = LevelsDialog(doc, win)
    dialog.auto_levels()
    assert 50 <= dialog.in_black.value() <= 70
    assert 210 <= dialog.in_white.value() <= 230
    dialog.reject()
