# SPDX-License-Identifier: Apache-2.0
"""Beam Dither (#384): the dither kernels, the beam model, and the filter.

The algorithms are tested as arithmetic rather than by eye. Each one has a
property that defines it — error diffusion preserves average tone, ordered
dithering depends on position alone, beam modulation deflects with the signal —
and those properties are what these tests pin, so a change that still "looks
dithered" but has stopped doing the actual thing turns them red.
"""

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage

from photoslop import dither, filters
from photoslop.npimage import view_u32


def make_image(plane: np.ndarray, alpha: int = 255) -> QImage:
    h, w = plane.shape
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    view = view_u32(img)
    g = np.rint(np.clip(plane, 0, 1) * 255).astype(np.uint32)
    scaled = np.rint(g * (alpha / 255.0)).astype(np.uint32)
    view[...] = (np.uint32(alpha) << 24) | (scaled << 16) | (scaled << 8) | scaled
    return img


def channels(img: QImage):
    v = view_u32(img)
    return (
        (v >> np.uint32(24)) & 0xFF,
        (v >> np.uint32(16)) & 0xFF,
        (v >> np.uint32(8)) & 0xFF,
        v & 0xFF,
    )


# ----- error diffusion -------------------------------------------------------


@pytest.mark.parametrize("kernel", sorted(dither.ERROR_KERNELS))
def test_error_diffusion_preserves_average_tone(kernel):
    """The defining property. A flat mid grey rendered to pure black and white
    must still average to mid grey — that is the entire point of pushing the
    rounding error into the neighbours rather than discarding it."""
    flat = np.full((64, 64), 0.5, np.float32)
    out = dither.error_diffuse(flat, kernel, 2)
    assert set(np.unique(out)) <= {0.0, 1.0}, "levels=2 must be strictly two-tone"
    assert out.mean() == pytest.approx(0.5, abs=0.01), kernel


@pytest.mark.parametrize("kernel", sorted(dither.ERROR_KERNELS))
def test_error_diffusion_tracks_a_ramp(kernel):
    """Tone is preserved locally, not just globally: a dark band stays darker
    than a bright one. A kernel wired up with the wrong signs can still average
    correctly overall while inverting locally."""
    ramp = np.tile(np.linspace(0, 1, 96, dtype=np.float32), (48, 1))
    out = dither.error_diffuse(ramp, kernel, 2)
    thirds = [out[:, :32].mean(), out[:, 32:64].mean(), out[:, 64:].mean()]
    assert thirds[0] < thirds[1] < thirds[2], kernel


def test_kernel_weights_are_the_published_ones():
    """Atkinson deliberately diffuses only 6/8 of the error — that deficit is
    why classic Macintosh dithers look crisp and slightly blown out. Every
    other kernel here conserves it exactly."""
    for name, (offsets, divisor) in dither.ERROR_KERNELS.items():
        total = sum(weight for _, _, weight in offsets)
        if name == "atkinson":
            assert (total, divisor) == (6, 8)
        else:
            assert total == divisor, name


def test_error_diffusion_only_writes_forward():
    """A pixel's error may only reach pixels not yet visited. If a kernel
    offset pointed backwards the render would depend on rows already emitted,
    which is unstable and would make the result depend on tiling."""
    for offsets in (k for k, _ in dither.ERROR_KERNELS.values()):
        for dx, dy, _ in offsets:
            assert dy > 0 or (dy == 0 and dx > 0)


# ----- ordered dithering -----------------------------------------------------


@pytest.mark.parametrize("size", [2, 4, 8, 16])
def test_bayer_matrix_is_a_full_permutation(size):
    """The recurrence must produce every threshold exactly once, strictly
    inside 0..1 — a duplicated or zero threshold is a band that never dithers."""
    matrix = dither.bayer_matrix(size)
    assert matrix.shape == (size, size)
    assert len(np.unique(matrix)) == size * size
    assert matrix.min() > 0.0 and matrix.max() < 1.0


def test_bayer_rejects_non_power_of_two():
    with pytest.raises(ValueError):
        dither.bayer_matrix(6)


def test_ordered_dither_depends_on_position_only():
    """No neighbour memory: the same tone at the same grid position always
    resolves the same way, which is what makes ordered dithering stable and
    tileable where error diffusion is neither."""
    flat = np.full((32, 32), 0.5, np.float32)
    first = dither.ordered_dither(flat, 4, 2)
    assert np.array_equal(first, dither.ordered_dither(flat, 4, 2))
    # The pattern repeats on the matrix period.
    assert np.array_equal(first[0:4, 0:4], first[4:8, 4:8])


def test_ordered_dither_preserves_a_ramp_on_average():
    ramp = np.tile(np.linspace(0, 1, 128, dtype=np.float32), (32, 1))
    assert dither.ordered_dither(ramp, 8, 2).mean() == pytest.approx(ramp.mean(), abs=0.02)


# ----- beam modulation -------------------------------------------------------


def test_beam_is_tonally_neutral_at_mid_grey():
    """An undeflected raster over flat mid grey must light half its area. If
    the coverage curve is wrong the whole image gains or loses a stop before
    any deflection is even applied."""
    flat = np.full((60, 60), 0.5, np.float32)
    assert dither.beam_mask(flat, 6, 0.0).mean() == pytest.approx(0.5, abs=0.02)


def test_beam_coverage_rises_with_luminance():
    """Coverage must climb monotonically with tone and actually reach both
    ends: a curve that saturates early would clip the highlights off, and one
    that never closes would leave white looking like grey stripes."""
    ramp = np.tile(np.linspace(0, 1, 120, dtype=np.float32), (60, 1))
    mask = dither.beam_mask(ramp, 6, 0.0)
    quarters = [mask[:, i : i + 30].mean() for i in range(0, 120, 30)]
    assert quarters == sorted(quarters)
    # The darkest and brightest columns, rather than quarter averages, are
    # where the ends of the range are actually visible.
    assert mask[:, :3].mean() < 0.05, "black should be very nearly unlit"
    assert mask[:, -3:].mean() > 0.9, "white should close up into solid"


def test_beam_without_deflection_is_pure_scanlines():
    """Amplitude zero must give identical columns: the raster alone, with the
    picture affecting only how much of each beam lights."""
    ramp = np.tile(np.linspace(0.2, 0.8, 40, dtype=np.float32), (40, 1))
    mask = dither.beam_mask(ramp, 5, 0.0)
    # Every column is the same beam profile, scaled by its own luminance, so
    # the *position* of the brightest row is shared.
    assert len({int(np.argmax(mask[:, x])) for x in range(40)}) == 1


def test_beam_deflects_where_the_picture_varies():
    """The feature itself: with amplitude, luminance displaces the beam, so
    columns of differing brightness no longer light the same rows. Without
    this the effect is just scanlines."""
    ramp = np.tile(np.linspace(0.0, 1.0, 40, dtype=np.float32), (40, 1))
    straight = dither.beam_mask(ramp, 5, 0.0)
    bent = dither.beam_mask(ramp, 5, 2.0)
    peaks = lambda m: {int(np.argmax(m[:, x])) for x in range(40)}  # noqa: E731
    assert len(peaks(straight)) == 1, "no amplitude should mean no bend"
    assert len(peaks(bent)) > 1, "amplitude should displace the beam"


# ----- the filter ------------------------------------------------------------


def test_filter_is_registered_and_parses_colours(qapp):
    cls = filters.available_filters()["beam-dither"]
    params = filters.parse_params(cls, "algorithm=beam,scale=4,background=#101010")
    assert params["background"] == "#101010"
    assert params["algorithm"] == "beam"
    assert params["scale"] == 4


def test_unknown_colour_falls_back_rather_than_raising():
    """These arrive from a free-text box; a half-typed colour must not abort a
    render in progress."""
    assert filters._hex_rgb("not a colour", (1, 2, 3)) == (1, 2, 3)
    assert filters._hex_rgb("#0f0", (0, 0, 0)) == (0, 255, 0)
    assert filters._hex_rgb("6CCFF6", (0, 0, 0)) == (108, 207, 246)


def test_tonal_mode_uses_exactly_the_four_inks(qapp):
    ramp = np.tile(np.linspace(0, 1, 120, dtype=np.float32), (120, 1))
    img = make_image(ramp)
    cls = filters.available_filters()["beam-dither"]
    cls().apply(
        img,
        filters.parse_params(
            cls,
            "algorithm=beam,mode=tonal,scale=1,background=#000000,"
            "shadows=#0B3C5D,midtones=#6CCFF6,highlights=#FFFFFF",
        ),
    )
    _, r, g, b = channels(img)
    used = set(zip(r.flatten().tolist(), g.flatten().tolist(), b.flatten().tolist(), strict=True))
    assert used <= {(0, 0, 0), (11, 60, 93), (108, 207, 246), (255, 255, 255)}
    assert (11, 60, 93) in used and (255, 255, 255) in used


def test_mono_mode_is_two_tone(qapp):
    ramp = np.tile(np.linspace(0, 1, 80, dtype=np.float32), (80, 1))
    img = make_image(ramp)
    cls = filters.available_filters()["beam-dither"]
    cls().apply(img, filters.parse_params(cls, "algorithm=floyd-steinberg,scale=1"))
    _, r, g, b = channels(img)
    assert set(np.unique(r).tolist()) <= {0, 255}


def test_alpha_is_preserved(qapp):
    """A dither must not turn a half-transparent layer opaque — the buffers are
    premultiplied, so getting this wrong is silent until something composites."""
    ramp = np.tile(np.linspace(0, 1, 40, dtype=np.float32), (40, 1))
    img = make_image(ramp, alpha=128)
    cls = filters.available_filters()["beam-dither"]
    cls().apply(img, filters.parse_params(cls, "algorithm=beam,scale=2"))
    a, _, _, _ = channels(img)
    assert set(np.unique(a).tolist()) == {128}


def test_colour_mode_keeps_channels_independent(qapp):
    """RGB mode dithers each channel separately, so a saturated red stays red
    rather than collapsing onto a grey mask."""
    h = w = 60
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(200, 40, 40))
    cls = filters.available_filters()["beam-dither"]
    cls().apply(img, filters.parse_params(cls, "algorithm=floyd-steinberg,mode=color,scale=1"))
    _, r, g, b = channels(img)
    assert r.mean() > g.mean() and r.mean() > b.mean()


def test_scale_makes_cells_not_pixels(qapp):
    """The cell size is what makes a dither read as chunky. At scale 4 the
    output must be constant within each 4x4 block."""
    ramp = np.tile(np.linspace(0, 1, 64, dtype=np.float32), (64, 1))
    img = make_image(ramp)
    cls = filters.available_filters()["beam-dither"]
    cls().apply(img, filters.parse_params(cls, "algorithm=bayer-4,scale=4"))
    _, r, _, _ = channels(img)
    block = r[4:8, 4:8]
    assert len(np.unique(block)) == 1
