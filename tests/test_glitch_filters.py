# SPDX-License-Identifier: Apache-2.0
"""Glitch filters: pixel sorting, and datamosh + chromatic aberration."""

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from photoslop.filters import (
    DatamoshFilter,
    PixelSortFilter,
    available_filters,
    parse_params,
)
from photoslop.npimage import view_u32


def _noise(w=64, h=48, seed=1):
    """A deterministic opaque texture — blocks and gradients, not flat fill."""
    rng = np.random.default_rng(seed)
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    arr = view_u32(img)
    rgb = rng.integers(0, 256, size=(h, w, 3), dtype=np.uint32)
    arr[...] = (
        (np.uint32(255) << np.uint32(24))
        | (rgb[..., 0] << np.uint32(16))
        | (rgb[..., 1] << np.uint32(8))
        | rgb[..., 2]
    )
    return img


def _luma(arr):
    r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
    g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
    b = (arr & 0xFF).astype(np.float32)
    return 0.299 * r + 0.587 * g + 0.114 * b


# --- registration ---------------------------------------------------------


def test_glitch_filters_are_built_in(qapp):
    reg = available_filters()
    assert reg.get("pixel-sort") is PixelSortFilter
    assert reg.get("datamosh") is DatamoshFilter


def test_params_parse_and_validate(qapp):
    assert parse_params(PixelSortFilter, "") == {
        "low": 60,
        "high": 200,
        "vertical": 0,
        "reverse": 0,
    }
    assert parse_params(DatamoshFilter, "block=8,seed=3")["block"] == 8
    with pytest.raises(ValueError):
        parse_params(PixelSortFilter, "low=999")  # out of range
    with pytest.raises(ValueError):
        parse_params(DatamoshFilter, "blocks=8")  # misspelt key


# --- pixel sort -----------------------------------------------------------


def test_pixel_sort_permutes_within_rows(qapp):
    """Every row must be a permutation of itself: no pixel invented or lost."""
    img = _noise()
    before = view_u32(img).copy()
    PixelSortFilter().apply(img, {"low": 0, "high": 255, "vertical": 0, "reverse": 0})
    after = view_u32(img)
    for y in range(img.height()):
        assert sorted(before[y].tolist()) == sorted(after[y].tolist())


def test_pixel_sort_full_band_orders_each_row_by_luma(qapp):
    img = _noise()
    PixelSortFilter().apply(img, {"low": 0, "high": 255, "vertical": 0, "reverse": 0})
    lum = _luma(view_u32(img))
    assert np.all(np.diff(lum, axis=1) >= -1e-3)  # non-decreasing left to right


def test_pixel_sort_reverse_flips_the_order(qapp):
    img = _noise()
    PixelSortFilter().apply(img, {"low": 0, "high": 255, "vertical": 0, "reverse": 1})
    lum = _luma(view_u32(img))
    assert np.all(np.diff(lum, axis=1) <= 1e-3)  # non-increasing


def test_pixel_sort_leaves_out_of_band_pixels_alone(qapp):
    """Black is below the band, so the black stripe must survive untouched."""
    img = _noise()
    arr = view_u32(img)
    arr[10:14, :] = np.uint32(0xFF000000)  # opaque black, luma 0 < low
    before = arr.copy()
    PixelSortFilter().apply(img, {"low": 60, "high": 255, "vertical": 0, "reverse": 0})
    assert np.array_equal(view_u32(img)[10:14, :], before[10:14, :])


def test_pixel_sort_runs_do_not_cross_rows(qapp):
    """Two rows, each fully in band, must sort independently."""
    img = QImage(4, 2, QImage.Format.Format_ARGB32_Premultiplied)
    row0 = [200, 180, 160, 140]  # greys, all inside a 0..255 band
    row1 = [80, 100, 120, 90]
    for x, v in enumerate(row0):
        img.setPixelColor(x, 0, QColor(v, v, v))
    for x, v in enumerate(row1):
        img.setPixelColor(x, 1, QColor(v, v, v))
    PixelSortFilter().apply(img, {"low": 0, "high": 255, "vertical": 0, "reverse": 0})
    assert sorted(row0) == [img.pixelColor(x, 0).red() for x in range(4)]
    assert sorted(row1) == [img.pixelColor(x, 1).red() for x in range(4)]


def test_pixel_sort_vertical_sorts_columns(qapp):
    img = _noise()
    before = view_u32(img).copy()
    PixelSortFilter().apply(img, {"low": 0, "high": 255, "vertical": 1, "reverse": 0})
    after = view_u32(img)
    lum = _luma(after)
    assert np.all(np.diff(lum, axis=0) >= -1e-3)  # non-decreasing top to bottom
    for x in range(img.width()):
        assert sorted(before[:, x].tolist()) == sorted(after[:, x].tolist())


def test_pixel_sort_empty_band_is_a_no_op(qapp):
    """A band nothing falls into must leave the buffer byte-identical."""
    img = QImage(8, 4, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(20, 20, 20))  # luma 20, well below the band
    before = view_u32(img).copy()
    PixelSortFilter().apply(img, {"low": 200, "high": 255, "vertical": 0, "reverse": 0})
    assert np.array_equal(view_u32(img), before)


def test_pixel_sort_accepts_a_backwards_band(qapp):
    """low > high is still a band, not an error and not a silent no-op."""
    a, b = _noise(), _noise()
    PixelSortFilter().apply(a, {"low": 200, "high": 60, "vertical": 0, "reverse": 0})
    PixelSortFilter().apply(b, {"low": 60, "high": 200, "vertical": 0, "reverse": 0})
    assert np.array_equal(view_u32(a), view_u32(b))


def test_pixel_sort_preserves_alpha_per_pixel(qapp):
    img = _noise()
    arr = view_u32(img)
    arr[...] = (arr & np.uint32(0x00FFFFFF)) | (np.uint32(128) << np.uint32(24))
    PixelSortFilter().apply(img, {"low": 0, "high": 255, "vertical": 0, "reverse": 0})
    assert np.all((view_u32(img) >> np.uint32(24)) == 128)


# --- datamosh + chromatic aberration --------------------------------------


def test_datamosh_is_deterministic_for_a_seed(qapp):
    a, b = _noise(), _noise()
    p = {"block": 8, "amount": 60, "drift": 10, "aberration": 2.0, "seed": 42}
    DatamoshFilter().apply(a, dict(p))
    DatamoshFilter().apply(b, dict(p))
    assert np.array_equal(view_u32(a), view_u32(b))  # replay-safe


def test_datamosh_different_seeds_differ(qapp):
    a, b = _noise(), _noise()
    base = {"block": 8, "amount": 60, "drift": 10, "aberration": 0.0}
    DatamoshFilter().apply(a, {**base, "seed": 1})
    DatamoshFilter().apply(b, {**base, "seed": 2})
    assert not np.array_equal(view_u32(a), view_u32(b))


def test_datamosh_zeroed_params_are_a_no_op(qapp):
    img = _noise()
    before = view_u32(img).copy()
    DatamoshFilter().apply(
        img, {"block": 16, "amount": 0, "drift": 0, "aberration": 0.0, "seed": 7}
    )
    assert np.array_equal(view_u32(img), before)


def test_datamosh_changes_the_image(qapp):
    img = _noise()
    before = view_u32(img).copy()
    DatamoshFilter().apply(
        img, {"block": 8, "amount": 80, "drift": 16, "aberration": 0.0, "seed": 5}
    )
    assert not np.array_equal(view_u32(img), before)


def test_datamosh_invents_no_pixel_values(qapp):
    """Blocks are copied whole, so every output pixel came from the input."""
    img = _noise()
    source = set(view_u32(img).ravel().tolist())
    DatamoshFilter().apply(
        img, {"block": 8, "amount": 70, "drift": 12, "aberration": 0.0, "seed": 9}
    )
    assert set(view_u32(img).ravel().tolist()) <= source


def test_chromatic_aberration_alone_shifts_colour_but_not_alpha(qapp):
    img = _noise()
    before = view_u32(img).copy()
    DatamoshFilter().apply(
        img, {"block": 16, "amount": 0, "drift": 0, "aberration": 8.0, "seed": 7}
    )
    after = view_u32(img)
    assert not np.array_equal(after, before)  # colour moved
    assert np.array_equal(after >> np.uint32(24), before >> np.uint32(24))  # alpha did not


def test_chromatic_aberration_leaves_the_centre_alone(qapp):
    """The fringe is radial, so it vanishes at the optical centre."""
    img = _noise(w=65, h=65)
    before = view_u32(img).copy()
    DatamoshFilter().apply(
        img, {"block": 16, "amount": 0, "drift": 0, "aberration": 6.0, "seed": 7}
    )
    assert view_u32(img)[32, 32] == before[32, 32]


def _moshed(w, h, seed, drift=2, amount=30):
    """Mosh a coordinate-encoded image and return a COPY of the result.

    Each pixel carries its own (x, y), so the output *is* the displacement
    field. The copy matters: a view_u32 view dies with the QImage backing it."""
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    arr = view_u32(img)
    ys, xs = np.mgrid[0:h, 0:w]
    arr[...] = (
        (np.uint32(255) << np.uint32(24))
        | (ys.astype(np.uint32) << np.uint32(8))
        | xs.astype(np.uint32)
    )
    DatamoshFilter().apply(
        img,
        {"block": 8, "amount": amount, "drift": drift, "aberration": 0.0, "seed": seed},
    )
    return view_u32(img).copy()


@pytest.mark.parametrize("size", [(512, 256), (256, 512), (512, 512), (1024, 768)])
def test_datamosh_seed_reproduces_across_image_sizes(qapp, size):
    """One seed must lay the same glitch over a whole set of images.

    The motion field is keyed by block position, not by draw order, so
    neither width nor height may shift it. Regression test for the bug where
    a single RNG stream made the vectors depend on the image's block count."""
    base = _moshed(256, 256, seed=42)
    other = _moshed(*size, seed=42)
    assert np.array_equal(base[:200, :200], other[:200, :200])


def test_datamosh_seed_survives_a_size_change_but_not_the_canvas_edge(qapp):
    """The honest limit: displacement is clamped to the canvas, so a drift
    big enough to run off a small image cannot land the same way on a large
    one. Same field, different boundary — not a reproducibility bug."""
    near = _moshed(256, 256, seed=42, drift=24, amount=60)
    wide = _moshed(512, 256, seed=42, drift=24, amount=60)
    assert not np.array_equal(near[:200, :200], wide[:200, :200])


def test_datamosh_handles_a_tiny_image(qapp):
    """Blocks bigger than the image must not walk off the buffer."""
    img = _noise(w=3, h=2)
    DatamoshFilter().apply(
        img, {"block": 64, "amount": 100, "drift": 64, "aberration": 20.0, "seed": 3}
    )
    assert img.width() == 3 and img.height() == 2
