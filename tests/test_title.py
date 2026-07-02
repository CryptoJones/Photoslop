# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop import __version__
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_version_in_window_title(qapp):
    win = MainWindow()
    assert __version__ in win.windowTitle()

    win.add_document(Document.new(QSize(40, 30), 72.0, "titledoc", QColor(255, 255, 255)))
    assert win.windowTitle().startswith("titledoc")
    assert __version__ in win.windowTitle()

    # dirty marker joins the doc name, version stays
    win.current_doc().undo_stack.resetClean()
    win._refresh_tab(win.current_doc())
    assert f"— Photoslop {__version__}" in win.windowTitle()
