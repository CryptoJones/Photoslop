# SPDX-License-Identifier: Apache-2.0
"""Widget-independent file, export, filter, and model operation services."""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage

from photoslop import color, io_formats, npimage
from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.io_raw import develop_raw, is_raw_path, load_raw


class FileService:
    @staticmethod
    def load(path: str, raw_params: dict | None = None) -> Document:
        if path.lower().endswith(".ora"):
            return load_ora(path)
        if is_raw_path(path):
            image = (develop_raw(path, **raw_params) if raw_params is not None
                     else load_raw(path))
            return Document.from_image(image, os.path.basename(path), 72.0)
        if io_formats.is_extra_path(path):
            if not io_formats.available(path):
                raise ValueError(io_formats.missing_hint(path))
            image = io_formats.load_extra(path)
        else:
            image = QImage(path)
        if image is None or image.isNull():
            raise ValueError(f"Could not open {path}")
        dpm = image.dotsPerMeterX()
        dpi = round(dpm * 0.0254) if dpm > 0 else 72
        return Document.from_image(image, os.path.basename(path), float(dpi))

    @staticmethod
    def save(document: Document, path: str) -> str:
        save_ora(document, path)
        return path


@dataclass(frozen=True)
class ExportRequest:
    path: str
    format: str
    quality: int
    size: QSize
    dpi: float


class ExportService:
    @staticmethod
    def write(base: QImage, document: Document, request: ExportRequest) -> str:
        image = (base if request.size == base.size() else base.scaled(
            request.size, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        image.setDotsPerMeterX(round(request.dpi / 0.0254))
        image.setDotsPerMeterY(round(request.dpi / 0.0254))
        color.tag_for_export(image, document)
        if request.format in {"AVIF", "JPEG XL"}:
            ok = io_formats.save_extra(image, request.path, max(1, request.quality))
        else:
            ok = image.save(request.path, request.format, request.quality)
        if not ok:
            raise ValueError(f"Export failed: {request.path}")
        return request.path


class FilterService:
    @staticmethod
    def apply(snapshot: QImage, operation, mask=None, weights=None) -> QImage:
        image = QImage(snapshot)
        operation(image, mask)
        if weights is not None:
            npimage.blend_by_weights(image, snapshot, weights)
        return image


class ModelService:
    @staticmethod
    def denoise(adapter, image: QImage, strength: int) -> QImage:
        return adapter.denoise(image, strength).convertToFormat(image.format())

    @staticmethod
    def generative_fill(adapter, image: QImage, mask: QImage, prompt: str,
                        expected: QSize) -> QImage:
        result = adapter.generative_fill(image, mask, prompt)
        if result.size() != expected:
            raise ValueError("Backend returned an image of the wrong size")
        return result.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    @staticmethod
    def select_subject(adapter, image: QImage) -> QImage:
        return adapter.select_subject(image)


def opaque_export_base(document: Document, fmt: str, transparent: QImage) -> QImage:
    return (document.flatten(QColor(255, 255, 255))
            if fmt in {"JPEG", "BMP"} else QImage(transparent))
