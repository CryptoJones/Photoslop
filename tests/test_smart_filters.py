# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QPointF, QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.mainwindow import MainWindow
from tests.test_actions_macro import edge_image


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    doc = Document.new(QSize(60, 40), 72.0, "sf", QColor(0, 0, 0))
    doc.layers[0].image = edge_image()
    win.add_document(doc)
    return win


def test_smart_filters_record_and_reapply(qapp):
    win = make_window(qapp)
    doc = win.current_doc()
    layer = doc.active_layer

    win.action_gaussian_blur_direct(4)  # before conversion: not recorded
    assert layer.smart_filters == []
    doc.undo_stack.undo()

    win.action_convert_smart()
    win.action_gaussian_blur_direct(8)
    win.action_unsharp_direct(120)
    assert layer.smart_filters == [("gaussian", 8), ("unsharp", 120)]
    filtered_edge = layer.image.pixelColor(30, 20).red()

    # deface, then re-apply: restore + replay in one macro
    brush = win.tools["brush"]
    win.options.size = 20
    win.options.foreground = QColor(255, 0, 0)
    editor = win.current_editor()
    brush.press(doc, editor.canvas, QPointF(30, 20), None)
    brush.release(doc, editor.canvas, QPointF(30, 20), None)
    assert layer.image.pixelColor(30, 20).red() > 200

    count_before = doc.undo_stack.count()
    win.action_reapply_smart_filters()
    assert layer.smart_filters == [("gaussian", 8), ("unsharp", 120)]  # no dupes
    assert abs(layer.image.pixelColor(30, 20).red() - filtered_edge) <= 2
    assert doc.undo_stack.count() == count_before + 1  # one macro
    doc.undo_stack.undo()
    assert layer.image.pixelColor(30, 20).red() > 200  # deface back


def test_smart_filters_guards_and_ora_round_trip(qapp, tmp_path):
    win = make_window(qapp)
    doc = win.current_doc()

    win.action_reapply_smart_filters()  # not smart: refused
    assert doc.undo_stack.count() == 0
    win.action_convert_smart()
    win.action_reapply_smart_filters()  # smart but empty stack: refused
    assert doc.undo_stack.count() == 0

    win.action_gaussian_blur_direct(6)
    path = str(tmp_path / "sf.ora")
    save_ora(doc, path)
    loaded = load_ora(path)
    assert loaded.layers[0].smart_filters == [("gaussian", 6)]
    assert loaded.layers[0].clone().smart_filters == [("gaussian", 6)]
