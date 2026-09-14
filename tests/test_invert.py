# SPDX-License-Identifier: Apache-2.0
"""Image ▸ Adjustments ▸ Invert, and its `--invert` mirror.

Invert is the only adjustment in that menu without a dialog, so it runs
through the filter plumbing rather than `ScopedAdjustMixin`. That choice is
what these tests pin: one undo step, and a selection confines it the way a
selection confines a filter.
"""

import numpy as np
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainterPath

from photoslop import cli
from photoslop.adjust import apply_luts, invert_luts
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def filled(size: QSize | None = None, color: QColor | None = None) -> QImage:
    img = QImage(size or QSize(60, 40), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(color or QColor(10, 200, 30))
    return img


def test_invert_luts_are_the_reverse_ramp():
    luts = invert_luts()
    assert luts.shape == (3, 256)
    for channel in luts:
        assert channel[0] == 255 and channel[255] == 0
        assert list(channel) == list(range(255, -1, -1))


def test_inverting_twice_is_the_identity(qapp):
    """The defining property, and the cheapest guard against an off-by-one:
    255 - (255 - c) == c for every value, with no drift at either end."""
    img = QImage(256, 1, QImage.Format.Format_ARGB32_Premultiplied)
    for x in range(256):
        img.setPixelColor(x, 0, QColor(x, 255 - x, (x * 7) % 256))
    before = QImage(img)
    apply_luts(img, invert_luts())
    assert img != before
    apply_luts(img, invert_luts())
    assert img == before


def test_invert_preserves_alpha(qapp):
    """Premultiplied buffers make this silent to get wrong: inverting the
    colour must not disturb the alpha channel."""
    img = QImage(8, 8, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(10, 200, 30, 128))
    apply_luts(img, invert_luts())
    assert img.pixelColor(0, 0).alpha() == 128


def test_menu_action_is_one_undo_step_and_selection_aware(qapp):
    win = MainWindow()
    doc = Document.new(QSize(60, 40), 72.0, "i", QColor(0, 0, 0))
    doc.layers[0].image = filled()
    win.add_document(doc)

    path = QPainterPath()
    path.addRect(QRect(0, 0, 60, 20))  # top half only
    doc.set_selection(path)
    win.action_invert()

    img = doc.active_layer.image
    assert img.pixelColor(30, 5).getRgb()[:3] == (245, 55, 225), "inside the selection"
    assert img.pixelColor(30, 30).getRgb()[:3] == (10, 200, 30), "outside it, untouched"

    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.command(0).text() == "Invert"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(30, 5).getRgb()[:3] == (10, 200, 30)


def test_menu_action_without_a_selection_covers_the_layer(qapp):
    win = MainWindow()
    doc = Document.new(QSize(20, 20), 72.0, "i", QColor(0, 0, 0))
    doc.layers[0].image = filled(QSize(20, 20))
    win.add_document(doc)
    win.action_invert()
    img = doc.active_layer.image
    for x, y in ((0, 0), (19, 19), (10, 10)):
        assert img.pixelColor(x, y).getRgb()[:3] == (245, 55, 225)


def test_cli_invert_matches_the_gui(qapp, tmp_path):
    src = str(tmp_path / "in.png")
    filled().save(src)
    out = str(tmp_path / "out.png")
    assert cli.main([src, "--invert", "--output", out]) == 0
    assert QImage(out).pixelColor(5, 5).getRgb()[:3] == (245, 55, 225)


def test_cli_invert_is_a_flag_not_a_value(qapp, tmp_path):
    """It takes no argument, like --auto-levels: there is nothing to tune."""
    assert cli.OPS["invert"][0] is None


def test_masked_apply_luts_leaves_the_rest_alone(qapp):
    img = filled(QSize(4, 4))
    mask = np.zeros((4, 4), bool)
    mask[:2, :] = True
    apply_luts(img, invert_luts(), mask)
    assert img.pixelColor(0, 0).getRgb()[:3] == (245, 55, 225)
    assert img.pixelColor(0, 3).getRgb()[:3] == (10, 200, 30)
