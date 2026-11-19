# SPDX-License-Identifier: Apache-2.0
import os

import pytest
from PySide6.QtCore import QSettings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _isolated_settings(tmp_path_factory):
    """Keep tests away from the real QSettings — a live Photoslop session's
    saved workspace/geometry must not leak into test windows."""
    path = str(tmp_path_factory.mktemp("qsettings"))
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    # QSettings(org, app) hardcodes NativeFormat — redirect both formats
    for fmt in (QSettings.Format.IniFormat, QSettings.Format.NativeFormat):
        QSettings.setPath(fmt, QSettings.Scope.UserScope, path)
    yield


@pytest.fixture(autouse=True)
def _fresh_settings():
    """Each test starts with clean settings — closeEvent persists window
    geometry/workspace, which would otherwise leak between tests."""
    QSettings("CryptoJones", "Photoslop").clear()
    yield


# Hold the QApplication for the life of the process. The session ``qapp``
# fixture used to drop its only reference at teardown, which let shiboken delete
# the C++ QApplication during pytest's sessionfinish — while Qt's pixmap/font
# caches and other QObjects were still alive. On ubuntu-latest + Python 3.14 that
# deletion order segfaults (exit 139) right after ``[100%]`` and before the
# summary line, with no faulthandler dump because pytest has already disabled its
# handler by then. Keeping a module-level reference means the app is not deleted
# at fixture teardown; the interpreter reclaims it at exit, after pytest is done.
_QAPP = None


@pytest.fixture(scope="session")
def qapp():
    global _QAPP
    if _QAPP is None:
        _QAPP = QApplication.instance() or QApplication([])
    yield _QAPP
