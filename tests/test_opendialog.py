# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QHeaderView, QMainWindow, QTreeView, QWidget

from photoslop.document import Document
from photoslop.io_ora import save_ora
from photoslop.layer import Layer
from photoslop.opendialog import OpenImageDialog, preview_info


def make_png(tmp_path, name="pic.png", size=(600, 400)):
    img = QImage(QSize(*size), QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(10, 120, 240))
    path = str(tmp_path / name)
    img.save(path)
    return path


def test_preview_info_png_scaled(qapp, tmp_path):
    path = make_png(tmp_path)
    img, info = preview_info(path)
    assert img is not None
    assert max(img.width(), img.height()) <= 256  # scaled decode, not full size
    assert "600×400" in info and "PNG" in info and "KB" in info


def test_preview_info_ora(qapp, tmp_path):
    doc = Document.new(QSize(80, 50), 72.0, "d", QColor(255, 0, 0))
    doc.layers.append(Layer.blank("top", QSize(80, 50)))
    path = str(tmp_path / "art.ora")
    save_ora(doc, path)
    img, info = preview_info(path)
    assert img is not None and not img.isNull()
    assert "80×50" in info and "2 layers" in info and "OpenRaster" in info


def test_preview_info_garbage(qapp, tmp_path):
    bad = tmp_path / "fake.ora"
    bad.write_bytes(b"not a zip")
    img, info = preview_info(str(bad))
    assert img is None and "Unreadable" in info
    img, info = preview_info(str(tmp_path / "missing.png"))
    assert img is None and info == "No preview"


def test_dialog_updates_preview(qapp, tmp_path):
    path = make_png(tmp_path, size=(300, 200))
    dialog = OpenImageDialog()
    dialog._update_preview(path)
    while dialog._preview_tasks.active:
        qapp.processEvents()
        QTest.qWait(5)
    assert dialog._image_label.pixmap() is not None
    assert not dialog._image_label.pixmap().isNull()
    assert "300×200" in dialog._info_label.text()

    dialog._update_preview(str(tmp_path / "nope.png"))
    while dialog._preview_tasks.active:
        qapp.processEvents()
        QTest.qWait(5)
    assert "No preview" in dialog._info_label.text()


def test_dialog_fits_to_parent_canvas(qapp):
    # With a shown main window, the dialog targets its central widget's
    # on-screen rect so it fills the workable image area (issue #144).
    win = QMainWindow()
    central = QWidget()
    win.setCentralWidget(central)
    win.resize(1000, 700)
    win.show()
    qapp.processEvents()
    try:
        dialog = OpenImageDialog(win)
        rect = dialog._canvas_target_rect(win)
        assert rect is not None
        assert rect.size() == central.size()
    finally:
        win.close()


def test_dialog_fit_rect_none_without_parent(qapp):
    # No parent main window -> nothing to fit to, so no forced geometry.
    dialog = OpenImageDialog()
    assert dialog._fit_rect is None
    assert dialog._canvas_target_rect(None) is None


def test_dialog_shows_all_columns_untruncated(qapp):
    dialog = OpenImageDialog()
    tree = dialog.findChild(QTreeView, "treeView")
    assert tree is not None  # Detail view is active, not the icon/list view
    header = tree.header()
    assert not header.stretchLastSection()
    # every column sizes to its contents -> nothing gets clipped on first open
    for col in range(header.count()):
        assert header.sectionResizeMode(col) == QHeaderView.ResizeMode.ResizeToContents
