# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.huesatdialog import HueSatDialog
from photoslop.layer import Layer
from photoslop.levelsdialog import LevelsDialog
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    """Background gray + a second dark layer; the second layer is active."""
    win = MainWindow()
    doc = Document.new(QSize(30, 30), 72.0, "sc", QColor(100, 100, 100))
    top = Layer.blank("top", QSize(10, 10), QPoint(20, 20))
    top.image.fill(QColor(40, 40, 40))
    doc.layers.append(top)
    doc.active_index = 1
    win.add_document(doc)
    return win


def test_levels_scope_all_layers(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    bg, top = doc.layers

    dialog = LevelsDialog(doc, win)
    dialog.out_black.setValue(60)  # lift blacks noticeably
    dialog.scope_all.setChecked(True)
    dialog._debounce.stop()
    dialog._preview()
    assert bg.image.pixelColor(5, 5).red() > 100  # background adjusted too
    assert top.image.pixelColor(5, 5).red() > 40

    dialog.accept()
    assert doc.undo_stack.count() == 1  # one macro for both layers
    doc.undo_stack.undo()
    assert bg.image.pixelColor(5, 5) == QColor(100, 100, 100)
    assert top.image.pixelColor(5, 5) == QColor(40, 40, 40)


def test_default_scope_touches_active_only_and_cancel_restores_all(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    bg, top = doc.layers

    dialog = HueSatDialog(doc, win)
    dialog._sliders["lightness"].setValue(80)
    dialog._debounce.stop()
    dialog._preview()
    assert top.image.pixelColor(5, 5).red() > 150  # active layer lightened
    assert bg.image.pixelColor(5, 5) == QColor(100, 100, 100)  # bg untouched

    dialog.scope_all.setChecked(True)  # widen the scope mid-session
    dialog._debounce.stop()
    dialog._preview()
    assert bg.image.pixelColor(5, 5).red() > 150

    dialog.reject()  # cancel restores every touched layer
    assert bg.image.pixelColor(5, 5) == QColor(100, 100, 100)
    assert top.image.pixelColor(5, 5) == QColor(40, 40, 40)
    assert doc.undo_stack.count() == 0
