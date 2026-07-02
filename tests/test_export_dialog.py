# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop.document import Document
from photoslop.exportdialog import ExportDialog


def make_doc(qapp) -> Document:
    return Document.new(QSize(200, 100), 72.0, "e", QColor(30, 60, 200, 255))


def test_scale_and_dimensions(qapp):
    dialog = ExportDialog(make_doc(qapp))
    assert dialog.export_size() == QSize(200, 100)
    dialog.scale.setValue(50)
    assert dialog.export_size() == QSize(100, 50)
    assert dialog.export_image().size() == QSize(100, 50)
    assert "100 × 50" in dialog.dims_label.text()


def test_quality_only_for_lossy(qapp):
    dialog = ExportDialog(make_doc(qapp))
    dialog.format_box.setCurrentText("PNG")
    assert not dialog.quality.isEnabled()
    assert dialog.quality_label.text() == "lossless"
    assert dialog.chosen_quality() == -1
    dialog.format_box.setCurrentText("JPEG")
    assert dialog.quality.isEnabled()
    assert dialog.chosen_quality() == 90


def test_opaque_formats_flatten_white(qapp):
    doc = Document.new(QSize(10, 10), 72.0, "t", None)  # transparent background
    dialog = ExportDialog(doc)
    dialog.format_box.setCurrentText("JPEG")
    img = dialog.export_image()
    px = img.pixelColor(5, 5)
    assert px.red() > 250 and px.green() > 250 and px.blue() > 250

    dialog.format_box.setCurrentText("PNG")
    assert dialog.export_image().pixelColor(5, 5).alpha() == 0


def test_encoded_size_readout(qapp):
    dialog = ExportDialog(make_doc(qapp))
    dialog._update_size()  # bypass debounce
    text = dialog.size_label.text()
    assert text.endswith("KB") or text.endswith("MB")


def test_export_roundtrip_file(qapp, tmp_path):
    dialog = ExportDialog(make_doc(qapp))
    dialog.scale.setValue(50)
    dialog.format_box.setCurrentText("PNG")
    path = str(tmp_path / "out.png")
    assert dialog.export_image().save(path, dialog.chosen_format(),
                                      dialog.chosen_quality())
    loaded = QImage(path)
    assert loaded.size() == QSize(100, 50)
    assert loaded.pixelColor(50, 25) == QColor(30, 60, 200)
