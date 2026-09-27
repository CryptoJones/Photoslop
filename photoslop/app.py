# SPDX-License-Identifier: Apache-2.0
"""Application entry point."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from photoslop import __version__

# The Qt widget stack and the editor window are imported inside main(), after
# the argv checks below. `photoslop --help`, `--version`, `--cli` and `--mcp`
# never need a window, and importing MainWindow alone costs most of a second.
if TYPE_CHECKING:
    from photoslop.mainwindow import MainWindow

USAGE = """\
usage: photoslop [FILE ...]
       photoslop --cli [ARGS ...]
       photoslop --mcp [ARGS ...]
       photoslop -h | --help | --version

Opens the Photoslop editor with each FILE loaded as a document, or a blank
800x600 canvas when none is given.

  --cli       run the headless editor (same as photoslop-cli); see --cli --help
  --mcp       run the MCP server (same as photoslop-mcp); see --mcp --help
  -h, --help  show this message and exit
  --version   print the version and exit
"""


def _attach_console() -> None:
    """Give a windowed Windows build somewhere to print.

    pip's `photoslop` launcher on Windows is a gui-script (pythonw) and the
    portable Photoslop.exe is built --windowed, so a terminal user's stdout is
    None there and anything printed simply vanishes. Borrow the parent
    process's console when there is one; do nothing anywhere else.
    """
    if sys.platform != "win32" or (sys.stdout is not None and sys.stderr is not None):
        return
    try:
        import ctypes

        attach_parent_process = -1
        if not ctypes.windll.kernel32.AttachConsole(attach_parent_process):
            return
        console = open("CONOUT$", "w", encoding="utf-8")  # noqa: SIM115 - lives for the process
    except Exception:
        return
    if sys.stdout is None:
        sys.stdout = console
    if sys.stderr is None:
        sys.stderr = console


def _info_entry_point(argv: list[str]):
    """Answer -h / --help / --version without creating a QApplication (#409).

    Same rule as the --cli/--mcp selector: the flag has to lead, so a file
    literally named `--help` later in argv still opens as a document.
    """
    if len(argv) < 2 or argv[1] not in ("-h", "--help", "--version"):
        return None
    text = f"photoslop {__version__}\n" if argv[1] == "--version" else USAGE

    def show() -> int:
        if sys.stdout is not None:
            sys.stdout.write(text)
            sys.stdout.flush()
        return 0

    return show


def _console_entry_point(argv: list[str]):
    """Reach photoslop-cli / photoslop-mcp through the one bundled executable.

    A pip or uv install exposes both console scripts from pyproject.toml, but a
    portable bundle is a single PyInstaller executable — so without this the
    CLI and the MCP server simply are not present in the shipped archive, and
    the GUI is the only surface a portable user gets.

    The selector has to lead. Accepting it anywhere in argv would swallow a
    file literally named `--cli`, and file arguments are exactly what this
    binary is handed the rest of the time.
    """
    if len(argv) < 2 or argv[1] not in ("--cli", "--mcp"):
        return None
    rest = argv[2:]
    if argv[1] == "--cli":
        from photoslop.cli import main as cli_main

        return lambda: cli_main(rest)

    from photoslop.server import main as server_main

    def run_server() -> int:
        # server.main() parses sys.argv itself and returns None.
        sys.argv = ["photoslop-mcp", *rest]
        server_main()
        return 0

    return run_server


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    delegate = _info_entry_point(argv) or _console_entry_point(argv)
    if delegate is not None:
        _attach_console()
        return delegate()

    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from photoslop.appicon import app_icon
    from photoslop.document import Document
    from photoslop.mainwindow import MainWindow

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
        window.add_document(Document.new(QSize(800, 600), 72.0, None, QColor(255, 255, 255)))
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
    from PySide6.QtGui import QColor

    from photoslop.services import ExportRequest, ExportService, FileService

    document = window.current_doc()
    if document is None or document.active_layer is None:
        raise RuntimeError("smoke document was not created")
    document.active_layer.image.setPixelColor(0, 0, QColor("#13579b"))
    with tempfile.TemporaryDirectory(prefix="photoslop-smoke-") as directory:
        output = Path(directory) / "roundtrip.png"
        request = ExportRequest(str(output), "PNG", 90, document.size, document.dpi)
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
            [
                "osascript",
                "-e",
                'tell application "System Events" to set frontmost of '
                f"(first process whose unix id is {os.getpid()}) to true",
            ],
            check=False,
            timeout=5,
        )


if __name__ == "__main__":
    raise SystemExit(main())
