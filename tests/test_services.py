# SPDX-License-Identifier: Apache-2.0
"""Widget-independent file, export, filter, model, and workspace services."""

import os

import numpy as np
import pytest
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QColor, QImage

from photoslop import services
from photoslop.atomicio import WriteCoordinator
from photoslop.document import Document
from photoslop.services import (
    ExportRequest,
    ExportService,
    FileService,
    FilterService,
    ModelService,
    export_artboards,
    opaque_export_base,
)
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


def test_file_service_routes_svg_through_the_svg_loader(qapp, tmp_path):
    path = tmp_path / "shape.svg"
    path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="8">'
        '<rect width="12" height="8" fill="#00ff00"/></svg>',
        encoding="utf-8",
    )
    loaded = FileService.load(str(path))
    assert loaded.size == QSize(12, 8)


def test_file_service_names_the_missing_extra_for_an_uninstalled_codec(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(services.io_formats, "available", lambda _path: False)
    path = str(tmp_path / "photo.avif")
    with pytest.raises(ValueError, match="needs the optional extra"):
        FileService.load(path)


def test_export_service_raises_when_the_encoder_refuses(qapp, tmp_path):
    doc = Document.new(QSize(4, 4), 72, "export", QColor("green"))
    path = tmp_path / "refused.png"
    request = ExportRequest(str(path), "NOT-A-FORMAT", -1, QSize(4, 4), 72)
    with pytest.raises(ValueError, match="Export failed"):
        ExportService.write(doc.flatten(), snapshot_document(doc), request)
    assert not path.exists()


def test_export_service_commits_through_a_write_ticket(qapp, tmp_path):
    doc = Document.new(QSize(6, 6), 72, "export", QColor("blue"))
    path = str(tmp_path / "ticketed.png")
    ticket = WriteCoordinator().reserve(path)
    request = ExportRequest(path, "PNG", -1, QSize(6, 6), 300)
    written_path = ExportService.write(
        doc.flatten(), snapshot_document(doc), request, ticket=ticket
    )
    assert written_path == path
    written = QImage(path)
    assert written.size() == QSize(6, 6)
    assert round(written.dotsPerMeterX() * 0.0254) == 300


def test_export_artboards_skips_off_canvas_boards_and_deduplicates_names(qapp, tmp_path):
    doc = Document.new(QSize(20, 20), 72, "boards", QColor("red"))
    doc.artboards = [
        ("Hero", QRect(0, 0, 10, 10)),
        ("hero", QRect(10, 10, 10, 10)),
        ("off canvas", QRect(100, 100, 5, 5)),
        ("???", QRect(0, 10, 5, 5)),
    ]
    written = export_artboards(doc, str(tmp_path / "out"))
    assert [os.path.basename(p) for p in written] == ["Hero.png", "hero-2.png", "___.png"]
    assert QImage(written[0]).size() == QSize(10, 10)


def test_export_artboards_raises_when_a_board_cannot_be_encoded(qapp, tmp_path, monkeypatch):
    doc = Document.new(QSize(8, 8), 72, "boards", QColor("red"))
    doc.artboards = [("only", QRect(0, 0, 8, 8))]
    monkeypatch.setattr(QImage, "save", lambda *_args, **_kwargs: False)
    with pytest.raises(ValueError, match="Artboard export failed"):
        export_artboards(doc, str(tmp_path))


def test_filter_service_blends_back_by_feather_weights(qapp):
    source = QImage(2, 1, QImage.Format.Format_ARGB32_Premultiplied)
    source.fill(QColor("red"))
    weights = np.array([[1.0, 0.0]], dtype=np.float32)
    result = FilterService.apply(
        source, lambda image, _mask: image.fill(QColor("blue")), weights=weights
    )
    assert result.pixelColor(0, 0) == QColor("blue")
    assert result.pixelColor(1, 0) == QColor("red")


class _Adapter:
    def __init__(self, result: QImage):
        self.result = result

    def denoise(self, _image, _strength):
        return self.result

    def generative_fill(self, _image, _mask, _prompt):
        return self.result

    def select_subject(self, _image):
        return self.result


def _image(width: int, height: int, fmt=QImage.Format.Format_RGB32) -> QImage:
    image = QImage(width, height, fmt)
    image.fill(QColor("white"))
    return image


def test_model_service_normalises_well_formed_backend_results(qapp):
    source = _image(4, 4, QImage.Format.Format_ARGB32)
    denoised = ModelService.denoise(_Adapter(_image(4, 4)), source, 50)
    assert denoised.format() == source.format()
    filled = ModelService.generative_fill(
        _Adapter(_image(4, 4)), source, _image(4, 4), "sky", QSize(4, 4)
    )
    assert filled.format() == QImage.Format.Format_ARGB32_Premultiplied
    mask = ModelService.select_subject(_Adapter(_image(4, 4)), source)
    assert mask.format() == QImage.Format.Format_Grayscale8


@pytest.mark.parametrize("result", [QImage(), _image(3, 4)])
def test_model_service_rejects_null_or_missized_backend_results(qapp, result):
    source = _image(4, 4)
    adapter = _Adapter(result)
    with pytest.raises(ValueError, match="image of the wrong size"):
        ModelService.denoise(adapter, source, 50)
    with pytest.raises(ValueError, match="mask of the wrong size"):
        ModelService.select_subject(adapter, source)
    with pytest.raises(ValueError, match="image of the wrong size"):
        ModelService.generative_fill(adapter, source, source, "sky", QSize(4, 4))


def test_opaque_export_base_flattens_onto_white_only_for_alpha_less_formats(qapp):
    doc = Document.new(QSize(2, 2), 72, "base", QColor(0, 0, 0, 0))
    transparent = doc.flatten()
    assert opaque_export_base(doc, "JPEG", transparent).pixelColor(0, 0) == QColor("white")
    assert opaque_export_base(doc, "BMP", transparent).pixelColor(0, 0) == QColor("white")
    assert opaque_export_base(doc, "PNG", transparent).pixelColor(0, 0).alpha() == 0
