# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSettings
from PySide6.QtGui import QAction

from photoslop.mainwindow import MainWindow
from photoslop.preferences import PreferencesDialog


def test_preferences_has_both_tabs(qapp):
    dlg = PreferencesDialog()
    titles = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert titles == ["Model Backend", "Color"]


def test_preferences_apply_persists_model_backend(qapp):
    dlg = PreferencesDialog()
    dlg.model_panel.combo.setCurrentIndex(0)  # "(none)"
    dlg.model_panel.url.setText("http://example.test:8188/photoslop")
    dlg._apply()  # OK
    s = QSettings("CryptoJones", "Photoslop")
    assert s.value("model/http_url") == "http://example.test:8188/photoslop"
    assert s.value("model/adapter") == ""


def test_preferences_menu_action_has_role(qapp):
    win = MainWindow()
    roles = {}

    def walk(menu):
        for act in menu.actions():
            if act.menu():
                walk(act.menu())
            else:
                roles[act.text().replace("&", "")] = act.menuRole()

    for act in win.menuBar().actions():
        if act.menu():
            walk(act.menu())

    assert roles["Preferences…"] == QAction.MenuRole.PreferencesRole
    assert roles["About Photoslop"] == QAction.MenuRole.AboutRole
    assert roles["Quit"] == QAction.MenuRole.QuitRole
