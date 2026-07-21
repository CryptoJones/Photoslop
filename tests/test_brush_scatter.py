# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(200, 80), 72.0, "sc", QColor(255, 255, 255)))
    win.options.size = 8
    win.options.hardness = 50  # soft → stamp path
    win.options.opacity = 100
    win.options.flow = 100
    win.options.foreground = QColor(0, 0, 0)
    return win


def stroke_line(win):
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    tool = win.tools["brush"]
    tool.press(doc, canvas, QPointF(20, 40), None)
    tool.move(doc, canvas, QPointF(180, 40), None)
    tool.release(doc, canvas, QPointF(180, 40), None)
    return doc.active_layer.image


def vertical_spread(img) -> int:
    rows = [
        y
        for y in range(img.height())
        if any(img.pixelColor(x, y).red() < 200 for x in range(20, 180, 4))
    ]
    return max(rows) - min(rows) if rows else 0


def test_scatter_spreads_stamps(qapp):
    win = make_window(qapp)
    win.options.scatter = 0
    tight = vertical_spread(stroke_line(win))
    win.current_doc().undo_stack.undo()

    win.options.scatter = 150
    loose = vertical_spread(stroke_line(win))
    assert loose > tight + 8  # scattered stamps range well beyond the line

    win.current_doc().undo_stack.undo()  # undo restores the whole stroke
    assert vertical_spread(win.current_doc().active_layer.image) == 0
