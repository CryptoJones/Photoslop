# SPDX-License-Identifier: Apache-2.0
"""The ruler hairline and a guide under the cursor must form one continuous
line — rendered-pixel test, not just coordinate math (regression: rulers used
viewport-relative origins and sat a frame-width off the canvas)."""

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QMouseEvent
from PySide6.QtWidgets import QApplication

from photoslop.document import Document
from photoslop.mainwindow import MainWindow

RED = (220, 60, 60)
CYAN = (0, 200, 255)


def window_pixels(win) -> np.ndarray:
    img = win.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
    w, h, bpl = img.width(), img.height(), img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), np.uint8, count=h * bpl).reshape(h, bpl)
    return arr[:, : w * 3].reshape(h, w, 3).copy()


def color_hits(arr, region, color, axis, tol=40):
    x0, y0, x1, y1 = region
    sub = arr[y0:y1, x0:x1].astype(int)
    mask = (np.abs(sub - np.array(color)) <= tol).all(axis=2)
    idx = np.flatnonzero(mask.any(axis=0 if axis == "col" else 1))
    return [(x0 if axis == "col" else y0) + int(i) for i in idx]


@pytest.mark.parametrize("zoom", [1.0, 0.75, 2.0])
def test_hairline_continuous_with_guide(qapp, zoom):
    win = MainWindow()
    win.add_document(Document.new(QSize(400, 300), 72.0, "a", QColor(255, 255, 255)))
    win.show()
    QApplication.processEvents()

    editor = win.current_editor()
    canvas = editor.canvas
    editor.doc.add_guide("v", 150.0)
    editor.doc.add_guide("h", 100.0)
    editor.set_zoom(zoom)
    QApplication.processEvents()

    # hover exactly on the guide crossing
    wpt = QPointF(150 * canvas.zoom, 100 * canvas.zoom)
    gp = QPointF(canvas.mapToGlobal(wpt.toPoint()))
    QApplication.sendEvent(
        canvas,
        QMouseEvent(QEvent.Type.MouseMove, wpt, gp, Qt.MouseButton.NoButton,
                    Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier),
    )
    QApplication.processEvents()
    arr = window_pixels(win)

    hr = editor.hruler.mapTo(win, QPoint(0, 0))
    hr_geo = (hr.x(), hr.y(), hr.x() + editor.hruler.width(), hr.y() + editor.hruler.height())
    vr = editor.vruler.mapTo(win, QPoint(0, 0))
    vr_geo = (vr.x(), vr.y(), vr.x() + editor.vruler.width(), vr.y() + editor.vruler.height())
    cv = canvas.mapTo(win, QPoint(0, 0))
    cv_geo = (cv.x(), cv.y(), cv.x() + canvas.width(), cv.y() + canvas.height())

    # strips that contain only one of the two guides
    v_strip = (cv_geo[0], cv_geo[1] + 4, cv_geo[2], cv_geo[1] + 40)
    h_strip = (cv_geo[0] + 4, cv_geo[1], cv_geo[0] + 40, cv_geo[3])

    marker_cols = color_hits(arr, hr_geo, RED, "col")
    guide_cols = color_hits(arr, v_strip, CYAN, "col")
    marker_rows = color_hits(arr, vr_geo, RED, "row")
    guide_rows = color_hits(arr, h_strip, CYAN, "row")
    assert marker_cols and guide_cols and marker_rows and guide_rows

    mx = marker_cols[len(marker_cols) // 2]
    gx = guide_cols[len(guide_cols) // 2]
    my = marker_rows[len(marker_rows) // 2]
    gy = guide_rows[len(guide_rows) // 2]
    assert mx == gx, f"hairline x {mx} != guide x {gx} at zoom {zoom}"
    assert my == gy, f"hairline y {my} != guide y {gy} at zoom {zoom}"
