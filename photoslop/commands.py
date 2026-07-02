# SPDX-License-Identifier: Apache-2.0
"""Undo commands. The design rule: a command may keep alive only the pixels
it actually changed (tiles or a region), never whole-canvas snapshots.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QUndoCommand

from photoslop.document import Document
from photoslop.layer import Layer, blank_image

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
        assert self.layer is not None
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
        assert self.upper is not None and self.old_lower is not None
        lower = doc.layers[self.index - 1]
        dirty = lower.bounds()
        lower.image, lower.offset, lower.opacity = self.old_lower
        doc.insert_layer(self.index, self.upper)
        doc.notify_pixels(dirty)


class ResizeImageCommand(QUndoCommand):
    """Rescale the canvas and every layer. Undo restores the original image
    objects; redo recomputes the scaled versions (CPU is cheaper than holding
    both resolutions in RAM)."""

    def __init__(self, doc: Document, new_size: QSize):
        super().__init__("Resize Image")
        self.doc = doc
        self.old_size = QSize(doc.size)
        self.new_size = QSize(new_size)
        self.old_layers = [
            (layer, QImage(layer.image), QPoint(layer.offset)) for layer in doc.layers
        ]

    def redo(self) -> None:
        doc = self.doc
        sx = self.new_size.width() / self.old_size.width()
        sy = self.new_size.height() / self.old_size.height()
        for layer, old_img, old_off in self.old_layers:
            w = max(1, round(old_img.width() * sx))
            h = max(1, round(old_img.height() * sy))
            layer.image = old_img.scaled(
                w, h,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            layer.offset = QPoint(round(old_off.x() * sx), round(old_off.y() * sy))
        doc.size = QSize(self.new_size)
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))

    def undo(self) -> None:
        doc = self.doc
        for layer, old_img, old_off in self.old_layers:
            layer.image = QImage(old_img)
            layer.offset = QPoint(old_off)
        doc.size = QSize(self.old_size)
        doc.notify_structure()
        doc.notify_pixels(QRect(QPoint(0, 0), doc.size))


class ResizeCanvasCommand(QUndoCommand):
    """Change canvas size and shift layers; no pixels are copied or dropped,
    which also makes crop instant and fully undoable."""

    def __init__(self, doc: Document, new_size: QSize, delta: QPoint, text: str = "Canvas Size"):
        super().__init__(text)
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
