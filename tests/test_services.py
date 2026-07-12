# SPDX-License-Identifier: Apache-2.0
"""Widget-independent file, export, filter, model, and workspace services."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from photoslop.document import Document
from photoslop.services import ExportRequest, ExportService, FileService, FilterService
from photoslop.tasks import snapshot_document
from photoslop.workspace import WorkspaceController


def test_file_service_round_trips_ora_without_widgets(qapp, tmp_path):
    doc = Document.new(QSize(30, 20), 72, "service", QColor("red"))
    path = str(tmp_path / "service.ora")
    FileService.save(snapshot_document(doc), path)
    loaded = FileService.load(path)
    assert loaded.size == doc.size
    assert loaded.flatten().pixelColor(5, 5) == QColor("red")


def test_filter_service_uses_cow_and_does_not_mutate_snapshot(qapp):
    source = QImage(10, 10, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("red"))
    result = FilterService.apply(source, lambda image, _mask: image.fill(QColor("blue")))
    assert source.pixelColor(0, 0) == QColor("red")
    assert result.pixelColor(0, 0) == QColor("blue")


def test_export_service_writes_headless_engine_result(qapp, tmp_path):
    doc = Document.new(QSize(20, 10), 72, "export", QColor("green"))
    path = str(tmp_path / "export.png")
    request = ExportRequest(path, "PNG", -1, QSize(10, 5), 72)
    ExportService.write(doc.flatten(), snapshot_document(doc), request)
    assert QImage(path).size() == QSize(10, 5)


def test_workspace_controller_delegates_save_restore_and_reset(qapp):
    from photoslop.mainwindow import MainWindow

    win = MainWindow()
    controller = WorkspaceController(win, win.settings)
    controller.save()
    assert controller.restore()
    controller.reset()
