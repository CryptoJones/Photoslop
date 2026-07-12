# SPDX-License-Identifier: Apache-2.0
"""Object, node, appearance, geometry, snapping, and headless vector workflows."""

import json

from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop import cli, vector, vectorops
from photoslop.document import Document


def _document():
    doc = Document(QSize(120, 100), 72, "vectors")
    for index, x in enumerate((10, 45, 80)):
        layer = vector.render_vector(
            {"kind": "rect", "x1": x, "y1": 10, "x2": x + 20, "y2": 30,
             "color": [220, 20, 30, 255]}, f"R{index}", doc.canvas_rect())
        doc.layers.append(layer)
    doc.active_index = 0
    return doc


def _ids(doc):
    return [layer.vector_data["id"] for layer in doc.layers]


def test_selection_transform_group_and_undo(qapp):
    doc = _document()
    ids = _ids(doc)
    assert vectorops.select(doc, ids[:2]) == ids[:2]
    assert vectorops.select(doc, [ids[2]], "add") == ids
    vectorops.transform(doc, ids[:2], dx=7, dy=4, rotate=10, sx=1.2)
    assert doc.layers[0].vector_data["transform"] != [1, 0, 0, 1, 0, 0]
    doc.undo_stack.undo()
    assert doc.layers[0].vector_data["transform"] == [1, 0, 0, 1, 0, 0]
    vectorops.group(doc, ids[:2], "group-a")
    assert doc.layers[0].vector_data["parent_id"] == "group-a"


def test_appearance_align_distribute_boolean_and_nodes(qapp):
    doc = _document()
    ids = _ids(doc)
    gradient = {"type": "linear-gradient", "start": [10, 10], "end": [30, 10],
                "stops": [[0, [0, 0, 0, 255]], [1, [255, 255, 255, 255]]]}
    vectorops.set_appearance(doc, [ids[0]], fill=gradient, stroke_width=3,
                             dash=[2, 1])
    assert doc.layers[0].image.pixelColor(12, 20) != QColor(220, 20, 30, 255)
    vectorops.align(doc, ids[:2], "top")
    vectorops.distribute(doc, ids, "horizontal")
    result = vectorops.boolean_path(doc, ids[:2], "union")
    assert result["geometry"]["commands"]
    vectorops.edit_node(doc, result["id"], 0, "convert", node_type="smooth")
    assert doc.layers[0].vector_data["geometry"]["commands"][0]["node"] == "smooth"


def test_snapping_and_cli_mcp_parity(qapp, tmp_path):
    doc = _document()
    doc.guides_v = [33]
    snapped = vectorops.snap(doc, QPointF(35, 50), 3)
    assert snapped.point.x() == 33 and snapped.target == "vertical guide"

    output = str(tmp_path / "vectors.ora")
    result = cli.apply_pipeline(
        new="100x80",
        operations=[
            ("shape", "rect,10,10,20,20,255,0,0"),
            ("vector-op", json.dumps({"op": "transform", "ids": [], "dx": 4})),
        ], output=output, info=True)
    assert result["info"]["layers"][-1]["vector_id"]
    assert result["info"]["layers"][-1]["vector_type"] == "shape"
