# SPDX-License-Identifier: Apache-2.0
"""A single raster layer: one pixel buffer, an offset, and blend attributes.

The pixel buffer is a premultiplied ARGB32 QImage. Layer objects are cheap to
clone because QImage is copy-on-write: clones share pixel memory until one
side is painted on.
"""

from __future__ import annotations

import uuid

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
ORA_OPS = {
    name: f"svg:{'src-over' if name == 'normal' else 'plus' if name == 'addition' else name}"
    for name in BLEND_MODES
}
ORA_OPS_REVERSE = {v: k for k, v in ORA_OPS.items()}


def blank_image(size: QSize) -> QImage:
    img = QImage(size, FORMAT)
    img.fill(Qt.GlobalColor.transparent)
    return img


def mask_to_alpha(mask: QImage) -> QImage:
    """Reinterpret a Grayscale8 mask's bytes as Alpha8 (convertToFormat would
    route through ARGB and produce opaque alpha everywhere)."""
    alpha = QImage(
        mask.constBits(),
        mask.width(),
        mask.height(),
        mask.bytesPerLine(),
        QImage.Format.Format_Alpha8,
    )
    return alpha.copy()  # detach from the mask's buffer


class Layer:
    __slots__ = (
        "adjustment",
        "blend_mode",
        "clipped",
        "effects",
        "fill_opacity",
        "fx_cache",
        "group",
        "image",
        "mask",
        "name",
        "offset",
        "opacity",
        "smart_filters",
        "source",
        "text_data",
        "id",
        "smart_filters_trusted",
        "vector_data",
        "visible",
    )

    def __init__(
        self,
        name: str,
        image: QImage,
        offset: QPoint | None = None,
        visible: bool = True,
        opacity: float = 1.0,
        blend_mode: str = "normal",
        layer_id: str | None = None,
    ) -> None:
        self.id = layer_id or uuid.uuid4().hex
        self.name = name
        self.image = image if image.format() == FORMAT else image.convertToFormat(FORMAT)
        self.offset = QPoint(offset) if offset is not None else QPoint(0, 0)
        self.visible = visible
        self.opacity = float(opacity)
        self.blend_mode = blend_mode if blend_mode in BLEND_MODES else "normal"
        self.mask: QImage | None = None  # Grayscale8, white = opaque
        self.clipped = False  # confined to the alpha of the layer below
        self.group: str | None = None  # group name; members move as a unit
        self.adjustment = None  # (3, 256) uint8 LUTs: applies to composite below
        self.source: QImage | None = None  # smart-object pristine snapshot
        self.smart_filters: list = []  # (kind, *params) applied to a smart object
        self.smart_filters_trusted = True  # imported recipes require explicit trust
        self.effects: list = []  # versioned live appearance-effect objects
        self.fill_opacity = 1.0  # scales the fill only, never the effects
        self.fx_cache = None  # (key, rendered effect images) — derived
        self.text_data: dict | None = None  # text/family/size/color for re-editing
        self.vector_data: dict | None = None  # shape/pen geometry for re-editing

    @classmethod
    def blank(cls, name: str, size: QSize, offset: QPoint | None = None) -> Layer:
        return cls(name, blank_image(size), offset)

    def clone(self, name: str | None = None, *, preserve_id: bool = False) -> Layer:
        # QImage(...) copy construction shares pixel data (copy-on-write).
        layer = Layer(
            name if name is not None else self.name,
            QImage(self.image),
            QPoint(self.offset),
            self.visible,
            self.opacity,
            self.blend_mode,
            self.id if preserve_id else None,
        )
        if self.mask is not None:
            layer.mask = QImage(self.mask)
        layer.clipped = self.clipped
        layer.group = self.group
        if self.adjustment is not None:
            layer.adjustment = self.adjustment.copy()
        if self.source is not None:
            layer.source = QImage(self.source)
        layer.smart_filters = [tuple(f) for f in self.smart_filters]
        layer.smart_filters_trusted = self.smart_filters_trusted
        from copy import deepcopy

        layer.effects = deepcopy(self.effects)
        layer.fill_opacity = self.fill_opacity
        if self.text_data is not None:
            layer.text_data = dict(self.text_data)
        if self.vector_data is not None:
            layer.vector_data = deepcopy(self.vector_data)
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
