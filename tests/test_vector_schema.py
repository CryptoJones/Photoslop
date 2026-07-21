# SPDX-License-Identifier: Apache-2.0
"""Versioned vector migration, direct rendering, transforms, and ORA fallback."""

from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document, render_region
from photoslop.io_ora import load_ora, save_ora
from photoslop.vector import SCHEMA_VERSION, migrate_vector, render_vector


def legacy_rect(**extra):
    return {
        "kind": "rect",
        "x1": 10,
        "y1": 10,
        "x2": 50,
        "y2": 40,
        "color": [220, 20, 30, 255],
        **extra,
    }


def test_legacy_migration_adds_stable_model_and_preserves_unknown_fields(qapp):
    migrated = migrate_vector(legacy_rect(vendor_future={"answer": 42}))
    assert migrated["schema_version"] == SCHEMA_VERSION
    assert migrated["id"]
    assert migrated["type"] == "shape"
    assert migrated["geometry"] == {"kind": "rect", "rect": [10.0, 10.0, 50.0, 40.0]}
    assert migrated["appearance"]["fill"]["color"] == [220, 20, 30, 255]
    assert migrated["transform"] == [1, 0, 0, 1, 0, 0]
    assert migrated["extensions"]["vendor_future"] == {"answer": 42}
    assert migrate_vector(migrated)["id"] == migrated["id"]


def test_catmull_legacy_path_migrates_to_explicit_cubic_handles(qapp):
    migrated = migrate_vector(
        {
            "kind": "path",
            "points": [[10, 10], [40, 20], [60, 50]],
            "close": False,
            "fill": False,
            "width": 4,
            "color": [0, 0, 0, 255],
        }
    )
    commands = migrated["geometry"]["commands"]
    assert commands[0]["op"] == "M"
    assert all(command["op"] == "C" for command in commands[1:])
    assert all("c1" in command and "c2" in command for command in commands[1:])


def test_direct_renderer_ignores_destroyed_raster_fallback(qapp):
    doc = Document(QSize(80, 60), 72, "direct")
    layer = render_vector(legacy_rect(), "Shape", doc.canvas_rect())
    assert layer is not None
    layer.image.fill(QColor(0, 0, 0, 0))  # simulate stale/low-resolution fallback
    doc.layers = [layer]
    doc.active_index = 0
    rendered = render_region(doc, QRect(0, 0, 80, 60))
    assert rendered.pixelColor(20, 20) == QColor(220, 20, 30, 255)


def test_native_transform_and_appearance_round_trip_in_ora(qapp, tmp_path):
    data = migrate_vector(legacy_rect())
    data.pop("kind")  # native-only payload, no legacy projection dependency
    for key in ("x1", "y1", "x2", "y2", "color"):
        data.pop(key, None)
    data["transform"] = [1, 0, 0, 1, 7, 9]
    data["appearance"]["fill_rule"] = "evenodd"
    data["extensions"]["future"] = [1, 2, 3]
    doc = Document(QSize(100, 80), 72, "native")
    layer = render_vector(data, "Native", doc.canvas_rect())
    doc.layers = [layer]
    doc.active_index = 0
    path = str(tmp_path / "native.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    restored = loaded.layers[0].vector_data
    assert restored["id"] == data["id"]
    assert restored["transform"] == [1, 0, 0, 1, 7, 9]
    assert restored["appearance"]["fill_rule"] == "evenodd"
    assert restored["extensions"]["future"] == [1, 2, 3]
    assert not loaded.layers[0].image.isNull()  # non-Photoslop ORA fallback
