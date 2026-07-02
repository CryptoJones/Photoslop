# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.adjust import AdjustSettings, apply_settings, build_luts
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def test_identity_luts_and_noop(qapp):
    s = AdjustSettings()
    assert s.is_identity()
    luts = build_luts(s)
    for c in range(3):
        assert (luts[c] == np.arange(256)).all()
    img = blank_image(QSize(8, 8))
    img.fill(QColor(12, 200, 34))
    before = img.copy()
    apply_settings(img, s)
    assert img == before


def test_exposure_brightens_and_temperature_warms(qapp):
    lut_plus = build_luts(AdjustSettings(exposure=1.0))
    assert lut_plus[0][100] > 180  # one stop ≈ double
    warm = build_luts(AdjustSettings(temperature=80))
    assert warm[0][128] > warm[2][128]  # R up, B down

    for field in AdjustSettings.FIELDS:
        luts = build_luts(AdjustSettings(**{field: 60}))
        for c in range(3):
            assert (np.diff(luts[c].astype(int)) >= 0).all(), f"{field} not monotonic"


def test_saturation_and_vibrance(qapp):
    img = blank_image(QSize(4, 4))
    img.fill(QColor(200, 40, 40))
    apply_settings(img, AdjustSettings(saturation=-100))
    px = img.pixelColor(1, 1)
    assert abs(px.red() - px.green()) <= 2 and abs(px.green() - px.blue()) <= 2

    gray = blank_image(QSize(4, 4))
    gray.fill(QColor(120, 120, 120))
    before = gray.copy()
    apply_settings(gray, AdjustSettings(vibrance=100))
    assert gray == before  # vibrance leaves gray alone


def test_alpha_preserved(qapp):
    img = blank_image(QSize(4, 4))
    img.fill(QColor(100, 50, 25, 128))
    apply_settings(img, AdjustSettings(exposure=0.5))
    assert img.pixelColor(0, 0).alpha() == 128


def test_panel_session_apply_undo(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 30), 72.0, "a", QColor(100, 100, 100)))
    doc = win.current_doc()
    panel = win.adjust_panel
    layer = doc.active_layer

    panel._sliders["exposure"].setValue(100)  # +1 stop
    panel._debounce.stop()
    panel._recompute()
    assert layer.image.pixelColor(5, 5).red() > 150  # live preview applied

    panel.apply()
    assert doc.undo_stack.count() == 1
    assert layer.image.pixelColor(5, 5).red() > 150
    assert panel._pristine is None  # session closed
    assert panel._sliders["exposure"].value() == 0

    doc.undo_stack.undo()
    assert layer.image.pixelColor(5, 5).red() == 100
    doc.undo_stack.redo()
    assert layer.image.pixelColor(5, 5).red() > 150


def test_panel_reset_restores(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(20, 20), 72.0, "b", QColor(80, 90, 100)))
    doc = win.current_doc()
    panel = win.adjust_panel
    layer = doc.active_layer

    panel._sliders["contrast"].setValue(80)
    panel._debounce.stop()
    panel._recompute()
    assert layer.image.pixelColor(3, 3) != QColor(80, 90, 100)

    panel.reset()
    assert layer.image.pixelColor(3, 3) == QColor(80, 90, 100)
    assert doc.undo_stack.count() == 0
