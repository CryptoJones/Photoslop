# SPDX-License-Identifier: Apache-2.0
"""Undo commands. The design rule: a command may keep alive only the pixels
it actually changed (tiles or a region), never whole-canvas snapshots.
"""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QTransform, QUndoCommand

from photoslop.document import Document
from photoslop.layer import BLEND_MODES, Layer, blank_image, mask_to_alpha

TILE = 128

_SOURCE = QPainter.CompositionMode.CompositionMode_Source


def _blit(dst: QImage, pos: QPoint, src: QImage) -> None:
    p = QPainter(dst)
    p.setCompositionMode(_SOURCE)
    p.drawImage(pos, src)
    p.end()


class TileRecorder:
    """Snapshots 128px tiles of a layer lazily, just before they are painted.

    Tools call will_change(rect) before each stamp; only tiles not yet seen
    are copied, so heavily overlapping stamps cost one snapshot per tile.
    """

    def __init__(self, doc: Document, layer: Layer) -> None:
        self.doc = doc
        self.layer = layer
        self.before: dict[tuple[int, int], tuple[QRect, QImage]] = {}

    def will_change(self, rect: QRect) -> None:
        img = self.layer.image
        rect = rect.intersected(QRect(0, 0, img.width(), img.height()))
        if rect.isEmpty():
            return
        for ty in range(rect.top() // TILE, rect.bottom() // TILE + 1):
            for tx in range(rect.left() // TILE, rect.right() // TILE + 1):
                key = (tx, ty)
                if key not in self.before:
                    trect = QRect(tx * TILE, ty * TILE, TILE, TILE).intersected(img.rect())
                    self.before[key] = (trect, img.copy(trect))

    def finish(self, text: str) -> TileCommand | None:
        img = self.layer.image
        tiles = []
        for trect, before in self.before.values():
            after = img.copy(trect)
            if after != before:  # untouched tiles are dropped entirely
                tiles.append((trect, before, after))
        if not tiles:
            return None
        return TileCommand(self.doc, self.layer, tiles, text)

    def restore(self) -> None:
        """Restore every captured tile when an in-progress gesture is cancelled."""
        dirty = QRect()
        for tile_rect, before in self.before.values():
            _blit(self.layer.image, tile_rect.topLeft(), before)
            dirty = dirty.united(tile_rect)
        if not dirty.isEmpty():
            self.doc.notify_pixels(dirty.translated(self.layer.offset))


class TileCommand(QUndoCommand):
    """Before/after pixel tiles for one paint gesture. Pixels were already
    painted live, so the first redo() is a no-op."""

    def __init__(self, doc, layer, tiles, text):
        super().__init__(text)
        self.doc = doc
        self.layer = layer
        self.tiles = tiles
        self._applied = True

    def _dirty(self) -> QRect:
        rect = QRect()
        for trect, _b, _a in self.tiles:
            rect = rect.united(trect)
        return rect.translated(self.layer.offset)

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        for trect, _before, after in self.tiles:
            _blit(self.layer.image, trect.topLeft(), after)
        self.doc.notify_pixels(self._dirty())

    def undo(self) -> None:
        for trect, before, _after in self.tiles:
            _blit(self.layer.image, trect.topLeft(), before)
        self.doc.notify_pixels(self._dirty())


class LayerRegionCommand(QUndoCommand):
    """Before/after snapshot of one rectangular region of a layer (bucket
    fill, delete-selection). `applied=True` means the edit is already live."""

    def __init__(self, doc, layer, rect, before, after, text, applied=True):
        super().__init__(text)
        self.doc = doc
        self.layer = layer
        self.rect = QRect(rect)  # layer coords
        self.before = before
        self.after = after
        self._applied = applied

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        _blit(self.layer.image, self.rect.topLeft(), self.after)
        self.doc.notify_pixels(self.rect.translated(self.layer.offset))

    def undo(self) -> None:
        _blit(self.layer.image, self.rect.topLeft(), self.before)
        self.doc.notify_pixels(self.rect.translated(self.layer.offset))


class InsertLayerCommand(QUndoCommand):
    def __init__(self, doc: Document, index: int, layer: Layer, text: str = "Add Layer"):
        super().__init__(text)
        self.doc, self.index, self.layer = doc, index, layer

    def redo(self) -> None:
        self.doc.insert_layer(self.index, self.layer)

    def undo(self) -> None:
        self.doc.take_layer(self.index)


class RemoveLayerCommand(QUndoCommand):
    def __init__(self, doc: Document, index: int, text: str = "Delete Layer"):
        super().__init__(text)
        self.doc, self.index = doc, index
        self.layer: Layer | None = None

    def redo(self) -> None:
        self.layer = self.doc.take_layer(self.index)

    def undo(self) -> None:
        if self.layer is None:
            raise RuntimeError("cannot undo layer removal before it was applied")
        self.doc.insert_layer(self.index, self.layer)


class MoveLayerStackCommand(QUndoCommand):
    def __init__(self, doc: Document, src: int, dst: int):
        super().__init__("Reorder Layer")
        self.doc, self.src, self.dst = doc, src, dst

    def redo(self) -> None:
        self.doc.move_layer(self.src, self.dst)

    def undo(self) -> None:
        self.doc.move_layer(self.dst, self.src)


class SetLayerOffsetCommand(QUndoCommand):
    """Move-tool drags and arrow nudges; consecutive moves of the same layer
    merge into one undo step."""

    def __init__(self, doc: Document, layer: Layer, old: QPoint, new: QPoint):
        super().__init__("Move Layer")
        self.doc, self.layer = doc, layer
        self.old, self.new = QPoint(old), QPoint(new)
        self._applied = True

    def id(self) -> int:
        return 0x4D4F5645  # "MOVE"

    def mergeWith(self, other) -> bool:
        if isinstance(other, SetLayerOffsetCommand) and other.layer is self.layer:
            self.new = QPoint(other.new)
            return True
        return False

    def _apply(self, pos: QPoint) -> None:
        dirty = self.layer.bounds()
        self.layer.offset = QPoint(pos)
        self.doc.notify_pixels(dirty.united(self.layer.bounds()))

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        self._apply(self.new)

    def undo(self) -> None:
        self._apply(self.old)


class SetLayerPropertyCommand(QUndoCommand):
    """Undo one layer property edit; consecutive opacity edits merge."""

    _TEXT = {
        "name": "Rename Layer",
        "visible": "Layer Visibility",
        "opacity": "Layer Opacity",
        "blend_mode": "Layer Blend Mode",
    }
    _VISUAL = frozenset({"visible", "opacity", "blend_mode"})

    def __init__(self, doc: Document, layer: Layer, prop: str, value) -> None:
        if prop not in self._TEXT:
            raise ValueError(f"Unsupported layer property: {prop}")
        super().__init__(self._TEXT[prop])
        self.doc = doc
        self.layer = layer
        self.prop = prop
        self.old = getattr(layer, prop)
        self.new = value

    def _apply(self, value) -> None:
        if not any(candidate is self.layer for candidate in self.doc.layers):
            return
        setattr(self.layer, self.prop, value)
        if self.prop in self._VISUAL:
            self.doc.notify_pixels(self.layer.bounds())
        self.doc.notify_structure()

    def redo(self) -> None:
        self._apply(self.new)

    def undo(self) -> None:
        self._apply(self.old)

    def id(self) -> int:
        return 0x4F504143 if self.prop == "opacity" else -1  # "OPAC"

    def mergeWith(self, other) -> bool:
        if (
            not isinstance(other, SetLayerPropertyCommand)
            or other.doc is not self.doc
            or other.layer is not self.layer
            or other.prop != self.prop
        ):
            return False
        self.new = other.new
        return True


class MergeDownCommand(QUndoCommand):
    def __init__(self, doc: Document, index: int):
        super().__init__("Merge Down")
        self.doc, self.index = doc, index
        self.upper: Layer | None = None
        self.old_lower: tuple[QImage, QPoint, float] | None = None

    def redo(self) -> None:
        doc = self.doc
        upper = doc.layers[self.index]
        lower = doc.layers[self.index - 1]
        self.old_lower = (QImage(lower.image), QPoint(lower.offset), lower.opacity)

        union = upper.bounds().united(lower.bounds())
        merged = blank_image(union.size())
        p = QPainter(merged)
        p.setOpacity(lower.opacity)
        p.drawImage(lower.offset - union.topLeft(), lower.image)
        if upper.visible:
            p.setOpacity(upper.opacity)
            p.drawImage(upper.offset - union.topLeft(), upper.image)
        p.end()

        lower.image = merged
        lower.offset = union.topLeft()
        lower.opacity = 1.0
        self.upper = doc.take_layer(self.index)
        doc.active_index = self.index - 1
        doc.notify_structure()
        doc.notify_pixels(union)

    def undo(self) -> None:
        doc = self.doc
        if self.upper is None or self.old_lower is None:
            raise RuntimeError("cannot undo merge before it was applied")
        lower = doc.layers[self.index - 1]
        dirty = lower.bounds()
        lower.image, lower.offset, lower.opacity = self.old_lower
        doc.insert_layer(self.index, self.upper)
        doc.notify_pixels(dirty)


class SetLayerStyleCommand(QUndoCommand):
    """Swap a layer's live effects list and/or fill opacity."""

    def __init__(
        self,
        doc,
        layer,
        effects: list,
        fill_opacity: float,
        text: str = "Layer Style",
        merge_key=None,
    ) -> None:
        super().__init__(text)
        self._doc = doc
        self._layer = layer
        from photoslop.appearance import normalize_effects

        self._old = (deepcopy(normalize_effects(layer.effects)), layer.fill_opacity)
        self._new = (deepcopy(normalize_effects(effects)), float(fill_opacity))
        self._merge_key = merge_key

    def _apply(self, state) -> None:
        effects, fill = state
        self._layer.effects = deepcopy(effects)
        self._layer.fill_opacity = fill
        self._layer.fx_cache = None
        self._doc.notify_pixels(self._doc.canvas_rect())

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)

    def id(self) -> int:
        return 0xA550 if self._merge_key is not None else -1

    def mergeWith(self, other) -> bool:
        if (
            not isinstance(other, SetLayerStyleCommand)
            or self._doc is not other._doc
            or self._layer is not other._layer
            or self._merge_key != other._merge_key
        ):
            return False
        self._new = deepcopy(other._new)
        return True


class EditVectorLayerCommand(QUndoCommand):
    """Replace a vector layer's rendered content and geometry — one step."""

    def __init__(
        self, doc: Document, layer: Layer, rendered: Layer, text: str = "Edit Shape"
    ) -> None:
        super().__init__(text)
        self._doc = doc
        self._layer = layer
        self._old = (QImage(layer.image), QPoint(layer.offset), deepcopy(layer.vector_data or {}))
        self._new = (
            QImage(rendered.image),
            QPoint(rendered.offset),
            deepcopy(rendered.vector_data or {}),
        )

    def _apply(self, state) -> None:
        image, offset, data = state
        dirty = self._layer.bounds()
        self._layer.image = QImage(image)
        self._layer.offset = QPoint(offset)
        self._layer.vector_data = dict(data) if data else None
        self._layer.fx_cache = None
        self._doc.notify_pixels(dirty.united(self._layer.bounds()))

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)


class EditTextLayerCommand(QUndoCommand):
    """Replace a text layer's rendered content and remembered text data."""

    def __init__(
        self, doc: Document, layer: Layer, rendered: Layer, text: str = "Edit Text"
    ) -> None:
        super().__init__(text)
        self._doc = doc
        self._layer = layer
        self._old = (
            QImage(layer.image),
            QPoint(layer.offset),
            layer.name,
            dict(layer.text_data or {}),
            deepcopy(layer.effects),
            layer.fill_opacity,
        )
        self._new = (
            QImage(rendered.image),
            QPoint(rendered.offset),
            rendered.name,
            dict(rendered.text_data or {}),
            deepcopy(rendered.effects),
            rendered.fill_opacity,
        )

    def _apply(self, state) -> None:
        image, offset, name, data, effects, fill_opacity = state
        dirty = self._layer.bounds()
        self._layer.image = QImage(image)
        self._layer.offset = QPoint(offset)
        self._layer.name = name
        self._layer.text_data = dict(data)
        self._layer.effects = deepcopy(effects)
        self._layer.fill_opacity = fill_opacity
        self._layer.fx_cache = None
        self._doc.notify_pixels(dirty.united(self._layer.bounds()))

    def redo(self) -> None:
        self._apply(self._new)

    def undo(self) -> None:
        self._apply(self._old)


class SetLayerMaskCommand(QUndoCommand):
    """Add, replace, or delete a layer mask (new_mask=None deletes)."""

    def __init__(
        self, doc: Document, layer: Layer, new_mask: QImage | None, text: str = "Layer Mask"
    ):
        super().__init__(text)
        self.doc, self.layer = doc, layer
        self.old_mask = QImage(layer.mask) if layer.mask is not None else None
        self.new_mask = new_mask

    def _apply(self, mask: QImage | None) -> None:
        self.layer.mask = QImage(mask) if mask is not None else None
        self.doc.notify_structure()
        self.doc.notify_pixels(self.layer.bounds())

    def redo(self) -> None:
        self._apply(self.new_mask)

    def undo(self) -> None:
        self._apply(self.old_mask)


class SetLayerGroupCommand(QUndoCommand):
    def __init__(self, doc: Document, layer: Layer, group: str | None):
        super().__init__("Group Layer" if group else "Ungroup Layer")
        self.doc, self.layer = doc, layer
        self.old_group, self.new_group = layer.group, group

    def _apply(self, group: str | None) -> None:
        self.layer.group = group
        self.doc.notify_structure()

    def redo(self) -> None:
        self._apply(self.new_group)

    def undo(self) -> None:
        self._apply(self.old_group)


class MoveGroupCommand(QUndoCommand):
    """Shift every member of a group by one delta; merges like layer moves."""

    def __init__(self, doc: Document, layers: list[Layer], delta: QPoint):
        super().__init__("Move Group")
        self.doc = doc
        self.layers = list(layers)
        self.delta = QPoint(delta)
        self._applied = True

    def id(self) -> int:
        return 0x47525550  # "GRUP"

    def mergeWith(self, other) -> bool:
        if not isinstance(other, MoveGroupCommand) or other.layers != self.layers:
            return False
        self.delta += other.delta
        return True

    def _shift(self, delta: QPoint) -> None:
        dirty = QRect()
        for layer in self.layers:
            dirty = dirty.united(layer.bounds())
            layer.offset += delta
            dirty = dirty.united(layer.bounds())
        self.doc.notify_pixels(dirty)

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        self._shift(self.delta)

    def undo(self) -> None:
        self._shift(-self.delta)


class SetGroupPropsCommand(QUndoCommand):
    """Set or clear a group's compositing properties (opacity/blend)."""

    def __init__(self, doc: Document, group: str, props: dict | None):
        super().__init__("Group Properties")
        self.doc, self.group = doc, group
        self.old = doc.group_props.get(group)
        self.new = props

    def _apply(self, props: dict | None) -> None:
        if props is None:
            self.doc.group_props.pop(self.group, None)
        else:
            self.doc.group_props[self.group] = dict(props)
        self.doc.notify_structure()
        self.doc.notify_pixels(QRect(QPoint(0, 0), self.doc.size))

    def redo(self) -> None:
        self._apply(self.new)

    def undo(self) -> None:
        self._apply(self.old)


class SetLayerClippedCommand(QUndoCommand):
    def __init__(self, doc: Document, layer: Layer, clipped: bool):
        super().__init__("Clip to Layer Below" if clipped else "Release Clip")
        self.doc, self.layer, self.clipped = doc, layer, clipped

    def _apply(self, value: bool) -> None:
        self.layer.clipped = value
        self.doc.notify_structure()
        self.doc.notify_pixels(self.layer.bounds())

    def redo(self) -> None:
        self._apply(self.clipped)

    def undo(self) -> None:
        self._apply(not self.clipped)


class ApplyLayerMaskCommand(QUndoCommand):
    """Bake the mask into the layer's alpha and drop the mask."""

    def __init__(self, doc: Document, layer: Layer):
        super().__init__("Apply Layer Mask")
        self.doc, self.layer = doc, layer
        self.old_image = QImage(layer.image)
        self.old_mask = QImage(layer.mask)

    def redo(self) -> None:
        layer = self.layer
        baked = QImage(self.old_image)
        alpha = mask_to_alpha(self.old_mask)
        p = QPainter(baked)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        p.drawImage(0, 0, alpha)
        p.end()
        layer.image = baked
        layer.mask = None
        self.doc.notify_structure()
        self.doc.notify_pixels(layer.bounds())

    def undo(self) -> None:
        self.layer.image = QImage(self.old_image)
        self.layer.mask = QImage(self.old_mask)
        self.doc.notify_structure()
        self.doc.notify_pixels(self.layer.bounds())


class ArbitraryRotateCommand(QUndoCommand):
    """Rotate the whole image by any angle: canvas grows to the rotated
    bounding box, every layer resamples once (smooth) about the canvas
    centre. Undo restores the stored pre-rotation refs exactly — no second
    resample. Guides and selection are cleared (axis-aligned notions)."""

    def __init__(self, doc: Document, angle_deg: float):
        super().__init__(f"Rotate {angle_deg:g}\u00b0")
        self.doc = doc
        self.angle = float(angle_deg)
        self.old_size = QSize(doc.size)
        self.old_guides = (list(doc.guides_h), list(doc.guides_v))
        self.old_layers = [
            (layer, QImage(layer.image), QPoint(layer.offset)) for layer in doc.layers
        ]
        self.new_state: tuple | None = None

    def redo(self) -> None:
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QTransform

        doc = self.doc
        if self.new_state is None:
            t = QTransform().rotate(self.angle)
            w, h = self.old_size.width(), self.old_size.height()
            bounds = t.mapRect(QRectF(0, 0, w, h))
            new_size = QSize(round(bounds.width()), round(bounds.height()))
            old_c = QPointF(w / 2.0, h / 2.0)
            new_c = QPointF(new_size.width() / 2.0, new_size.height() / 2.0)
            entries = []
            for layer, old_img, old_offset in self.old_layers:
                new_img = old_img.transformed(t, Qt.TransformationMode.SmoothTransformation)
                centre = QPointF(
                    old_offset.x() + old_img.width() / 2.0, old_offset.y() + old_img.height() / 2.0
                )
                rotated = t.map(centre - old_c) + new_c
                new_offset = QPoint(
                    round(rotated.x() - new_img.width() / 2.0),
                    round(rotated.y() - new_img.height() / 2.0),
                )
                entries.append((layer, new_img, new_offset))
            self.new_state = (new_size, entries)
        new_size, entries = self.new_state
        doc.size = QSize(new_size)
        for layer, img, offset in entries:
            layer.image = QImage(img)
            layer.offset = QPoint(offset)
        doc.guides_h.clear()
        doc.guides_v.clear()
        doc.guidesChanged.emit()
        doc.set_selection(None)
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))

    def undo(self) -> None:
        doc = self.doc
        doc.size = QSize(self.old_size)
        for layer, img, offset in self.old_layers:
            layer.image = QImage(img)
            layer.offset = QPoint(offset)
        doc.guides_h[:] = self.old_guides[0]
        doc.guides_v[:] = self.old_guides[1]
        doc.guidesChanged.emit()
        doc.set_selection(None)
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))


class MergeVisibleCommand(QUndoCommand):
    """Composite every visible layer into one (at the lowest visible slot),
    leaving hidden layers untouched. Undo restores the exact stack."""

    def __init__(self, doc: Document):
        super().__init__("Merge Visible")
        self.doc = doc
        self.removed: list[tuple[int, Layer]] = []
        self.merged: Layer | None = None
        self.insert_at = 0
        self.old_active = doc.active_index

    def redo(self) -> None:
        doc = self.doc
        if self.merged is None:
            self.removed = [(i, layer) for i, layer in enumerate(doc.layers) if layer.visible]
            union = QRect()
            for _, layer in self.removed:
                union = union.united(layer.bounds())
            img = blank_image(union.size())
            p = QPainter(img)
            for _, layer in self.removed:
                p.setOpacity(layer.opacity)
                p.setCompositionMode(BLEND_MODES[layer.blend_mode])
                p.drawImage(layer.offset - union.topLeft(), layer.image)
            p.end()
            self.merged = Layer("Merged", img, union.topLeft())
            self.insert_at = self.removed[0][0]
        for i, _ in reversed(self.removed):
            doc.layers.pop(i)
        doc.layers.insert(self.insert_at, self.merged)
        doc.active_index = self.insert_at
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))

    def undo(self) -> None:
        doc = self.doc
        doc.layers.pop(self.insert_at)
        for i, layer in self.removed:
            doc.layers.insert(i, layer)
        doc.active_index = self.old_active
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))


class ResizeImageCommand(QUndoCommand):
    """Rescale the canvas and every layer. Undo restores the original image
    objects; redo recomputes the scaled versions (CPU is cheaper than holding
    both resolutions in RAM)."""

    def __init__(self, doc: Document, new_size: QSize, *, allow_large: bool = False):
        super().__init__("Resize Image")
        from photoslop.resources import validate_dimensions

        validate_dimensions(
            new_size.width(),
            new_size.height(),
            operation="resize image",
            buffers=2,
            allow_large=allow_large,
        )
        self.doc = doc
        self.old_size = QSize(doc.size)
        self.new_size = QSize(new_size)
        self.old_layers = [
            (
                layer,
                QImage(layer.image),
                QPoint(layer.offset),
                deepcopy(layer.vector_data) if layer.vector_data else None,
            )
            for layer in doc.layers
        ]

    def redo(self) -> None:
        from photoslop import vector

        doc = self.doc
        sx = self.new_size.width() / self.old_size.width()
        sy = self.new_size.height() / self.old_size.height()
        canvas = QRect(QPoint(0, 0), QSize(self.new_size))
        for layer, old_img, old_off, old_vec in self.old_layers:
            if old_vec is not None and vector.rerender_into(
                layer, vector.scale_vector(old_vec, sx, sy), canvas
            ):
                continue  # crisp re-render from parameters, not resampling
            w = max(1, round(old_img.width() * sx))
            h = max(1, round(old_img.height() * sy))
            layer.image = old_img.scaled(
                w,
                h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            layer.offset = QPoint(round(old_off.x() * sx), round(old_off.y() * sy))
        doc.size = QSize(self.new_size)
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))

    def undo(self) -> None:
        doc = self.doc
        for layer, old_img, old_off, old_vec in self.old_layers:
            layer.image = QImage(old_img)
            layer.offset = QPoint(old_off)
            layer.vector_data = dict(old_vec) if old_vec else None
        doc.size = QSize(self.old_size)
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))


def _rotate_doc(doc: Document, deg: int) -> None:
    """Rotate the whole document (layers, offsets, canvas, guides) by a
    multiple of 90° clockwise. Exact and lossless — undo just rotates back,
    so rotation costs no undo memory at all."""
    deg %= 360
    if deg == 0:
        return
    from photoslop import vector

    old_w, old_h = doc.size.width(), doc.size.height()
    transform = QTransform().rotate(deg)
    for layer in doc.layers:
        if layer.vector_data is not None:
            layer.vector_data = vector.rotate_vector(layer.vector_data, deg, old_w, old_h)
        lw, lh = layer.image.width(), layer.image.height()
        x0, y0 = layer.offset.x(), layer.offset.y()
        layer.image = layer.image.transformed(transform)
        if deg == 90:
            layer.offset = QPoint(old_h - (y0 + lh), x0)
        elif deg == 180:
            layer.offset = QPoint(old_w - (x0 + lw), old_h - (y0 + lh))
        else:  # 270 (== 90 CCW)
            layer.offset = QPoint(y0, old_w - (x0 + lw))
    if deg in (90, 270):
        doc.size = QSize(old_h, old_w)
    gh, gv = doc.guides_h[:], doc.guides_v[:]
    if deg == 90:
        doc.guides_v = [old_h - g for g in gh]
        doc.guides_h = gv
    elif deg == 180:
        doc.guides_h = [old_h - g for g in gh]
        doc.guides_v = [old_w - g for g in gv]
    else:
        doc.guides_h = [old_w - g for g in gv]
        doc.guides_v = gh
    doc.set_selection(None)
    doc.notify_structure()
    doc.guidesChanged.emit()
    doc.notify_pixels(QRect(QPoint(0, 0), doc.size))


def _flip_doc(doc: Document, horizontal: bool) -> None:
    from photoslop import vector

    w, h = doc.size.width(), doc.size.height()
    axis = Qt.Orientation.Horizontal if horizontal else Qt.Orientation.Vertical
    for layer in doc.layers:
        if layer.vector_data is not None:
            layer.vector_data = vector.flip_vector(layer.vector_data, horizontal, w, h)
        layer.image = layer.image.flipped(axis)
        if horizontal:
            layer.offset = QPoint(w - (layer.offset.x() + layer.image.width()), layer.offset.y())
        else:
            layer.offset = QPoint(layer.offset.x(), h - (layer.offset.y() + layer.image.height()))
    if horizontal:
        doc.guides_v = [w - g for g in doc.guides_v]
    else:
        doc.guides_h = [h - g for g in doc.guides_h]
    doc.set_selection(None)
    doc.notify_structure()
    doc.guidesChanged.emit()
    doc.notify_pixels(QRect(QPoint(0, 0), doc.size))


class RotateImageCommand(QUndoCommand):
    def __init__(self, doc: Document, degrees: int):
        super().__init__(f"Rotate Image {degrees}°")
        self.doc = doc
        self.degrees = degrees % 360

    def redo(self) -> None:
        _rotate_doc(self.doc, self.degrees)

    def undo(self) -> None:
        _rotate_doc(self.doc, 360 - self.degrees)


class FlipImageCommand(QUndoCommand):
    def __init__(self, doc: Document, horizontal: bool):
        super().__init__("Flip Image " + ("Horizontal" if horizontal else "Vertical"))
        self.doc = doc
        self.horizontal = horizontal

    def redo(self) -> None:
        _flip_doc(self.doc, self.horizontal)

    undo = redo  # flipping is an involution


class RotateLayerCommand(QUndoCommand):
    """Rotate the active layer about its own centre."""

    def __init__(self, doc: Document, layer: Layer, degrees: int):
        super().__init__(f"Rotate Layer {degrees}°")
        self.doc, self.layer = doc, layer
        self.degrees = degrees % 360
        self.old_offset = QPoint(layer.offset)
        self.old_vector = deepcopy(layer.vector_data) if layer.vector_data else None

    def _apply(self, deg: int) -> None:
        layer = self.layer
        # layer-local rotation invalidates doc-space geometry: drop to raster
        layer.vector_data = (
            None if deg == self.degrees else (dict(self.old_vector) if self.old_vector else None)
        )
        dirty = layer.bounds()
        cx = layer.offset.x() + layer.image.width() / 2.0
        cy = layer.offset.y() + layer.image.height() / 2.0
        layer.image = layer.image.transformed(QTransform().rotate(deg))
        layer.offset = QPoint(
            round(cx - layer.image.width() / 2.0), round(cy - layer.image.height() / 2.0)
        )
        self.doc.notify_pixels(dirty.united(layer.bounds()))

    def redo(self) -> None:
        self._apply(self.degrees)

    def undo(self) -> None:
        self._apply(360 - self.degrees)
        self.layer.offset = QPoint(self.old_offset)  # exact, no rounding drift
        self.doc.notify_pixels(self.layer.bounds())


class FlipLayerCommand(QUndoCommand):
    def __init__(self, doc: Document, layer: Layer, horizontal: bool):
        super().__init__("Flip Layer " + ("Horizontal" if horizontal else "Vertical"))
        self.doc, self.layer = doc, layer
        self.horizontal = horizontal

    def redo(self) -> None:
        from photoslop import vector

        layer = self.layer
        axis = Qt.Orientation.Horizontal if self.horizontal else Qt.Orientation.Vertical
        layer.image = layer.image.flipped(axis)
        if layer.vector_data is not None:  # self-inverse, like the flip
            layer.vector_data = vector.flip_vector_local(layer.vector_data, self.horizontal)
        self.doc.notify_pixels(layer.bounds())

    undo = redo


class ResizeCanvasCommand(QUndoCommand):
    """Change canvas size and shift layers; no pixels are copied or dropped,
    which also makes crop instant and fully undoable."""

    def __init__(
        self,
        doc: Document,
        new_size: QSize,
        delta: QPoint,
        text: str = "Canvas Size",
        *,
        allow_large: bool = False,
    ):
        super().__init__(text)
        from photoslop.resources import validate_dimensions

        validate_dimensions(
            new_size.width(),
            new_size.height(),
            operation=text.lower(),
            buffers=2,
            allow_large=allow_large,
        )
        self.doc = doc
        self.old_size = QSize(doc.size)
        self.new_size = QSize(new_size)
        self.delta = QPoint(delta)

    def _apply(self, size: QSize, delta: QPoint) -> None:
        doc = self.doc
        doc.size = QSize(size)
        for layer in doc.layers:
            layer.offset += delta
        doc.set_selection(None)
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))

    def redo(self) -> None:
        self._apply(self.new_size, self.delta)

    def undo(self) -> None:
        self._apply(self.old_size, -self.delta)
