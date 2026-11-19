# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter

from photoslop import npimage


def test_poisson_laplace_ramp_reconstruction():
    """Laplace equation Δf = 0 has a unique solution that exactly reproduces
    linear ramps from boundary conditions."""
    h, w = 48, 48
    yy, xx = np.ogrid[:h, :w]
    ground_truth = (20.0 + 1.5 * xx + 2.5 * yy).astype(np.float32)
    dest = ground_truth.copy()
    dest = np.repeat(dest[None, :, :], 3, axis=0)

    mask = np.zeros((h, w), dtype=bool)
    mask[12:36, 12:36] = True
    dest[:, mask] = 0.0  # erase inside hole

    res = npimage.poisson_solve_multigrid(dest, mask, src=None, omega=1.7)
    err = np.abs(res[0, mask] - ground_truth[mask]).max()
    assert err < 0.05, f"Ramp reconstruction error too high: {err}"


def test_poisson_seamless_cloning_texture_and_tone():
    """Seamless cloning transplants source texture gradients onto destination
    low-frequency illumination."""
    h, w = 40, 40
    dest = np.full((3, h, w), 50.0, dtype=np.float32)

    # High frequency checkerboard texture in source
    src = np.zeros((3, h, w), dtype=np.float32)
    yy, xx = np.ogrid[:h, :w]
    checker = ((yy // 4) + (xx // 4)) % 2 == 0
    src[:, checker] = 220.0
    src[:, ~checker] = 160.0  # mean is 190.0

    mask = np.zeros((h, w), dtype=bool)
    mask[10:30, 10:30] = True

    res = npimage.poisson_solve_multigrid(dest, mask, src=src, mixed=False, omega=1.7)

    inside = res[0, 10:30, 10:30]
    # Tone shifted to match destination (50.0)
    assert abs(inside.mean() - 50.0) < 1.0
    # Checkerboard variance is preserved
    assert inside.var() > 700.0
    # Boundary matches destination exactly
    assert res[0, 9, 20] == 50.0
    assert res[0, 30, 20] == 50.0


def test_poisson_mixed_gradients():
    """With mixed gradients, the larger gradient magnitude between source and
    destination is preserved."""
    h, w = 36, 36
    dest = np.full((3, h, w), 100.0, dtype=np.float32)
    # Put a sharp edge in destination
    dest[:, :, 18:] = 180.0

    src = np.full((3, h, w), 120.0, dtype=np.float32)
    # Put a sharp horizontal edge in source
    src[:, 18:, :] = 40.0

    mask = np.zeros((h, w), dtype=bool)
    mask[8:28, 8:28] = True

    res = npimage.poisson_solve_multigrid(dest, mask, src=src, mixed=True, omega=1.7)
    # Destination vertical edge at x=18 is preserved
    diff_dest = res[0, 12, 19] - res[0, 12, 17]
    assert diff_dest > 40.0
    # Source horizontal edge at y=18 is preserved
    diff_src = res[0, 17, 24] - res[0, 19, 24]
    assert diff_src > 40.0


def test_heal_patch_multigrid():
    src_img = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    src_img.fill(QColor(200, 200, 200))
    p = QPainter(src_img)
    p.fillRect(QRect(8, 8, 16, 16), QColor(240, 240, 240))
    p.end()

    dst_img = QImage(32, 32, QImage.Format.Format_ARGB32_Premultiplied)
    dst_img.fill(QColor(60, 60, 60))

    healed = npimage.heal_patch(src_img, dst_img)
    assert healed.size() == QSize(32, 32)
    center_color = healed.pixelColor(16, 16)
    # Tone pulled down toward dark destination
    assert center_color.red() < 120
    # Outer border is unchanged destination
    assert healed.pixelColor(0, 0) == QColor(60, 60, 60)


def test_patch_heal_multigrid():
    img = QImage(64, 64, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(150, 150, 150))
    p = QPainter(img)
    p.fillRect(QRect(10, 10, 12, 12), QColor(220, 220, 220))  # texture source
    p.fillRect(QRect(40, 40, 12, 12), QColor(0, 0, 0))  # blemish destination
    p.end()

    mask = np.zeros((64, 64), dtype=bool)
    mask[40:52, 40:52] = True

    # dx = 10 - 40 = -30, dy = 10 - 40 = -30
    rect = npimage.patch_heal(img, mask, -30, -30)
    assert not rect.isEmpty()
    healed_px = img.pixelColor(46, 46)
    assert healed_px.red() > 130


def test_inpaint_poisson_canvas_boundary():
    """Inpainting must handle holes touching canvas boundaries cleanly."""
    img = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(180, 180, 180))
    p = QPainter(img)
    p.fillRect(QRect(0, 0, 10, 10), QColor(10, 10, 10))  # touches top-left
    p.end()

    mask = np.zeros((40, 40), dtype=bool)
    mask[0:10, 0:10] = True

    dirty = npimage.inpaint_poisson(img, mask)
    assert not dirty.isEmpty()
    healed = img.pixelColor(2, 2)
    assert healed.red() > 140


def test_poisson_large_constant_offset_clone():
    """A large interior mask with a flat source must converge to the exact
    harmonic offset everywhere — the coarse solve has to carry the boundary
    offset to the centre, not leave it at the source value (issue #415)."""
    n = 1024
    dest = np.full((3, n, n), 60.0, dtype=np.float32)
    src = np.full((3, n, n), 220.0, dtype=np.float32)
    mask = np.zeros((n, n), dtype=bool)
    mask[8:-8, 8:-8] = True

    res = npimage.poisson_solve_multigrid(dest, mask, src=src, mixed=False)
    inside = res[0, 8:-8, 8:-8]
    # Correct offset is -160 throughout: f = 220 - 160 = 60.
    assert abs(float(res[0, n // 2, n // 2]) - 60.0) < 0.5
    assert np.abs(inside - 60.0).max() < 1.0


def test_poisson_large_hole_ramp_center():
    """The harmonic fill of a large hole must reproduce a linear ramp at the
    centre, not just near the boundary (residual-stopped multigrid)."""
    n = 600
    yy, xx = np.ogrid[:n, :n]
    gt = (20.0 + 0.05 * xx + 0.08 * yy).astype(np.float32)  # stays within u8
    dest = np.repeat(gt[None], 3, axis=0)
    mask = np.zeros((n, n), dtype=bool)
    mask[4:-4, 4:-4] = True
    dest[:, mask] = 0.0

    res = npimage.poisson_solve_multigrid(dest, mask, src=None)
    assert abs(float(res[0, n // 2, n // 2]) - float(gt[n // 2, n // 2])) < 0.5
    assert np.abs(res[0, mask] - gt[mask]).max() < 0.5


def test_heal_patch_explicit_mask_touching_edge():
    """An explicit mask that selects a blemish on the patch edge must still be
    healed (the solver ghost-pads touched edges), not left unchanged."""
    dst = QImage(9, 9, QImage.Format.Format_ARGB32_Premultiplied)
    dst.fill(QColor(100, 100, 100))
    p = QPainter(dst)
    p.fillRect(QRect(0, 3, 1, 3), QColor(0, 0, 0))  # blemish on the left edge
    p.end()
    src = QImage(9, 9, QImage.Format.Format_ARGB32_Premultiplied)
    src.fill(QColor(200, 200, 200))

    mask = np.zeros((9, 9), dtype=bool)
    mask[3:6, 0] = True  # touches column 0
    healed = npimage.heal_patch(src, dst, mask=mask)
    # The dark edge blemish is filled toward the surrounding tone.
    assert healed.pixelColor(0, 4).red() > 50
    # An unmasked interior pixel keeps the destination tone.
    assert healed.pixelColor(5, 5).red() == 100


def test_heal_patch_too_small_preserves_destination_alpha():
    """A patch too small to solve returns the destination, preserving its
    alpha — an opaque source must not make a transparent destination opaque."""
    src = QImage(8, 2, QImage.Format.Format_ARGB32_Premultiplied)
    src.fill(QColor(255, 255, 255, 255))
    dst = QImage(8, 2, QImage.Format.Format_ARGB32_Premultiplied)
    dst.fill(QColor(0, 0, 0, 0))  # fully transparent

    healed = npimage.heal_patch(src, dst)
    assert healed.size() == QSize(8, 2)
    assert healed.pixelColor(0, 0).alpha() == 0
    assert healed.pixelColor(7, 1).alpha() == 0


def test_patch_heal_source_footprint_at_canvas_edge():
    """A dab whose sampled source footprint fits on-canvas must heal even when
    the solver halo around it crosses the edge (halo is replicated, not
    refused) — issue #415 / CodeRabbit npimage.py:911."""
    img = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(60, 60, 60))
    p = QPainter(img)
    # Distinct checker texture near the left edge (the sampled source region).
    for y in range(16, 25):
        for x in range(0, 9):
            c = 220 if ((x // 2) + (y // 2)) % 2 == 0 else 160
            p.fillRect(QRect(x, y, 1, 1), QColor(c, c, c))
    # Reset the destination dab to flat 60 so it starts untextured.
    p.fillRect(QRect(2, 18, 5, 5), QColor(60, 60, 60))
    p.end()

    mask = np.zeros((40, 60), dtype=bool)
    mask[18:23, 2:7] = True  # dab near left edge
    pts = [(x, y) for y in range(18, 23) for x in range(2, 7)]
    before = [img.pixelColor(x, y).red() for x, y in pts]
    # dx = -2: source footprint x=0..4 fits, but the pad-4 halo reaches x=-2.
    rect = npimage.patch_heal(img, mask, -2, 0)
    assert not rect.isEmpty(), "valid source footprint must not be refused"
    after = [img.pixelColor(x, y).red() for x, y in pts]
    assert any(a != b for a, b in zip(before, after, strict=True)), "texture must transfer"
    # An unmasked pixel far from the dab is untouched.
    assert img.pixelColor(30, 20).red() == 60


def test_patch_heal_refuses_offcanvas_source_footprint():
    """When a masked pixel's actual source lies off-canvas, the heal is refused
    (empty rect) rather than silently writing an unchanged result."""
    img = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(60, 60, 60))
    mask = np.zeros((40, 60), dtype=bool)
    mask[18:23, 2:7] = True
    rect = npimage.patch_heal(img, mask, -10, 0)  # source x = -8..-3: off-canvas
    assert rect.isEmpty()
    assert img.pixelColor(4, 20).red() == 60


def test_poisson_clone_highfreq_texture_tone_matched():
    """A near-Nyquist (single-pixel checkerboard) source must be tone-matched to
    the destination across a large hole, not aliased to one phase by the coarse
    restriction (issue #415 / CodeRabbit npimage.py:350). Injection restriction
    sampled only the 220 phase, biasing the coarse harmonic offset to −160
    instead of −130; aligned full-weighting restriction preserves the source
    mean (190) so the cloned tone matches the destination everywhere."""
    n = 256
    yy, xx = np.ogrid[:n, :n]
    dest = np.full((3, n, n), 60.0, dtype=np.float32)
    src = np.zeros((3, n, n), dtype=np.float32)
    phase0 = ((yy + xx) % 2) == 0
    src[:, phase0] = 220.0
    src[:, ~phase0] = 160.0  # mean is 190.0
    mask = np.zeros((n, n), dtype=bool)
    mask[8:-8, 8:-8] = True

    res = npimage.poisson_solve_multigrid(dest, mask, src=src, mixed=False)
    # Correct harmonic offset is 60 − 190 = −130 throughout the interior.
    assert abs(float(res[0, mask].mean()) - 60.0) < 1.0
    c = n // 2
    assert abs(float(res[0, c, c]) - 90.0) < 1.0  # 220 − 130
    assert abs(float(res[0, c, c + 1]) - 30.0) < 1.0  # 160 − 130
