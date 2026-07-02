# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 30), 72.0, "m", QColor(255, 0, 0)))
    return win


def select_rect(doc, x, y, w, h):
    path = QPainterPath()
    path.addRect(QRect(x, y, w, h))
    doc.set_selection(path)


def test_mask_from_selection_hides_outside(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    select_rect(doc, 0, 0, 20, 30)
    win.action_add_mask(True)

    layer = doc.active_layer
    assert layer.mask is not None
    flat = doc.flatten()
    assert flat.pixelColor(5, 5) == QColor(255, 0, 0)  # inside selection
    assert flat.pixelColor(30, 5).alpha() == 0  # masked away
    assert layer.image.pixelColor(30, 5) == QColor(255, 0, 0)  # pixels intact

    doc.undo_stack.undo()
    assert layer.mask is None
    assert doc.flatten().pixelColor(30, 5) == QColor(255, 0, 0)


def test_apply_mask_bakes_alpha(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    select_rect(doc, 0, 0, 20, 30)
    win.action_add_mask(True)
    win.action_apply_mask()

    layer = doc.active_layer
    assert layer.mask is None
    assert layer.image.pixelColor(30, 5).alpha() == 0  # baked into pixels
    assert layer.image.pixelColor(5, 5) == QColor(255, 0, 0)

    doc.undo_stack.undo()  # un-apply
    assert layer.mask is not None
    assert layer.image.pixelColor(30, 5) == QColor(255, 0, 0)


def test_delete_mask_and_reveal_all(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    win.action_add_mask(False)  # reveal-all mask changes nothing visually
    assert doc.active_layer.mask is not None
    assert doc.flatten().pixelColor(30, 5) == QColor(255, 0, 0)

    win.action_delete_mask()
    assert doc.active_layer.mask is None
    doc.undo_stack.undo()
    assert doc.active_layer.mask is not None


def test_mask_round_trips_ora_and_clone(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()
    select_rect(doc, 0, 0, 20, 30)
    win.action_add_mask(True)

    path = str(tmp_path / "masked.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    layer = loaded.layers[0]
    assert layer.mask is not None
    assert loaded.flatten().pixelColor(30, 5).alpha() == 0
    assert loaded.flatten().pixelColor(5, 5) == QColor(255, 0, 0)

    clone = doc.active_layer.clone()
    assert clone.mask is not None and clone.mask == doc.active_layer.mask
