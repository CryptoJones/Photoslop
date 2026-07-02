# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.adjust import apply_luts, color_balance_luts
from photoslop.colorbalancedialog import ColorBalanceDialog
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def test_color_balance_luts(qapp):
    identity = color_balance_luts({})
    for c in range(3):
        assert (identity[c] == np.arange(256)).all()

    warm_mids = color_balance_luts({"midtones": (60.0, 0.0, 0.0)})
    assert warm_mids[0][128] > 128  # red pushed up in the midtones
    assert warm_mids[0][2] <= 4 and warm_mids[0][253] >= 250  # extremes ~kept
    assert (warm_mids[1] == np.arange(256)).all()  # green untouched

    dark_blue_shadows = color_balance_luts({"shadows": (0.0, 0.0, -80.0)})
    assert dark_blue_shadows[2][40] < 40  # blue pulled down in shadows
    assert dark_blue_shadows[2][240] >= 235  # highlights barely move
    for c in range(3):
        assert (np.diff(dark_blue_shadows[c].astype(int)) >= 0).all()


def test_apply_color_balance_to_image(qapp):
    img = blank_image(QSize(4, 4))
    img.fill(QColor(128, 128, 128))
    apply_luts(img, color_balance_luts({"midtones": (50.0, 0.0, 0.0)}))
    px = img.pixelColor(1, 1)
    assert px.red() > 128 and px.green() == 128


def test_dialog_bands_store_independently(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(10, 10), 72.0, "cb", QColor(120, 120, 120)))
    dialog = ColorBalanceDialog(win.current_doc(), win)

    dialog._sliders[0].setValue(40)  # midtones cyan-red = +40
    dialog._radios["shadows"].setChecked(True)
    assert dialog._sliders[0].value() == 0  # fresh band shows its own values
    dialog._sliders[2].setValue(-30)  # shadows yellow-blue = -30
    dialog._radios["midtones"].setChecked(True)
    assert dialog._sliders[0].value() == 40  # midtone value preserved

    values = dialog.balance_values()
    assert values["midtones"][0] == 40.0
    assert values["shadows"][2] == -30.0
    dialog.reject()


def test_dialog_ok_undo_cancel(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(10, 10), 72.0, "cb", QColor(120, 120, 120)))
    doc = win.current_doc()

    dialog = ColorBalanceDialog(doc, win)
    dialog._sliders[0].setValue(60)
    dialog._debounce.stop()
    dialog._preview()
    assert doc.active_layer.image.pixelColor(5, 5).red() > 120
    dialog.accept()
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.command(0).text() == "Color Balance"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(120, 120, 120)
