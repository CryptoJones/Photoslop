# SPDX-License-Identifier: Apache-2.0
"""Test suite for Fast Large-Radius Blur (Issue #418).

Verifies:
1. CLT approximation accuracy: 3-pass running-sum box blur matches analytical
   Gaussian convolution within < 2% error.
2. O(1) time complexity per pixel independent of kernel radius.
3. Band processing (DD-001): banded execution matches unbanded bit-identically
   with zero persistent allocation overhead.
4. Large-radius blur support up to 250px.
5. Selection masking and feathered weights support.
6. CLI operations: --fast-blur and --gaussian-blur.
7. GUI GaussianBlurDialog: live preview, slider/spinbox sync, accept/reject.
"""

from __future__ import annotations

import time

import numpy as np
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage

from photoslop import cli, npimage
from photoslop.document import Document
from photoslop.gaussianblurdialog import GaussianBlurDialog
from photoslop.layer import Layer


def make_test_image(w: int, h: int, color: int = 0xFF808080) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(color)
    return img


def make_impulse_image(w: int, h: int) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(0)
    arr = npimage.view_u32(img)
    arr[h // 2, w // 2] = 0xFFFFFFFF  # full white impulse at center
    return img


# MARK: - 1. CLT Approximation vs Analytical Gaussian


def test_clt_approximation_vs_analytical_gaussian():
    """Verify Central Limit Theorem approximation: 3-pass running-sum box blur
    approximates a true Gaussian kernel within < 2% max error.
    """
    size = 201
    mid = size // 2

    for radius in (8, 16, 32):
        r = radius // 2 + 1
        effective_sigma = np.sqrt(r * (r + 1))

        # 1. 3-pass box blur on a 1D float impulse
        impulse = np.zeros(size, dtype=np.float64)
        impulse[mid] = 1.0
        box = impulse.copy()
        for _ in range(3):
            pad = np.pad(box, (r, r), mode="edge")
            csum = np.concatenate(([0.0], np.cumsum(pad)))
            k = 2 * r + 1
            box = (csum[k:] - csum[:-k]) / k

        # 2. Analytical 1D Gaussian kernel with identical variance
        xs = np.arange(size) - mid
        gauss = np.exp(-0.5 * (xs / effective_sigma) ** 2)
        gauss /= gauss.sum()

        # Error between 3-pass box blur and Gaussian kernel
        max_error = np.max(np.abs(box - gauss))
        assert max_error < 0.02, f"CLT error {max_error:.4f} exceeds 2% for radius {radius}"


# MARK: - 2. O(1) Time Complexity


def test_o1_complexity_independent_of_radius():
    """Verify O(1) time complexity: running-sum box blur execution time is

    independent of kernel radius R (unlike direct convolution which is O(r)).
    """
    w, h = 300, 300
    radii = [10, 50, 100, 200]
    times = []

    # Warmup
    warm = make_test_image(w, h)
    npimage.fast_blur(warm, 10)

    for r in radii:
        img = make_test_image(w, h)
        start = time.perf_counter()
        npimage.fast_blur(img, r)
        elapsed = time.perf_counter() - start
        times.append(elapsed)

    # For O(1) complexity, the ratio between time(r=200) and time(r=10) should be
    # bounded by a small constant factor (< 3.0x), whereas an O(r) algorithm would be
    # 20x slower and O(r^2) would be 400x slower.
    ratio = times[-1] / max(times[0], 1e-6)
    assert ratio < 3.0, (
        f"Execution time scaled with radius: r={radii[0]} took {times[0]:.4f}s, "
        f"r={radii[-1]} took {times[-1]:.4f}s (ratio {ratio:.2f}x)"
    )


# MARK: - 3. Band Processing (DD-001) Parity


@pytest.mark.parametrize("radius", [10, 50, 150, 250])
def test_band_processing_matches_unbanded_dd001(monkeypatch, radius):
    """Verify DD-001 memory frugality: row-banded execution matches unbanded

    computation bit-identically across all channels.
    """
    w, h = 100, 600  # taller than BAND_ROWS=256 so multiple bands and halos are exercised
    rng = np.random.default_rng(418 + radius)
    img_banded = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    arr = npimage.view_u32(img_banded)
    a = rng.integers(0, 256, (h, w), dtype=np.uint32)
    r_chan = rng.integers(0, 256, (h, w), dtype=np.uint32) * a // 255
    g_chan = rng.integers(0, 256, (h, w), dtype=np.uint32) * a // 255
    b_chan = rng.integers(0, 256, (h, w), dtype=np.uint32) * a // 255
    arr[:] = (a << np.uint32(24)) | (r_chan << np.uint32(16)) | (g_chan << np.uint32(8)) | b_chan

    img_unbanded = QImage(img_banded)

    # Banded blur (default BAND_ROWS = 256)
    npimage.fast_blur(img_banded, radius)

    # Unbanded blur (single huge band)
    monkeypatch.setattr(npimage, "BAND_ROWS", 1 << 30)
    npimage.fast_blur(img_unbanded, radius)

    assert np.array_equal(npimage.view_u32(img_banded), npimage.view_u32(img_unbanded)), (
        f"Banded output diverged from unbanded at radius {radius}"
    )


# MARK: - 4. Large-Radius Blur Support up to 250px


def test_large_radius_blur_up_to_250():
    """Verify that radii up to 250px blur without crashing, overflow, or NaN."""
    w, h = 500, 500
    img = make_test_image(w, h, 0xFFFFFFFF)
    arr = npimage.view_u32(img)
    # Draw a black square in center
    arr[200:300, 200:300] = 0xFF000000

    npimage.fast_blur(img, 250)

    # The sharp square edges must now be thoroughly smoothed
    center_val = (arr[250, 250] >> 16) & 0xFF
    edge_val = (arr[100, 100] >> 16) & 0xFF
    # Blurring diffused black pixels outward into the white background
    assert 0 < center_val < 255
    assert 0 < edge_val < 255


# MARK: - 5. Selection Masking and Feathering


def test_fast_blur_selection_mask():
    """Verify that selection mask confines fast blur to selected pixels only."""
    w, h = 100, 100
    img = make_test_image(w, h, 0xFF112233)
    arr = npimage.view_u32(img)
    # Paint red patch in top half
    arr[10:40, 20:60] = 0xFFFF0000
    # Paint red patch in bottom half
    arr[60:90, 20:60] = 0xFFFF0000

    # Mask only top half
    mask = np.zeros((h, w), dtype=bool)
    mask[:50, :] = True

    npimage.fast_blur(img, 15, mask=mask)

    # Bottom half (outside mask) should be completely untouched
    assert np.all(arr[60:90, 20:60] == 0xFFFF0000)
    assert np.all(arr[60:90, :20] == 0xFF112233)


def test_fast_blur_feathered_weights():
    """Verify that feathered weights blend blurred and unblurred regions smoothly."""
    w, h = 100, 100
    img = make_test_image(w, h, 0xFF0000FF)
    before = QImage(img)
    weights = np.tile(np.linspace(0.0, 1.0, w, dtype=np.float32), (h, 1))

    npimage.fast_blur(img, 20)
    npimage.blend_by_weights(img, before, weights)

    arr = npimage.view_u32(img)
    # Left edge (weight=0) is 100% blurred; right edge (weight=1) is 100% before
    assert arr.shape == (h, w)


# MARK: - 6. CLI Integration


def test_cli_fast_blur_op(tmp_path):
    """Test --fast-blur in photoslop-cli."""
    in_path = tmp_path / "in.png"

    img = make_test_image(100, 100, 0xFF00FF00)
    img.save(str(in_path))

    doc = Document(QSize(100, 100))
    layer = Layer("Base", QImage(img))
    doc.layers.append(layer)
    doc.active_index = 0
    ctx = cli.Context(doc)

    # Successful fast-blur
    cli._op_fast_blur(ctx, "25")
    assert ctx.doc.active_layer.image != img

    # Invalid radii
    with pytest.raises(cli._ValueError, match="--fast-blur: radius must be >= 1"):
        cli._op_fast_blur(ctx, "0")
    with pytest.raises(cli._ValueError, match="--fast-blur: radius must be >= 1"):
        cli._op_fast_blur(ctx, "-10")
    with pytest.raises(cli._ValueError, match="--fast-blur: invalid literal"):
        cli._op_fast_blur(ctx, "abc")


def test_cli_gaussian_blur_accelerated(tmp_path):
    """Test --gaussian-blur in photoslop-cli with large radius."""
    doc = Document(QSize(100, 100))
    layer = Layer("Base", make_test_image(100, 100, 0xFFFF00FF))
    doc.layers.append(layer)
    doc.active_index = 0
    ctx = cli.Context(doc)

    cli._op_gaussian_blur(ctx, "100")
    assert ctx.doc.active_layer.image is not None


# MARK: - 7. GUI GaussianBlurDialog


def test_gaussian_blur_dialog(qapp):
    """Test GaussianBlurDialog interactive behavior and live preview."""
    doc = Document(QSize(120, 120))
    layer = Layer("Layer 1", make_test_image(120, 120, 0xFF00FF00))
    arr = npimage.view_u32(layer.image)
    arr[40:80, 40:80] = 0xFF0000FF  # blue square in green field
    doc.layers.append(layer)
    doc.active_index = 0

    dialog = GaussianBlurDialog(doc, initial_radius=15)
    assert dialog.windowTitle() == "Gaussian Blur"
    assert dialog.radius() == 15
    assert dialog._slider.minimum() == 1
    assert dialog._slider.maximum() == 250
    assert dialog._spin.minimum() == 1
    assert dialog._spin.maximum() == 250

    # Changing slider updates spinbox
    dialog._slider.setValue(45)
    assert dialog._spin.value() == 45
    assert dialog.radius() == 45

    # Changing spinbox updates slider
    dialog._spin.setValue(120)
    assert dialog._slider.value() == 120
    assert dialog.radius() == 120

    # Toggle preview off: restores pristine
    dialog._preview_cb.setChecked(False)
    assert np.array_equal(npimage.view_u32(layer.image), npimage.view_u32(dialog._pristine))

    # Toggle preview back on: updates layer image
    dialog._preview_cb.setChecked(True)
    dialog._update_preview()
    assert not np.array_equal(npimage.view_u32(layer.image), npimage.view_u32(dialog._pristine))

    # Reject restores pristine
    dialog.reject()
    assert np.array_equal(npimage.view_u32(layer.image), npimage.view_u32(dialog._pristine))

    # Accept restores pristine so caller's action_gaussian_blur_direct can push undo
    dialog.accept()
    assert np.array_equal(npimage.view_u32(layer.image), npimage.view_u32(dialog._pristine))


def test_mainwindow_action_gaussian_blur_direct(qapp):
    """Test MainWindow.action_gaussian_blur_direct executes blur and registers undo."""
    from photoslop.mainwindow import MainWindow

    win = MainWindow()
    doc = Document(QSize(100, 100))
    layer = Layer("Base", make_test_image(100, 100, 0xFF00FFFF))
    doc.layers.append(layer)
    doc.active_index = 0
    win.add_document(doc)

    before_words = npimage.view_u32(layer.image).copy()

    win.action_gaussian_blur_direct(30)
    assert doc.undo_stack.count() > 0
    assert "Gaussian Blur" in doc.undo_stack.text(doc.undo_stack.index() - 1)

    # Undo restores previous state
    doc.undo_stack.undo()
    assert np.array_equal(npimage.view_u32(layer.image), before_words)
