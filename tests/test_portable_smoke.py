# SPDX-License-Identifier: Apache-2.0

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

from photoslop.app import _run_portable_smoke
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def test_portable_smoke_round_trips_qt_codec_and_pixels(qapp):
    window = MainWindow(recovery_enabled=False)
    window.add_document(Document.new(
        QSize(12, 8), 72, "smoke", QColor("white")))
    _run_portable_smoke(window)
