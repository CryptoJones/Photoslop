# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QRect, QSize, Qt
from PySide6.QtGui import QColor, QPainter

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


class _AltEv:
    def modifiers(self):
        return Qt.KeyboardModifier.AltModifier


def make_window(qapp) -> MainWindow:
    """Bright checkered texture on the left, flat dark field on the right."""
    win = MainWindow()
    doc = Document.new(QSize(120, 60), 72.0, "hb", QColor(60, 60, 60))
    p = QPainter(doc.active_layer.image)
    for y in range(0, 60, 4):
        for x in range(0, 40, 4):
            if (x // 4 + y // 4) % 2 == 0:
                p.fillRect(QRect(x, y, 4, 4), QColor(220, 220, 220))
            else:
                p.fillRect(QRect(x, y, 4, 4), QColor(160, 160, 160))
    p.end()
    win.add_document(doc)
    win.options.size = 16
    win.options.opacity = 100
    win.options.spacing = 25
    return win


def region_stats(img, x0, y0, size=10):
    values = [img.pixelColor(x0 + dx, y0 + dy).red() for dx in range(size) for dy in range(size)]
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / len(values)
    return mean, var


def test_heal_matches_tone_keeps_texture(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["heal"]

    tool.press(doc, editor.canvas, QPointF(20, 30), _AltEv())  # source: texture
    tool.press(doc, editor.canvas, QPointF(80, 30), None)  # heal into dark field
    tool.release(doc, editor.canvas, QPointF(80, 30), None)

    img = doc.active_layer.image
    mean, var = region_stats(img, 76, 26, 8)
    assert mean < 110  # tone stayed close to the dark destination (60)
    assert var > 30  # but the checker texture came along

    assert doc.undo_stack.command(0).text() == "Healing Brush"
    doc.undo_stack.undo()
    assert img.pixelColor(80, 30) == QColor(60, 60, 60)


def test_no_source_noop(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    doc = editor.doc
    tool = win.tools["heal"]
    tool.press(doc, editor.canvas, QPointF(80, 30), None)
    tool.release(doc, editor.canvas, QPointF(80, 30), None)
    assert doc.undo_stack.count() == 0
