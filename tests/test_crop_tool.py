# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPoint, QPointF, QRect, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(100, 80), 72.0, "c", QColor(255, 255, 255)))
    return win


def drag(tool, doc, canvas, a: QPointF, b: QPointF):
    tool.press(doc, canvas, a, None)
    tool.move(doc, canvas, b, None)
    tool.release(doc, canvas, b, None)


def test_crop_commit_and_undo(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    drag(tool, doc, editor.canvas, QPointF(20, 10), QPointF(70, 60))
    assert tool.rect == QRect(20, 10, 50, 50)

    tool.commit(editor.canvas)
    assert doc.size == QSize(50, 50)
    assert doc.layers[0].offset == QPoint(-20, -10)  # shifted, not copied
    assert tool.rect is None
    assert doc.undo_stack.command(0).text() == "Crop"

    doc.undo_stack.undo()
    assert doc.size == QSize(100, 80)
    assert doc.layers[0].offset == QPoint(0, 0)


def test_crop_clamps_and_escape_clears(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    drag(tool, doc, editor.canvas, QPointF(80, 60), QPointF(200, 200))
    assert tool.rect == QRect(80, 60, 20, 20)  # clamped to canvas

    tool.cancel(doc)
    assert tool.rect is None
    tool.commit(editor.canvas)  # no rect: no-op
    assert doc.undo_stack.count() == 0

    drag(tool, doc, editor.canvas, QPointF(10, 10), QPointF(11, 11))
    assert tool.rect is None  # sub-2px drags are discarded


def test_crop_layer_only_trims_the_layer_and_leaves_the_canvas(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    from photoslop.layer import Layer

    doc.layers.append(Layer.blank("Second", QSize(100, 80)))
    doc.active_index = 1
    other = doc.layers[0]

    win.options.crop_layer_only = True
    drag(tool, doc, editor.canvas, QPointF(20, 10), QPointF(70, 60))
    tool.commit(editor.canvas)

    assert doc.size == QSize(100, 80)  # canvas untouched
    assert doc.layers[1].image.size() == QSize(50, 50)
    assert doc.layers[1].offset == QPoint(20, 10)
    assert other.image.size() == QSize(100, 80)  # other layers untouched
    assert other.offset == QPoint(0, 0)
    assert doc.undo_stack.command(0).text() == "Crop Layer"

    doc.undo_stack.undo()
    assert doc.layers[1].image.size() == QSize(100, 80)
    assert doc.layers[1].offset == QPoint(0, 0)
    assert doc.size == QSize(100, 80)


def test_crop_layer_only_refuses_a_box_that_misses_the_layer(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    doc.layers[0].offset = QPoint(80, 60)  # layer now sits in the far corner
    win.options.crop_layer_only = True
    drag(tool, doc, editor.canvas, QPointF(0, 0), QPointF(40, 40))
    tool.commit(editor.canvas)

    assert doc.undo_stack.count() == 0
    assert tool.rect == QRect(0, 0, 40, 40)  # kept up, ready to be redrawn


def test_crop_layer_drops_parametric_data_and_undo_restores_it(qapp):
    """A cropped shape is no longer the shape its vector record describes, so
    the layer falls back to raster — and undo has to bring the record back."""
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    layer = doc.layers[0]
    layer.vector_data = {"kind": "rect", "x": 0, "y": 0, "w": 100, "h": 80}
    win.options.crop_layer_only = True
    drag(tool, doc, editor.canvas, QPointF(10, 10), QPointF(60, 50))
    tool.commit(editor.canvas)

    assert layer.vector_data is None
    doc.undo_stack.undo()
    assert layer.vector_data == {"kind": "rect", "x": 0, "y": 0, "w": 100, "h": 80}


def test_crop_tool_still_crops_the_document_by_default(qapp):
    win = make_window(qapp)
    assert win.options.crop_layer_only is False
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]

    drag(tool, doc, editor.canvas, QPointF(20, 10), QPointF(70, 60))
    tool.commit(editor.canvas)
    assert doc.size == QSize(50, 50)
    assert doc.undo_stack.command(0).text() == "Crop"


def test_layer_only_shield_covers_the_layer_not_the_document(qapp):
    """The darkened area is a promise about what the commit discards, so in
    layer-only mode it has to follow the layer's extent."""
    from PySide6.QtGui import QImage, QPainter

    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["crop"]
    doc.layers[0].offset = QPoint(0, 0)
    doc.layers[0].image = doc.layers[0].image.copy(QRect(0, 0, 40, 30))

    def shielded(pixel: QPoint) -> bool:
        canvas_img = QImage(100, 80, QImage.Format.Format_ARGB32_Premultiplied)
        canvas_img.fill(QColor(255, 255, 255))
        painter = QPainter(canvas_img)
        tool.overlay(doc, painter, editor.canvas)
        painter.end()
        return QColor(canvas_img.pixel(pixel)).red() < 250

    editor.canvas.zoom = 1.0
    drag(tool, doc, editor.canvas, QPointF(5, 5), QPointF(20, 20))

    win.options.crop_layer_only = False
    assert shielded(QPoint(60, 50)) is True  # outside the box, inside the doc

    win.options.crop_layer_only = True
    assert shielded(QPoint(60, 50)) is False  # outside the layer: nothing lost
    assert shielded(QPoint(30, 25)) is True  # inside the layer, outside the box


def test_layer_only_checkbox_is_wired_and_shown_only_for_crop(qapp):
    win = make_window(qapp)
    checkbox = win._option_widgets["crop_layer_only"]

    checkbox.setChecked(True)
    assert win.options.crop_layer_only is True
    checkbox.setChecked(False)
    assert win.options.crop_layer_only is False

    checkbox.setChecked(True)
    win._reset_tool_options()
    assert win.options.crop_layer_only is False  # reset restores the default

    (crop_act,) = win._option_actions["crop"]
    win._set_tool("crop")
    assert crop_act.isVisible() is True
    win._set_tool("brush")
    assert crop_act.isVisible() is False
