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


def test_all_27_blend_modes_registered():
    from photoslop.blends import CUSTOM_BLEND_MODES

    expected_27 = {
        "normal",
        "dissolve",
        "darken",
        "multiply",
        "color-burn",
        "linear-burn",
        "darker-color",
        "lighten",
        "screen",
        "color-dodge",
        "linear-dodge",
        "addition",
        "lighter-color",
        "overlay",
        "soft-light",
        "hard-light",
        "vivid-light",
        "linear-light",
        "pin-light",
        "hard-mix",
        "difference",
        "exclusion",
        "subtract",
        "divide",
        "hue",
        "saturation",
        "color",
        "luminosity",
    }
    assert expected_27.issubset(set(BLEND_MODES))
    assert len(CUSTOM_BLEND_MODES) == 14
    for mode in CUSTOM_BLEND_MODES:
        assert mode in BLEND_MODES
        assert BLEND_MODES[mode] is None


def test_arithmetic_linear_burn_dodge(qapp):
    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(180, 100, 50))
    top = Layer.blank("top", QSize(10, 10))
    top.image.fill(QColor(100, 150, 200))
    doc.layers.append(top)

    top.blend_mode = "linear-burn"
    px = doc.flatten().pixelColor(5, 5)
    # R: 180 + 100 - 255 = 25, G: max(0, 100+150-255)=0, B: max(0, 50+200-255)=0
    assert abs(px.red() - 25) <= 2
    assert px.green() == 0
    assert px.blue() == 0

    top.blend_mode = "linear-dodge"
    px = doc.flatten().pixelColor(5, 5)
    # R: min(255, 180+100) = 255, G: 250, B: 250
    assert px.red() == 255
    assert abs(px.green() - 250) <= 2
    assert abs(px.blue() - 250) <= 2


def test_arithmetic_subtract_divide(qapp):
    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(180, 100, 50))
    top = Layer.blank("top", QSize(10, 10))
    top.image.fill(QColor(100, 150, 200))
    doc.layers.append(top)

    top.blend_mode = "subtract"
    px = doc.flatten().pixelColor(5, 5)
    # R: max(0, 180-100) = 80, G: 0, B: 0
    assert abs(px.red() - 80) <= 2
    assert px.green() == 0
    assert px.blue() == 0

    doc2 = Document.new(QSize(10, 10), 72.0, "b", QColor(100, 150, 50))
    top2 = Layer.blank("top", QSize(10, 10))
    top2.image.fill(QColor(200, 100, 100))
    doc2.layers.append(top2)
    top2.blend_mode = "divide"
    px = doc2.flatten().pixelColor(5, 5)
    # R: min(255, 100/200*255) ≈ 128, G: 255, B: 50/100*255 ≈ 128
    assert abs(px.red() - 128) <= 2
    assert px.green() == 255
    assert abs(px.blue() - 128) <= 2


def test_contrast_modes_vivid_linear_pin_hard_mix(qapp):
    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(128, 128, 128))
    top = Layer.blank("top", QSize(10, 10))
    top.image.fill(QColor(150, 60, 140))
    doc.layers.append(top)

    top.blend_mode = "linear-light"
    px = doc.flatten().pixelColor(5, 5)
    # R: min(255, max(0, 128 + 2*150 - 255)) = 173
    assert abs(px.red() - 173) <= 2

    top.blend_mode = "pin-light"
    px = doc.flatten().pixelColor(5, 5)
    # G: s=60 <= 128 -> min(b, 2*s) = min(128, 120) = 120
    assert abs(px.green() - 120) <= 2

    top.blend_mode = "hard-mix"
    px = doc.flatten().pixelColor(5, 5)
    # R: 128 + 150 = 278 >= 255 -> 255
    # G: 128 + 60 = 188 < 255 -> 0
    # B: 128 + 140 = 268 >= 255 -> 255
    assert px.red() == 255
    assert px.green() == 0
    assert px.blue() == 255

    top.blend_mode = "vivid-light"
    px = doc.flatten().pixelColor(5, 5)
    assert 0 <= px.red() <= 255
    assert 0 <= px.green() <= 255


def test_darker_lighter_color(qapp):
    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(100, 100, 100))  # sum = 300
    top = Layer.blank("top", QSize(10, 10))
    top.image.fill(QColor(50, 200, 20))  # sum = 270
    doc.layers.append(top)

    top.blend_mode = "darker-color"
    px = doc.flatten().pixelColor(5, 5)
    # Top is darker overall (270 < 300), so Top is chosen
    assert px == QColor(50, 200, 20)

    top.blend_mode = "lighter-color"
    px = doc.flatten().pixelColor(5, 5)
    # Base is lighter overall (300 > 270), so Base is chosen
    assert px == QColor(100, 100, 100)


def test_dissolve_stochastic(qapp):
    doc = Document.new(QSize(20, 20), 72.0, "b", QColor(0, 0, 0))
    top = Layer.blank("top", QSize(20, 20))
    top.image.fill(QColor(255, 255, 255))
    top.blend_mode = "dissolve"
    doc.layers.append(top)

    top.opacity = 1.0
    flat = doc.flatten()
    assert flat.pixelColor(10, 10) == QColor(255, 255, 255)

    top.opacity = 0.0
    flat = doc.flatten()
    assert flat.pixelColor(10, 10) == QColor(0, 0, 0)

    top.opacity = 0.5
    flat = doc.flatten()
    colors = {flat.pixelColor(x, y).red() for x in range(20) for y in range(20)}
    # At 50% opacity, both black (0) and white (255) pixels exist
    assert 0 in colors and 255 in colors


def test_hsl_component_modes(qapp):
    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(200, 100, 50))
    top = Layer.blank("top", QSize(10, 10))
    top.image.fill(QColor(50, 100, 200))
    doc.layers.append(top)

    for mode in ("hue", "saturation", "color", "luminosity"):
        top.blend_mode = mode
        flat = doc.flatten()
        px = flat.pixelColor(5, 5)
        assert 0 <= px.red() <= 255
        assert 0 <= px.green() <= 255
        assert 0 <= px.blue() <= 255


def test_needs_offscreen_detects_custom_blends(qapp):
    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(255, 255, 255))
    top = Layer.blank("top", QSize(10, 10))
    doc.layers.append(top)

    assert not doc.needs_offscreen()
    top.blend_mode = "multiply"
    assert not doc.needs_offscreen()
    top.blend_mode = "linear-burn"
    assert doc.needs_offscreen()
    top.visible = False
    assert not doc.needs_offscreen()


def test_merge_down_custom_blend(qapp):
    from photoslop.commands import MergeDownCommand

    doc = Document.new(QSize(10, 10), 72.0, "b", QColor(180, 100, 50))
    top = Layer.blank("top", QSize(10, 10))
    top.image.fill(QColor(100, 150, 200))
    top.blend_mode = "linear-burn"
    doc.layers.append(top)
    doc.active_index = 1

    cmd = MergeDownCommand(doc, 1)
    cmd.redo()
    assert len(doc.layers) == 1
    px = doc.layers[0].image.pixelColor(5, 5)
    assert abs(px.red() - 25) <= 2
    assert px.green() == 0
    assert px.blue() == 0
