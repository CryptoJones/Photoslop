# SPDX-License-Identifier: Apache-2.0
import time

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

    t0 = time.perf_counter()
    res = npimage.poisson_solve_multigrid(dest, mask, src=src, mixed=False, omega=1.7)
    elapsed = (time.perf_counter() - t0) * 1000.0
    assert elapsed < 100.0, f"Multigrid solver too slow: {elapsed:.2f} ms"

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
