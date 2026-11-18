# SPDX-License-Identifier: Apache-2.0
"""Unit tests for Make Work Path from selection via contour tracing (#424)."""

import numpy as np
import pytest
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop import cli, contour, vector
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_empty_mask_produces_no_contours():
    empty = np.zeros((40, 40), dtype=bool)
    loops = contour.trace_contours(empty)
    assert loops == []
    cmds = contour.contour_to_commands(loops)
    assert cmds == []
    data = contour.selection_to_vector_data(empty)
    assert data["geometry"]["commands"] == []


def test_single_pixel_contour():
    m = np.zeros((10, 10), dtype=bool)
    m[3, 4] = True
    loops = contour.trace_contours(m)
    assert len(loops) == 1
    # 1 pixel has 4 corners: (4,3), (5,3), (5,4), (4,4)
    assert len(loops[0]) == 4
    cmds = contour.contour_to_commands(loops)
    assert cmds[0]["op"] == "M"
    assert cmds[-1]["op"] == "Z"


def test_rectangle_contour_and_sharp_corners():
    m = np.zeros((60, 60), dtype=bool)
    m[10:40, 15:45] = True
    loops = contour.trace_contours(m)
    assert len(loops) == 1
    assert len(loops[0]) == 4
    cmds = contour.contour_to_commands(loops, tolerance=2.0)
    assert len(cmds) == 6  # M + 4 C's + Z
    assert cmds[0]["op"] == "M"
    assert cmds[0]["node"] == "corner"
    for c in cmds[1:5]:
        assert c["op"] == "C"
        assert c["node"] == "corner"
    assert cmds[5]["op"] == "Z"


def test_full_canvas_rect():
    full = np.ones((50, 70), dtype=bool)
    loops = contour.trace_contours(full)
    assert len(loops) == 1
    assert len(loops[0]) == 4
    cmds = contour.contour_to_commands(loops)
    assert len(cmds) == 6


def test_donut_hole_winding_and_containment(qapp):
    yy, xx = np.ogrid[:80, :80]
    dist = np.sqrt((xx - 40) ** 2 + (yy - 40) ** 2)
    donut = (dist <= 30) & (dist >= 15)

    loops = contour.trace_contours(donut)
    assert len(loops) == 2  # outer boundary + inner hole
    cmds = contour.contour_to_commands(loops, tolerance=2.0)
    m_ops = [c for c in cmds if c["op"] == "M"]
    z_ops = [c for c in cmds if c["op"] == "Z"]
    assert len(m_ops) == 2
    assert len(z_ops) == 2

    # Render into QPainterPath and check containment
    path = vector.path_from_commands(cmds)
    # Inside the ring
    assert path.contains(QPointF(40, 20))
    # Inside the center hole
    assert not path.contains(QPointF(40, 40))
    # Outside the donut
    assert not path.contains(QPointF(5, 5))


def test_disjoint_islands():
    m = np.zeros((100, 100), dtype=bool)
    m[10:30, 10:30] = True
    m[60:80, 60:80] = True
    loops = contour.trace_contours(m)
    assert len(loops) == 2
    cmds = contour.contour_to_commands(loops)
    m_count = sum(1 for c in cmds if c["op"] == "M")
    assert m_count == 2


def test_tolerance_simplification_decimation():
    yy, xx = np.ogrid[:100, :100]
    dist = np.sqrt((xx - 50) ** 2 + (yy - 50) ** 2)
    circle = dist <= 40
    loops = contour.trace_contours(circle)
    assert len(loops) == 1

    cmds_tight = contour.contour_to_commands(loops, tolerance=0.5)
    cmds_loose = contour.contour_to_commands(loops, tolerance=8.0)
    assert len(cmds_loose) < len(cmds_tight)


def test_commands_to_svg_path():
    cmds = [
        {"op": "M", "p": [10.0, 20.0], "node": "smooth"},
        {"op": "C", "c1": [12.0, 22.0], "c2": [18.0, 28.0], "p": [20.0, 30.0], "node": "smooth"},
        {"op": "Z"},
    ]
    svg_d = contour.commands_to_svg_path(cmds)
    assert svg_d == "M 10.0 20.0 C 12.0 22.0 18.0 28.0 20.0 30.0 Z"


def test_desktop_make_work_path_action(qapp, monkeypatch):
    win = MainWindow()
    doc = Document.new(QSize(100, 100), 72.0, "test", QColor(255, 255, 255))
    win.add_document(doc)

    # Calling when no selection exists shows status and does not add a layer
    win.action_make_work_path()
    assert len(doc.layers) == 1
    assert "needs a selection" in win.statusBar().currentMessage()

    # Now make a rectangular selection
    sel = QPainterPath()
    sel.addRect(QRect(15, 15, 40, 40))
    doc.set_selection(sel)

    # Mock QInputDialog.getDouble to return (2.0, True)
    from PySide6.QtWidgets import QInputDialog

    monkeypatch.setattr(QInputDialog, "getDouble", lambda *args, **kwargs: (2.0, True))

    win.action_make_work_path()
    assert len(doc.layers) == 2
    work_layer = doc.layers[-1]
    assert work_layer.name.startswith("Work Path")
    assert work_layer.vector_data is not None
    assert work_layer.vector_data["geometry"]["kind"] == "path"
    assert doc.vector_selection == [work_layer.vector_data["id"]]

    # Undo removes the layer; redo restores it
    doc.undo_stack.undo()
    assert len(doc.layers) == 1
    doc.undo_stack.redo()
    assert len(doc.layers) == 2


def test_cli_selection_to_path_pipeline(tmp_path):
    out_ora = str(tmp_path / "out.ora")
    res = cli.apply_pipeline(
        new="80x80",
        operations=[
            ("select", "20,20,30,30"),
            ("selection-to-path", "2.0"),
        ],
        output=out_ora,
        info=True,
    )
    assert res["info"]["layers"][-1]["name"] == "Work Path 1"
    assert res["info"]["layers"][-1]["vector_type"] == "path"
    svg_path = res["info"]["layers"][-1]["svg_path"]
    assert svg_path.startswith("M 50.0 20.0")
    assert svg_path.endswith("Z")


def test_cli_selection_to_path_default_tolerance():
    res = cli.apply_pipeline(
        new="80x80",
        operations=[
            ("select", "10,10,20,20"),
            ("selection-to-path", ""),
        ],
        info=True,
    )
    last_layer = res["info"]["layers"][-1]
    assert last_layer["name"] == "Work Path 1"
    assert last_layer["vector_type"] == "path"


def test_cli_selection_to_path_without_selection_raises():
    with pytest.raises(cli._ValueError, match="needs a selection"):
        cli.apply_pipeline(
            new="80x80",
            operations=[
                ("selection-to-path", "2.0"),
            ],
            info=True,
        )


def test_cli_selection_to_path_invalid_tolerance_raises():
    with pytest.raises(cli._ValueError, match="tolerance must be"):
        cli.apply_pipeline(
            new="80x80",
            operations=[
                ("select", "10,10,20,20"),
                ("selection-to-path", "invalid"),
            ],
            info=True,
        )

    with pytest.raises(cli._ValueError, match="between 0.5 and 10.0"):
        cli.apply_pipeline(
            new="80x80",
            operations=[
                ("select", "10,10,20,20"),
                ("selection-to-path", "15.0"),
            ],
            info=True,
        )


def test_cli_svg_export_contains_path_element(tmp_path):
    out_svg = str(tmp_path / "out.svg")
    cli.apply_pipeline(
        new="100x100",
        operations=[
            ("select", "20,20,40,40"),
            ("selection-to-path", "2.0"),
        ],
        output=out_svg,
    )
    with open(out_svg, encoding="utf-8") as f:
        content = f.read()
    assert '<path d="M ' in content
    assert 'data-name="Work Path 1"' in content
