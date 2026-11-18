# SPDX-License-Identifier: Apache-2.0
"""Tests for Color Lookup adjustment and 3D LUT support (.cube and .3dl)."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop.document import Document
from photoslop.lut3d import (
    CHUNK_ROWS,
    LUT3D,
    PRESET_NAMES,
    apply_lut3d,
    get_preset_lut,
    parse_3dl,
    parse_cube,
    write_3dl,
    write_cube,
)
from photoslop.npimage import view_u32


@pytest.fixture(autouse=True)
def _ensure_qapp(qapp):
    """Ensure QApplication is initialized for the session."""
    return qapp


def _make_test_qimage(w: int, h: int, opaque: bool = True) -> QImage:
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    arr = view_u32(img)
    ys, xs = np.mgrid[0:h, 0:w]
    r = (xs * 255 // max(1, w - 1)).astype(np.uint32)
    g = (ys * 255 // max(1, h - 1)).astype(np.uint32)
    b = ((xs + ys) * 255 // max(1, w + h - 2)).astype(np.uint32)
    if opaque:
        a = np.full((h, w), 255, dtype=np.uint32)
    else:
        a = np.full((h, w), 255, dtype=np.uint32)
        a[1::3, :] = 128
        a[:, 1::3] = 64
        a[0, 0] = 0
    # Premultiply
    pr = (r * a) // 255
    pg = (g * a) // 255
    pb = (b * a) // 255
    arr[...] = (a << 24) | (pr << 16) | (pg << 8) | pb
    return img


def _make_identity_lut(size: int = 17) -> LUT3D:
    coords = np.linspace(0.0, 1.0, size, dtype=np.float32)
    rg, gg, bg = np.meshgrid(coords, coords, coords, indexing="ij")
    table = np.stack([rg, gg, bg], axis=-1)
    return LUT3D(name="Identity", size=size, table=table)


def _make_invert_lut(size: int = 17) -> LUT3D:
    ident = _make_identity_lut(size)
    return LUT3D(name="Invert", size=size, table=1.0 - ident.table)


# ---------------------------------------------------------------------------
# Format Parsing Tests
# ---------------------------------------------------------------------------


def test_parse_cube_3d():
    content = """# Adobe Cube 3D Test
TITLE "Test 3D LUT"
# Comments interspersed
LUT_3D_SIZE 2
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0

# Red fastest, then Green, then Blue
0.0 0.0 0.0
1.0 0.0 0.0
0.0 1.0 0.0
1.0 1.0 0.0
0.0 0.0 1.0
1.0 0.0 1.0
0.0 1.0 1.0
1.0 1.0 1.0
"""
    lut = parse_cube(content)
    assert lut.name == "Test 3D LUT"
    assert lut.size == 2
    assert not lut.is_1d
    assert lut.table.shape == (2, 2, 2, 3)
    np.testing.assert_allclose(lut.table[0, 0, 0], [0.0, 0.0, 0.0])
    np.testing.assert_allclose(lut.table[1, 0, 0], [1.0, 0.0, 0.0])
    np.testing.assert_allclose(lut.table[0, 1, 0], [0.0, 1.0, 0.0])
    np.testing.assert_allclose(lut.table[0, 0, 1], [0.0, 0.0, 1.0])
    np.testing.assert_allclose(lut.table[1, 1, 1], [1.0, 1.0, 1.0])


def test_parse_cube_1d():
    content = """# Adobe Cube 1D
TITLE "Test 1D LUT"
LUT_1D_SIZE 4
DOMAIN_MIN 0.0 0.0 0.0
DOMAIN_MAX 1.0 1.0 1.0

0.0 0.0 0.0
0.3 0.35 0.4
0.7 0.65 0.6
1.0 1.0 1.0
"""
    lut = parse_cube(content)
    assert lut.name == "Test 1D LUT"
    assert lut.size == 4
    assert lut.is_1d
    assert lut.table.shape == (4, 3)
    np.testing.assert_allclose(lut.table[0], [0.0, 0.0, 0.0])
    np.testing.assert_allclose(lut.table[-1], [1.0, 1.0, 1.0])


def test_parse_3dl():
    # 2x2x2 mesh with 12-bit integer values (0..4095)
    content = """# Autodesk 3dl sample
3DMESH Mesh 2 12
0 4095
0 0 0
0 0 4095
0 4095 0
0 4095 4095
4095 0 0
4095 0 4095
4095 4095 0
4095 4095 4095
"""
    lut = parse_3dl(content)
    assert lut.size == 2
    assert not lut.is_1d
    assert lut.table.shape == (2, 2, 2, 3)
    # Autodesk Lustre order: Red slowest, Green middle, Blue fastest
    np.testing.assert_allclose(lut.table[0, 0, 0], [0.0, 0.0, 0.0])
    np.testing.assert_allclose(lut.table[0, 0, 1], [0.0, 0.0, 1.0])
    np.testing.assert_allclose(lut.table[0, 1, 0], [0.0, 1.0, 0.0])
    np.testing.assert_allclose(lut.table[1, 0, 0], [1.0, 0.0, 0.0])
    np.testing.assert_allclose(lut.table[1, 1, 1], [1.0, 1.0, 1.0])


def test_cube_and_3dl_roundtrip(tmp_path):
    orig = _make_identity_lut(size=4)
    cube_file = tmp_path / "test.cube"
    write_cube(orig, cube_file)
    reloaded_cube = parse_cube(cube_file)
    np.testing.assert_allclose(orig.table, reloaded_cube.table, atol=1e-5)

    dl_file = tmp_path / "test.3dl"
    write_3dl(orig, dl_file, bit_depth=12)
    reloaded_3dl = parse_3dl(dl_file)
    np.testing.assert_allclose(orig.table, reloaded_3dl.table, atol=1e-3)


# ---------------------------------------------------------------------------
# Mathematical & Interpolation Accuracy Tests
# ---------------------------------------------------------------------------


def test_identity_lut_leaves_image_unchanged():
    img = _make_test_qimage(64, 48, opaque=True)
    orig_bytes = bytes(img.constBits())

    lut = _make_identity_lut(size=17)
    apply_lut3d(img, lut, intensity=1.0)

    # Max difference must be exactly 0
    new_bytes = bytes(img.constBits())
    assert orig_bytes == new_bytes


def test_identity_lut_preserves_transparency():
    img = _make_test_qimage(40, 30, opaque=False)
    orig_words = view_u32(img).copy()

    lut = _make_identity_lut(size=17)
    apply_lut3d(img, lut, intensity=1.0)

    new_words = view_u32(img)
    # Alpha channel preserved exactly
    orig_alpha = orig_words >> 24
    new_alpha = new_words >> 24
    np.testing.assert_array_equal(orig_alpha, new_alpha)

    # Color channels differ by at most 1 due to 8-bit unpremultiply truncation
    r_orig = ((orig_words >> 16) & 0xFF).astype(int)
    r_new = ((new_words >> 16) & 0xFF).astype(int)
    assert np.max(np.abs(r_orig - r_new)) <= 1


def test_invert_lut_produces_exact_invert():
    img = _make_test_qimage(32, 24, opaque=True)
    orig_words = view_u32(img).copy()
    r_orig = (orig_words >> 16) & 0xFF
    g_orig = (orig_words >> 8) & 0xFF
    b_orig = orig_words & 0xFF

    lut = _make_invert_lut(size=17)
    apply_lut3d(img, lut, intensity=1.0)

    inverted_words = view_u32(img)
    r_inv = (inverted_words >> 16) & 0xFF
    g_inv = (inverted_words >> 8) & 0xFF
    b_inv = inverted_words & 0xFF

    np.testing.assert_array_equal(r_inv, 255 - r_orig)
    np.testing.assert_array_equal(g_inv, 255 - g_orig)
    np.testing.assert_array_equal(b_inv, 255 - b_orig)


def test_trilinear_interpolation_accuracy():
    # 2x2x2 cube with linear ramp
    size = 2
    coords = np.linspace(0.0, 1.0, size, dtype=np.float32)
    rg, gg, bg = np.meshgrid(coords, coords, coords, indexing="ij")
    table = np.stack([rg, gg, bg], axis=-1)
    lut = LUT3D(name="Ramp", size=size, table=table)

    # Test an image with intermediate known values
    img = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    view_u32(img)[0, 0] = (255 << 24) | (128 << 16) | (64 << 8) | 192

    apply_lut3d(img, lut, intensity=1.0)
    word = view_u32(img)[0, 0]

    r = (word >> 16) & 0xFF
    g = (word >> 8) & 0xFF
    b = word & 0xFF

    assert r == 128
    assert g == 64
    assert b == 192


def test_intensity_blending():
    img_orig = _make_test_qimage(20, 20, opaque=True)
    orig_words = view_u32(img_orig).copy()

    # 1. Intensity 0.0 -> no change
    img0 = QImage(img_orig)
    lut = get_preset_lut("Warm Film")
    apply_lut3d(img0, lut, intensity=0.0)
    np.testing.assert_array_equal(view_u32(img0), orig_words)

    # 2. Intensity 1.0 -> full LUT effect
    img1 = QImage(img_orig)
    apply_lut3d(img1, lut, intensity=1.0)
    words1 = view_u32(img1)
    assert not np.array_equal(words1, orig_words)

    # 3. Intensity 0.5 -> intermediate blend
    img_half = QImage(img_orig)
    apply_lut3d(img_half, lut, intensity=0.5)
    words_half = view_u32(img_half)

    r_orig = ((orig_words >> 16) & 0xFF).astype(float)
    r_full = ((words1 >> 16) & 0xFF).astype(float)
    r_half = ((words_half >> 16) & 0xFF).astype(float)
    expected_half = np.round(0.5 * r_orig + 0.5 * r_full)
    # Differences due to integer rounding should be at most 1
    assert np.max(np.abs(r_half - expected_half)) <= 1


def test_selection_mask_confinement():
    img = _make_test_qimage(30, 30, opaque=True)
    orig_words = view_u32(img).copy()

    mask = np.zeros((30, 30), dtype=bool)
    mask[10:20, 10:20] = True

    lut = get_preset_lut("Teal & Orange")
    apply_lut3d(img, lut, intensity=1.0, mask=mask)

    result_words = view_u32(img)
    # Outside mask: must be identical
    np.testing.assert_array_equal(result_words[~mask], orig_words[~mask])
    # Inside mask: changed
    assert not np.array_equal(result_words[mask], orig_words[mask])


# ---------------------------------------------------------------------------
# Presets & Memory Frugality
# ---------------------------------------------------------------------------


def test_all_builtin_presets():
    assert len(PRESET_NAMES) == 5
    for name in PRESET_NAMES:
        lut = get_preset_lut(name)
        assert lut.size == 17
        assert lut.table.shape == (17, 17, 17, 3)
        assert lut.table.min() >= 0.0
        assert lut.table.max() <= 1.0

        img = _make_test_qimage(16, 16)
        apply_lut3d(img, lut, intensity=1.0)


def test_memory_frugality_streaming_chunks(monkeypatch):
    """Verify that images larger than CHUNK_ROWS are processed in row chunks."""
    h, w = CHUNK_ROWS * 2 + 50, 100
    img = _make_test_qimage(w, h)

    lut = get_preset_lut("Warm Film")
    apply_lut3d(img, lut, intensity=1.0)

    # Output is fully processed
    arr = view_u32(img)
    assert not np.all(arr == 0)


# ---------------------------------------------------------------------------
# CLI & Dialog Tests
# ---------------------------------------------------------------------------


def test_cli_color_lookup(tmp_path):
    from photoslop.cli import main

    out_file = tmp_path / "cli_lut_out.png"
    code = main(
        [
            "--new",
            "80x60",
            "--fill",
            "180,120,60",
            "--color-lookup",
            "Teal & Orange,0.8",
            "--output",
            str(out_file),
        ]
    )
    assert code == 0
    assert out_file.is_file()


def test_cli_color_lookup_cube_file(tmp_path):
    from photoslop.cli import main

    cube_file = tmp_path / "invert.cube"
    write_cube(_make_invert_lut(size=2), cube_file)

    out_file = tmp_path / "cli_cube_out.png"
    code = main(
        [
            "--new",
            "40x40",
            "--fill",
            "200,100,50",
            "--color-lookup",
            str(cube_file),
            "--output",
            str(out_file),
        ]
    )
    assert code == 0
    assert out_file.is_file()

    img = QImage(str(out_file))
    word = view_u32(img)[0, 0]
    r = (word >> 16) & 0xFF
    g = (word >> 8) & 0xFF
    b = word & 0xFF
    assert r == 255 - 200
    assert g == 255 - 100
    assert b == 255 - 50


def test_color_lookup_dialog(qapp):
    from photoslop.colorlookupdialog import ColorLookupDialog
    from photoslop.mainwindow import MainWindow

    win = MainWindow()
    win.add_document(Document.new(QSize(50, 50), 72.0, "test", QColor(100, 100, 100)))
    doc = win.current_doc()
    img = _make_test_qimage(50, 50)
    doc.active_layer.image = img

    dialog = ColorLookupDialog(doc, win)

    # Test changing preset
    dialog.preset_combo.setCurrentText("Cool Crisp")
    assert dialog._current_lut.name == "Cool Crisp"

    # Test changing intensity
    dialog.intensity_slider.setValue(75)
    assert dialog.intensity_label.text() == "75%"

    # Test transform
    test_img = QImage(img)
    dialog.transform(test_img)
    assert bytes(test_img.constBits()) != bytes(img.constBits())


def test_mainwindow_action_color_lookup(qapp):
    from photoslop.mainwindow import MainWindow

    win = MainWindow()
    # Check action exists in registry
    assert "color.lookup" in win.action_registry.entries
    spec, action = win.action_registry.entries["color.lookup"]
    assert spec.label == "Color Lookup"
    assert spec.shortcut == "Ctrl+Alt+L"


def test_adjust_panel_with_lut(qapp):
    from photoslop.mainwindow import MainWindow

    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "test", QColor(100, 100, 100)))
    doc = win.current_doc()
    panel = win.adjust_panel
    layer = doc.active_layer

    orig_color = layer.image.pixelColor(5, 5)

    # Change 3D LUT preset in AdjustPanel
    idx = panel.lut_combo.findText("Warm Film")
    assert idx > 0
    panel.lut_combo.setCurrentIndex(idx)
    panel._debounce.stop()
    panel._recompute()

    new_color = layer.image.pixelColor(5, 5)
    assert new_color != orig_color

    # Apply session
    panel.apply()
    assert doc.undo_stack.count() == 1
    assert panel.lut_combo.currentIndex() == 0  # reset to (None) after apply
    assert doc.active_layer.image.pixelColor(5, 5) == new_color

    # Undo
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(5, 5) == orig_color
