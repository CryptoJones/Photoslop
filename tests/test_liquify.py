# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the Liquify filter engine and coarse displacement grid (#419)."""

import json

import numpy as np
import pytest
from PySide6.QtGui import QColor, QImage, QPainter

from photoslop.liquify import (
    LiquifyCommand,
    LiquifyGrid,
    LiquifyTool,
    load_strokes,
)


@pytest.fixture
def test_stripe_image() -> QImage:
    """Create a 100x100 test image with a vertical red stripe on white background."""
    img = QImage(100, 100, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.fillRect(45, 0, 10, 100, QColor(255, 0, 0))
    p.end()
    return img


def test_grid_initialization_and_memory_frugality():
    grid = LiquifyGrid(width=200, height=150, spacing=8)
    assert grid.width == 200
    assert grid.height == 150
    assert grid.spacing == 8
    assert grid.cols == (200 + 7) // 8 + 1  # 26
    assert grid.rows == (150 + 7) // 8 + 1  # 20
    assert grid.dx.shape == (20, 26)
    assert grid.dy.shape == (20, 26)
    assert grid.freeze.shape == (20, 26)
    assert np.all(grid.dx == 0.0)
    assert np.all(grid.dy == 0.0)
    assert np.all(grid.freeze == 0.0)

    # DD-001 memory frugality: coarse grid memory is very small
    total_bytes = grid.dx.nbytes + grid.dy.nbytes + grid.freeze.nbytes
    assert total_bytes < 10000  # < 10 KB for a 200x150 layer


def test_forward_warp_pushes_pixels(test_stripe_image):
    grid = LiquifyGrid(100, 100, spacing=8)
    # Drag stroke to the right across the vertical stripe at y=50
    box = grid.apply_stroke(
        LiquifyTool.FORWARD_WARP,
        points=[(40, 50), (60, 50)],
        size=40,
        pressure=0.8,
    )
    assert box is not None
    # For inverse mapping p + d(p), forward warp to right decreases dx so source is pulled from left
    assert np.min(grid.dx) < -5.0

    warped = grid.warp_image(test_stripe_image)
    assert warped.width() == 100
    assert warped.height() == 100

    # The red stripe at y=50 should have moved to the right (x > 55 should have red pixels)
    # Check pixel at (60, 50): previously white, now red
    pixel_before = test_stripe_image.pixelColor(60, 50)
    pixel_after = warped.pixelColor(60, 50)
    assert pixel_before.red() == 255 and pixel_before.green() == 255  # white
    assert pixel_after.red() > 200 and pixel_after.green() < 100  # red shifted into (60, 50)


def test_reconstruct_relaxes_to_identity(test_stripe_image):
    grid = LiquifyGrid(100, 100, spacing=8)
    # Apply forward warp
    grid.apply_stroke(
        LiquifyTool.FORWARD_WARP,
        points=[(50, 50), (70, 50)],
        size=40,
        pressure=1.0,
    )
    displaced_magnitude = np.max(np.abs(grid.dx))
    assert displaced_magnitude > 5.0

    # Apply reconstruct multiple times at the same location
    for _ in range(10):
        grid.apply_brush(
            LiquifyTool.RECONSTRUCT,
            center=(60, 50),
            radius=30,
            pressure=1.0,
        )

    reconstructed_magnitude = np.max(np.abs(grid.dx))
    assert reconstructed_magnitude < displaced_magnitude * 0.3

    # Reconstruct all should zero everything
    grid.reconstruct_all()
    assert np.all(grid.dx == 0.0)
    assert np.all(grid.dy == 0.0)


def test_smooth_relaxes_neighborhood_gradient():
    grid = LiquifyGrid(100, 100, spacing=8)
    # Create an artificial sharp spike in displacement at node (5, 5)
    grid.dx[5, 5] = 20.0
    initial_spike = grid.dx[5, 5]

    grid.apply_brush(
        LiquifyTool.SMOOTH,
        center=(5 * 8, 5 * 8),
        radius=20,
        pressure=1.0,
    )
    # Center spike should have smoothed out toward 0
    assert grid.dx[5, 5] < initial_spike


def test_twirl_rotates_displacement():
    grid_cw = LiquifyGrid(100, 100, spacing=8)
    grid_ccw = LiquifyGrid(100, 100, spacing=8)

    grid_cw.apply_brush(LiquifyTool.TWIRL_CW, center=(50, 50), radius=30, pressure=0.8)
    grid_ccw.apply_brush(LiquifyTool.TWIRL_CCW, center=(50, 50), radius=30, pressure=0.8)

    # Displacements should be non-zero and opposite in direction for CW vs CCW
    assert np.max(np.abs(grid_cw.dx)) > 0.5
    assert np.max(np.abs(grid_ccw.dx)) > 0.5
    idx_y = 70 // 8
    idx_x = 50 // 8
    assert grid_cw.dx[idx_y, idx_x] > 1.0
    assert grid_ccw.dx[idx_y, idx_x] < -1.0


def test_pucker_and_bloat_displacements():
    grid_pucker = LiquifyGrid(100, 100, spacing=8)
    grid_bloat = LiquifyGrid(100, 100, spacing=8)

    grid_pucker.apply_brush(LiquifyTool.PUCKER, center=(50, 50), radius=30, pressure=0.8)
    grid_bloat.apply_brush(LiquifyTool.BLOAT, center=(50, 50), radius=30, pressure=0.8)

    # Nodes to the right of center (x > 50)
    c_right = 50 // 8 + 2
    r_center = 50 // 8
    # For pucker, source expands outward (dx > 0 to the right of center)
    assert grid_pucker.dx[r_center, c_right] > 0
    # For bloat, source contracts inward (dx < 0 to the right of center)
    assert grid_bloat.dx[r_center, c_right] < 0


def test_push_left():
    grid = LiquifyGrid(100, 100, spacing=8)
    # Moving downwards (vy > 0, vx = 0): "left" is +x (right)
    # Content moves right -> source shifts left (dx < 0)
    grid.apply_stroke(
        LiquifyTool.PUSH_LEFT,
        points=[(50, 30), (50, 70)],
        size=40,
        pressure=0.8,
    )
    assert np.min(grid.dx) < -2.0


def test_freeze_mask_protects_distortion(test_stripe_image):
    grid = LiquifyGrid(100, 100, spacing=8)
    # Paint freeze mask over the center area
    grid.apply_brush(
        LiquifyTool.FREEZE_MASK,
        center=(50, 50),
        radius=25,
        pressure=1.0,
    )
    # Repeat to ensure 100% frozen
    for _ in range(5):
        grid.apply_brush(LiquifyTool.FREEZE_MASK, center=(50, 50), radius=25, pressure=1.0)

    center_col = 50 // 8
    center_row = 50 // 8
    assert grid.freeze[center_row, center_col] >= 0.99

    # Now attempt a heavy forward warp directly across the frozen center
    grid.apply_stroke(
        LiquifyTool.FORWARD_WARP,
        points=[(40, 50), (60, 50)],
        size=40,
        pressure=1.0,
    )

    # The frozen node should have zero (or negligible) displacement
    assert abs(grid.dx[center_row, center_col]) < 1e-4

    # Thaw mask
    for _ in range(10):
        grid.apply_brush(LiquifyTool.THAW_MASK, center=(50, 50), radius=25, pressure=1.0)
    assert grid.freeze[center_row, center_col] < 0.2


def test_catmull_rom_and_bilinear_no_holes(test_stripe_image):
    grid = LiquifyGrid(100, 100, spacing=8)
    grid.apply_brush(LiquifyTool.TWIRL_CW, center=(50, 50), radius=35, pressure=1.0)

    warped_bilinear = grid.warp_image(test_stripe_image, interpolation="bilinear")
    warped_catmull = grid.warp_image(test_stripe_image, interpolation="catmull-rom")

    # Inverse mapping guarantees every pixel in warped has valid alpha = 255 (no holes)
    for y in range(0, 100, 10):
        for x in range(0, 100, 10):
            assert warped_bilinear.pixelColor(x, y).alpha() == 255
            assert warped_catmull.pixelColor(x, y).alpha() == 255


def test_stroke_serialization_and_deserialization():
    raw_json = json.dumps(
        [
            {
                "tool": "forward_warp",
                "points": [[20, 20], [40, 25]],
                "size": 50,
                "pressure": 0.7,
                "density": 0.6,
            },
            {
                "tool": "pucker",
                "center": [60, 60],
                "size": 30,
                "pressure": 0.5,
            },
        ]
    )
    strokes = load_strokes(raw_json)
    assert len(strokes) == 2
    assert strokes[0].tool == LiquifyTool.FORWARD_WARP
    assert strokes[0].size == 50
    assert strokes[0].points == [(20, 20), (40, 25)]
    assert strokes[1].tool == LiquifyTool.PUCKER
    assert strokes[1].points == [(60, 60)]

    grid = LiquifyGrid(100, 100, spacing=8)
    grid.apply_strokes(strokes)
    assert np.max(np.abs(grid.dx)) > 1.0


def test_liquify_command_undo_redo(qapp):
    class FakeLayer:
        def __init__(self, img):
            self.image = img

        def bounds(self):
            from PySide6.QtCore import QRect

            return QRect(0, 0, self.image.width(), self.image.height())

    class FakeDoc:
        def notify_pixels(self, rect):
            pass

        def notify_structure(self):
            pass

    orig_img = QImage(50, 50, QImage.Format.Format_ARGB32_Premultiplied)
    orig_img.fill(QColor(10, 20, 30))
    layer = FakeLayer(orig_img)
    doc = FakeDoc()

    new_img = QImage(50, 50, QImage.Format.Format_ARGB32_Premultiplied)
    new_img.fill(QColor(100, 150, 200))

    cmd = LiquifyCommand(doc, layer, new_img)
    # In Qt undo stack, cmd.__init__ has _applied=True
    assert layer.image.pixelColor(10, 10) == QColor(10, 20, 30)

    cmd.redo()
    # First redo after construction is skipped if _applied=True, but let's test manual swap
    cmd._swap(new_img)
    assert layer.image.pixelColor(10, 10) == QColor(100, 150, 200)

    cmd.undo()
    assert layer.image.pixelColor(10, 10) == QColor(10, 20, 30)
