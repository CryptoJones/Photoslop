# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize
from PySide6.QtGui import QColor, QPainter

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def stepped_edge_image(w=80, h=50):
    """Black left / white right with the boundary stepping from x=30 to x=45
    halfway down — a straight line between edge points would cut the corner."""
    img = blank_image(QSize(w, h))
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    p.fillRect(QRect(30, 0, w - 30, 25), QColor(255, 255, 255))
    p.fillRect(QRect(45, 25, w - 45, h - 25), QColor(255, 255, 255))
    p.end()
    return img


def test_livewire_follows_the_edge(qapp):
    img = stepped_edge_image()
    path = npimage.livewire_path(img, (30, 4), (45, 46))
    assert path[0] == (30, 4) and path[-1] == (45, 46)

    on_edge = 0
    for x, y in path:
        boundary_x = 30 if y < 25 else 45
        if abs(x - boundary_x) <= 2 or 23 <= y <= 27:
            on_edge += 1
    assert on_edge / len(path) > 0.8  # the wire hugs the stepped boundary

    # straight-line fallback when the corridor would be huge
    big = blank_image(QSize(600, 600))
    fallback = npimage.livewire_path(big, (0, 0), (599, 599))
    assert fallback == [(0, 0), (599, 599)]


def test_magnetic_lasso_tool_closes_selection(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 50), 72.0, "ml", QColor(0, 0, 0))
    doc.layers[0].image = stepped_edge_image()
    win.add_document(doc)
    editor = win.current_editor()
    tool = win.tools["magnetic-lasso"]

    tool.press(doc, editor.canvas, QPointF(30, 4), None)
    tool.press(doc, editor.canvas, QPointF(45, 46), None)
    tool.press(doc, editor.canvas, QPointF(70, 46), None)
    tool.press(doc, editor.canvas, QPointF(70, 4), None)
    tool.double_click(doc, editor.canvas, QPointF(70, 4), None)

    bounds = doc.selection_bounds()
    assert bounds is not None
    assert bounds.width() > 30 and bounds.height() > 35
