# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter

from photoslop.commands import (
    ArbitraryRotateCommand,
    FlipImageCommand,
    InsertLayerCommand,
    MergeDownCommand,
    MergeVisibleCommand,
    ResizeCanvasCommand,
    ResizeImageCommand,
    RotateLayerCommand,
    SetLayerOffsetCommand,
    TileRecorder,
)
from photoslop.document import Document
from photoslop.layer import Layer, blank_image


def make_doc(qapp):
    return Document.new(QSize(100, 80), 72.0, "t", QColor(255, 255, 255))


def test_tile_recorder_undo_redo(qapp):
    doc = make_doc(qapp)
    layer = doc.active_layer
    recorder = TileRecorder(doc, layer)
    rect = QRect(10, 10, 20, 20)
    recorder.will_change(rect)
    p = QPainter(layer.image)
    p.fillRect(rect, QColor(0, 0, 0))
    p.end()
    cmd = recorder.finish("stroke")
    assert cmd is not None
    doc.undo_stack.push(cmd)

    assert layer.image.pixelColor(15, 15) == QColor(0, 0, 0)
    doc.undo_stack.undo()
    assert layer.image.pixelColor(15, 15) == QColor(255, 255, 255)
    doc.undo_stack.redo()
    assert layer.image.pixelColor(15, 15) == QColor(0, 0, 0)


def test_tile_recorder_skips_untouched(qapp):
    doc = make_doc(qapp)
    recorder = TileRecorder(doc, doc.active_layer)
    recorder.will_change(QRect(0, 0, 50, 50))
    assert recorder.finish("noop") is None  # nothing changed → no command


def test_move_command_merges(qapp):
    doc = make_doc(qapp)
    layer = doc.active_layer
    layer.offset = QPoint(5, 0)
    doc.undo_stack.push(SetLayerOffsetCommand(doc, layer, QPoint(0, 0), QPoint(5, 0)))
    layer.offset = QPoint(9, 3)
    doc.undo_stack.push(SetLayerOffsetCommand(doc, layer, QPoint(5, 0), QPoint(9, 3)))
    assert doc.undo_stack.count() == 1  # merged
    doc.undo_stack.undo()
    assert layer.offset == QPoint(0, 0)


def test_resize_image(qapp):
    doc = make_doc(qapp)
    doc.undo_stack.push(ResizeImageCommand(doc, QSize(50, 40)))
    assert doc.size == QSize(50, 40)
    assert doc.active_layer.image.width() == 50
    doc.undo_stack.undo()
    assert doc.size == QSize(100, 80)
    assert doc.active_layer.image.width() == 100


def test_canvas_resize_and_crop(qapp):
    doc = make_doc(qapp)
    layer = doc.active_layer
    # crop to (20,10)-(60,50): canvas shrinks, layer shifts, pixels survive
    doc.undo_stack.push(ResizeCanvasCommand(doc, QSize(40, 40), QPoint(-20, -10), "Crop"))
    assert doc.size == QSize(40, 40)
    assert layer.offset == QPoint(-20, -10)
    assert doc.flatten().pixelColor(0, 0) == QColor(255, 255, 255)
    doc.undo_stack.undo()
    assert doc.size == QSize(100, 80)
    assert layer.offset == QPoint(0, 0)


# ── Merge-down regression tests ────────────────────────────────────────


def _mask_with_black_rect(size: QSize, rect: QRect) -> QImage:
    """Grayscale8 mask: white everywhere, black inside *rect*."""
    mask = QImage(size, QImage.Format.Format_Grayscale8)
    mask.fill(255)
    p = QPainter(mask)
    p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
    p.setBrush(QColor(0))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRect(rect)
    p.end()
    return mask


def test_merge_down_blend_mode_difference(qapp):
    """CRITICAL: MergeDown must honour the upper layer's blend mode."""
    doc = make_doc(qapp)
    doc.layers[0].image.fill(QColor(255, 255, 255))  # lower = white
    upper = Layer.blank("upper", doc.size)
    upper.image.fill(QColor(0, 255, 0))  # upper = green
    upper.blend_mode = "difference"
    doc.undo_stack.push(InsertLayerCommand(doc, 1, upper))

    expected = doc.flatten().pixelColor(50, 40)  # white ⊕ green = magenta
    assert expected == QColor(255, 0, 255)

    doc.undo_stack.push(MergeDownCommand(doc, 1))
    assert doc.flatten().pixelColor(50, 40) == expected  # still magenta
    doc.undo_stack.undo()
    assert len(doc.layers) == 2
    assert doc.flatten().pixelColor(50, 40) == expected


def test_merge_down_blend_mode_screen(qapp):
    """CRITICAL: screen blend mode must also be baked in, not SourceOver."""
    doc = make_doc(qapp)
    doc.layers[0].image.fill(QColor(128, 64, 32))  # lower = brown
    upper = Layer.blank("upper", doc.size)
    upper.image.fill(QColor(255, 0, 0))  # upper = red
    upper.blend_mode = "screen"
    doc.undo_stack.push(InsertLayerCommand(doc, 1, upper))

    expected = doc.flatten().pixelColor(50, 40)
    assert expected != QColor(255, 0, 0)  # must NOT be SourceOver result

    doc.undo_stack.push(MergeDownCommand(doc, 1))
    assert doc.flatten().pixelColor(50, 40) == expected
    doc.undo_stack.undo()
    assert doc.flatten().pixelColor(50, 40) == expected


def test_merge_down_upper_mask(qapp):
    """HIGH: the upper layer's mask must be honoured during the merge."""
    doc = make_doc(qapp)
    doc.layers[0].image.fill(QColor(255, 255, 255))  # lower = white
    upper = Layer.blank("upper", doc.size)
    upper.image.fill(QColor(255, 0, 0))  # upper = red
    upper.mask = _mask_with_black_rect(doc.size, QRect(40, 20, 20, 20))
    doc.undo_stack.push(InsertLayerCommand(doc, 1, upper))

    # Reference: flatten respects the mask
    expected = doc.flatten().pixelColor(50, 30)  # inside the masked-out rect
    assert expected == QColor(255, 255, 255)  # white — mask hides the red

    doc.undo_stack.push(MergeDownCommand(doc, 1))
    assert doc.flatten().pixelColor(50, 30) == expected  # match flatten


def test_merge_down_upper_fill_opacity(qapp):
    """HIGH: the upper layer's fill_opacity must be honoured."""
    doc = make_doc(qapp)
    doc.layers[0].image.fill(QColor(255, 255, 255))  # lower = white
    upper = Layer.blank("upper", doc.size)
    upper.image.fill(QColor(255, 0, 0))  # upper = red
    upper.fill_opacity = 0.0  # upper invisible
    doc.undo_stack.push(InsertLayerCommand(doc, 1, upper))

    expected = doc.flatten().pixelColor(50, 40)  # white — upper is invisible
    assert expected == QColor(255, 255, 255)

    doc.undo_stack.push(MergeDownCommand(doc, 1))
    assert doc.flatten().pixelColor(50, 40) == expected  # still white


def test_merge_down_stale_lower_mask_cleared(qapp):
    """HAL9000 finding: lower layer's stale mask must be cleared after merge.

    Lower layer has a mask with a black square; upper layer is fully opaque
    red.  Before the fix the stale mask survived and hid merged-in red pixels
    in the masked area.
    """
    doc = make_doc(qapp)
    lower = doc.layers[0]
    lower.image.fill(QColor(255, 255, 255))
    lower.mask = _mask_with_black_rect(doc.size, QRect(20, 10, 20, 20))
    upper = Layer.blank("upper", doc.size)
    upper.image.fill(QColor(255, 0, 0))
    doc.undo_stack.push(InsertLayerCommand(doc, 1, upper))

    # The red pixel at (30, 20) is inside the lower layer's masked-out region.
    # After merge it must survive (the mask is baked in / cleared).
    doc.undo_stack.push(MergeDownCommand(doc, 1))
    assert doc.layers[0].mask is None  # stale mask cleared
    assert doc.flatten().pixelColor(30, 20) == QColor(255, 0, 0)  # red visible

    doc.undo_stack.undo()
    assert doc.layers[0].mask is not None  # restored by undo
    assert len(doc.layers) == 2


def test_merge_down_stale_lower_properties_cleared(qapp):
    """HAL9000 finding: all stale lower-layer appearance props cleared."""
    doc = make_doc(qapp)
    lower = doc.layers[0]
    lower.image.fill(QColor(255, 255, 255))
    lower.fill_opacity = 0.5
    lower.mask = _mask_with_black_rect(doc.size, QRect(20, 10, 20, 20))
    lower.clipped = True
    upper = Layer.blank("upper", doc.size)
    upper.image.fill(QColor(255, 0, 0))
    doc.undo_stack.push(InsertLayerCommand(doc, 1, upper))

    doc.undo_stack.push(MergeDownCommand(doc, 1))
    assert doc.layers[0].fill_opacity == 1.0
    assert doc.layers[0].mask is None
    assert doc.layers[0].effects == []
    assert doc.layers[0].adjustment is None
    assert doc.layers[0].clipped is False

    doc.undo_stack.undo()
    assert doc.layers[0].fill_opacity == 0.5
    assert doc.layers[0].mask is not None
    assert doc.layers[0].clipped is True


def test_merge_visible_applies_mask(qapp):
    """HIGH: MergeVisible must honour per-layer masks (not just raw pixels)."""
    doc = make_doc(qapp)
    doc.layers[0].image.fill(QColor(255, 255, 255))  # lower = white
    upper = Layer.blank("upper", doc.size)
    upper.image.fill(QColor(0, 0, 255))  # upper = blue
    upper.mask = _mask_with_black_rect(doc.size, QRect(40, 20, 20, 20))
    doc.undo_stack.push(InsertLayerCommand(doc, 1, upper))

    expected = doc.flatten().pixelColor(50, 30)  # inside masked-out rect
    assert expected == QColor(255, 255, 255)  # white through mask gap

    doc.undo_stack.push(MergeVisibleCommand(doc))
    assert doc.flatten().pixelColor(50, 30) == expected


# ── Transform mask regression tests ────────────────────────────────────


def test_resize_preserves_mask(qapp):
    """MEDIUM: ResizeImageCommand must scale layer masks to match."""
    doc = make_doc(qapp)
    layer = doc.active_layer
    layer.mask = _mask_with_black_rect(doc.size, QRect(10, 10, 20, 20))
    doc.undo_stack.push(ResizeImageCommand(doc, QSize(200, 160)))
    assert layer.image.size() == QSize(200, 160)
    assert layer.mask.size() == QSize(200, 160)  # mask must match image size
    # The black rect (10,10,20,20) scaled 2× → (20,20,40,40)
    assert layer.mask.pixelColor(30, 30) == QColor(0, 0, 0, 255)  # inside black rect
    assert layer.mask.pixelColor(10, 10) == QColor(255, 255, 255, 255)  # outside

    doc.undo_stack.undo()
    assert layer.mask is not None
    assert layer.mask.size() == QSize(100, 80)  # restored


def test_flip_preserves_mask(qapp):
    """MEDIUM: FlipImageCommand must flip layer masks alongside images."""
    doc = make_doc(qapp)
    layer = doc.active_layer
    layer.mask = _mask_with_black_rect(doc.size, QRect(40, 10, 20, 20))
    black_pos = 50  # x=50 inside the black rect (40..60)
    white_pos = 10  # x=10 outside, should be white

    doc.undo_stack.push(FlipImageCommand(doc, horizontal=True))
    # After horizontal flip: x_new = 99 - x
    assert layer.mask.pixelColor(99 - black_pos, 15) == QColor(0, 0, 0, 255)  # was black
    assert layer.mask.pixelColor(99 - white_pos, 15) == QColor(255, 255, 255, 255)  # was white
    doc.undo_stack.undo()
    assert layer.mask.pixelColor(black_pos, 15) == QColor(0, 0, 0, 255)  # restored
    assert layer.mask.pixelColor(white_pos, 15) == QColor(255, 255, 255, 255)


# ── HAL9000 regression tests ───────────────────────────────────────────


def test_merge_down_preserves_adjustment(qapp):
    """CRITICAL regression: merge-down must not clear lower.adjustment.

    An adjustment layer post-processes the composite *beneath* it via a LUT
    (document.py:59-61).  draw_layer does not bake the LUT into the layer's
    pixels, so clearing it (commands.py old code) silently deletes the filter.
    The LUT must survive the merge and survive undo.
    """
    import numpy as np

    doc = make_doc(qapp)  # 100x80, white background
    lower = doc.layers[0]
    lower.image.fill(QColor(100, 100, 100))

    # Adjustment layer with a brighten LUT (100 → 160)
    adj = Layer("Levels", blank_image(QSize(1, 1)))
    lut = np.clip(np.arange(256) + 60, 0, 255).astype(np.uint8)
    adj.adjustment = np.tile(lut, (3, 1))
    doc.undo_stack.push(InsertLayerCommand(doc, 1, adj))

    # Upper layer — red pixels above the adjustment
    upper = Layer.blank("upper", QSize(100, 80))
    upper.image.fill(QColor(255, 0, 0))
    doc.undo_stack.push(InsertLayerCommand(doc, 2, upper))

    original_lut = adj.adjustment.copy()

    # Merge upper into the adjustment layer
    doc.undo_stack.push(MergeDownCommand(doc, 2))
    merged = doc.layers[1]
    assert merged.adjustment is not None  # adjustment NOT cleared
    np.testing.assert_array_equal(merged.adjustment, original_lut)

    doc.undo_stack.undo()
    assert doc.layers[1].adjustment is not None
    np.testing.assert_array_equal(doc.layers[1].adjustment, original_lut)


def test_arbitrary_rotate_preserves_mask_format(qapp):
    """HIGH regression: ArbitraryRotateCommand must keep layer.mask in
    Grayscale8 after a non-90° rotation.

    QImage.transformed(SmoothTransformation) on Grayscale8 returns
    ARGB32_Premultiplied.  Without format preservation, mask_to_alpha
    (layer.py:49) reinterprets the 4-byte ARGB stride as 1-byte Alpha8,
    scrambling the mask.
    """
    doc = make_doc(qapp)
    layer = doc.active_layer
    layer.mask = _mask_with_black_rect(doc.size, QRect(30, 20, 40, 40))
    original_mask = QImage(layer.mask)

    doc.undo_stack.push(ArbitraryRotateCommand(doc, 30.0))
    assert layer.mask is not None
    assert layer.mask.format() == QImage.Format.Format_Grayscale8

    doc.undo_stack.undo()
    assert layer.mask is not None
    assert layer.mask.format() == QImage.Format.Format_Grayscale8
    assert layer.mask == original_mask


def test_rotate_layer_preserves_mask_format(qapp):
    """HIGH regression: RotateLayerCommand at a non-90° angle must keep
    layer.mask in Grayscale8.  Reachable from the CLI via --rotate-layer."""
    doc = make_doc(qapp)
    layer = doc.active_layer
    layer.image = QImage(40, 40, QImage.Format.Format_ARGB32_Premultiplied)
    layer.image.fill(QColor(255, 0, 0, 255))
    layer.mask = _mask_with_black_rect(QSize(40, 40), QRect(10, 10, 20, 20))
    original_mask = QImage(layer.mask)

    doc.undo_stack.push(RotateLayerCommand(doc, layer, 30))
    assert layer.mask is not None
    assert layer.mask.format() == QImage.Format.Format_Grayscale8

    doc.undo_stack.undo()
    assert layer.mask is not None
    assert layer.mask.format() == QImage.Format.Format_Grayscale8
    assert layer.mask == original_mask
