# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import BLEND_MODES, ORA_OPS, Layer
from photoslop.mainwindow import MainWindow


def make_doc(qapp) -> Document:
    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(200, 200, 200))
    top = Layer.blank("top", QSize(10, 10))
    top.image.fill(QColor(128, 128, 128))
    doc.layers.append(top)
    doc.active_index = 1
    return doc


def test_multiply_and_screen_composite(qapp):
    doc = make_doc(qapp)
    doc.layers[1].blend_mode = "multiply"
    px = doc.flatten().pixelColor(5, 5)
    assert abs(px.red() - 200 * 128 // 255) <= 2  # ≈100

    doc.layers[1].blend_mode = "screen"
    px = doc.flatten().pixelColor(5, 5)
    assert abs(px.red() - (255 - (255 - 200) * (255 - 128) // 255)) <= 2  # ≈227

    doc.layers[1].blend_mode = "normal"
    assert doc.flatten().pixelColor(5, 5) == QColor(128, 128, 128)


def test_ora_round_trips_blend_mode(qapp, tmp_path):
    doc = make_doc(qapp)
    doc.layers[1].blend_mode = "multiply"
    path = str(tmp_path / "blend.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.layers[1].blend_mode == "multiply"
    assert loaded.layers[0].blend_mode == "normal"


def test_ora_op_names_and_clone(qapp):
    assert ORA_OPS["normal"] == "svg:src-over"
    assert ORA_OPS["multiply"] == "svg:multiply"
    assert ORA_OPS["addition"] == "svg:plus"
    assert set(ORA_OPS) == set(BLEND_MODES)

    doc = make_doc(qapp)
    doc.layers[1].blend_mode = "overlay"
    assert doc.layers[1].clone().blend_mode == "overlay"


def test_panel_combo_sets_blend(qapp):
    win = MainWindow()
    doc = make_doc(qapp)
    win.add_document(doc)
    panel = win.layer_panel
    assert panel.blend.currentText() == "normal"

    panel.blend.setCurrentText("darken")
    panel._on_blend()
    assert doc.active_layer.blend_mode == "darken"

    # selecting the bottom layer syncs the combo back
    panel.list.setCurrentRow(1)
    assert panel.blend.currentText() == "normal"
