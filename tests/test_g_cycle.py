# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_g_cycles_bucket_and_gradient(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(10, 10), 72.0, "g", QColor(255, 255, 255)))
    assert win.active_tool.name == "brush"

    win._cycle_fill_tool()  # from any other tool: G lands on bucket
    assert win.active_tool.name == "bucket"
    assert win._tool_actions["bucket"].isChecked()

    win._cycle_fill_tool()  # from bucket: G flips to gradient
    assert win.active_tool.name == "gradient"
    assert win._tool_actions["gradient"].isChecked()

    win._cycle_fill_tool()  # and back
    assert win.active_tool.name == "bucket"
