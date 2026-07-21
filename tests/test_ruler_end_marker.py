# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def end_tick_present(win, width_px: int) -> bool:
    editor = win.current_editor()
    editor.zoom_fit()
    win.repaint()
    ruler = editor.hruler
    img = ruler.grab().toImage()
    end_x = round(ruler.origin + width_px * ruler.zoom)
    # the end marker is the only full-height tick: probe the very top rows
    for dx in (-1, 0, 1):
        x = end_x + dx
        if 0 <= x < img.width():
            c = img.pixelColor(x, 1)
            if c.red() < 120 and c.alpha() > 200:
                return True
    return False


def test_end_marker_at_non_round_sizes(qapp):
    for w, h in ((8192, 5464), (11648, 8736)):  # Canon R5, Fuji GFX 100
        win = MainWindow()
        win.resize(1600, 1000)
        win.add_document(Document.new(QSize(w, h), 72.0, "cam", QColor(255, 255, 255)))
        win.show()
        assert end_tick_present(win, w), f"no end marker for {w}px image"
        win.close()


def test_end_marker_at_round_size_and_units_survive(qapp):
    win = MainWindow()
    win.resize(1600, 1000)
    win.add_document(Document.new(QSize(2000, 1000), 72.0, "r", QColor(255, 255, 255)))
    win.show()
    assert end_tick_present(win, 2000)
    for unit in ("in", "mm", "pc"):  # paint path holds in every unit
        win.set_unit(unit)
        win.repaint()
        assert win.current_editor().hruler.grab().width() > 0
    win.close()
