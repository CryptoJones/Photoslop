# SPDX-License-Identifier: Apache-2.0
"""Edit → Options → Rulers switches units, in sync with View → Units."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_edit_options_rulers_switches_units(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(40, 30), 72.0, "u", QColor(255, 255, 255)))
    win.set_unit("px")

    rulers = win._rulers_menu
    assert rulers.title().replace("&", "") == "Rulers"
    assert win._options_menu.title().replace("&", "") == "Options"
    # the Rulers submenu really hangs off Edit → Options
    assert rulers.menuAction() in win._options_menu.actions()

    by_label = {a.text(): a for a in rulers.actions()}
    assert set(by_label) == {"pixels", "freedom units", "millimetres", "picas"}

    by_label["millimetres"].trigger()
    assert win.unit == "mm"
    by_label["freedom units"].trigger()
    assert win.unit == "in"
    # the View → Units radio is the same action object, so it is checked too
    assert win._unit_actions["in"].isChecked()
    by_label["picas"].trigger()
    assert win.unit == "pc"
    win.set_unit("px")
