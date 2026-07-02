# SPDX-License-Identifier: Apache-2.0
"""A single raster layer: one pixel buffer, an offset, and blend attributes.

The pixel buffer is a premultiplied ARGB32 QImage. Layer objects are cheap to
clone because QImage is copy-on-write: clones share pixel memory until one
side is painted on.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage, QPainter, Qt

FORMAT = QImage.Format.Format_ARGB32_Premultiplied

_CM = QPainter.CompositionMode
BLEND_MODES: dict[str, QPainter.CompositionMode] = {
    "normal": _CM.CompositionMode_SourceOver,
    "multiply": _CM.CompositionMode_Multiply,
    "screen": _CM.CompositionMode_Screen,
    "overlay": _CM.CompositionMode_Overlay,
    "darken": _CM.CompositionMode_Darken,
    "lighten": _CM.CompositionMode_Lighten,
    "color-dodge": _CM.CompositionMode_ColorDodge,
    "color-burn": _CM.CompositionMode_ColorBurn,
    "hard-light": _CM.CompositionMode_HardLight,
    "soft-light": _CM.CompositionMode_SoftLight,
    "difference": _CM.CompositionMode_Difference,
    "exclusion": _CM.CompositionMode_Exclusion,
    "addition": _CM.CompositionMode_Plus,
}

# OpenRaster composite-op names (GIMP/Krita-interoperable)
ORA_OPS = {name: f"svg:{'src-over' if name == 'normal' else 'plus' if name == 'addition' else name}"
           for name in BLEND_MODES}
ORA_OPS_REVERSE = {v: k for k, v in ORA_OPS.items()}


def blank_image(size: QSize) -> QImage:
    img = QImage(size, FORMAT)
    img.fill(Qt.GlobalColor.transparent)
    return img


def mask_to_alpha(mask: QImage) -> QImage:
    """Reinterpret a Grayscale8 mask's bytes as Alpha8 (convertToFormat would
    route through ARGB and produce opaque alpha everywhere)."""
    alpha = QImage(mask.constBits(), mask.width(), mask.height(),
                   mask.bytesPerLine(), QImage.Format.Format_Alpha8)
    return alpha.copy()  # detach from the mask's buffer


class Layer:
    __slots__ = ("blend_mode", "image", "mask", "name", "offset", "opacity",
                 "visible")

    def __init__(
        self,
        name: str,
        image: QImage,
        offset: QPoint | None = None,
        visible: bool = True,
        opacity: float = 1.0,
        blend_mode: str = "normal",
    ) -> None:
        self.name = name
        self.image = image if image.format() == FORMAT else image.convertToFormat(FORMAT)
        self.offset = QPoint(offset) if offset is not None else QPoint(0, 0)
        self.visible = visible
        self.opacity = float(opacity)
        self.blend_mode = blend_mode if blend_mode in BLEND_MODES else "normal"
        self.mask: QImage | None = None  # Grayscale8, white = opaque

    @classmethod
    def blank(cls, name: str, size: QSize, offset: QPoint | None = None) -> Layer:
        return cls(name, blank_image(size), offset)

    def clone(self, name: str | None = None) -> Layer:
        # QImage(...) copy construction shares pixel data (copy-on-write).
        layer = Layer(
            name if name is not None else self.name,
            QImage(self.image),
            QPoint(self.offset),
            self.visible,
            self.opacity,
            self.blend_mode,
        )
        if self.mask is not None:
            layer.mask = QImage(self.mask)
        return layer

    def paint_image(self, local_region: QRect) -> QImage:
        """The drawable content for a layer-local region: the image with the
        mask applied (transient, region-sized). Masked compositing goes
        through here so the transient buffer never exceeds the region."""
        if self.mask is None:
            return self.image.copy(local_region)
        out = self.image.copy(local_region)
        alpha = mask_to_alpha(self.mask.copy(local_region))
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.drawImage(0, 0, alpha)
        p.end()
        return out

    def bounds(self) -> QRect:
        """Layer extent in canvas coordinates."""
        return QRect(self.offset, self.image.size())

    def memory_bytes(self) -> int:
        return int(self.image.sizeInBytes())
