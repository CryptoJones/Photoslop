# SPDX-License-Identifier: Apache-2.0
"""File → Open with a live preview pane: thumbnail + dimensions/format/size,
decoded scaled-down (QImageReader.setScaledSize) so browsing a folder of huge
images stays fast and memory-frugal. .ora previews come free from the zip's
embedded thumbnail — no layer decoding."""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import QFileDialog, QGridLayout, QLabel, QVBoxLayout, QWidget

OPEN_FILTER = (
    "Images (*.ora *.png *.jpg *.jpeg *.bmp *.webp *.gif *.tif *.tiff "
    "*.avif *.jxl "
    "*.arw *.cr2 *.cr3 *.dng *.nef *.nrw *.orf *.pef *.raf *.rw2 *.srw);;"
    "OpenRaster (*.ora);;All files (*)"
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
            with zipfile.ZipFile(path) as zf:
                names = set(zf.namelist())
                src = ("Thumbnails/thumbnail.png"
                       if "Thumbnails/thumbnail.png" in names else "mergedimage.png")
                img = QImage.fromData(zf.read(src))
                root = ET.fromstring(zf.read("stack.xml"))
                w, h = root.get("w", "?"), root.get("h", "?")
                layers = len(root.findall(".//layer"))
            if img.isNull():
                return None, f"OpenRaster · {human}"
            return img, f"{w}×{h} · {layers} layers · OpenRaster · {human}"
        except Exception:
            return None, f"Unreadable .ora · {human}"

    from photoslop import io_formats

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

    def __init__(self, parent=None) -> None:
        super().__init__(parent, "Open images")
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setFileMode(QFileDialog.FileMode.ExistingFiles)
        self.setNameFilter(OPEN_FILTER)

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

    def _update_preview(self, path: str) -> None:
        img, info = preview_info(path)
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
    def get_paths(parent=None) -> list[str]:
        dialog = OpenImageDialog(parent)
        if dialog.exec():
            return list(dialog.selectedFiles())
        return []
