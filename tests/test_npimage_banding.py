# SPDX-License-Identifier: Apache-2.0
"""Row-banded float transients in npimage (#347): the banded blur, unsharp,
weighted blend, and puppet warp must match a whole-image computation, and
their peak transient must be a band's worth of memory, not the layer's."""

import tracemalloc
from functools import partial

import numpy as np
import pytest
from PySide6.QtGui import QImage

from photoslop import npimage

# heights deliberately off the BAND_ROWS grid; widths small so the halo
# maths dominates and the float64 reference stays quick
SIZES = [(1, 1), (5, 7), (37, 300), (23, 255), (23, 257), (64, 700)]
RADII = [1, 8, 50, 600]  # 600 -> r=301: the 3r halo is wider than the band


def random_layer(rng, w, h) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    arr = npimage.view_u32(img)
    a = rng.integers(0, 256, (h, w), dtype=np.uint32)
    r = rng.integers(0, 256, (h, w), dtype=np.uint32) * a // 255
    g = rng.integers(0, 256, (h, w), dtype=np.uint32) * a // 255
    b = rng.integers(0, 256, (h, w), dtype=np.uint32) * a // 255
    arr[:] = (a << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    return img


def planes(img: QImage) -> np.ndarray:
    """(4, h, w) int32 A, R, G, B."""
    v = npimage.view_u32(img)
    return np.stack([((v >> np.uint32(k)) & 0xFF).astype(np.int32) for k in (24, 16, 8, 0)])


def ref_box(plane: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Direct (2r+1)-window mean along `axis`, zero outside the array —
    the definition the cumsum trick implements, one shifted add at a time."""
    n = plane.shape[axis]
    pad = [(r, r) if ax == axis else (0, 0) for ax in range(2)]
    padded = np.pad(plane, pad)
    out = np.zeros_like(plane)
    for off in range(2 * r + 1):
        out += np.take(padded, np.arange(off, off + n), axis=axis)
    return out / (2 * r + 1)


def ref_triple_box(plane: np.ndarray, r: int) -> np.ndarray:
    out = plane.astype(np.float64)
    for _ in range(3):
        out = ref_box(ref_box(out, r, 0), r, 1)
    return out


def round_u8(v: np.ndarray) -> np.ndarray:
    return np.clip(v + 0.5, 0, 255).astype(np.int32)


def ref_gaussian_blur(img: QImage, radius: int) -> np.ndarray:
    r = max(1, int(radius) // 2 + 1)
    return np.stack([round_u8(ref_triple_box(c, r)) for c in planes(img)])


def ref_unsharp(img: QImage, radius: int, amount: float) -> np.ndarray:
    r = max(1, int(radius) // 2 + 1)
    a, *rgb = planes(img)
    out = [a]
    for c in rgb:
        sharp = np.minimum(np.clip(c + amount * (c - ref_triple_box(c, r)), 0, 255), a)
        out.append(round_u8(sharp))
    return np.stack(out)


def unbanded(monkeypatch, fn, *args):
    """Run `fn` with the whole image as a single band."""
    monkeypatch.setattr(npimage, "BAND_ROWS", 1 << 30)
    result = fn(*args)
    monkeypatch.undo()
    return result


@pytest.mark.parametrize("w,h", SIZES)
@pytest.mark.parametrize("radius", RADII)
def test_banded_blur_is_bit_identical_to_unbanded_and_within_1lsb_of_reference(
    qapp, monkeypatch, w, h, radius
):
    rng = np.random.default_rng(w * 1000 + h + radius)
    src = random_layer(rng, w, h)

    banded = QImage(src)
    npimage.gaussian_blur(banded, radius)
    whole = QImage(src)
    unbanded(monkeypatch, npimage.gaussian_blur, whole, radius)
    assert np.array_equal(planes(banded), planes(whole))  # exact: integer maths

    # float64 reference: same rounding unless a value sits within ~1e-12 of
    # a .5 boundary, so 1 LSB is the documented tolerance
    assert np.abs(planes(banded) - ref_gaussian_blur(src, radius)).max() <= 1


@pytest.mark.parametrize("w,h", SIZES)
@pytest.mark.parametrize("radius", [1, 8, 600])
def test_banded_unsharp_matches_reference(qapp, monkeypatch, w, h, radius):
    rng = np.random.default_rng(w * 7 + h * 3 + radius)
    src = random_layer(rng, w, h)

    banded = QImage(src)
    npimage.unsharp_mask(banded, radius, 0.8)
    whole = QImage(src)
    unbanded(monkeypatch, npimage.unsharp_mask, whole, radius, 0.8)
    assert np.array_equal(planes(banded), planes(whole))
    assert np.abs(planes(banded) - ref_unsharp(src, radius, 0.8)).max() <= 1
    assert np.array_equal(planes(banded)[0], planes(src)[0])  # alpha untouched
    assert (planes(banded)[1:] <= planes(banded)[0]).all()  # premultiplied


def test_blur_and_unsharp_honour_the_mask_across_band_edges(qapp, monkeypatch):
    rng = np.random.default_rng(3)
    src = random_layer(rng, 31, 600)
    mask = rng.random((600, 31)) > 0.5
    mask[250:262] = True  # straddles the first band boundary
    for fn, args in ((npimage.gaussian_blur, (8,)), (npimage.unsharp_mask, (4, 1.2))):
        masked = QImage(src)
        fn(masked, *args, mask)
        whole = QImage(src)
        unbanded(monkeypatch, fn, whole, *args, None)
        assert np.array_equal(planes(masked)[:, mask], planes(whole)[:, mask])
        assert np.array_equal(planes(masked)[:, ~mask], planes(src)[:, ~mask])


def test_blur_accepts_radii_wider_than_the_layer(qapp):
    """The float32 vstack trick raised once r reached the short side; the
    banded sums truncate the window instead, like every other edge."""
    for w, h in ((1, 1), (200, 4), (4, 200)):
        img = random_layer(np.random.default_rng(1), w, h)
        npimage.gaussian_blur(img, 100)
        npimage.unsharp_mask(img, 100, 1.0)


@pytest.mark.parametrize("w,h", SIZES)
def test_banded_blend_by_weights_is_bit_identical_to_the_stacked_formula(qapp, w, h):
    rng = np.random.default_rng(w + h)
    filtered = random_layer(rng, w, h)
    original = random_layer(rng, w, h)
    weights = rng.random((h, w), dtype=np.float32)

    fp = planes(filtered).astype(np.float32)
    op = planes(original).astype(np.float32)
    expected = round_u8(op * (1.0 - weights) + fp * weights)  # the pre-#347 (h, w, 4) maths

    npimage.blend_by_weights(filtered, original, weights)
    assert np.array_equal(planes(filtered), expected)


@pytest.mark.parametrize("w,h", [(5, 7), (37, 300), (23, 257), (64, 700)])
def test_banded_puppet_warp_is_bit_identical_to_unbanded(qapp, monkeypatch, w, h):
    src = random_layer(np.random.default_rng(w * h), w, h)
    pins = [
        ((1, 1), (1, 1)),
        ((w * 0.6, h * 0.5), (w * 0.7, h * 0.4)),
        ((w - 2, h - 2), (w - 2, h - 2)),
    ]
    banded = npimage.puppet_warp(src, pins)
    whole = unbanded(monkeypatch, npimage.puppet_warp, src, pins)
    assert np.array_equal(planes(banded), planes(whole))


def _peak_traced(fn) -> int:
    """Peak bytes tracemalloc sees (numpy reports its allocations to it)
    while `fn` runs. Deterministic, unlike RSS, so safe to compare in CI."""
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    tracemalloc.reset_peak()
    fn()
    _current, peak = tracemalloc.get_traced_memory()
    if not was_tracing:
        tracemalloc.stop()
    return peak


@pytest.mark.parametrize(
    "radius,op",
    [
        (8, lambda img: npimage.gaussian_blur(img, 8)),
        (100, lambda img: npimage.gaussian_blur(img, 100)),
        (4, lambda img: npimage.unsharp_mask(img, 4, 0.8)),
    ],
    ids=["blur-8", "blur-100", "unsharp"],
)
def test_blur_transient_is_bounded_by_the_band_not_the_layer(qapp, radius, op):
    w, short_h, tall_h = 2000, 1500, 3000  # 3 MP and 6 MP
    rng = np.random.default_rng(9)
    short = random_layer(rng, w, short_h)
    tall = random_layer(rng, w, tall_h)

    peak_short = _peak_traced(lambda: op(short))
    peak_tall = _peak_traced(lambda: op(tall))

    # the pre-#347 code held four float32 planes of the layer before it even
    # started blurring (and ~3.5x that at peak); the band plus its 3r halo
    # either side, in int64, is the unit the new code works in
    four_float32_planes = short_h * w * 4 * 4
    band_plane = (npimage.BAND_ROWS + 6 * (radius // 2 + 1)) * w * 8
    assert peak_short < four_float32_planes
    assert peak_short <= 8 * band_plane
    # doubling the height must not move the peak: the transient is per band
    assert peak_tall <= peak_short * 1.05 + (1 << 20)


def test_blend_and_puppet_transients_are_bounded_by_the_band(qapp):
    w, short_h, tall_h = 2000, 1500, 3000
    rng = np.random.default_rng(11)
    pins = [((10, 10), (10, 10)), ((1000, 750), (1100, 700))]
    blend_peaks, warp_peaks = [], []
    for h in (short_h, tall_h):
        filtered = random_layer(rng, w, h)
        original = random_layer(rng, w, h)
        weights = rng.random((h, w), dtype=np.float32)
        blend_peaks.append(
            _peak_traced(partial(npimage.blend_by_weights, filtered, original, weights))
        )
        warp_peaks.append(_peak_traced(partial(npimage.puppet_warp, original, pins)))

    two_stacks = short_h * w * 4 * 4 * 2  # the pre-#347 (h, w, 4) float32 pair
    assert blend_peaks[0] < two_stacks
    assert blend_peaks[1] <= blend_peaks[0] * 1.05 + (1 << 20)
    assert warp_peaks[1] <= warp_peaks[0] * 1.05 + (1 << 20)
