# SPDX-License-Identifier: Apache-2.0
"""Appearance schema, renderers, panel editing, presets, and SVG export."""

import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QTextDocument
from PySide6.QtSvg import QSvgRenderer

from photoslop.appearance import EFFECT_DEFAULTS, new_effect, normalize_effects
from photoslop.appearancepanel import AppearancePanel
from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.io_svg import load_svg, save_svg
from photoslop.layer import Layer
from photoslop.textdialog import render_text_document, render_text_layer
from photoslop.tools import MoveTool, ToolOptions


def chip_document() -> tuple[Document, Layer]:
    doc = Document.new(QSize(80, 80), 72, "appearance", QColor("white"))
    layer = Layer.blank("chip", QSize(24, 24), QPoint(28, 28))
    layer.image.fill(QColor(220, 30, 20))
    doc.layers.append(layer)
    doc.active_index = 1
    return doc, layer


def test_legacy_effects_migrate_to_versioned_objects():
    legacy = [
        ("drop-shadow", 2, 3, 4, [0, 0, 0, 128]),
        ("glow", 6, [255, 200, 20, 180]),
        ("stroke", 2, [10, 20, 30, 255]),
    ]
    effects = normalize_effects(legacy)
    assert [effect["type"] for effect in effects] == ["drop-shadow", "outer-glow", "outline"]
    assert all(effect["schema_version"] == 1 and effect["id"] for effect in effects)
    assert [effect["id"] for effect in effects] == [
        effect["id"] for effect in normalize_effects(legacy)
    ]


def test_future_effect_fields_are_preserved():
    effect = new_effect("outer-glow")
    effect["future"] = {"mode": "plasma"}
    effect["parameters"]["future_radius"] = 42
    normalized = normalize_effects([effect])[0]
    assert normalized["extensions"]["future"] == {"mode": "plasma"}
    assert normalized["parameters"]["future_radius"] == 42


@pytest.mark.parametrize("kind", EFFECT_DEFAULTS)
def test_every_effect_renders_without_mutating_source(qapp, kind):
    doc, layer = chip_document()
    before = layer.image.copy()
    baseline = doc.flatten()
    layer.effects = [new_effect(kind)]
    flat = doc.flatten()
    assert flat.size() == doc.size
    assert flat != baseline
    assert layer.image == before
    assert layer.fx_cache is not None


def test_effects_honor_masks_and_fill_opacity(qapp):
    doc, layer = chip_document()
    layer.mask = layer.image.convertToFormat(QImage.Format.Format_Grayscale8)
    layer.mask.fill(QColor("black"))
    layer.effects = [new_effect("outer-glow")]
    assert doc.flatten().pixelColor(27, 40) == QColor("white")
    layer.mask.fill(QColor("white"))
    layer.fill_opacity = 0
    flat = doc.flatten()
    assert flat.pixelColor(40, 40) == QColor("white")
    assert flat.pixelColor(27, 40) != QColor("white")


def test_move_tool_translates_cached_text_and_drop_shadow(qapp):
    doc = Document(QSize(240, 120), 72, "move appearance")
    layer = render_text_layer("Move", QFont("Sans Serif", 20), QColor("black"), QPoint(20, 20))
    layer.effects = [new_effect("drop-shadow", offset_x=5, offset_y=5, blur=4)]
    doc.layers = [layer]
    doc.active_index = 0
    editor = SimpleNamespace(snap_layer_offset=lambda _layer, proposed, _mods: proposed)
    canvas = SimpleNamespace(zoom=1.0, editor=editor)

    before = doc.flatten()  # Populate the appearance cache before dragging.
    cached = layer.fx_cache[1]
    delta = QPoint(60, 20)
    tool = MoveTool(ToolOptions())
    start = QPointF(30, 30)
    tool.press(doc, canvas, start, None)
    tool.move(doc, canvas, start + delta, None)
    tool.release(doc, canvas, start + delta, None)

    expected = QImage(doc.size, before.format())
    expected.fill(Qt.GlobalColor.transparent)
    painter = QPainter(expected)
    painter.drawImage(delta, before)
    painter.end()
    after = doc.flatten()
    assert layer.offset == QPoint(80, 40)
    assert after == expected
    assert layer.fx_cache[1] is cached


def test_new_stack_round_trips_ora(qapp, tmp_path):
    doc, layer = chip_document()
    layer.effects = [new_effect("inner-shadow"), new_effect("bevel-emboss")]
    path = str(tmp_path / "appearance.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.layers[1].effects == layer.effects


def test_appearance_panel_add_duplicate_toggle_reorder_and_delete(qapp):
    doc, layer = chip_document()
    panel = AppearancePanel()
    panel.set_document(doc)
    panel.effect_kind.setCurrentIndex(panel.effect_kind.findData("inner-shadow"))
    panel.add_effect()
    panel.duplicate_effect()
    assert [effect["type"] for effect in layer.effects] == ["inner-shadow", "inner-shadow"]
    first_id = layer.effects[0]["id"]
    panel.effects.setCurrentRow(0)
    panel.move_effect(1)
    assert layer.effects[1]["id"] == first_id
    panel.effects.currentItem().setCheckState(Qt.CheckState.Unchecked)
    assert not layer.effects[panel.effects.currentRow()]["enabled"]
    panel.delete_effect()
    assert len(layer.effects) == 1
    doc.undo_stack.undo()
    assert len(layer.effects) == 2


def test_continuous_parameter_changes_merge_into_one_undo_step(qapp):
    doc, layer = chip_document()
    panel = AppearancePanel()
    panel.set_document(doc)
    panel.add_effect()
    effect_id = layer.effects[0]["id"]
    panel._set_parameter(effect_id, "blur", 12)
    panel._set_parameter(effect_id, "blur", 18)
    assert doc.undo_stack.count() == 2  # add + one merged parameter edit
    doc.undo_stack.undo()
    assert layer.effects[0]["parameters"]["blur"] == 8


def test_custom_preset_is_versioned_json(qapp, monkeypatch):
    settings = QSettings("CryptoJones", "Photoslop")
    settings.remove("appearance/presets/v1")
    doc, layer = chip_document()
    layer.effects = [new_effect("outline")]
    panel = AppearancePanel()
    panel.set_document(doc)
    monkeypatch.setattr(
        "photoslop.appearancepanel.QInputDialog.getText", lambda *_args: ("My Style", True)
    )
    panel.save_preset()
    saved = json.loads(str(settings.value("appearance/presets/v1")))
    assert saved["My Style"][0]["type"] == "outline"
    settings.remove("appearance/presets/v1")


def test_svg_exports_text_runs_raster_layers_and_filters(qapp, tmp_path):
    doc = Document(QSize(200, 100), 72, "svg appearance")
    font = QFont("Sans Serif", 20)
    layer = render_text_layer("Nebraska", font, QColor("red"), QPoint(10, 10))
    layer.effects = [new_effect("drop-shadow"), new_effect("outline")]
    doc.layers = [layer]
    doc.active_index = 0
    path = tmp_path / "appearance.svg"
    save_svg(doc, str(path))
    source = path.read_text(encoding="utf-8")
    assert "<filter" in source and "feGaussianBlur" in source
    assert "<text" in source and "<tspan" in source
    assert "photoslop" in source and "appearances" in source
    restored = load_svg(str(path))
    assert restored.layers[0].text_data["text"] == "Nebraska"
    assert [effect["type"] for effect in restored.layers[0].effects] == ["drop-shadow", "outline"]


def test_svg_round_trips_embedded_raster_with_appearance(qapp, tmp_path):
    doc, layer = chip_document()
    layer.effects = [new_effect("outer-glow")]
    path = tmp_path / "raster.svg"
    save_svg(doc, str(path))
    restored = load_svg(str(path))
    chip = next(item for item in restored.layers if item.name == "layer-2")
    assert chip.image.size() == layer.image.size()
    assert chip.offset == layer.offset
    assert chip.effects[0]["type"] == "outer-glow"


def test_svg_styled_text_runs_are_valid_and_editable(qapp, tmp_path):
    rich = QTextDocument()
    rich.setHtml(
        '<span style="color:#ff0000;font-size:24pt;font-weight:700">A</span>'
        '<span style="color:#0000ff;font-size:18pt;font-style:italic">B</span>'
        "<br>C"
    )
    layer = render_text_document(rich, QPoint(8, 12))
    layer.effects = [new_effect("gradient-overlay"), new_effect("bevel-emboss")]
    doc = Document(QSize(160, 90), 72, "rich svg")
    doc.layers = [layer]
    doc.active_index = 0
    path = tmp_path / "rich.svg"
    save_svg(doc, str(path))
    source = path.read_text(encoding="utf-8")
    assert source.count("<tspan") >= 3
    assert 'font-weight="bold"' in source
    assert 'font-style="italic"' in source
    assert QSvgRenderer(str(path)).isValid()
    restored = load_svg(str(path))
    assert restored.layers[0].text_data["text"] == "AB\nC"
