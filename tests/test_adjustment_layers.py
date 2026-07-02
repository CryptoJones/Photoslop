# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import Layer, blank_image
from photoslop.mainwindow import MainWindow


def brighten_lut() -> np.ndarray:
    lut = np.clip(np.arange(256) + 60, 0, 255).astype(np.uint8)
    return np.tile(lut, (3, 1))


def make_doc(qapp) -> Document:
    doc = Document.new(QSize(40, 30), 72.0, "adj", QColor(100, 100, 100))
    adj = Layer("Levels adjustment", blank_image(QSize(1, 1)))
    adj.adjustment = brighten_lut()
    doc.layers.append(adj)
    top = Layer.blank("above", QSize(10, 10), QPoint(0, 0))
    top.image.fill(QColor(20, 20, 20))
    doc.layers.append(top)
    return doc


def test_adjustment_applies_to_composite_below_only(qapp):
    doc = make_doc(qapp)
    flat = doc.flatten()
    assert flat.pixelColor(30, 20) == QColor(160, 160, 160)  # 100+60 below
    assert flat.pixelColor(5, 5) == QColor(20, 20, 20)  # layer ABOVE untouched
    assert doc.sample_color(30, 20) == QColor(160, 160, 160)  # sampler agrees

    doc.layers[1].visible = False  # hide the adjustment
    assert doc.flatten().pixelColor(30, 20) == QColor(100, 100, 100)


def test_adjustment_round_trips_ora_and_clone(qapp, tmp_path):
    doc = make_doc(qapp)
    path = str(tmp_path / "adj.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.layers[1].adjustment is not None
    assert (loaded.layers[1].adjustment == brighten_lut()).all()
    assert loaded.flatten().pixelColor(30, 20) == QColor(160, 160, 160)
    assert (doc.layers[1].clone().adjustment == brighten_lut()).all()


def test_new_adjustment_layer_undo(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "a", QColor(100, 100, 100)))
    doc = win.current_doc()

    adj = Layer("Levels adjustment", blank_image(QSize(1, 1)))
    adj.adjustment = brighten_lut()
    from photoslop.commands import InsertLayerCommand

    doc.undo_stack.push(InsertLayerCommand(doc, 1, adj, "New Adjustment Layer"))
    assert doc.flatten().pixelColor(10, 10) == QColor(160, 160, 160)
    doc.undo_stack.undo()
    assert doc.flatten().pixelColor(10, 10) == QColor(100, 100, 100)
