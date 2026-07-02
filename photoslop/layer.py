# SPDX-License-Identifier: Apache-2.0
"""A single raster layer: one pixel buffer, an offset, and blend attributes.

The pixel buffer is a premultiplied ARGB32 QImage. Layer objects are cheap to
clone because QImage is copy-on-write: clones share pixel memory until one
side is painted on.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage, Qt

FORMAT = QImage.Format.Format_ARGB32_Premultiplied


def blank_image(size: QSize) -> QImage:
    img = QImage(size, FORMAT)
    img.fill(Qt.GlobalColor.transparent)
    return img


class Layer:
    __slots__ = ("image", "name", "offset", "opacity", "visible")

    def __init__(
        self,
        name: str,
        image: QImage,
        offset: QPoint | None = None,
        visible: bool = True,
        opacity: float = 1.0,
    ) -> None:
        self.name = name
        self.image = image if image.format() == FORMAT else image.convertToFormat(FORMAT)
        self.offset = QPoint(offset) if offset is not None else QPoint(0, 0)
        self.visible = visible
        self.opacity = float(opacity)

    @classmethod
    def blank(cls, name: str, size: QSize, offset: QPoint | None = None) -> Layer:
        return cls(name, blank_image(size), offset)

    def clone(self, name: str | None = None) -> Layer:
        # QImage(...) copy construction shares pixel data (copy-on-write).
        return Layer(
            name if name is not None else self.name,
            QImage(self.image),
            QPoint(self.offset),
            self.visible,
            self.opacity,
        )

    def bounds(self) -> QRect:
        """Layer extent in canvas coordinates."""
        return QRect(self.offset, self.image.size())

    def memory_bytes(self) -> int:
        return int(self.image.sizeInBytes())
