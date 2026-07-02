# SPDX-License-Identifier: Apache-2.0
"""Selection copy/delete/paste and cross-document layer copy — driven through
the real MainWindow actions."""

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QPainterPath

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(60, 40), 72.0, "a", QColor(255, 0, 0)))
    win.add_document(Document.new(QSize(80, 50), 72.0, "b", QColor(0, 0, 255)))
    return win


def rect_path(x, y, w, h) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRect(x, y, w, h))
    return path


def test_copy_paste_within_document(qapp):
    win = make_window(qapp)
    win.tabs.setCurrentIndex(0)
    doc = win.current_doc()
    doc.set_selection(rect_path(10, 10, 20, 10))
    win.action_copy()
    assert win.pixel_clip is not None
    img, origin = win.pixel_clip
    assert img.size() == QSize(20, 10)
    assert origin == QPoint(10, 10)
    assert img.pixelColor(5, 5) == QColor(255, 0, 0)

    win.action_paste()
    assert len(doc.layers) == 2
    assert doc.layers[1].name == "Pasted"
    assert doc.layers[1].offset == QPoint(10, 10)
    doc.undo_stack.undo()
    assert len(doc.layers) == 1


def test_delete_selection(qapp):
    win = make_window(qapp)
    win.tabs.setCurrentIndex(0)
    doc = win.current_doc()
    doc.set_selection(rect_path(0, 0, 10, 10))
    win.action_delete_selection()
    assert doc.active_layer.image.pixelColor(5, 5).alpha() == 0
    assert doc.active_layer.image.pixelColor(15, 15) == QColor(255, 0, 0)
    doc.undo_stack.undo()
    assert doc.active_layer.image.pixelColor(5, 5) == QColor(255, 0, 0)


def test_cross_document_pixel_paste(qapp):
    win = make_window(qapp)
    win.tabs.setCurrentIndex(0)
    doc_a = win.current_doc()
    doc_a.set_selection(rect_path(0, 0, 30, 20))
    win.action_copy()

    win.tabs.setCurrentIndex(1)
    doc_b = win.current_doc()
    win.action_paste()
    assert len(doc_b.layers) == 2
    pasted = doc_b.layers[1]
    assert pasted.image.size() == QSize(30, 20)
    assert pasted.image.pixelColor(2, 2) == QColor(255, 0, 0)


def test_cross_document_layer_copy(qapp):
    win = make_window(qapp)
    win.tabs.setCurrentIndex(0)
    doc_a = win.current_doc()
    doc_a.active_layer.name = "hero"
    win.action_copy_layer()

    win.tabs.setCurrentIndex(1)
    doc_b = win.current_doc()
    win.action_paste_layer()
    assert len(doc_b.layers) == 2
    assert doc_b.layers[1].name == "hero"
    assert doc_b.layers[1].image.pixelColor(1, 1) == QColor(255, 0, 0)
    # copy-on-write: painting the copy must not touch the original
    doc_b.layers[1].image.fill(QColor(0, 255, 0))
    assert doc_a.layers[0].image.pixelColor(1, 1) == QColor(255, 0, 0)


def test_select_all_and_deselect(qapp):
    win = make_window(qapp)
    win.tabs.setCurrentIndex(0)
    doc = win.current_doc()
    win.action_select_all()
    assert doc.selection is not None
    assert doc.selection_bounds() == QRect(QPoint(0, 0), doc.size)
    win.action_deselect()
    assert doc.selection is None
