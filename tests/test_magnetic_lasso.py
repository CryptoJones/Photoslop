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


def test_magnetic_lasso_options_bar_and_cycle(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 50), 72.0, "ml_cycle", QColor(0, 0, 0))
    win.add_document(doc)

    # Shift+L cycles lasso group
    win._set_tool("lasso")
    assert win.active_tool.name == "lasso"
    win._cycle_lasso_tool()
    assert win.active_tool.name == "poly-lasso"
    win._cycle_lasso_tool()
    assert win.active_tool.name == "magnetic-lasso"
    win._cycle_lasso_tool()
    assert win.active_tool.name == "lasso"

    # Option controls
    win._set_tool("magnetic-lasso")
    assert "detection_width" in win._option_widgets
    assert "edge_contrast" in win._option_widgets
    assert "frequency" in win._option_widgets
    assert win.options.detection_width == 20
    assert win.options.edge_contrast == 10
    assert win.options.frequency == 50


def test_magnetic_lasso_auto_drops_points(qapp):
    win = MainWindow()
    doc = Document.new(QSize(80, 50), 72.0, "ml_autodrop", QColor(0, 0, 0))
    doc.layers[0].image = stepped_edge_image()
    win.add_document(doc)
    editor = win.current_editor()
    tool = win.tools["magnetic-lasso"]

    tool.opts.frequency = 80  # threshold max(10, 150 - 80*1.2) = 54
    tool.press(doc, editor.canvas, QPointF(30, 4), None)
    assert len(tool._points) == 1

    # Small movement: below threshold, no drop
    tool.hover(doc, editor.canvas, QPointF(30, 10))
    assert len(tool._points) == 1

    # Large movement: above threshold, auto-drops fastening point
    tool.hover(doc, editor.canvas, QPointF(30, 70))
    assert len(tool._points) >= 2
