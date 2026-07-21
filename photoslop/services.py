# SPDX-License-Identifier: Apache-2.0
"""Widget-independent file, export, filter, and model operation services."""

from __future__ import annotations

import os
from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage

from photoslop import color, io_formats, npimage
from photoslop.atomicio import WriteTicket, atomic_write
from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.io_raw import develop_raw, is_raw_path, load_raw
from photoslop.io_svg import load_svg, save_svg


class FileService:
    @staticmethod
    def load(path: str, raw_params: dict | None = None) -> Document:
        if path.lower().endswith(".ora"):
            return load_ora(path)
        if path.lower().endswith(".svg"):
            return load_svg(path)
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
    def save(document: Document, path: str, *, ticket: WriteTicket | None = None,
             before_commit=None) -> str:
        (save_svg if path.lower().endswith(".svg") else save_ora)(
            document, path, ticket=ticket, before_commit=before_commit)
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
    def write(base: QImage, document: Document, request: ExportRequest,
              *, ticket: WriteTicket | None = None, before_commit=None) -> str:
        image = (base if request.size == base.size() else base.scaled(
            request.size, Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        image.setDotsPerMeterX(round(request.dpi / 0.0254))
        image.setDotsPerMeterY(round(request.dpi / 0.0254))
        color.tag_for_export(image, document)
        def writer(temporary: str) -> None:
            if request.format in {"AVIF", "JPEG XL"}:
                ok = io_formats.save_extra(
                    image, temporary, max(1, request.quality))
            else:
                ok = image.save(temporary, request.format, request.quality)
            if not ok:
                raise ValueError(f"Export failed: {request.path}")

        if ticket is None:
            atomic_write(request.path, writer, before_commit=before_commit)
        else:
            ticket.write(writer, before_commit=before_commit)
        return request.path


def export_artboards(document: Document, directory: str) -> list[str]:
    """Export every valid artboard atomically with collision-safe names."""
    os.makedirs(directory, exist_ok=True)
    flat = document.flatten()
    written: list[str] = []
    used: set[str] = set()
    for name, rect in document.artboards:
        region = rect.intersected(document.canvas_rect())
        if region.isEmpty():
            continue
        stem = "".join(
            char if char.isalnum() or char in "-_ " else "_" for char in name
        ).strip() or "artboard"
        candidate = stem
        number = 2
        while candidate.casefold() in used:
            candidate = f"{stem}-{number}"
            number += 1
        used.add(candidate.casefold())
        path = os.path.join(directory, f"{candidate}.png")
        image = flat.copy(region)

        def writer(temporary: str, source=image, destination=path) -> None:
            if not source.save(temporary, "PNG"):
                raise ValueError(f"Artboard export failed: {destination}")

        atomic_write(path, writer)
        written.append(path)
    return written


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
        result = adapter.denoise(image, strength)
        if result.isNull() or result.size() != image.size():
            raise ValueError("Backend returned an image of the wrong size")
        return result.convertToFormat(image.format())

    @staticmethod
    def generative_fill(adapter, image: QImage, mask: QImage, prompt: str,
                        expected: QSize) -> QImage:
        result = adapter.generative_fill(image, mask, prompt)
        if result.size() != expected:
            raise ValueError("Backend returned an image of the wrong size")
        return result.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

    @staticmethod
    def select_subject(adapter, image: QImage) -> QImage:
        result = adapter.select_subject(image)
        if result.isNull() or result.size() != image.size():
            raise ValueError("Backend returned a mask of the wrong size")
        return result.convertToFormat(QImage.Format.Format_Grayscale8)


def opaque_export_base(document: Document, fmt: str, transparent: QImage) -> QImage:
    return (document.flatten(QColor(255, 255, 255))
            if fmt in {"JPEG", "BMP"} else QImage(transparent))
