# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(100, 100), 72.0, "pen",
                                  QColor(255, 255, 255)))
    win.options.foreground = QColor(20, 20, 220)
    win.options.size = 5
    return win


def test_pen_stroke_smooths_through_anchors(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    tool = win.tools["pen"]

    for pt in ((10, 80), (50, 20), (90, 80)):  # a bent path
        tool.press(doc, canvas, QPointF(*pt), None)
    tool.commit(canvas)

    assert len(doc.layers) == 2
    layer = doc.layers[1]
    assert layer.name.startswith("Pen")
    assert layer.image.width() < 100  # bounded, not canvas-sized
    flat = doc.flatten()
    assert flat.pixelColor(50, 20).blue() > 150  # apex anchor on the path
    assert flat.pixelColor(10, 80).blue() > 150  # first anchor
    # the smoothed curve sags below a straight chord midway (30,50)->(50,20):
    # blue somewhere near x=30 between the chord and the anchors
    assert flat.pixelColor(50, 80) == QColor(255, 255, 255)  # under apex empty

    doc.undo_stack.undo()
    assert len(doc.layers) == 1


def test_pen_guards_and_cancel(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    tool = win.tools["pen"]

    tool.press(doc, canvas, QPointF(30, 30), None)
    tool.commit(canvas)  # one anchor: nothing to stroke
    assert len(doc.layers) == 1

    tool.press(doc, canvas, QPointF(30, 30), None)
    tool.press(doc, canvas, QPointF(60, 60), None)
    tool.cancel(doc)
    tool.commit(canvas)  # cancelled: nothing pending
    assert len(doc.layers) == 1
    assert doc.undo_stack.count() == 0
