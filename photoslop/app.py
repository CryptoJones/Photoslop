# SPDX-License-Identifier: Apache-2.0
"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from photoslop import __version__
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("Photoslop")
    app.setOrganizationName("CryptoJones")
    app.setApplicationVersion(__version__)

    window = MainWindow()
    opened = False
    for path in argv[1:]:
        opened = window.open_path(path) or opened
    if not opened:
        window.add_document(
            Document.new(QSize(800, 600), 72.0, None, QColor(255, 255, 255))
        )
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
