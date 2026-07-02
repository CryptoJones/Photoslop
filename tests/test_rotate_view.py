# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


class _Ev:
    def __init__(self, pos: QPointF):
        self._p = pos

    def position(self) -> QPointF:
        return self._p


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(80, 40), 72.0, "rv", QColor(255, 255, 255)))
    return win


def test_rotate_view_geometry_and_mapping(qapp):
    win = make_window(qapp)
    canvas = win.current_editor().canvas
    canvas.set_zoom(1.0)
    assert (canvas.width(), canvas.height()) == (80, 40)

    win.action_rotate_view(90)
    assert canvas.view_rotation == 90
    assert (canvas.width(), canvas.height()) == (40, 80)  # dims swapped

    # round trip: canvas point → widget point → _canvas_pos recovers it
    widget_pt = canvas._view_transform().map(QPointF(10.0, 5.0))
    recovered = canvas._canvas_pos(_Ev(widget_pt))
    assert abs(recovered.x() - 10.0) < 0.01 and abs(recovered.y() - 5.0) < 0.01

    win.action_rotate_view(90)  # 180: dims restore
    assert (canvas.width(), canvas.height()) == (80, 40)
    widget_pt = canvas._view_transform().map(QPointF(70.0, 30.0))
    recovered = canvas._canvas_pos(_Ev(widget_pt))
    assert abs(recovered.x() - 70.0) < 0.01 and abs(recovered.y() - 30.0) < 0.01


def test_rotated_paint_and_reset(qapp):
    win = make_window(qapp)
    canvas = win.current_editor().canvas
    win.action_rotate_view(90)
    grabbed = canvas.grab()  # paint path under rotation must not crash
    assert grabbed.width() == canvas.width()

    win.action_reset_view_rotation()
    assert canvas.view_rotation == 0
    assert (canvas.width(), canvas.height()) == (80, 40)
