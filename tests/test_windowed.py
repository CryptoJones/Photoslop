# SPDX-License-Identifier: Apache-2.0
"""Real-window coverage (#274).

Every other desktop test runs ``QT_QPA_PLATFORM=offscreen``, which leaves the
half of the app a person sees first — window creation, exposure by the window
system, HiDPI scale factors, the menu bar — with no coverage at all. These
tests demand a real window system: xvfb on the Linux runner, the native window
server on macOS. They are opted into with ``PHOTOSLOP_WINDOWED_TESTS=1`` so
the offscreen jobs skip them, and they verify the opt-in was honest — asking
for windowed coverage while Qt still got the offscreen platform is a
configuration error, not a pass.
"""

import os
import subprocess
import sys
import textwrap

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from photoslop.document import Document
from photoslop.mainwindow import MainWindow

pytestmark = pytest.mark.skipif(
    os.environ.get("PHOTOSLOP_WINDOWED_TESTS") != "1",
    reason="needs a real window system; run with PHOTOSLOP_WINDOWED_TESTS=1",
)


@pytest.fixture
def window(qapp):
    assert qapp.platformName() != "offscreen", (
        "windowed tests were asked for, but Qt still got the offscreen platform — "
        "set QT_QPA_PLATFORM explicitly (xcb under xvfb, cocoa on macOS), because "
        "conftest.py defaults it to offscreen before Qt starts"
    )
    window = MainWindow(recovery_enabled=False)
    window.add_document(Document.new(QSize(320, 240), 72.0, None, QColor("white")))
    yield window
    window.close()


def test_the_window_system_actually_exposes_the_window(window):
    """`show()` succeeding offscreen proves nothing about a real screen; only
    the window system can expose a window, and waiting for that exposure is
    the one assertion offscreen cannot fake."""
    window.show()
    window.raise_()
    window.activateWindow()
    assert QTest.qWaitForWindowExposed(window, 15000), "the window system never exposed the window"
    assert window.isVisible()
    assert window.windowHandle() is not None and window.windowHandle().isExposed()


def test_the_screen_reports_a_usable_scale_factor(window):
    window.show()
    assert QTest.qWaitForWindowExposed(window, 15000)
    assert window.devicePixelRatio() >= 1.0
    assert window.screen() is not None
    assert window.screen().logicalDotsPerInch() > 0


def test_a_forced_hidpi_scale_factor_reaches_the_window():
    """HiDPI, without HiDPI hardware: QT_SCALE_FACTOR must be set before Qt
    starts, so the check runs in a process of its own. On a genuinely HiDPI
    screen the factor multiplies, hence at least rather than exactly two."""
    probe = textwrap.dedent(
        """
        import sys
        from PySide6.QtWidgets import QApplication, QMainWindow
        app = QApplication(sys.argv)
        window = QMainWindow()
        window.show()
        sys.exit(0 if window.devicePixelRatio() >= 2.0 else 17)
        """
    )
    environment = dict(os.environ, QT_SCALE_FACTOR="2")
    result = subprocess.run(
        [sys.executable, "-c", probe], env=environment, capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"a window under QT_SCALE_FACTOR=2 did not report a HiDPI ratio "
        f"(exit {result.returncode}): {result.stderr.strip()}"
    )


def test_the_menu_bar_is_real(window):
    """On macOS the bar must be the native one at the top of the screen; under
    X it lives in the window, where visible-with-a-height is what real means."""
    bar = window.menuBar()
    assert bar is not None
    titles = [action.text() for action in bar.actions() if action.text()]
    assert len(titles) >= 3, f"the menu bar is nearly empty: {titles}"
    if sys.platform == "darwin":
        assert bar.isNativeMenuBar(), "macOS should get the native menu bar"
    else:
        window.show()
        assert QTest.qWaitForWindowExposed(window, 15000)
        assert bar.isVisible() and bar.height() > 0
