# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop import nodemachine, npimage
from photoslop.filters import available_filters, parse_params
from photoslop.layer import blank_image

BLOB_CENTRE = 48
BLOB_RADIUS = 30


def _blob(size=96, colour=None):
    """A solid circle on a transparent layer — the cut-out subject the
    filter is designed for."""
    colour = colour or QColor(200, 40, 40)
    img = blank_image(QSize(size, size))
    for y in range(size):
        for x in range(size):
            if (x - BLOB_CENTRE) ** 2 + (y - BLOB_CENTRE) ** 2 <= BLOB_RADIUS**2:
                img.setPixelColor(x, y, colour)
    return img


def _alpha(img):
    return (npimage.view_u32(img) >> np.uint32(24)).astype(np.uint16)


def _painted(img):
    """Pixels that carry ink but were outside the source blob."""
    arr = npimage.view_u32(img)
    return int(np.count_nonzero(arr >> np.uint32(24)))


def test_all_presets_are_registered(qapp):
    registry = available_filters()
    for cls in nodemachine.NODE_MACHINE_FILTERS:
        assert registry.get(cls.name) is cls
    assert registry["node-machine"] is nodemachine.NodeMachineFilter


def test_presets_share_the_base_parameter_keys(qapp):
    base = [spec.key for spec in nodemachine.NodeMachineFilter.params]
    for cls in nodemachine.NODE_MACHINE_FILTERS:
        assert [spec.key for spec in cls.params] == base


def test_preset_overrides_change_defaults(qapp):
    defaults = {spec.key: spec.default for spec in nodemachine.NodeMachineNodesFilter.params}
    assert defaults["style"] == "straight"
    assert defaults["glow"] == 60
    assert defaults["hue-b"] == 235


def test_output_is_deterministic_for_a_seed(qapp):
    first, second = _blob(), _blob()
    nodemachine.NodeMachineFilter().apply(first, {"seed": 11})
    nodemachine.NodeMachineFilter().apply(second, {"seed": 11})
    assert np.array_equal(npimage.view_u32(first), npimage.view_u32(second))


def test_seed_changes_the_layout(qapp):
    first, second = _blob(), _blob()
    nodemachine.NodeMachineFilter().apply(first, {"seed": 11})
    nodemachine.NodeMachineFilter().apply(second, {"seed": 12})
    assert not np.array_equal(npimage.view_u32(first), npimage.view_u32(second))


def test_ink_stays_near_the_silhouette(qapp):
    img = _blob()
    nodemachine.NodeMachineFilter().apply(img, {"seed": 5, "glow": 0, "pads": 3})
    alpha = _alpha(img)
    ys, xs = np.nonzero(alpha)
    margin = 8  # pads and line weight round outward past the blob edge
    assert xs.min() >= BLOB_CENTRE - BLOB_RADIUS - margin
    assert xs.max() <= BLOB_CENTRE + BLOB_RADIUS + margin
    assert ys.min() >= BLOB_CENTRE - BLOB_RADIUS - margin
    assert ys.max() <= BLOB_CENTRE + BLOB_RADIUS + margin


def test_keep_zero_discards_the_source_art(qapp):
    img = _blob()
    nodemachine.NodeMachineFilter().apply(img, {"seed": 5, "keep": 0})
    arr = npimage.view_u32(img)
    # the original flat red is gone; only generated ink remains
    reds = np.count_nonzero(arr == npimage.premultiplied_u32(200, 40, 40, 255))
    assert reds == 0
    assert _painted(img) > 0


def test_keep_full_preserves_the_source_art(qapp):
    img = _blob()
    nodemachine.NodeMachineFilter().apply(img, {"seed": 5, "keep": 100, "components": 8})
    arr = npimage.view_u32(img)
    assert np.count_nonzero(arr == npimage.premultiplied_u32(200, 40, 40, 255)) > 0


def test_transparent_layer_is_untouched(qapp):
    img = blank_image(QSize(64, 64))
    before = npimage.view_u32(img).copy()
    nodemachine.NodeMachineFilter().apply(img, {})
    assert np.array_equal(npimage.view_u32(img), before)


def test_tiny_layer_does_not_crash(qapp):
    img = blank_image(QSize(4, 4))
    for x in range(4):
        for y in range(4):
            img.setPixelColor(x, y, QColor(255, 255, 255))
    before = npimage.view_u32(img).copy()
    nodemachine.NodeMachineFilter().apply(img, {})
    assert np.array_equal(npimage.view_u32(img), before)


def test_hue_drives_the_ink_colour(qapp):
    green = _blob()
    nodemachine.NodeMachineFilter().apply(
        green, {"seed": 3, "hue-a": 120, "hue-b": 120, "sat-a": 100, "sat-b": 100}
    )
    arr = npimage.view_u32(green)
    lit = arr[(arr >> np.uint32(24)) > 200]
    r = (lit >> np.uint32(16)) & 0xFF
    g = (lit >> np.uint32(8)) & 0xFF
    assert int(g.sum()) > int(r.sum())


def test_glow_widens_the_painted_footprint(qapp):
    sharp, glowing = _blob(), _blob()
    nodemachine.NodeMachineFilter().apply(sharp, {"seed": 5, "glow": 0})
    nodemachine.NodeMachineFilter().apply(glowing, {"seed": 5, "glow": 70})
    assert _painted(glowing) > _painted(sharp)


def test_vertical_style_renders(qapp):
    img = _blob()
    nodemachine.NodeMachineVerticalFilter().apply(
        img, {"seed": 5, "style": "vertical", "outline": 0}
    )
    assert _painted(img) > 0


def test_buffers_stay_premultiplied(qapp):
    img = _blob()
    nodemachine.NodeMachineLightningFilter().apply(img, {"seed": 9, "glow": 80})
    arr = npimage.view_u32(img)
    a = (arr >> np.uint32(24)) & 0xFF
    for shift in (16, 8, 0):
        assert np.all(((arr >> np.uint32(shift)) & 0xFF) <= a)


def test_cli_parameter_parsing(qapp):
    cls = nodemachine.NodeMachineFilter
    values = parse_params(cls, "components=80,seed=3")
    assert values["components"] == 80
    assert values["seed"] == 3
    assert values["traces"] == 3  # untouched keys keep their defaults
    for bad in ("components=999", "seed=-1", "nonsense=1", "style=diagonal"):
        try:
            parse_params(cls, bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} should have been rejected")


def test_opposite_hues_sweep_upward(qapp):
    """55 -> 235 is exactly half the wheel; the shortest-arc formula picks
    the descending sweep (through red) unless the tie is broken. The Nodes
    preset depends on the ascending one (through green and cyan)."""
    mask = np.zeros((16, 16), dtype=bool)
    mask[2:14, 2:14] = True
    grad = nodemachine._Gradient(
        mask, {"angle": 0, "hue-a": 55, "sat-a": 100, "hue-b": 235, "sat-b": 100}
    )
    mid = grad.at(8.0, 8.0)
    assert 120 <= mid.hue() <= 200, f"midpoint swept the wrong way: hue={mid.hue()}"


def test_choice_parameters_round_trip(qapp):
    """style and source are modes, so the framework's choice type renders
    them as combo boxes instead of magic integers in a spin box."""
    cls = nodemachine.NodeMachineFilter
    specs = {s.key: s for s in cls.params}
    assert specs["style"].type == "choice"
    assert specs["style"].choices == ("pcb", "straight", "vertical")
    assert specs["source"].choices == ("auto", "alpha", "luma")
    assert parse_params(cls, "style=vertical")["style"] == "vertical"


def test_luma_source_traces_a_bright_subject_on_black(qapp):
    """An opaque layer has no alpha silhouette; luma mode is what makes a
    subject on a black background work."""
    img = blank_image(QSize(96, 96))
    for y in range(96):
        for x in range(96):
            inside = (x - BLOB_CENTRE) ** 2 + (y - BLOB_CENTRE) ** 2 <= BLOB_RADIUS**2
            img.setPixelColor(x, y, QColor(230, 230, 230) if inside else QColor(0, 0, 0))
    nodemachine.NodeMachineFilter().apply(img, {"seed": 5, "source": "luma", "keep": 0})
    alpha = _alpha(img)
    ys, xs = np.nonzero(alpha)
    assert len(xs) > 0
    assert xs.min() >= BLOB_CENTRE - BLOB_RADIUS - 8
    assert xs.max() <= BLOB_CENTRE + BLOB_RADIUS + 8
