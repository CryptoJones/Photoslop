# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainter, QPainterPath

from photoslop import npimage
from photoslop.document import Document
from photoslop.layer import blank_image
from photoslop.mainwindow import MainWindow


def edge_image(w=60, h=40):
    img = blank_image(QSize(w, h))
    img.fill(QColor(0, 0, 0))
    p = QPainter(img)
    p.fillRect(QRect(30, 0, 30, h), QColor(255, 255, 255))
    p.end()
    return img


def test_gaussian_blur_softens_edge(qapp):
    img = edge_image()
    npimage.gaussian_blur(img, 8)
    edge = img.pixelColor(30, 20).red()
    assert 40 < edge < 215  # hard step became a ramp
    assert img.pixelColor(5, 20).red() < 30  # far field ~unchanged
    assert img.pixelColor(55, 20).red() > 225


def test_unsharp_increases_edge_contrast(qapp):
    img = edge_image()
    npimage.gaussian_blur(img, 6)  # soften first
    before_dark = img.pixelColor(26, 20).red()
    before_bright = img.pixelColor(34, 20).red()
    npimage.unsharp_mask(img, 6, 1.5)
    after_dark = img.pixelColor(26, 20).red()
    after_bright = img.pixelColor(34, 20).red()
    assert after_dark < before_dark  # dark side pushed darker
    assert after_bright > before_bright  # bright side pushed brighter


def test_filter_menu_selection_aware_undo(qapp):
    win = MainWindow()
    doc = Document.new(QSize(60, 40), 72.0, "f", QColor(0, 0, 0))
    doc.layers[0].image = edge_image()
    win.add_document(doc)

    path = QPainterPath()
    path.addRect(QRect(0, 0, 60, 20))  # top half only
    doc.set_selection(path)
    win._run_filter("Gaussian Blur", lambda img, m: npimage.gaussian_blur(img, 8, m))

    img = doc.active_layer.image
    assert 40 < img.pixelColor(30, 10).red() < 215  # blurred inside selection
    assert img.pixelColor(29, 35).red() < 10  # crisp outside
    assert img.pixelColor(31, 35).red() > 245
    assert doc.undo_stack.command(0).text() == "Gaussian Blur"
    doc.undo_stack.undo()
    assert img.pixelColor(30, 10).red() in (0, 255)  # exact restore
