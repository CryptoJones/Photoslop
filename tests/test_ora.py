# SPDX-License-Identifier: Apache-2.0
import zipfile

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage

from photoslop.document import Document
from photoslop.io_ora import MIMETYPE, _png_bytes, load_ora, save_ora
from photoslop.layer import FORMAT, Layer


def test_ora_round_trip(qapp, tmp_path):
    doc = Document.new(QSize(40, 30), 144.0, "art", QColor(10, 20, 30))
    top = Layer.blank("scribble", QSize(16, 12), QPoint(5, 7))
    top.image.fill(QColor(200, 100, 50, 255))
    top.opacity = 0.5
    top.visible = False
    doc.layers.append(top)

    path = str(tmp_path / "art.ora")
    save_ora(doc, path)

    with zipfile.ZipFile(path) as zf:
        assert zf.read("mimetype") == b"image/openraster"
        names = zf.namelist()
        assert "stack.xml" in names and "mergedimage.png" in names

    loaded = load_ora(path)
    assert loaded.size == QSize(40, 30)
    assert loaded.dpi == 144.0
    assert len(loaded.layers) == 2
    bottom, restored = loaded.layers
    assert bottom.name == "Background"
    assert restored.name == "scribble"
    assert restored.offset == QPoint(5, 7)
    assert abs(restored.opacity - 0.5) < 1e-3
    assert restored.visible is False
    assert restored.image.size() == QSize(16, 12)
    assert restored.image.pixelColor(3, 3) == QColor(200, 100, 50)
    assert bottom.image.pixelColor(0, 0) == QColor(10, 20, 30)


def _foreign_ora(path, stack_xml, layers):
    """Write a GIMP/Krita-shaped .ora by hand.

    save_ora only ever emits a flat stack, so nested groups — the thing every
    other OpenRaster editor writes — cannot be produced through it.
    """
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        info = zipfile.ZipInfo("mimetype")
        zf.writestr(info, MIMETYPE, compress_type=zipfile.ZIP_STORED)
        zf.writestr("stack.xml", stack_xml)
        for src, image in layers:
            zf.writestr(src, _png_bytes(image))
        merged = QImage(QSize(20, 20), FORMAT)
        merged.fill(QColor(0, 0, 0, 0))
        zf.writestr("mergedimage.png", _png_bytes(merged))


def _swatch(color):
    image = QImage(QSize(8, 8), FORMAT)
    image.fill(color)
    return image


def test_ora_nested_group_carries_opacity_visibility_and_blend(qapp, tmp_path):
    """A GIMP group's compositing state must survive the flatten to one level.

    Previously _walk_layers read only x/y off a nested <stack>, so a hidden
    20%-opacity multiply group opened fully visible at 100% normal (#186).
    """
    path = str(tmp_path / "grouped.ora")
    _foreign_ora(
        path,
        """<?xml version='1.0' encoding='UTF-8'?>
        <image w="20" h="20" xres="72" yres="72" version="0.0.3">
          <stack>
            <stack name="Shadows" x="2" y="3" opacity="0.2"
                   visibility="hidden" composite-op="svg:multiply">
              <layer name="upper" src="data/a.png" x="1" y="1"/>
              <layer name="lower" src="data/b.png" x="0" y="0"/>
            </stack>
            <layer name="base" src="data/c.png" x="0" y="0"/>
          </stack>
        </image>""",
        [
            ("data/a.png", _swatch(QColor(255, 0, 0, 255))),
            ("data/b.png", _swatch(QColor(0, 255, 0, 255))),
            ("data/c.png", _swatch(QColor(0, 0, 255, 255))),
        ],
    )

    doc = load_ora(path)

    # internal order is bottom-first: base, then the group's lower and upper
    base, lower, upper = doc.layers
    assert [layer.name for layer in doc.layers] == ["base", "lower", "upper"]

    # a hidden group hides every layer it holds — exact, not an approximation
    assert upper.visible is False
    assert lower.visible is False
    assert base.visible is True

    # group offsets still accumulate into the children, as before
    assert upper.offset == QPoint(3, 4)
    assert lower.offset == QPoint(2, 3)

    # the group's own state lands where render_region will actually apply it
    assert upper.group == "Shadows"
    assert lower.group == "Shadows"
    assert base.group is None
    assert doc.group_props["Shadows"] == {"opacity": 0.2, "blend_mode": "multiply"}

    # per-layer opacity is untouched — the 20% belongs to the group, not to
    # each member, and multiplying it in would double-apply it
    assert abs(upper.opacity - 1.0) < 1e-6
    assert abs(lower.opacity - 1.0) < 1e-6


def test_ora_nested_groups_collapse_into_one_level(qapp, tmp_path):
    path = str(tmp_path / "deep.ora")
    _foreign_ora(
        path,
        """<?xml version='1.0' encoding='UTF-8'?>
        <image w="20" h="20" xres="72" yres="72" version="0.0.3">
          <stack>
            <stack name="Outer" opacity="0.5" composite-op="svg:multiply">
              <stack name="Inner" opacity="0.5">
                <layer name="deep" src="data/a.png" x="0" y="0"/>
              </stack>
            </stack>
          </stack>
        </image>""",
        [("data/a.png", _swatch(QColor(255, 0, 0, 255)))],
    )

    doc = load_ora(path)

    (deep,) = doc.layers
    # Each stack keeps its own entry carrying the cumulative state of its
    # chain, so the layer lands in Inner at 0.5 * 0.5 with Outer's multiply
    # inherited. Outer holds no layers of its own, so it records nothing.
    assert deep.group == "Inner"
    assert abs(doc.group_props["Inner"]["opacity"] - 0.25) < 1e-6
    assert doc.group_props["Inner"]["blend_mode"] == "multiply"
    assert "Outer" not in doc.group_props


def test_ora_hidden_outer_group_hides_nested_children(qapp, tmp_path):
    path = str(tmp_path / "hidden-outer.ora")
    _foreign_ora(
        path,
        """<?xml version='1.0' encoding='UTF-8'?>
        <image w="20" h="20" xres="72" yres="72" version="0.0.3">
          <stack>
            <stack name="Outer" visibility="hidden">
              <stack name="Inner" visibility="visible">
                <layer name="deep" src="data/a.png" x="0" y="0"/>
              </stack>
            </stack>
          </stack>
        </image>""",
        [("data/a.png", _swatch(QColor(255, 0, 0, 255)))],
    )

    (deep,) = load_ora(path).layers
    assert deep.visible is False


def test_ora_empty_group_records_no_props(qapp, tmp_path):
    """A props entry with no contiguous run behind it would never be applied."""
    path = str(tmp_path / "empty-group.ora")
    _foreign_ora(
        path,
        """<?xml version='1.0' encoding='UTF-8'?>
        <image w="20" h="20" xres="72" yres="72" version="0.0.3">
          <stack>
            <stack name="Empty" opacity="0.3"/>
            <layer name="base" src="data/a.png" x="0" y="0"/>
          </stack>
        </image>""",
        [("data/a.png", _swatch(QColor(0, 0, 255, 255)))],
    )

    doc = load_ora(path)
    assert doc.group_props == {}
    assert [layer.name for layer in doc.layers] == ["base"]


def test_ora_group_props_survive_photoslop_round_trip(qapp, tmp_path):
    """Recovering group state on import is hollow if saving drops it again."""
    doc = Document.new(QSize(20, 20), 72.0, "grouped", QColor(0, 0, 0))
    member = Layer.blank("member", QSize(8, 8), QPoint(0, 0))
    member.image.fill(QColor(255, 0, 0, 255))
    member.group = "Shadows"
    doc.layers.append(member)
    doc.group_props["Shadows"] = {"opacity": 0.2, "blend_mode": "multiply"}

    path = str(tmp_path / "grouped.ora")
    save_ora(doc, path)
    loaded = load_ora(path)

    assert loaded.layers[-1].group == "Shadows"
    assert abs(loaded.group_props["Shadows"]["opacity"] - 0.2) < 1e-6
    assert loaded.group_props["Shadows"]["blend_mode"] == "multiply"


def test_ora_group_opacity_actually_changes_the_composite(qapp, tmp_path):
    """The regression that matters: pixels, not attributes."""
    path = str(tmp_path / "opaque-group.ora")
    stack = """<?xml version='1.0' encoding='UTF-8'?>
        <image w="8" h="8" xres="72" yres="72" version="0.0.3">
          <stack>
            <stack name="Faint" opacity="{opacity}">
              <layer name="red" src="data/a.png" x="0" y="0"/>
            </stack>
          </stack>
        </image>"""
    layers = [("data/a.png", _swatch(QColor(255, 0, 0, 255)))]

    _foreign_ora(path, stack.format(opacity="1.0"), layers)
    full = load_ora(path).flatten().pixelColor(4, 4)

    faint_path = str(tmp_path / "faint.ora")
    _foreign_ora(faint_path, stack.format(opacity="0.25"), layers)
    faint = load_ora(faint_path).flatten().pixelColor(4, 4)

    assert full.alpha() == 255
    assert faint.alpha() < full.alpha()


def test_ora_sibling_groups_sharing_a_name_stay_distinct(qapp, tmp_path):
    """Two runs under one props entry would apply the wrong state to one of them."""
    path = str(tmp_path / "twins.ora")
    _foreign_ora(
        path,
        """<?xml version='1.0' encoding='UTF-8'?>
        <image w="20" h="20" xres="72" yres="72" version="0.0.3">
          <stack>
            <stack name="Group" opacity="0.25">
              <layer name="upper" src="data/a.png" x="0" y="0"/>
            </stack>
            <stack name="Group" opacity="0.75">
              <layer name="lower" src="data/b.png" x="0" y="0"/>
            </stack>
          </stack>
        </image>""",
        [
            ("data/a.png", _swatch(QColor(255, 0, 0, 255))),
            ("data/b.png", _swatch(QColor(0, 255, 0, 255))),
        ],
    )

    doc = load_ora(path)
    lower, upper = doc.layers
    assert upper.name == "upper" and lower.name == "lower"
    assert upper.group != lower.group
    assert abs(doc.group_props[upper.group]["opacity"] - 0.25) < 1e-6
    assert abs(doc.group_props[lower.group]["opacity"] - 0.75) < 1e-6
