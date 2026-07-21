# SPDX-License-Identifier: Apache-2.0
"""File → Open with a live preview pane: thumbnail + dimensions/format/size,
decoded scaled-down (QImageReader.setScaledSize) so browsing a folder of huge
images stays fast and memory-frugal. .ora previews come free from the zip's
embedded thumbnail — no layer decoding."""

from __future__ import annotations

import os
import zipfile

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QLabel,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from photoslop import io_formats
from photoslop.resources import (
    DESKTOP_BUDGET,
    parse_xml_limited,
    read_archive_member,
    validate_archive_members,
    validate_dimensions,
)
from photoslop.tasks import TaskService

OPEN_FILTER = (
    "Images (*.ora *.svg *.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff "
    "*.avif *.jxl "
    "*.arw *.cr2 *.cr3 *.dng *.nef *.nrw *.orf *.pef *.raf *.rw2 *.srw);;"
    "OpenRaster (*.ora);;Scalable Vector Graphics (*.svg);;All files (*)"
)

_PREVIEW_DIM = 256


def _human_size(n: int) -> str:
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


def preview_info(path: str, max_dim: int = _PREVIEW_DIM) -> tuple[QImage | None, str]:
    """(thumbnail, caption) for a file, without a full-size decode."""
    try:
        human = _human_size(os.path.getsize(path))
    except OSError:
        return None, "No preview"

    if path.lower().endswith(".ora"):
        try:
            if os.path.getsize(path) > DESKTOP_BUDGET.max_file_bytes:
                raise ValueError("archive too large")
            with zipfile.ZipFile(path) as zf:
                members = validate_archive_members(
                    zf.infolist(), operation="OpenRaster preview")
                src = ("Thumbnails/thumbnail.png"
                       if "Thumbnails/thumbnail.png" in members else "mergedimage.png")
                if src not in members or "stack.xml" not in members:
                    raise ValueError("missing preview members")
                img = QImage.fromData(read_archive_member(
                    zf, members[src], operation="OpenRaster preview image"))
                root = parse_xml_limited(read_archive_member(
                    zf, members["stack.xml"],
                    operation="OpenRaster preview stack"),
                    operation="OpenRaster preview")
                w, h = root.get("w", "?"), root.get("h", "?")
                layers = len(root.findall(".//layer"))
                validate_dimensions(int(w), int(h),
                                    operation="OpenRaster preview",
                                    allow_large=True)
                if layers > DESKTOP_BUDGET.max_layers:
                    raise ValueError("too many layers")
            if img.isNull():
                return None, f"OpenRaster · {human}"
            return img, f"{w}×{h} · {layers} layers · OpenRaster · {human}"
        except Exception:
            return None, f"Unreadable .ora · {human}"

    if io_formats.is_extra_path(path):
        img = io_formats.load_extra(path)
        if img is None or img.isNull():
            why = "codec missing" if not io_formats.available(path) else "undecodable"
            return None, f"No preview ({why}) · {human}"
        w, h = img.width(), img.height()
        if max(w, h) > max_dim:
            img = img.scaled(max_dim, max_dim, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        fmt = path.rsplit(".", 1)[-1].upper()
        return img, f"{w}×{h} · {fmt} · {human}"

    reader = QImageReader(path)
    reader.setAutoTransform(True)
    fmt = bytes(reader.format()).decode() or "?"
    size = reader.size()
    if size.isValid():
        try:
            validate_dimensions(size.width(), size.height(),
                                operation="image preview", allow_large=True)
        except ValueError:
            return None, f"Preview exceeds safety limits · {human}"
    if size.isValid() and max(size.width(), size.height()) > max_dim:
        reader.setScaledSize(size.scaled(max_dim, max_dim, Qt.AspectRatioMode.KeepAspectRatio))
    img = reader.read()
    if img.isNull():
        return None, f"No preview · {human}"
    if not size.isValid():
        size = img.size()
    return img, f"{size.width()}×{size.height()} · {fmt.upper()} · {human}"


class OpenImageDialog(QFileDialog):
    """Non-native Open dialog with a preview pane on the right."""

    def __init__(self, parent=None, directory: str | None = None) -> None:
        super().__init__(parent, "Open images")
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setFileMode(QFileDialog.FileMode.ExistingFiles)
        self.setNameFilter(OPEN_FILTER)
        if directory:
            self.setDirectory(directory)
        self._show_all_columns()

        self._image_label = QLabel("Select an image")
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setMinimumSize(_PREVIEW_DIM + 16, _PREVIEW_DIM + 16)
        self._info_label = QLabel("")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setWordWrap(True)

        panel = QWidget()
        box = QVBoxLayout(panel)
        box.setContentsMargins(8, 0, 0, 0)
        box.addWidget(self._image_label, 1)
        box.addWidget(self._info_label)

        grid = self.layout()
        if isinstance(grid, QGridLayout):
            grid.addWidget(panel, 1, grid.columnCount(), grid.rowCount() - 1, 1)
        self.currentChanged.connect(self._update_preview)
        self._preview_tasks = TaskService(max_workers=1, memory_budget=128 * 1024 * 1024,
                                          parent=self)
        self._preview_generation = 0

        # Open filling the parent's central "workable image area" rather than
        # floating as a smaller inset box (issue #144). Applied on first show so
        # the parent has a settled, on-screen geometry to map from.
        self._fit_rect = self._canvas_target_rect(parent)

    def _canvas_target_rect(self, parent) -> QRect | None:
        """Global-screen rect of the parent window's central canvas widget, or
        None when there's no shown main window to fit to."""
        get_central = getattr(parent, "centralWidget", None)
        central = get_central() if callable(get_central) else None
        if central is None or not central.isVisible() or central.width() <= 0:
            return None
        rect = central.rect()
        return QRect(central.mapToGlobal(rect.topLeft()), rect.size())

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        if self._fit_rect is not None:
            self.setGeometry(self._fit_rect)
            self._fit_rect = None  # fit once; let the user resize freely after

    def _show_all_columns(self) -> None:
        """Detail view with every column sized to its contents, so Name / Size /
        Kind / Date Modified are never truncated on first open."""
        self.setViewMode(QFileDialog.ViewMode.Detail)
        tree = self.findChild(QTreeView, "treeView")
        if tree is None:
            return
        header = tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)

    def _update_preview(self, path: str) -> None:
        self._preview_generation += 1
        generation = self._preview_generation
        self._preview_tasks.cancel_all()
        self._image_label.setText("Loading preview…")
        self._image_label.setPixmap(QPixmap())
        self._info_label.setText("")
        handle = self._preview_tasks.submit(
            "preview.decode", "Decode preview",
            lambda context: self._decode_preview(context, path),
            32 * 1024 * 1024)
        handle.succeeded.connect(
            lambda result, g=generation: self._install_preview(g, *result))

    @staticmethod
    def _decode_preview(context, path: str):
        context.check_cancelled()
        result = preview_info(path)
        context.check_cancelled()
        return result

    def _install_preview(self, generation: int, img, info: str) -> None:
        if generation != self._preview_generation:
            return
        if img is None:
            self._image_label.setText("No preview")
            self._image_label.setPixmap(QPixmap())
        else:
            pm = QPixmap.fromImage(img).scaled(
                _PREVIEW_DIM, _PREVIEW_DIM,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._image_label.setPixmap(pm)
        self._info_label.setText(info)

    @staticmethod
    def get_paths(parent=None, directory: str | None = None) -> list[str]:
        dialog = OpenImageDialog(parent, directory)
        if dialog.exec():
            return list(dialog.selectedFiles())
        return []
