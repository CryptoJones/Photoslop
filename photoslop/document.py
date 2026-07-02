# SPDX-License-Identifier: Apache-2.0
"""The document model: canvas geometry, the layer stack, selection, guides.

Pixel-touching edits go through QUndoCommands in commands.py; the document
itself only holds state and emits change signals. There is deliberately no
cached flattened composite — views composite the visible region on demand.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QUndoStack

from photoslop.layer import BLEND_MODES, FORMAT, Layer, blank_image

UNDO_LIMIT = 64


class Document(QObject):
    pixelsChanged = Signal(QRect)  # canvas-space dirty rect
    structureChanged = Signal()  # layer list / geometry / properties
    selectionChanged = Signal()
    guidesChanged = Signal()

    _untitled_count = 0

    def __init__(self, size: QSize, dpi: float = 72.0, name: str | None = None) -> None:
        super().__init__()
        if name is None:
            Document._untitled_count += 1
            name = f"Untitled-{Document._untitled_count}"
        self.name = name
        self.size = QSize(size)
        self.dpi = float(dpi)
        self.layers: list[Layer] = []  # index 0 = bottom
        self.active_index = -1
        self.selection: QPainterPath | None = None
        self.guides_h: list[float] = []  # y positions, canvas px
        self.guides_v: list[float] = []  # x positions, canvas px
        self.path: str | None = None
        self.undo_stack = QUndoStack()
        self.undo_stack.setUndoLimit(UNDO_LIMIT)

    # ----- layers ---------------------------------------------------------

    @property
    def active_layer(self) -> Layer | None:
        if 0 <= self.active_index < len(self.layers):
            return self.layers[self.active_index]
        return None

    def canvas_rect(self) -> QRect:
        return QRect(QPoint(0, 0), self.size)

    def insert_layer(self, index: int, layer: Layer) -> None:
        self.layers.insert(index, layer)
        self.active_index = index
        self.structureChanged.emit()
        self.pixelsChanged.emit(layer.bounds())

    def take_layer(self, index: int) -> Layer:
        layer = self.layers.pop(index)
        if self.active_index >= len(self.layers):
            self.active_index = len(self.layers) - 1
        self.structureChanged.emit()
        self.pixelsChanged.emit(layer.bounds())
        return layer

    def move_layer(self, src: int, dst: int) -> None:
        layer = self.layers.pop(src)
        self.layers.insert(dst, layer)
        self.active_index = dst
        self.structureChanged.emit()
        self.pixelsChanged.emit(layer.bounds())

    def notify_pixels(self, rect: QRect) -> None:
        self.pixelsChanged.emit(rect)

    def notify_structure(self) -> None:
        self.structureChanged.emit()

    # ----- selection ------------------------------------------------------

    def set_selection(self, path: QPainterPath | None) -> None:
        self.selection = path if path is not None and not path.isEmpty() else None
        self.selectionChanged.emit()

    def selection_bounds(self) -> QRect | None:
        if self.selection is None:
            return None
        rect = self.selection.boundingRect().toAlignedRect().intersected(self.canvas_rect())
        return rect if not rect.isEmpty() else None

    # ----- guides ---------------------------------------------------------

    def add_guide(self, orientation: str, pos: float) -> None:
        (self.guides_h if orientation == "h" else self.guides_v).append(float(pos))
        self.guidesChanged.emit()

    def clear_guides(self) -> None:
        if self.guides_h or self.guides_v:
            self.guides_h.clear()
            self.guides_v.clear()
            self.guidesChanged.emit()

    # ----- compositing / stats --------------------------------------------

    def flatten(self, background: QColor | None = None) -> QImage:
        """Composite all visible layers into a new canvas-sized image."""
        out = blank_image(self.size)
        if background is not None:
            out.fill(background)
        p = QPainter(out)
        for layer in self.layers:
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.setCompositionMode(BLEND_MODES[layer.blend_mode])
                p.drawImage(layer.offset, layer.image)
        p.end()
        return out

    def sample_color(self, x: int, y: int) -> QColor | None:
        """Merged-composite color at one canvas point — composites exactly one
        pixel, so sampling is free no matter how big the document is."""
        if not self.canvas_rect().contains(x, y):
            return None
        out = blank_image(QSize(1, 1))
        p = QPainter(out)
        p.translate(-x, -y)
        for layer in self.layers:
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.setCompositionMode(BLEND_MODES[layer.blend_mode])
                p.drawImage(layer.offset, layer.image)
        p.end()
        return out.pixelColor(0, 0)

    def memory_bytes(self) -> int:
        return sum(layer.memory_bytes() for layer in self.layers)

    def is_dirty(self) -> bool:
        return not self.undo_stack.isClean()

    # ----- constructors ----------------------------------------------------

    @classmethod
    def new(
        cls,
        size: QSize,
        dpi: float = 72.0,
        name: str | None = None,
        background: QColor | None = None,
    ) -> Document:
        doc = cls(size, dpi, name)
        base = Layer.blank("Background", size)
        if background is not None and background.alpha() > 0:
            base.image.fill(background)
        doc.layers.append(base)
        doc.active_index = 0
        return doc

    @classmethod
    def from_image(cls, image: QImage, name: str, dpi: float = 72.0) -> Document:
        img = image.convertToFormat(FORMAT)
        doc = cls(img.size(), dpi, name)
        doc.layers.append(Layer("Background", img))
        doc.active_index = 0
        return doc
