# SPDX-License-Identifier: Apache-2.0
"""Parametric vector layers (#110): render, edit, transforms, ORA, CLI."""

from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor, QImage

from photoslop import cli, vector
from photoslop.commands import (
    EditVectorLayerCommand,
    FlipLayerCommand,
    ResizeImageCommand,
    RotateImageCommand,
)
from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora

CANVAS = QRect(0, 0, 200, 160)


def _rect_data(**over):
    data = {"kind": "rect", "x1": 20, "y1": 10, "x2": 80, "y2": 50,
            "color": [200, 30, 30, 255]}
    data.update(over)
    return data


def test_render_vector_rect_and_bounds(qapp):
    layer = vector.render_vector(_rect_data(), "S", CANVAS)
    assert layer is not None and layer.vector_data["kind"] == "rect"
    assert layer.offset == QPoint(18, 8)  # bounds = geometry + 2px margin
    # doc-space pixel inside the rect is filled
    local = QPoint(30 - layer.offset.x(), 30 - layer.offset.y())
    assert layer.image.pixelColor(local).red() == 200


def test_render_vector_path_and_degenerate(qapp):
    data = {"kind": "path", "points": [[10, 10], [60, 20], [40, 60]],
            "close": True, "fill": True, "width": 3,
            "color": [30, 60, 200, 255]}
    layer = vector.render_vector(data, "P", CANVAS)
    assert layer is not None
    assert vector.render_vector({"kind": "path", "points": [[1, 1]],
                                 "fill": True, "color": [0, 0, 0]},
                                "x", CANVAS) is None


def test_resize_rerenders_crisp_and_undoes(qapp):
    doc = Document.new(QSize(200, 160), 72.0, "v", QColor(255, 255, 255))
    layer = vector.render_vector(_rect_data(), "S", CANVAS)
    doc.layers.append(layer)
    cmd = ResizeImageCommand(doc, QSize(400, 320))
    cmd.redo()
    assert layer.vector_data["x2"] == 160  # params scaled 2x
    flat = doc.flatten()
    assert flat.pixelColor(100, 60).red() == 200   # inside scaled rect
    # crisp edge: hard transition within ~2px of the doubled boundary
    assert flat.pixelColor(163, 60).red() == 255
    cmd.undo()
    assert layer.vector_data["x2"] == 80


def test_rotate_and_flip_document_keep_parametric(qapp):
    doc = Document.new(QSize(200, 160), 72.0, "v", QColor(255, 255, 255))
    layer = vector.render_vector(_rect_data(), "S", CANVAS)
    doc.layers.append(layer)
    RotateImageCommand(doc, 90).redo()
    assert layer.vector_data is not None
    xs = sorted([layer.vector_data["x1"], layer.vector_data["x2"]])
    assert xs == [110, 150]  # 90cw: x' = old_h - y
    flat = doc.flatten()
    assert flat.pixelColor(130, 50).red() == 200


def test_flip_layer_is_parametric_and_self_inverse(qapp):
    doc = Document.new(QSize(200, 160), 72.0, "v", QColor(255, 255, 255))
    data = {"kind": "line", "x1": 20, "y1": 10, "x2": 80, "y2": 50,
            "width": 4, "color": [10, 10, 200, 255]}
    layer = vector.render_vector(data, "L", CANVAS)
    doc.layers.append(layer)
    cmd = FlipLayerCommand(doc, layer, horizontal=True)
    cmd.redo()
    assert layer.vector_data["x1"] == 80 and layer.vector_data["x2"] == 20
    cmd.undo()
    assert layer.vector_data["x1"] == 20 and layer.vector_data["x2"] == 80


def test_grab_drag_and_edit_command(qapp):
    doc = Document.new(QSize(200, 160), 72.0, "v", QColor(255, 255, 255))
    layer = vector.render_vector(_rect_data(), "S", CANVAS)
    doc.layers.append(layer)
    assert vector.grab(layer.vector_data, 80, 50) == "c22"
    assert vector.grab(layer.vector_data, 50, 30) == "move"
    assert vector.grab(layer.vector_data, 150, 150) is None
    dragged = vector.drag(layer.vector_data, "c22", 120, 90, 0, 0)
    rendered = vector.render_vector(dragged, layer.name, CANVAS)
    doc.undo_stack.push(EditVectorLayerCommand(doc, layer, rendered))
    assert layer.vector_data["x2"] == 120
    doc.undo_stack.undo()
    assert layer.vector_data["x2"] == 80


def test_shape_tool_edit_in_place(qapp):
    from photoslop.tools import ShapeTool, ToolOptions

    doc = Document.new(QSize(200, 160), 72.0, "v", QColor(255, 255, 255))
    layer = vector.render_vector(_rect_data(), "S", CANVAS)
    doc.layers.append(layer)
    doc.active_index = len(doc.layers) - 1
    tool = ShapeTool(ToolOptions())

    class _FakeCanvas:
        zoom = 1.0

        def update(self):
            pass
    fake = _FakeCanvas()
    tool.press(doc, fake, QPointF(80, 50), None)   # grab corner c22
    assert tool._edit is not None
    tool.move(doc, fake, QPointF(120, 90), None)
    tool.release(doc, fake, QPointF(120, 90), None)
    assert layer.vector_data["x2"] == 120 and layer.vector_data["y2"] == 90


def test_pen_tool_anchor_edit(qapp):
    from photoslop.tools import PenTool, ToolOptions

    doc = Document.new(QSize(200, 160), 72.0, "v", QColor(255, 255, 255))
    data = {"kind": "path", "points": [[20, 20], [90, 30], [60, 90]],
            "close": False, "fill": False, "width": 3,
            "color": [10, 120, 10, 255]}
    layer = vector.render_vector(data, "P", CANVAS)
    doc.layers.append(layer)
    doc.active_index = len(doc.layers) - 1

    class _FakeCanvas:
        zoom = 1.0

        def __init__(self, d):
            self.doc = d

        def update(self):
            pass
    fake = _FakeCanvas(doc)
    tool = PenTool(ToolOptions())
    tool.press(doc, fake, QPointF(90, 30), None)   # grab anchor 1
    assert tool._edit_layer is layer and tool._drag_idx == 1
    tool.move(doc, fake, QPointF(130, 40), None)
    tool.release(doc, fake, QPointF(130, 40), None)
    tool.commit(fake)
    assert layer.vector_data["points"][1] == [130.0, 40.0]
    doc.undo_stack.undo()
    assert layer.vector_data["points"][1] == [90, 30]


def test_ora_round_trip_preserves_vector_data(qapp, tmp_path):
    doc = Document.new(QSize(200, 160), 72.0, "v", QColor(255, 255, 255))
    doc.layers.append(vector.render_vector(_rect_data(), "S", CANVAS))
    path = str(tmp_path / "vec.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    restored = loaded.layers[-1]
    for key, value in _rect_data().items():
        assert restored.vector_data[key] == value
    assert restored.vector_data["schema_version"] == 1
    assert restored.vector_data["geometry"]["kind"] == "rect"
    assert restored.vector_data["appearance"]["fill"]["type"] == "solid"
    # cloning keeps it too
    assert restored.clone().vector_data == restored.vector_data


def test_cli_shape_stamps_and_resize_rerenders(qapp, tmp_path):
    out = str(tmp_path / "crisp.png")
    assert cli.main(["--new", "100x80", "--fill", "255,255,255",
                     "--shape", "rect,10,10,40,30,200,30,30",
                     "--resize", "300x240", "--output", out]) == 0
    img = QImage(out)
    # scaled rect now spans x 30..150: crisp inside and outside
    assert img.pixelColor(90, 60).red() == 200
    assert img.pixelColor(155, 60).red() == 255
