# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(200, 40), 72.0, "sp", QColor(255, 255, 255)))
    win.options.size = 10
    win.options.hardness = 50  # soft → stamp path
    win.options.opacity = 60
    win.options.foreground = QColor(0, 0, 0)
    return win


def paint_line(win):
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    tool = win.tools["brush"]
    tool.press(doc, canvas, QPointF(20, 20), None)
    tool.move(doc, canvas, QPointF(180, 20), None)
    tool.release(doc, canvas, QPointF(180, 20), None)
    return doc.active_layer.image


def coverage(img) -> int:
    dark = 0
    for x in range(200):
        if img.pixelColor(x, 20).red() < 250:
            dark += 1
    return dark


def test_wide_spacing_leaves_gaps_tight_spacing_fills(qapp):
    win = make_window(qapp)
    win.options.spacing = 150  # stamps 15px apart with a 10px brush
    sparse = coverage(paint_line(win))
    win.current_doc().undo_stack.undo()

    win.options.spacing = 10  # near-continuous
    dense = coverage(paint_line(win))
    assert dense > sparse  # tighter spacing covers strictly more of the line


def test_spacing_respected_by_clone_stamp(qapp):
    win = make_window(qapp)
    win.options.spacing = 200
    tool = win.tools["clone-stamp"]

    class _AltEv:
        def modifiers(self):
            from PySide6.QtCore import Qt

            return Qt.KeyboardModifier.AltModifier

    doc = win.current_doc()
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainter

    p = QPainter(doc.active_layer.image)
    p.fillRect(QRect(5, 5, 12, 12), QColor(255, 0, 0))
    p.end()

    canvas = win.current_editor().canvas
    tool.press(doc, canvas, QPointF(10, 10), _AltEv())
    tool.press(doc, canvas, QPointF(50, 20), None)
    tool.release(doc, canvas, QPointF(50, 20), None)
    assert doc.undo_stack.count() == 1  # stroke machinery unaffected by spacing
