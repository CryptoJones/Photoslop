# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QPainter

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


def edge_softness(img) -> int:
    value = img.pixelColor(30, 20).red()
    return min(value, 255 - value) if 0 < value < 255 else 0


def test_record_replay_on_other_document(qapp):
    win = MainWindow()
    doc_a = Document.new(QSize(60, 40), 72.0, "a", QColor(0, 0, 0))
    doc_a.layers[0].image = edge_image()
    win.add_document(doc_a)

    win.action_record_start()
    win.action_gaussian_blur_direct(8)
    win.action_unsharp_direct(120)
    win.action_record_stop()
    assert win.action_recording is None
    assert [label for label, _fn in win.recorded_action] == [
        "Gaussian Blur 8px", "Unsharp Mask 120%"]

    # a second document gets the exact same treatment via Play
    doc_b = Document.new(QSize(60, 40), 72.0, "b", QColor(0, 0, 0))
    doc_b.layers[0].image = edge_image()
    win.add_document(doc_b)
    assert win.current_doc() is doc_b

    win.action_play()
    a_edge = doc_a.active_layer.image.pixelColor(30, 20).red()
    b_edge = doc_b.active_layer.image.pixelColor(30, 20).red()
    assert abs(a_edge - b_edge) <= 2  # replay matches the recorded run

    doc_b.undo_stack.undo()  # one macro step undoes the whole action
    assert doc_b.active_layer.image.pixelColor(30, 20).red() in (0, 255)


def test_recording_only_when_armed_and_play_guard(qapp):
    win = MainWindow()
    doc = Document.new(QSize(60, 40), 72.0, "g", QColor(0, 0, 0))
    doc.layers[0].image = edge_image()
    win.add_document(doc)

    win.action_gaussian_blur_direct(6)  # not recording
    assert win.recorded_action == []
    win.action_play()  # nothing recorded: no-op beyond the status message
    assert doc.undo_stack.count() == 1  # only the direct blur
