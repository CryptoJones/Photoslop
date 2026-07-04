# SPDX-License-Identifier: Apache-2.0
"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from photoslop import __version__
from photoslop.appicon import app_icon
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    app = QApplication(argv)
    app.setApplicationName("Photoslop")
    app.setOrganizationName("CryptoJones")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())

    window = MainWindow()
    opened = False
    for path in argv[1:]:
        opened = window.open_path(path) or opened
    if not opened:
        window.add_document(
            Document.new(QSize(800, 600), 72.0, None, QColor(255, 255, 255))
        )
    window.show()
    window.raise_()
    window.activateWindow()
    if sys.platform == "darwin":
        # A non-bundled Python app launched from a terminal doesn't steal
        # focus, so the global menu bar stays with the terminal and Photoslop
        # looks menu-less. Ask System Events to bring us to the front once the
        # event loop is running.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _macos_bring_to_front)
    return app.exec()


def _macos_bring_to_front() -> None:
    import contextlib
    import os
    import subprocess
    # best-effort only — never block startup if osascript is unavailable
    with contextlib.suppress(Exception):
        subprocess.run(
            ["osascript", "-e",
             "tell application \"System Events\" to set frontmost of "
             f"(first process whose unix id is {os.getpid()}) to true"],
            check=False, timeout=5,
        )


if __name__ == "__main__":
    raise SystemExit(main())
