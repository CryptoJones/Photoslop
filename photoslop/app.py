# SPDX-License-Identifier: Apache-2.0
"""Application entry point."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from photoslop import __version__
from photoslop.appicon import app_icon
from photoslop.document import Document
from photoslop.mainwindow import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    portable_smoke = "--portable-smoke" in argv
    argv = [item for item in argv if item != "--portable-smoke"]
    app = QApplication(argv)
    app.setApplicationName("Photoslop")
    app.setOrganizationName("CryptoJones")
    app.setApplicationVersion(__version__)
    app.setWindowIcon(app_icon())

    window = MainWindow(recovery_enabled=not portable_smoke)
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
    if portable_smoke:
        from PySide6.QtCore import QTimer

        def finish_smoke() -> None:
            try:
                _run_portable_smoke(window)
            except Exception as exc:
                print(f"Photoslop portable smoke failed: {exc}", file=sys.stderr)
                app.exit(1)
            else:
                app.exit(0)

        QTimer.singleShot(0, finish_smoke)
    if sys.platform == "darwin" and not portable_smoke:
        # A non-bundled Python app launched from a terminal doesn't steal
        # focus, so the global menu bar stays with the terminal and Photoslop
        # looks menu-less. Ask System Events to bring us to the front once the
        # event loop is running.
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _macos_bring_to_front)
    return app.exec()


def _run_portable_smoke(window: MainWindow) -> None:
    """Exercise Qt widgets, codecs, engine rendering, export, and import."""
    from photoslop.services import ExportRequest, ExportService, FileService

    document = window.current_doc()
    if document is None or document.active_layer is None:
        raise RuntimeError("smoke document was not created")
    document.active_layer.image.setPixelColor(0, 0, QColor("#13579b"))
    with tempfile.TemporaryDirectory(prefix="photoslop-smoke-") as directory:
        output = Path(directory) / "roundtrip.png"
        request = ExportRequest(
            str(output), "PNG", 90, document.size, document.dpi)
        ExportService.write(document.flatten(), document, request)
        reopened = FileService.load(str(output))
        if reopened.size != document.size:
            raise RuntimeError("PNG round trip changed dimensions")
        if reopened.active_layer.image.pixelColor(0, 0) != QColor("#13579b"):
            raise RuntimeError("PNG round trip changed pixels")


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
