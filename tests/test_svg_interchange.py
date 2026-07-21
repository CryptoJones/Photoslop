# SPDX-License-Identifier: Apache-2.0
"""SVG native-subset round trips, fallbacks, and artboard metadata."""

from PySide6.QtCore import QRect, QSize

from photoslop import artboards, vector
from photoslop.document import Document
from photoslop.io_svg import load_svg, save_svg


def test_svg_round_trip_preserves_vectors_gradients_transform_and_artboards(qapp, tmp_path):
    doc = Document(QSize(160, 120), 72, "svg")
    data = vector.migrate_vector(
        {"kind": "rect", "x1": 10, "y1": 20, "x2": 70, "y2": 80, "color": [255, 0, 0, 255]}
    )
    data["name"] = "Gradient box"
    data["transform"] = [1, 0, 0, 1, 5, 7]
    data["appearance"]["fill"] = {
        "type": "linear-gradient",
        "start": [10, 20],
        "end": [70, 20],
        "stops": [[0, [255, 0, 0, 255]], [1, [0, 0, 255, 255]]],
    }
    doc.layers = [vector.render_vector(data, data["name"], doc.canvas_rect())]
    doc.active_index = 0
    doc.artboards = [("Cover", QRect(4, 6, 100, 80))]
    path = str(tmp_path / "roundtrip.svg")
    save_svg(doc, path)
    loaded = load_svg(path)
    restored = loaded.layers[0].vector_data
    assert loaded.size == doc.size
    assert restored["id"] == data["id"]
    assert restored["name"] == "Gradient box"
    assert restored["transform"] == [1, 0, 0, 1, 5, 7]
    assert restored["appearance"]["fill"] == data["appearance"]["fill"]
    assert loaded.artboards == doc.artboards
    assert loaded.import_warnings == []


def test_svg_imports_paths_text_and_keeps_unsupported_raster_fallback(qapp, tmp_path):
    path = tmp_path / "mixed.svg"
    path.write_text(
        """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 80 60">
      <path id="curve" d="M 5 5 C 10 20 30 20 40 5 Z" fill="#ff0000"/>
      <text id="label" x="5" y="30" fill="#000">Nebraska 🌽</text>
      <polygon points="0,0 5,0 5,5" fill="#00f"/>
    </svg>""",
        encoding="utf-8",
    )
    doc = load_svg(str(path))
    vectors = [layer for layer in doc.layers if layer.vector_data]
    assert [layer.vector_data["id"] for layer in vectors] == ["curve", "label"]
    assert vectors[1].vector_data["text"]["content"] == "Nebraska 🌽"
    assert "polygon" in doc.import_warnings
    assert doc.layers[0].name.startswith("SVG raster fallback")
    assert not doc.layers[0].visible


def test_named_artboards_are_editable_ordered_and_undoable(qapp):
    doc = Document(QSize(100, 80), 72, "boards")
    artboards.edit(doc, "add", name="First", rect=[0, 0, 40, 30])
    artboards.edit(doc, "add", name="Second", rect=[40, 0, 40, 30])
    artboards.edit(doc, "update", index=1, name="Cover", rect=[40, 5, 50, 35])
    artboards.edit(doc, "reorder", index=1, to=0)
    assert [name for name, _rect in doc.artboards] == ["Cover", "First"]
    doc.undo_stack.undo()
    assert [name for name, _rect in doc.artboards] == ["First", "Cover"]
