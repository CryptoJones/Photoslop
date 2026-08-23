# SPDX-License-Identifier: Apache-2.0
"""Film Negative → Positive.

The interesting claim is not "the pixels got inverted" — it is that a scanned
colour negative comes back as the photograph that was on the film, with the
orange mask gone, and that a black-and-white negative comes back neutral rather
than tinted. Each test below builds a negative from a *known* positive, so the
result can be checked against the truth rather than against itself.
"""

import numpy as np
import pytest
from PySide6.QtGui import QImage

from photoslop.filters import available_filters, parse_params
from photoslop.npimage import view_u32

FMT = QImage.Format.Format_ARGB32_Premultiplied
ORANGE_MASK = (1.00, 0.55, 0.28)  # R, G, B transmittance of a C-41 film base


def filter_cls():
    return available_filters()["film-negative"]


def develop(rgb: np.ndarray, spec: str = "") -> np.ndarray:
    cls = filter_cls()
    image = make_image(rgb)
    cls().apply(image, parse_params(cls, spec))
    return rgb_of(image)


def make_image(rgb: np.ndarray) -> QImage:
    height, width, _ = rgb.shape
    image = QImage(width, height, FMT)
    arr = view_u32(image)
    arr[...] = (
        (np.uint32(255) << np.uint32(24))
        | (rgb[..., 0].astype(np.uint32) << np.uint32(16))
        | (rgb[..., 1].astype(np.uint32) << np.uint32(8))
        | rgb[..., 2].astype(np.uint32)
    )
    return image


def rgb_of(image: QImage) -> np.ndarray:
    arr = view_u32(image)
    return np.stack([(arr >> 16) & 0xFF, (arr >> 8) & 0xFF, arr & 0xFF], axis=-1).astype(np.int32)


def known_positive(height: int = 48, width: int = 48) -> np.ndarray:
    """Three independent ramps, so a per-channel error cannot hide."""
    y, x = np.mgrid[0:height, 0:width]
    positive = np.zeros((height, width, 3), dtype=np.int32)
    positive[..., 0] = x * 255 // (width - 1)
    positive[..., 1] = y * 255 // (height - 1)
    positive[..., 2] = (x + y) * 255 // (width + height - 2)
    return positive


def negative_of(positive: np.ndarray, mask=(1.0, 1.0, 1.0)) -> np.ndarray:
    """Expose film with the given base: reciprocal inversion, then the mask.

    Film records transmittance, so exposure is a reciprocal rather than
    ``255 - v``; building the fixture that way is what makes the round trip a
    real test of the filter's model instead of a test of its arithmetic.
    """
    linear = np.clip(positive, 1, 255) / 255.0
    exposed = 1.0 / (linear * 6.0 + 1.0)
    exposed = exposed / exposed.max()
    return np.clip(np.rint(exposed * np.array(mask) * 255), 1, 255).astype(np.int32)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.corrcoef(a.ravel(), b.ravel())[0, 1])


def test_colour_negative_develops_back_into_its_positive():
    positive = known_positive()
    developed = develop(negative_of(positive, ORANGE_MASK))
    for index, channel in enumerate("RGB"):
        assert correlation(developed[..., index], positive[..., index]) > 0.99, channel


def test_the_orange_mask_is_gone():
    """The mask leaves the negative strongly non-neutral; the positive must not
    inherit it. A plain 255-v inversion fails this — that is the whole point."""
    negative = negative_of(known_positive(), ORANGE_MASK)
    negative_spread = np.ptp(negative.reshape(-1, 3).mean(0))
    assert negative_spread > 50  # the fixture really does carry a mask

    developed = develop(negative)
    assert np.ptp(developed.reshape(-1, 3).mean(0)) < 10

    naive = 255 - negative  # what a simple invert would produce
    assert np.ptp(naive.reshape(-1, 3).mean(0)) > 50  # ... and it keeps the mask


def test_monochrome_negative_stays_neutral():
    """A faint warm base tint must not be stretched into a colour cast."""
    positive = known_positive()
    grey = np.repeat((positive.mean(-1, keepdims=True)).astype(np.int32), 3, axis=-1)
    negative = negative_of(grey, (1.04, 1.00, 0.97))

    developed = develop(negative)
    assert np.array_equal(developed[..., 0], developed[..., 1])
    assert np.array_equal(developed[..., 1], developed[..., 2])
    assert correlation(developed[..., 0], grey[..., 0]) > 0.99


def grey_positive() -> np.ndarray:
    positive = known_positive()
    return np.repeat(positive.mean(-1, keepdims=True).astype(np.int32), 3, axis=-1)


@pytest.mark.parametrize(
    ("subject", "mask", "expected"),
    [
        # A colour scene on masked film — the ordinary C-41 case.
        ("colour", ORANGE_MASK, "color"),
        # A colour scene on unmasked film is still a colour negative: the
        # detector keys on the scan being non-neutral, not on the mask alone.
        ("colour", (1.0, 1.0, 1.0), "color"),
        # A grey scene on a faintly warm acetate base is monochrome, and the
        # tint must not be mistaken for a mask.
        ("grey", (1.04, 1.00, 0.97), "mono"),
        ("grey", (1.0, 1.0, 1.0), "mono"),
        # A grey scene on *masked* film — a colour negative of a grey subject.
        # The mask alone makes it a colour negative, and it is one.
        ("grey", ORANGE_MASK, "color"),
    ],
)
def test_auto_detects_the_negative_type(subject, mask, expected):
    positive = grey_positive() if subject == "grey" else known_positive()
    developed = develop(negative_of(positive, mask))
    neutral = np.array_equal(developed[..., 0], developed[..., 2])
    assert neutral == (expected == "mono")


def test_mode_overrides_the_detection_in_both_directions():
    colour = negative_of(known_positive(), ORANGE_MASK)
    forced_mono = develop(colour, "mode=mono")
    assert np.array_equal(forced_mono[..., 0], forced_mono[..., 2])

    grey = negative_of(known_positive(), (1.04, 1.00, 0.97))
    forced_colour = develop(grey, "mode=color")
    assert not np.array_equal(forced_colour[..., 0], forced_colour[..., 2])


def test_clip_widens_the_range_it_throws_away():
    """A stray bright speck should not define the whole scale. With no clipping
    it does; with clipping the rest of the frame keeps its contrast."""
    negative = negative_of(known_positive(), ORANGE_MASK)
    negative[0, 0] = [255, 255, 255]  # scanner flare / clear film edge

    tight = develop(negative.copy(), "clip=0.0")
    clipped = develop(negative.copy(), "clip=2.0")
    assert clipped.std() >= tight.std()


def test_alpha_is_untouched_and_transparent_pixels_do_not_skew_the_result():
    negative = negative_of(known_positive(), ORANGE_MASK)
    image = make_image(negative)
    arr = view_u32(image)
    arr[:8, :] = 0  # a fully transparent band, premultiplied to zero

    cls = filter_cls()
    cls().apply(image, parse_params(cls, ""))
    assert (((view_u32(image)[:8, :] >> 24) & 0xFF) == 0).all()

    # The opaque remainder still develops correctly despite the empty band,
    # because the statistics only count pixels that carry any alpha.
    positive = known_positive()
    developed = rgb_of(image)[8:]
    assert correlation(developed[..., 0], positive[8:, :, 0]) > 0.99


def test_a_flat_frame_does_not_divide_by_zero():
    flat = np.full((16, 16, 3), 128, dtype=np.int32)
    developed = develop(flat)
    assert developed.shape == flat.shape  # no crash, no NaN escaping into pixels


def test_an_empty_layer_is_left_alone():
    cls = filter_cls()
    image = QImage(8, 8, FMT)
    view_u32(image)[...] = 0
    cls().apply(image, parse_params(cls, ""))
    assert (view_u32(image) == 0).all()
