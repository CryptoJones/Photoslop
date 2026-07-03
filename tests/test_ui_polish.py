# SPDX-License-Identifier: Apache-2.0
"""New-document presets, clipboard-aware File→New, the Select menu, and the
About button order (v1.0.5 UI polish)."""

from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QGuiApplication, QImage

from photoslop.dialogs import PAPER_SIZES, NewDocumentDialog
from photoslop.mainwindow import MainWindow


def test_paper_size_presets_populate_metric(qapp):
    dlg = NewDocumentDialog()
    dlg.preset_radios["A4"].setChecked(True)
    assert dlg.unit.currentText() == "mm"
    assert (dlg.width.value(), dlg.height.value()) == (210.0, 297.0)
    _, size, dpi, _ = dlg.values()
    assert dpi == 72.0
    assert (size.width(), size.height()) == (595, 842)  # A4 at 72 dpi

    dlg.preset_radios["Letter"].setChecked(True)  # 8.5×11″, the one CJ knows
    _, size, _, _ = dlg.values()
    assert (size.width(), size.height()) == (612, 792)


def test_every_preset_has_metric_and_freedom_labels(qapp):
    dlg = NewDocumentDialog()
    for name, _w, _h, metric, inches in PAPER_SIZES:
        text = dlg.preset_radios[name].text()
        assert metric in text and inches in text and "″" in text


def test_editing_size_flips_back_to_custom(qapp):
    dlg = NewDocumentDialog()
    dlg.preset_radios["A4"].setChecked(True)
    dlg.width.setValue(999)
    assert dlg.custom_radio.isChecked()
    assert not dlg.preset_radios["A4"].isChecked()


def test_unit_switch_keeps_the_preset(qapp):
    dlg = NewDocumentDialog()
    dlg.preset_radios["A4"].setChecked(True)
    dlg.unit.setCurrentText("in")
    assert dlg.preset_radios["A4"].isChecked()  # same physical size
    _, size, _, _ = dlg.values()
    assert (size.width(), size.height()) == (595, 842)


def test_new_dialog_prefills_from_initial_size(qapp):
    dlg = NewDocumentDialog(initial_size=QSize(123, 45))
    assert dlg.unit.currentText() == "px"
    assert (dlg.width.value(), dlg.height.value()) == (123.0, 45.0)
    assert dlg.custom_radio.isChecked()
    _, size, _, _ = dlg.values()
    assert (size.width(), size.height()) == (123, 45)


def test_clip_size_hint_prefers_internal_then_system(qapp):
    win = MainWindow()
    QGuiApplication.clipboard().clear()
    qapp.processEvents()

    sys_img = QImage(40, 30, QImage.Format.Format_ARGB32_Premultiplied)
    sys_img.fill(QColor(1, 2, 3))
    QGuiApplication.clipboard().setImage(sys_img)
    qapp.processEvents()
    assert win._clip_size_hint() == QSize(40, 30)

    internal = QImage(7, 9, QImage.Format.Format_ARGB32_Premultiplied)
    internal.fill(QColor(0, 0, 0))
    win.pixel_clip = (internal, QPoint(0, 0))  # in-app copy wins
    assert win._clip_size_hint() == QSize(7, 9)

    win.pixel_clip = None
    QGuiApplication.clipboard().clear()
    qapp.processEvents()
    assert win._clip_size_hint() is None


def _menu_texts(win, title):
    # resolve the texts while the action wrappers are alive — returning the
    # bare QMenu wrapper out of the loop leaves it prone to shiboken GC
    for act in win.menuBar().actions():
        if act.text() == title:
            return [a.text().replace("&", "")
                    for a in act.menu().actions() if a.text()]
    raise AssertionError(f"no menu titled {title!r}")


def test_select_menu_owns_the_selection_actions(qapp):
    win = MainWindow()
    select_texts = _menu_texts(win, "&Select")
    for expected in ("All", "Deselect", "Subject (Model)",
                     "Feather…", "Refine…"):
        assert expected in select_texts

    edit_texts = _menu_texts(win, "&Edit")
    for moved in ("Select All", "Deselect", "Select Subject (Model)"):
        assert moved not in edit_texts


def test_about_credits_sits_left_of_ok(qapp):
    from PySide6.QtWidgets import QMessageBox

    win = MainWindow()
    box = win._build_about()
    box.show()
    qapp.processEvents()
    ok = box.button(QMessageBox.StandardButton.Ok)
    credits = next(b for b in box.buttons() if "Credits" in b.text())
    assert credits.x() < ok.x()
    box.hide()
