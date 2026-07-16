# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor

from photoslop.appearance import normalize_effects
from photoslop.commands import SetLayerStyleCommand
from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import Layer
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    """White background + an opaque red 20×20 chip at (30, 30)."""
    win = MainWindow()
    doc = Document.new(QSize(80, 80), 72.0, "fx", QColor(255, 255, 255))
    chip = Layer.blank("chip", QSize(20, 20), QPoint(30, 30))
    chip.image.fill(QColor(255, 0, 0))
    doc.layers.append(chip)
    doc.active_index = 1
    win.add_document(doc)
    return win


def test_drop_shadow_is_live_and_non_destructive(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    chip = doc.layers[1]

    doc.undo_stack.push(SetLayerStyleCommand(
        doc, chip, [("drop-shadow", 6, 6, 2, [0, 0, 0, 255])], 1.0))
    flat = doc.flatten()
    shadow_px = flat.pixelColor(54, 54)  # right+below the chip
    assert shadow_px.red() < 200  # darkened by the shadow
    assert chip.image.pixelColor(10, 10) == QColor(255, 0, 0)
    assert chip.image.size() == QSize(20, 20)  # pixels untouched

    doc.undo_stack.undo()
    assert doc.flatten().pixelColor(54, 54) == QColor(255, 255, 255)


def test_fill_opacity_hides_fill_but_keeps_stroke(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    chip = doc.layers[1]

    doc.undo_stack.push(SetLayerStyleCommand(
        doc, chip, [("stroke", 3, [0, 0, 255, 255])], 0.0, "Fill Opacity"))
    flat = doc.flatten()
    assert flat.pixelColor(40, 40) == QColor(255, 255, 255)  # fill gone
    ring = flat.pixelColor(28, 40)  # just outside the chip edge
    assert ring.blue() > 180 and ring.red() < 80  # stroke fully visible

    doc.undo_stack.push(SetLayerStyleCommand(doc, chip, chip.effects, 0.5))
    half = doc.flatten().pixelColor(40, 40)
    assert 100 < half.green() < 160  # half red over white


def test_effects_round_trip_and_clone(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()
    chip = doc.layers[1]
    chip.effects = [("glow", 4, [255, 220, 120, 200]),
                    ("stroke", 2, [0, 0, 0, 255])]
    chip.fill_opacity = 0.25

    path = str(tmp_path / "fx.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    top = loaded.layers[1]
    migrated = normalize_effects(chip.effects)
    assert [(effect["type"], effect["parameters"]) for effect in top.effects] == [
        (effect["type"], effect["parameters"]) for effect in migrated]
    assert abs(top.fill_opacity - 0.25) < 1e-6
    assert top.clone().effects == top.effects

    win.action_clear_style()
    assert chip.effects == [] and chip.fill_opacity == 1.0
    doc.undo_stack.undo()
    assert chip.fill_opacity == 0.25 and len(chip.effects) == 2
