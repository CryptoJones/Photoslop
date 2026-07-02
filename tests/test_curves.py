# SPDX-License-Identifier: Apache-2.0
import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor

from photoslop.adjust import curve_lut, curves_luts
from photoslop.curvesdialog import CurvesDialog, CurveWidget
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_curve_lut_identity_and_scurve(qapp):
    identity = curve_lut([(0, 0), (255, 255)])
    assert (identity == np.arange(256)).all()

    lifted = curve_lut([(0, 0), (128, 160), (255, 255)])
    assert abs(int(lifted[128]) - 160) <= 1
    assert lifted[0] == 0 and lifted[255] == 255
    assert (np.diff(lifted.astype(int)) >= 0).all()  # monotone, no overshoot


def test_curves_luts_master_composes_with_channel(qapp):
    luts = curves_luts({
        "rgb": [(0, 0), (128, 160), (255, 255)],
        "r": [(0, 0), (160, 100), (255, 255)],
    })
    assert abs(int(luts[0][128]) - 100) <= 2  # master 128→160, red 160→100
    assert abs(int(luts[1][128]) - 160) <= 1  # green: master only


def test_curve_widget_add_drag_remove(qapp):
    w = CurveWidget()
    w.resize(256, 256)

    class Ev:
        def __init__(self, pos, button=Qt.MouseButton.LeftButton):
            self._p, self._b = pos, button

        def position(self):
            return self._p

        def button(self):
            return self._b

    w.mousePressEvent(Ev(w._to_widget(128, 128)))  # add a mid point
    assert len(w.points) == 3
    w.mouseMoveEvent(Ev(w._to_widget(128, 180)))  # drag it up
    w.mouseReleaseEvent(Ev(w._to_widget(128, 180)))
    assert abs(w.points[1][1] - 180) < 4

    w.mousePressEvent(Ev(w._to_widget(*w.points[1]), Qt.MouseButton.RightButton))
    assert len(w.points) == 2  # removed; endpoints survive
    w.mousePressEvent(Ev(QPointF(0, 256), Qt.MouseButton.RightButton))
    assert len(w.points) == 2  # endpoint refuses removal


def test_dialog_ok_undo_cancel(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(10, 10), 72.0, "cv", QColor(128, 128, 128)))
    doc = win.current_doc()

    dialog = CurvesDialog(doc, win)
    dialog.channel_points["rgb"] = [(0.0, 0.0), (128.0, 190.0), (255.0, 255.0)]
    dialog._debounce.stop()
    dialog._preview()
    assert doc.active_layer.image.pixelColor(5, 5).red() > 160
    dialog.accept()
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.command(0).text() == "Curves"
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(128, 128, 128)

    dialog = CurvesDialog(doc, win)
    dialog.channel_points["b"] = [(0.0, 255.0), (255.0, 255.0)]
    dialog._debounce.stop()
    dialog._preview()
    dialog.reject()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(128, 128, 128)
