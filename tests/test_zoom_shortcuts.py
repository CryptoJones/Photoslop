# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def make_window(qapp) -> MainWindow:
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 40), 72.0, "z", QColor(255, 255, 255)))
    win.show()
    return win


def test_ctrl_equal_zooms_in(qapp):
    win = make_window(qapp)
    qapp.processEvents()
    editor = win.current_editor()
    editor.set_zoom(1.0)

    # the physical "Ctrl and the +/= key" press on a US keyboard
    QTest.keyClick(win, Qt.Key.Key_Equal, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert editor.canvas.zoom > 1.0

    QTest.keyClick(win, Qt.Key.Key_Minus, Qt.KeyboardModifier.ControlModifier)
    qapp.processEvents()
    assert editor.canvas.zoom == 1.0
    win.close()


def test_zoom_actions_carry_all_bindings_and_buttons_work(qapp):
    win = make_window(qapp)
    editor = win.current_editor()
    editor.set_zoom(1.0)

    zoom_in = next(a for a in win.findChildren(type(win.zoom_in_button))
                   if a.text().startswith("Zoom &In"))
    bindings = {seq.toString() for seq in zoom_in.shortcuts()}
    assert {"Ctrl++", "Ctrl+="} <= bindings

    win.zoom_in_button.trigger()  # the magnifier + toolbar button
    assert editor.canvas.zoom > 1.0
    win.zoom_out_button.trigger()
    assert editor.canvas.zoom == 1.0
    assert not win.zoom_in_button.isCheckable()  # momentary, not a tool
    win.close()
