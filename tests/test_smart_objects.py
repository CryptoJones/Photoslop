# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 40), 72.0, "so", QColor(0, 200, 100)))
    win.options.size = 16
    win.options.hardness = 100
    win.options.opacity = 100
    win.options.flow = 100
    win.options.foreground = QColor(0, 0, 0)
    return win


def test_convert_paint_restore_undo(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    layer = doc.active_layer
    editor = win.current_editor()

    win.action_convert_smart()
    assert layer.source is not None

    brush = win.tools["brush"]  # deface the layer
    brush.press(doc, editor.canvas, QPointF(20, 20), None)
    brush.release(doc, editor.canvas, QPointF(20, 20), None)
    assert layer.image.pixelColor(20, 20) == QColor(0, 0, 0)

    win.action_restore_smart()
    assert layer.image.pixelColor(20, 20) == QColor(0, 200, 100)
    assert doc.undo_stack.command(1).text() == "Restore Smart Object"
    doc.undo_stack.undo()  # un-restore: the paint comes back
    assert layer.image.pixelColor(20, 20) == QColor(0, 0, 0)


def test_restore_requires_smart_and_ora_round_trip(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()
    win.action_restore_smart()  # not a smart object: refused
    assert doc.undo_stack.count() == 0

    win.action_convert_smart()
    path = str(tmp_path / "smart.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.layers[0].source is not None
    assert loaded.layers[0].source.pixelColor(10, 10) == QColor(0, 200, 100)
    assert loaded.layers[0].clone().source is not None
