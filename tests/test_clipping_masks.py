# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    """Transparent canvas, a small opaque base chip, and a full-size paint
    layer above it."""
    win = MainWindow()
    doc = Document.new(QSize(60, 40), 72.0, "c", None)
    base = Layer.blank("base", QSize(20, 20), QPoint(10, 10))
    base.image.fill(QColor(0, 255, 0))
    doc.layers.append(base)
    paint = Layer.blank("paint", QSize(60, 40))
    paint.image.fill(QColor(255, 0, 0))
    doc.layers.append(paint)
    doc.active_index = 2
    win.add_document(doc)
    return win


def test_clip_confines_to_base_alpha(qapp):
    win = make_window(qapp)
    doc = win.current_doc()

    assert doc.flatten().pixelColor(50, 35) == QColor(255, 0, 0)  # unclipped: red everywhere
    win.action_toggle_clip()
    assert doc.active_layer.clipped is True

    flat = doc.flatten()
    assert flat.pixelColor(15, 15) == QColor(255, 0, 0)  # over the base: visible
    assert flat.pixelColor(50, 35).alpha() == 0  # outside base: clipped away
    assert doc.sample_color(15, 15) == QColor(255, 0, 0)  # sampler agrees

    doc.undo_stack.undo()
    assert doc.active_layer.clipped is False
    assert doc.flatten().pixelColor(50, 35) == QColor(255, 0, 0)


def test_bottom_layer_cannot_clip(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    doc.active_index = 0
    win.action_toggle_clip()
    assert doc.layers[0].clipped is False
    assert doc.undo_stack.count() == 0


def test_clip_run_shares_base_and_ora_round_trip(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()
    win.action_toggle_clip()  # clip "paint" to "base"

    extra = Layer.blank("extra", QSize(60, 40))
    extra.image.fill(QColor(0, 0, 255, 128))
    extra.clipped = True  # second clipped layer in the run
    doc.layers.append(extra)
    flat = doc.flatten()
    assert flat.pixelColor(50, 35).alpha() == 0  # both clip to the base chip
    assert flat.pixelColor(15, 15).alpha() == 255

    path = str(tmp_path / "clip.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert [layer.clipped for layer in loaded.layers] == [False, False, True, True]
    assert loaded.flatten().pixelColor(50, 35).alpha() == 0
    assert loaded.layers[2].clone().clipped is True
