# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

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
    assert panel._pristines == {}  # session closed
    assert panel._sliders["exposure"].value() == 0

    doc.undo_stack.undo()
    assert layer.image.pixelColor(5, 5).red() == 100
    doc.undo_stack.redo()
    assert layer.image.pixelColor(5, 5).red() > 150


def test_panel_scope_all_layers(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(30, 20), 72.0, "s", QColor(100, 100, 100)))
    doc = win.current_doc()
    panel = win.adjust_panel
    from PySide6.QtCore import QPoint

    from photoslop.layer import Layer

    top = Layer.blank("top", QSize(10, 10), QPoint(2, 2))
    top.image.fill(QColor(60, 60, 60))
    doc.layers.append(top)
    doc.active_index = 1
    background = doc.layers[0]

    # scope = layer (default): only the active layer previews
    panel._sliders["exposure"].setValue(100)
    panel._debounce.stop()
    panel._recompute()
    assert top.image.pixelColor(5, 5).red() > 90
    assert background.image.pixelColor(5, 5).red() == 100

    # flip to full image mid-session: both layers preview from pristine
    panel.scope_all.setChecked(True)
    assert background.image.pixelColor(5, 5).red() > 150
    assert top.image.pixelColor(5, 5).red() > 90

    # flip back: the background is restored, only the layer stays adjusted
    panel.scope_all.setChecked(False)
    assert background.image.pixelColor(5, 5).red() == 100

    panel.scope_all.setChecked(True)
    panel.apply()
    assert doc.undo_stack.count() == 1  # one macro for both layers
    assert background.image.pixelColor(5, 5).red() > 150
    doc.undo_stack.undo()
    assert background.image.pixelColor(5, 5).red() == 100
    assert top.image.pixelColor(5, 5).red() == 60
    panel.scope_all.setChecked(False)


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


def test_point_color_targets_hue_band(qapp):
    from photoslop.adjust import apply_point_color

    img = QImage(3, 1, QImage.Format.Format_ARGB32_Premultiplied)
    img.setPixelColor(0, 0, QColor(200, 60, 40))  # orange-red: in band
    img.setPixelColor(1, 0, QColor(40, 60, 200))  # blue: out of band
    img.setPixelColor(2, 0, QColor(128, 128, 128))  # gray: protected
    apply_point_color(img, hue_deg=10, hue_range=40, d_hue=90, d_sat=0, d_light=0)
    hit = img.pixelColor(0, 0)
    assert hit.green() > hit.red()  # rotated toward green
    assert img.pixelColor(1, 0) == QColor(40, 60, 200)
    assert img.pixelColor(2, 0) == QColor(128, 128, 128)


def test_point_color_uniformity_pulls_to_centre(qapp):
    from photoslop.adjust import apply_point_color

    img = QImage(2, 1, QImage.Format.Format_ARGB32_Premultiplied)
    img.setPixelColor(0, 0, QColor.fromHsv(35, 200, 200))
    img.setPixelColor(1, 0, QColor.fromHsv(5, 200, 200))
    apply_point_color(img, hue_deg=20, hue_range=30, d_hue=0, d_sat=0, d_light=0, uniformity=100)
    h0 = img.pixelColor(0, 0).hsvHue()
    h1 = img.pixelColor(1, 0).hsvHue()
    assert abs(h0 - 20) < abs(35 - 20)
    assert abs(h1 - 20) < abs(5 - 20)


def test_point_color_dialog_preset_pick_and_scope(qapp):
    from photoslop.document import Document
    from photoslop.pointcolordialog import PointColorDialog

    doc = Document.new(QSize(24, 24), 72.0, "pc", QColor(200, 60, 40))
    dlg = PointColorDialog(doc)
    assert dlg.scope_all is not None  # layer<->document toggle
    dlg._skin_preset()
    assert dlg._sliders["hue"].value() == 20
    assert dlg._sliders["range"].value() == 28
    dlg._picked(QColor(40, 60, 200))  # sample a blue
    assert abs(dlg._sliders["hue"].value() - QColor(40, 60, 200).hsvHue()) <= 1
    dlg._skin_preset()  # back to the doc's own band
    dlg._sliders["dh"].setValue(45)
    dlg.accept()
    assert doc.undo_stack.count() >= 1  # one macro pushed
