# SPDX-License-Identifier: Apache-2.0
"""New-document presets, recent files, menus, and About dialog polish."""

from PySide6.QtCore import QPoint, QSettings, QSize
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtWidgets import QDialog, QFileDialog

from photoslop.dialogs import PAPER_SIZES, NewDocumentDialog
from photoslop.document import Document
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
            return [a.text().replace("&", "") for a in act.menu().actions() if a.text()]
    raise AssertionError(f"no menu titled {title!r}")


def test_open_recent_is_most_recent_first_deduplicated_and_capped(qapp, tmp_path):
    win = MainWindow()
    paths = [str(tmp_path / f"document-{index}.png") for index in range(5)]
    for path in [*paths, paths[2]]:
        win._remember_recent(path)

    expected = [paths[2], paths[4], paths[3], paths[1]]
    assert win._recent_paths() == expected
    assert QSettings("CryptoJones", "Photoslop").value("files/recent") == expected
    actions = win._recent_menu.actions()
    assert [action.data() for action in actions] == expected
    assert [action.text().replace("&", "") for action in actions] == [
        "1 document-2.png",
        "2 document-4.png",
        "3 document-3.png",
        "4 document-1.png",
    ]


def test_open_recent_opens_existing_and_removes_missing(qapp, tmp_path):
    existing = tmp_path / "existing.png"
    image = QImage(12, 8, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor("red"))
    assert image.save(str(existing))
    missing = str(tmp_path / "missing.png")
    QSettings("CryptoJones", "Photoslop").setValue("files/recent", [missing, str(existing)])
    win = MainWindow()

    win._recent_menu.actions()[0].trigger()
    assert win._recent_paths() == [str(existing)]
    assert "no longer exists" in win.statusBar().currentMessage()
    win._recent_menu.actions()[0].trigger()
    assert win.tabs.count() == 1
    assert win.current_doc().name == "existing.png"


def test_file_dialog_directory_defaults_home_and_follows_successful_save(
    qapp, tmp_path, monkeypatch
):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    win = MainWindow()
    assert win._last_directory() == str(home)

    previous = tmp_path / "previous"
    previous.mkdir()
    win.settings.setValue("files/last-directory", str(previous))
    destination = tmp_path / "saved" / "document.ora"
    destination.parent.mkdir()
    requested = []

    def accept_dialog(dialog):
        requested.append(
            (
                dialog.directory().absolutePath(),
                dialog.selectedFiles()[0],
                dialog.testOption(QFileDialog.Option.DontUseNativeDialog),
            )
        )
        dialog.setDirectory(str(destination.parent))
        dialog.selectFile(destination.name)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr("photoslop.mainwindow.QFileDialog.exec", accept_dialog)
    doc = Document.new(QSize(20, 10), 72, "document", QColor("white"))
    win.add_document(doc)

    assert win._save_doc(doc, background=False)
    assert requested == [(str(previous), str(previous / "document.ora"), True)]
    assert win._last_directory() == str(destination.parent)
    assert destination.exists()


def test_select_menu_owns_the_selection_actions(qapp):
    win = MainWindow()
    select_texts = _menu_texts(win, "&Select")
    for expected in ("All", "Deselect", "Subject (Model)", "Feather…", "Refine…"):
        assert expected in select_texts

    edit_texts = _menu_texts(win, "&Edit")
    for moved in ("Select All", "Deselect", "Select Subject (Model)"):
        assert moved not in edit_texts


def test_preferences_lives_in_edit_and_options_keeps_rulers(qapp):
    # Model Backend + Color Settings were consolidated into Edit → Preferences…
    # (#131); Edit → Options now only carries the Rulers submenu.
    win = MainWindow()
    edit_texts = _menu_texts(win, "&Edit")
    assert "Preferences…" in edit_texts
    assert "Model Backend…" not in edit_texts
    assert "Color Settings…" not in edit_texts

    # resolve within the loop (see _menu_texts) — Options is a submenu of Edit
    for act in win.menuBar().actions():
        if act.text() == "&Edit":
            for sub in act.menu().actions():
                if sub.text() == "&Options":
                    options_texts = [
                        a.text().replace("&", "") for a in sub.menu().actions() if a.text()
                    ]
                    assert "Rulers" in options_texts
                    assert "Model Backend…" not in options_texts
                    return
    raise AssertionError("no Edit → Options menu found")


def test_edit_menu_layer_transforms(qapp):
    from photoslop.document import Document

    win = MainWindow()
    win.add_document(Document.new(QSize(40, 30), 72.0, "t", QColor(90, 90, 90)))
    doc = win.current_doc()

    edit_texts = _menu_texts(win, "&Edit")
    for expected in ("Rotate 90° CW", "Rotate 90° CCW", "Flip Horizontal", "Flip Vertical"):
        assert expected in edit_texts

    # the entries act on the ACTIVE LAYER (Photoshop's Edit → Transform)
    for act in win.menuBar().actions():
        if act.text() == "&Edit":
            rotate = next(
                a for a in act.menu().actions() if a.text().replace("&", "") == "Rotate 90° CW"
            )
            rotate.trigger()
    layer = doc.active_layer
    assert layer.image.width() == 30 and layer.image.height() == 40
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert layer.image.width() == 40 and layer.image.height() == 30


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
