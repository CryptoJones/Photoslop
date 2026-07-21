# SPDX-License-Identifier: Apache-2.0
"""The document model: canvas geometry, the layer stack, selection, guides.

Pixel-touching edits go through QUndoCommands in commands.py; the document
itself only holds state and emits change signals. There is deliberately no
cached flattened composite — views composite the visible region on demand.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QRect, QSize, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QUndoStack

from photoslop.layer import BLEND_MODES, FORMAT, Layer, blank_image

UNDO_LIMIT = 64


@dataclass(frozen=True)
class DocumentRevision:
    """Immutable generation token for background work."""

    document_id: str
    pixels: int
    structure: int
    selection: int


def clip_base_for(doc: Document, layer: Layer) -> Layer | None:
    """The layer a clipped layer confines to: nearest non-clipped layer
    below it (a run of clipped layers shares one base)."""
    index = doc.layers.index(layer)
    for i in range(index - 1, -1, -1):
        if not doc.layers[i].clipped:
            return doc.layers[i]
    return None


def render_region(doc: Document, region: QRect,
                  exclude: Layer | None = None) -> QImage:
    """Composite every visible layer's contribution to a canvas-space region
    into a region-sized image — the offscreen path used when adjustment
    layers exist (they post-process the accumulated composite below them)."""
    from photoslop.adjust import apply_luts

    out = blank_image(region.size())
    p = QPainter(out)
    p.translate(-region.topLeft())
    index = 0
    layers = doc.layers
    while index < len(layers):
        layer = layers[index]
        if not layer.visible or layer is exclude:
            index += 1
            continue
        if layer.adjustment is not None:
            p.end()
            apply_luts(out, layer.adjustment)
            p = QPainter(out)
            p.translate(-region.topLeft())
            index += 1
            continue
        props = doc.group_props.get(layer.group) if layer.group else None
        if props is not None:
            run = []
            j = index
            while j < len(layers) and layers[j].group == layer.group:
                if layers[j].visible and layers[j] is not exclude:
                    run.append(layers[j])
                j += 1
            group_buf = blank_image(region.size())
            gp = QPainter(group_buf)
            gp.translate(-region.topLeft())
            for member in run:
                gp.setOpacity(member.opacity)
                gp.setCompositionMode(BLEND_MODES[member.blend_mode])
                draw_layer(gp, doc, member, region)
            gp.end()
            p.setOpacity(props.get("opacity", 1.0))
            p.setCompositionMode(
                BLEND_MODES[props.get("blend_mode", "normal")])
            p.drawImage(region.topLeft(), group_buf)
            index = j
            continue
        p.setOpacity(layer.opacity)
        p.setCompositionMode(BLEND_MODES[layer.blend_mode])
        draw_layer(p, doc, layer, region)
        index += 1
    p.end()
    return out


def _effects_margin(effects: list) -> int:
    """How far (px) any of these effects can reach beyond the layer."""
    from photoslop.appearance import effect_margin

    return effect_margin(effects)


def _effect_images(layer: Layer) -> list:
    """Render and cache a layer-local normalized appearance stack."""
    from photoslop.appearance import render, stack_key

    mask_key = layer.mask.cacheKey() if layer.mask is not None else 0
    key = (layer.image.cacheKey(), mask_key, stack_key(layer.effects))
    if layer.fx_cache is not None and layer.fx_cache[0] == key:
        return layer.fx_cache[1]
    out = render(layer)
    layer.fx_cache = (key, out)
    return out


def _draw_effects(p: QPainter, appearance, region: QRect, under: bool,
                  origin: QPoint) -> None:
    from photoslop.layer import BLEND_MODES

    base_opacity = p.opacity()
    base_mode = p.compositionMode()
    for plane in appearance.planes:
        if plane.under != under:
            continue
        offset = origin + plane.offset
        area = region.intersected(QRect(offset, plane.image.size()))
        if not area.isEmpty():
            p.setOpacity(base_opacity * plane.opacity)
            p.setCompositionMode(BLEND_MODES[plane.blend_mode])
            p.drawImage(area.topLeft(), plane.image, area.translated(-offset))
    p.setOpacity(base_opacity)
    p.setCompositionMode(base_mode)


def draw_layer(p: QPainter, doc: Document, layer: Layer, region: QRect) -> None:
    """Draw one layer's contribution to a canvas-space region, honouring its
    mask, clipping, live effects, and fill opacity. Transient buffers never
    exceed the region (effect images are layer-sized + effect padding). The
    caller sets opacity and composition mode; the painter is in canvas
    coords."""
    if layer.effects or layer.fill_opacity != 1.0:
        base = p.opacity()
        appearance = _effect_images(layer)
        _draw_effects(p, appearance, region, under=True, origin=layer.offset)
        p.setOpacity(base * layer.fill_opacity)
        if appearance.fill_image is None:
            _draw_fill(p, doc, layer, region)
        else:
            fill_offset = layer.offset + appearance.fill_offset
            area = region.intersected(QRect(fill_offset, appearance.fill_image.size()))
            if not area.isEmpty():
                p.drawImage(area.topLeft(), appearance.fill_image,
                            area.translated(-fill_offset))
        p.setOpacity(base)
        _draw_effects(p, appearance, region, under=False, origin=layer.offset)
        return
    _draw_fill(p, doc, layer, region)


def _draw_fill(p: QPainter, doc: Document, layer: Layer, region: QRect) -> None:
    area = region.intersected(layer.bounds())
    if area.isEmpty():
        return
    local = area.translated(-layer.offset)
    base = clip_base_for(doc, layer) if layer.clipped else None
    if base is None:
        if layer.mask is None:
            if layer.vector_data is not None:
                from photoslop.vector import draw_native

                draw_native(p, layer.vector_data)
                return
            p.drawImage(area.topLeft(), layer.image, local)
        else:
            p.drawImage(area.topLeft(), layer.paint_image(local))
        return

    content = layer.paint_image(local)
    base_alpha = blank_image(area.size())
    base_area = area.intersected(base.bounds())
    if not base_area.isEmpty():
        bp = QPainter(base_alpha)
        bp.drawImage(base_area.topLeft() - area.topLeft(),
                     base.paint_image(base_area.translated(-base.offset)))
        bp.end()
    cp = QPainter(content)
    cp.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    cp.drawImage(0, 0, base_alpha)
    cp.end()
    p.drawImage(area.topLeft(), content)


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
        self.document_id = uuid.uuid4().hex
        self._pixel_revision = 0
        self._structure_revision = 0
        self._selection_revision = 0
        self._closed = False
        self.size = QSize(size)
        self.dpi = float(dpi)
        self.layers: list[Layer] = []  # index 0 = bottom
        self.active_index = -1
        self.selection: QPainterPath | None = None
        self.selection_feather = 0.0  # px; consumed by filters/fills
        self.group_props: dict[str, dict] = {}  # group -> {opacity, blend_mode}
        self.icc_space = None  # QColorSpace | None; None = sRGB assumed
        self.guides_h: list[float] = []  # y positions, canvas px
        self.guides_v: list[float] = []  # x positions, canvas px
        self.artboards: list[tuple[str, QRect]] = []  # named export regions
        self.vector_selection: list[str] = []  # stable schema-v1 object IDs
        self.vector_node_selection: dict[str, list[int]] = {}
        self.path: str | None = None
        self.undo_stack = QUndoStack()
        self.undo_stack.setUndoLimit(UNDO_LIMIT)

    # ----- layers ---------------------------------------------------------

    @property
    def active_layer(self) -> Layer | None:
        if 0 <= self.active_index < len(self.layers):
            return self.layers[self.active_index]
        return None

    def has_adjustments(self) -> bool:
        return any(layer.visible and layer.adjustment is not None
                   for layer in self.layers)

    def needs_offscreen(self) -> bool:
        """True when compositing needs the buffered path: adjustment layers
        or groups with non-default opacity/blend."""
        return self.has_adjustments() or bool(self.group_props)

    def canvas_rect(self) -> QRect:
        return QRect(QPoint(0, 0), self.size)

    def insert_layer(self, index: int, layer: Layer) -> None:
        self.layers.insert(index, layer)
        self.active_index = index
        self.notify_structure()
        self.notify_pixels(layer.bounds())

    def take_layer(self, index: int) -> Layer:
        layer = self.layers.pop(index)
        if self.active_index >= len(self.layers):
            self.active_index = len(self.layers) - 1
        self.notify_structure()
        self.notify_pixels(layer.bounds())
        return layer

    def move_layer(self, src: int, dst: int) -> None:
        layer = self.layers.pop(src)
        self.layers.insert(dst, layer)
        self.active_index = dst
        self.notify_structure()
        self.notify_pixels(layer.bounds())

    def notify_pixels(self, rect: QRect) -> None:
        # live effects (shadows, strokes) reach beyond layer bounds — pad the
        # dirty rect by the largest effect margin of any intersecting layer
        pad = 0
        for layer in self.layers:
            if layer.effects and layer.visible:
                margin = _effects_margin(layer.effects)
                if rect.adjusted(-margin, -margin, margin, margin).intersects(
                        layer.bounds()):
                    pad = max(pad, margin)
        if pad:
            rect = rect.adjusted(-pad, -pad, pad, pad)
        self._pixel_revision += 1
        self.pixelsChanged.emit(rect)

    def notify_structure(self) -> None:
        self._structure_revision += 1
        self.structureChanged.emit()

    def capture_revision(self) -> DocumentRevision:
        return DocumentRevision(
            self.document_id,
            self._pixel_revision,
            self._structure_revision,
            self._selection_revision,
        )

    def accepts_revision(
        self, revision: DocumentRevision, layer: Layer | None = None,
    ) -> bool:
        """Return whether a task may still commit to this document/layer."""
        if self._closed or revision != self.capture_revision():
            return False
        return layer is None or any(candidate is layer for candidate in self.layers)

    def close(self) -> None:
        """Permanently reject completion callbacks captured for this document."""
        self._closed = True

    # ----- selection ------------------------------------------------------

    def set_selection(self, path: QPainterPath | None) -> None:
        self.selection = path if path is not None and not path.isEmpty() else None
        self.selection_feather = 0.0  # feather belongs to one selection
        self._selection_revision += 1
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
        if self.needs_offscreen():
            return render_region(self, self.canvas_rect())
        p = QPainter(out)
        for layer in self.layers:
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.setCompositionMode(BLEND_MODES[layer.blend_mode])
                draw_layer(p, self, layer, self.canvas_rect())
        p.end()
        return out

    def sample_color(self, x: int, y: int) -> QColor | None:
        """Merged-composite color at one canvas point — composites exactly one
        pixel, so sampling is free no matter how big the document is."""
        if not self.canvas_rect().contains(x, y):
            return None
        out = blank_image(QSize(1, 1))
        point = QRect(x, y, 1, 1)
        if self.needs_offscreen():
            return render_region(self, point).pixelColor(0, 0)
        p = QPainter(out)
        p.translate(-x, -y)
        for layer in self.layers:
            if layer.visible:
                p.setOpacity(layer.opacity)
                p.setCompositionMode(BLEND_MODES[layer.blend_mode])
                draw_layer(p, self, layer, point)
        p.end()
        return out.pixelColor(0, 0)

    def memory_bytes(self) -> int:
        return sum(layer.memory_bytes() for layer in self.layers)

    def is_dirty(self) -> bool:
        return not self.undo_stack.isClean()

    @property
    def is_closed(self) -> bool:
        return self._closed

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
