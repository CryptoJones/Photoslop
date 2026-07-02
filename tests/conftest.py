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


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
