# SPDX-License-Identifier: Apache-2.0
"""Export As — format, quality, and scale controls with a live preview and
the real encoded file size (computed in-memory, debounced)."""

from __future__ import annotations

from PySide6.QtCore import QBuffer, QIODevice, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSlider,
    QSpinBox,
)

from photoslop import io_formats
from photoslop.document import Document

_FORMATS = ("PNG", "JPEG", "WebP", "BMP")
_OPAQUE = {"JPEG", "BMP"}  # no alpha channel: flatten over white
_LOSSY = {"JPEG", "WebP", "AVIF", "JPEG XL"}
# extra formats appear only when the photoslop[formats] codecs are installed
_EXTRA = {"AVIF": ".avif", "JPEG XL": ".jxl"}

_PREVIEW = 220


class ExportDialog(QDialog):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export As")
        self._doc = doc
        self._flat = doc.flatten()  # transparent-backed master, flattened once
        self._flat_white = None  # lazily built for opaque formats

        self.format_box = QComboBox()
        self.format_box.addItems(list(_FORMATS))
        for name, ext in _EXTRA.items():
            if io_formats.available("x" + ext):
                self.format_box.addItem(name)
        self.format_box.currentTextChanged.connect(self._changed)

        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(1, 100)
        self.quality.setValue(90)
        self.quality.valueChanged.connect(self._changed)
        self.quality_label = QLabel("90")

        self.scale = QSpinBox()
        self.scale.setRange(1, 400)
        self.scale.setValue(100)
        self.scale.setSuffix(" %")
        self.scale.valueChanged.connect(self._changed)

        self.dims_label = QLabel("")
        self.size_label = QLabel("")
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(_PREVIEW + 8, _PREVIEW + 8)

        form = QFormLayout(self)
        form.addRow(self.preview)
        form.addRow("Format", self.format_box)
        form.addRow("Quality", self.quality)
        form.addRow("", self.quality_label)
        form.addRow("Scale", self.scale)
        form.addRow("Dimensions", self.dims_label)
        form.addRow("File size", self.size_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._update_size)
        self._changed()

    # ----- values -----------------------------------------------------------

    def chosen_format(self) -> str:
        return self.format_box.currentText()

    def chosen_quality(self) -> int:
        return self.quality.value() if self.chosen_format() in _LOSSY else -1

    def export_size(self) -> QSize:
        factor = self.scale.value() / 100.0
        return QSize(max(1, round(self._flat.width() * factor)),
                     max(1, round(self._flat.height() * factor)))

    def export_image(self) -> QImage:
        fmt = self.chosen_format()
        base = self._flat
        if fmt in _OPAQUE:
            if self._flat_white is None:
                self._flat_white = self._doc.flatten(QColor(255, 255, 255))
            base = self._flat_white
        size = self.export_size()
        if size == base.size():
            return base
        return base.scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)

    def suggested_suffix(self) -> str:
        return {"PNG": ".png", "JPEG": ".jpg", "WebP": ".webp", "BMP": ".bmp",
                "AVIF": ".avif", "JPEG XL": ".jxl"}[self.chosen_format()]

    def write_to(self, path: str, image: QImage | None = None) -> bool:
        """Encode the chosen export to `path`, routing extra formats through
        the io_formats codecs (Qt can't write AVIF/JXL itself)."""
        img = image if image is not None else self.export_image()
        fmt = self.chosen_format()
        if fmt in _EXTRA:
            return io_formats.save_extra(img, path, max(1, self.chosen_quality()))
        return img.save(path, fmt, self.chosen_quality())

    # ----- live feedback -----------------------------------------------------

    def _changed(self, *_args) -> None:
        fmt = self.chosen_format()
        lossy = fmt in _LOSSY
        self.quality.setEnabled(lossy)
        self.quality_label.setText(str(self.quality.value()) if lossy else "lossless")
        size = self.export_size()
        self.dims_label.setText(f"{size.width()} × {size.height()} px")

        pm = QPixmap.fromImage(self.export_image().scaled(
            _PREVIEW, _PREVIEW, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        self.preview.setPixmap(pm)

        self.size_label.setText("…")
        self._debounce.start()

    def _update_size(self) -> None:
        fmt = self.chosen_format()
        if fmt in _EXTRA:
            data = io_formats.encode_extra(
                self.export_image(), _EXTRA[fmt], max(1, self.chosen_quality()))
            n = len(data) if data else 0
        else:
            buf = QBuffer()
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            self.export_image().save(buf, fmt, self.chosen_quality())
            n = buf.size()
            buf.close()
        self.size_label.setText(
            f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1048576:.2f} MB")
