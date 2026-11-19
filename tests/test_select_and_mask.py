# SPDX-License-Identifier: Apache-2.0
"""Comprehensive test suite for Select and Mask (Issue #417).

Covers:
1. Guided Filter matting accuracy (edge extraction and boundary alignment).
2. Smart Radius (adaptive bandwidth based on transition width).
3. Global refinements (smooth, feather, contrast steepening, shift edge morphology).
4. Color decontamination (normalized convolution interior-to-fringe bleed removal).
5. Headless CLI invocation (--refine-selection and --select-and-mask).
6. Desktop RefineSelectionDialog (live preview, undo tracking, accept/cancel lifecycle).
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainterPath

from photoslop import cli, npimage
from photoslop.commands import LayerRegionCommand
from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.refinedialog import RefineSelectionDialog


@pytest.fixture(autouse=True)
def _ensure_app(qapp):
    """Ensure QApplication is initialized for all tests in this module."""
    return qapp


def test_guided_filter_extracts_and_aligns_edge():
    """Guided filter should snap an inaccurate mask towards the true image boundary."""
    h, w = 40, 40
    # Image has true vertical boundary at x = 20:
    # Left is dark blue [0, 0, 100], right is bright yellow [255, 255, 0]
    guide = np.zeros((h, w, 3), dtype=np.uint8)
    guide[:, :20] = [0, 0, 100]
    guide[:, 20:] = [255, 255, 0]

    # Inaccurate mask: boundary is at x = 24 (4 pixels off into the right region)
    rough_mask = np.zeros((h, w), dtype=np.float32)
    rough_mask[:, 24:] = 1.0

    refined = npimage.guided_filter(guide, rough_mask, radius=6, eps=1e-3)

    # In the background region (x <= 19), refined mask should be very close to 0
    assert refined[20, 15] < 0.05
    # Near the true edge (x = 20..21), it should transition
    assert refined[20, 20] < refined[20, 24]
    # In the foreground region (x >= 24), it should be high
    assert refined[20, 30] > 0.70

    # With threshold 0.5, the edge moves towards x=20 compared to rough_mask at x=24
    refined_binary = refined >= 0.5
    true_fg_pixels = np.count_nonzero(refined_binary[:, 20:])
    false_bg_pixels = np.count_nonzero(refined_binary[:, :20])
    assert false_bg_pixels == 0
    assert true_fg_pixels > 0


def test_guided_filter_fine_hair_strand_extraction():
    """Guided filter captures thin 1-pixel high-contrast features (hair / fur)."""
    h, w = 30, 30
    guide = np.zeros((h, w, 3), dtype=np.float32)
    # Background is black; a thin 1px white strand runs down col 15
    guide[:, 15] = [1.0, 1.0, 1.0]

    # Initial coarse mask covers the rough area col 13..17
    coarse = np.zeros((h, w), dtype=np.float32)
    coarse[:, 13:18] = 0.5

    refined = npimage.guided_filter(guide, coarse, radius=3, eps=1e-3)
    # The 1px hair strand at col 15 should have significantly higher response than its neighbors
    assert refined[15, 15] > refined[15, 13]
    assert refined[15, 15] > refined[15, 17]


# -----------------------------------------------------------------------------
# 2. Smart Radius
# -----------------------------------------------------------------------------


def test_smart_radius_adapts_bandwidth():
    """Smart Radius narrows bandwidth on sharp edges and widens on soft transitions."""
    h, w = 40, 40

    # Sharp knife-edge step
    sharp_guide = np.zeros((h, w, 3), dtype=np.float32)
    sharp_guide[:, 20:] = 1.0
    mask = np.zeros((h, w), dtype=np.float32)
    mask[:, 20:] = 1.0

    refined_sharp = npimage.guided_filter(sharp_guide, mask, radius=8, eps=1e-3, smart_radius=True)
    refined_uniform = npimage.guided_filter(
        sharp_guide, mask, radius=8, eps=1e-3, smart_radius=False
    )

    # On a sharp step, smart radius maintains a tighter, sharper transition
    # (closer to 0 just outside and closer to 1 just inside)
    assert refined_sharp[20, 18] <= refined_uniform[20, 18] + 1e-4
    assert refined_sharp[20, 22] >= refined_uniform[20, 22] - 1e-4


# -----------------------------------------------------------------------------
# 3. Global Refinements: Smooth, Feather, Contrast, Shift Edge
# -----------------------------------------------------------------------------


def test_smooth_refinement():
    """Smooth removes single-pixel notches and bumps."""
    mask = np.zeros((40, 40), dtype=bool)
    mask[10:30, 10:30] = True
    # Cut a notch in top edge
    mask[10:14, 18:22] = False

    b_out, a_out, _ = npimage.refine_selection(mask, smooth=4)
    # Notch should be filled
    assert b_out[11, 20]
    # And overall boundary remains bounded
    assert b_out.sum() > mask.sum()


def test_feather_refinement():
    """Feather produces a soft 3-pass Gaussian falloff ramp."""
    mask = np.zeros((80, 80), dtype=bool)
    mask[20:60, 20:60] = True

    _, a_out, _ = npimage.refine_selection(mask, feather=8)
    # Center pixel remains 1.0
    assert a_out[40, 40] > 0.95
    # Pixel on the boundary is intermediate
    boundary_val = a_out[20, 40]
    assert 0.2 < boundary_val < 0.8
    # Outside pixel fades smoothly towards 0.0
    outside_val = a_out[5, 40]
    assert outside_val < 0.1


def test_contrast_steepens_transition():
    """Contrast steepens the alpha ramp around 50% threshold."""
    mask = np.zeros((40, 40), dtype=bool)
    mask[:, 20:] = True

    # First feather to create a smooth ramp
    _, feathered, _ = npimage.refine_selection(mask, feather=6)

    # Now apply contrast 50% vs 90%
    _, c50, _ = npimage.refine_selection(mask, feather=6, contrast=50)
    _, c90, _ = npimage.refine_selection(mask, feather=6, contrast=90)

    # At points above 0.5, higher contrast pushes closer to 1.0
    x_above = 23
    assert feathered[20, x_above] > 0.5
    assert c90[20, x_above] >= c50[20, x_above] >= feathered[20, x_above]

    # At points below 0.5, higher contrast pushes closer to 0.0
    x_below = 17
    assert feathered[20, x_below] < 0.5
    assert c90[20, x_below] <= c50[20, x_below] <= feathered[20, x_below]


def test_shift_edge_dilation_and_erosion():
    """Shift Edge expands on positive shift and contracts on negative shift."""
    mask = np.zeros((50, 50), dtype=bool)
    mask[20:30, 20:30] = True
    orig_count = np.count_nonzero(mask)

    expanded, _, _ = npimage.refine_selection(mask, shift=4)
    contracted, _, _ = npimage.refine_selection(mask, shift=-3)

    assert np.count_nonzero(expanded) > orig_count
    assert np.count_nonzero(contracted) < orig_count

    # Bounds expand and contract symmetrically
    ys_e, xs_e = np.where(expanded)
    assert xs_e.min() == 16 and xs_e.max() == 33
    assert ys_e.min() == 16 and ys_e.max() == 33

    ys_c, xs_c = np.where(contracted)
    assert xs_c.min() == 23 and xs_c.max() == 26
    assert ys_c.min() == 23 and ys_c.max() == 26


# -----------------------------------------------------------------------------
# 4. Color Decontamination
# -----------------------------------------------------------------------------


def test_color_decontamination_eliminates_fringe_bleed():
    """Normalized convolution extrapolates interior colors into fringe pixels."""
    h, w = 30, 30
    img = np.zeros((h, w, 3), dtype=np.uint8)
    # Foreground is pure red [255, 0, 0] on cols 0..14
    img[:, :15] = [255, 0, 0]
    # Background is bright green [0, 255, 0] on cols 15..30
    img[:, 15:] = [0, 255, 0]
    # Simulate green background bleed at col 14 (edge of foreground)
    img[:, 14] = [120, 180, 20]

    # Mask with fringe at col 14
    mask = np.zeros((h, w), dtype=bool)
    mask[:, :15] = True

    _, alpha, decontam = npimage.refine_selection(
        mask,
        image=img,
        radius=4,
        decontaminate=True,
        decontaminate_amount=1.0,
    )

    assert decontam is not None
    # Fringe pixel at col 14 should have its green bleed purged and red reinforced
    orig_fringe = img[15, 14]
    clean_fringe = decontam[15, 14]

    assert clean_fringe[0] > orig_fringe[0]  # Red significantly boosted
    assert clean_fringe[1] < orig_fringe[1]  # Green bleed eliminated / attenuated


# -----------------------------------------------------------------------------
# 5. CLI Invocation
# -----------------------------------------------------------------------------


def test_cli_refine_selection_execution(tmp_path):
    """CLI --refine-selection works end-to-end in a pipeline."""
    img_path = tmp_path / "input.png"
    out_path = tmp_path / "output.png"

    # Create a small test image
    qimg = QImage(60, 40, QImage.Format.Format_ARGB32_Premultiplied)
    qimg.fill(QColor(40, 40, 180))
    qimg.save(str(img_path))

    # Run with selection + refine-selection + fill-selection
    res = cli.main(
        [
            str(img_path),
            "--select",
            "10,10,20,20",
            "--refine-selection",
            "4,2,0,10,2,1",
            "--fill-selection",
            "255,0,0",
            "--output",
            str(out_path),
        ]
    )
    assert res == 0
    assert out_path.exists()

    result_img = QImage(str(out_path))
    # Center of refined selection should be filled with red
    center_color = result_img.pixelColor(20, 20)
    assert center_color.red() == 255


def test_cli_select_and_mask_alias(tmp_path):
    """CLI --select-and-mask alias functions identically to --refine-selection."""
    img_path = tmp_path / "in_alias.png"
    out_path = tmp_path / "out_alias.png"

    qimg = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    qimg.fill(QColor(0, 0, 0))
    qimg.save(str(img_path))

    res = cli.main(
        [
            str(img_path),
            "--select",
            "10,10,20,20",
            "--select-and-mask",
            "2,0,0,0,0",
            "--output",
            str(out_path),
        ]
    )
    assert res == 0
    assert out_path.exists()


def test_cli_refine_selection_requires_selection(tmp_path):
    """CLI --refine-selection fails cleanly if no selection is active."""
    img_path = tmp_path / "no_sel.png"
    qimg = QImage(20, 20, QImage.Format.Format_ARGB32_Premultiplied)
    qimg.fill(QColor(0, 0, 0))
    qimg.save(str(img_path))

    with pytest.raises(SystemExit) as exc:
        cli.main(
            [
                str(img_path),
                "--refine-selection",
                "5,0,0,0,0",
                "--output",
                str(tmp_path / "out.png"),
            ]
        )
    assert exc.value.code == 2


# -----------------------------------------------------------------------------
# 6. Desktop Dialog: RefineSelectionDialog
# -----------------------------------------------------------------------------


def test_dialog_accept_and_undo_tracking(qapp):
    """RefineSelectionDialog updates doc selection, records undo for decontamination."""
    win = MainWindow()
    doc = Document.new(QSize(60, 40), 72.0, "test_doc", QColor(100, 100, 100))
    win.add_document(doc)

    # Initial rectangular selection
    path = QPainterPath()
    path.addRect(QRect(15, 10, 20, 20))
    doc.set_selection(path)
    initial_path = doc.selection

    dialog = RefineSelectionDialog(doc, win)
    dialog.radius.setValue(4)
    dialog.smart_radius.setChecked(True)
    dialog.shift.setValue(3)
    dialog.decontaminate.setChecked(True)
    dialog.decontaminate_amount.setValue(80)

    # Preview runs
    dialog._debounce.stop()
    dialog._preview()
    assert doc.selection is not None
    assert doc.selection != initial_path

    # Accept commits selection and decontamination undo command
    dialog.accept()
    assert doc.undo_stack.count() == 1
    assert isinstance(doc.undo_stack.command(0), LayerRegionCommand)

    # Undo restores original layer pixels
    doc.undo_stack.undo()


def test_dialog_cancel_restores_all(qapp):
    """RefineSelectionDialog Cancel restores original selection and layer pixels."""
    win = MainWindow()
    doc = Document.new(QSize(50, 50), 72.0, "cancel_test", QColor(50, 150, 50))
    win.add_document(doc)

    orig_path = QPainterPath()
    orig_path.addRect(QRect(10, 10, 15, 15))
    doc.set_selection(orig_path)

    layer = doc.active_layer
    orig_pixel = layer.image.pixelColor(15, 15)

    dialog = RefineSelectionDialog(doc, win)
    dialog.shift.setValue(-20)  # Erodes to nothing in preview
    dialog.decontaminate.setChecked(True)
    dialog._debounce.stop()
    dialog._preview()

    assert doc.selection is None

    dialog.reject()
    # Cancel restores original selection and layer pixel
    assert doc.selection is orig_path
    assert layer.image.pixelColor(15, 15) == orig_pixel
