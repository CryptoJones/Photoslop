# SPDX-License-Identifier: Apache-2.0
"""Layer panel: stack list (top layer first), visibility checkboxes, rename,
opacity slider, and the stack operations."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from photoslop.commands import (
    InsertLayerCommand,
    MergeDownCommand,
    MoveLayerStackCommand,
    RemoveLayerCommand,
    SetLayerPropertyCommand,
)
from photoslop.document import Document
from photoslop.layer import BLEND_MODES, Layer
from photoslop.svgicons import svg_icon

_THUMB = 36


class LayerPanel(QWidget):
    appearanceRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.doc: Document | None = None
        self._updating = False
        self._thumb_cache: dict[int, tuple[int, QIcon]] = {}

        self.list = QListWidget()
        self.list.setAccessibleName("Layer stack")
        self.list.setAccessibleDescription(
            "Layers in top-to-bottom reading order. Space toggles visibility; "
            "F2 renames; arrow keys change the active layer.")
        self.list.setIconSize(QSize(_THUMB, _THUMB))
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemChanged.connect(self._on_item_changed)
        self.list.itemDoubleClicked.connect(self._on_double_click)

        self.blend = QComboBox()
        self.blend.setAccessibleName("Active layer blend mode")
        self.blend.addItems(list(BLEND_MODES))
        self.blend.activated.connect(self._on_blend)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setAccessibleName("Active layer opacity")
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        self.opacity.valueChanged.connect(self._on_opacity)
        self.opacity_label = QLabel("100%")

        buttons = QHBoxLayout()
        self._buttons: dict[str, QPushButton] = {}
        for key, icon_name, tip in (
            ("add", "plus", "New layer"),
            ("dup", "copy", "Duplicate layer"),
            ("del", "trash", "Delete layer"),
            ("up", "arrow-up", "Raise layer"),
            ("down", "arrow-down", "Lower layer"),
            ("merge", "arrow-down", "Merge down"),
        ):
            btn = QPushButton()
            btn.setIcon(svg_icon(icon_name))
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
            btn.setFixedWidth(30)
            self._buttons[key] = btn
            buttons.addWidget(btn)
        buttons.addStretch(1)

        self._buttons["add"].clicked.connect(self.add_layer)
        self._buttons["dup"].clicked.connect(self.duplicate_layer)
        self._buttons["del"].clicked.connect(self.delete_layer)
        self._buttons["up"].clicked.connect(lambda: self.shift_layer(+1))
        self._buttons["down"].clicked.connect(lambda: self.shift_layer(-1))
        self._buttons["merge"].clicked.connect(self.merge_down)

        blend_row = QHBoxLayout()
        blend_row.addWidget(QLabel("Blend"))
        blend_row.addWidget(self.blend, 1)

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Opacity"))
        opacity_row.addWidget(self.opacity, 1)
        opacity_row.addWidget(self.opacity_label)

        box = QVBoxLayout(self)
        box.setContentsMargins(4, 4, 4, 4)
        box.addLayout(blend_row)
        box.addLayout(opacity_row)
        box.addWidget(self.list, 1)
        box.addLayout(buttons)

    # -- wiring --

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            self.doc.structureChanged.disconnect(self.rebuild)
            self.doc.undo_stack.indexChanged.disconnect(self._refresh_thumbs)
        self.doc = doc
        if doc is not None:
            doc.structureChanged.connect(self.rebuild)
            doc.undo_stack.indexChanged.connect(self._refresh_thumbs)
        self.rebuild()

    def _row_to_index(self, row: int) -> int:
        if self.doc is None:
            raise RuntimeError("layer row requested without an active document")
        return len(self.doc.layers) - 1 - row

    def _thumb(self, layer: Layer) -> QIcon:
        key = self._thumb_key(layer)
        cached = self._thumb_cache.get(id(layer))
        if cached is not None and cached[0] == key:
            return cached[1]
        img = layer.image.scaled(
            _THUMB, _THUMB, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        pixmap = QPixmap.fromImage(img)
        if layer.effects:
            painter = QPainter(pixmap)
            painter.setPen(QColor(255, 255, 255))
            painter.setBrush(QColor(25, 35, 50, 220))
            badge = pixmap.rect().adjusted(pixmap.width() // 2, pixmap.height() // 2, 0, 0)
            painter.drawRoundedRect(badge, 3, 3)
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, "fx")
            painter.end()
        icon = QIcon(pixmap)
        self._thumb_cache[id(layer)] = (key, icon)
        return icon

    @staticmethod
    def _thumb_key(layer: Layer):
        from photoslop.appearance import stack_key

        return layer.image.cacheKey(), stack_key(layer.effects)

    def rebuild(self) -> None:
        self._updating = True
        self.list.clear()
        if self.doc is not None:
            live = {id(layer) for layer in self.doc.layers}
            self._thumb_cache = {
                key: value for key, value in self._thumb_cache.items() if key in live}
            total = len(self.doc.layers)
            for position, layer in enumerate(reversed(self.doc.layers), start=1):
                item = QListWidgetItem(self._thumb(layer), layer.name)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEditable
                )
                if layer.clipped:
                    font = item.font()
                    font.setItalic(True)  # clipped-to-below indicator
                    item.setFont(font)
                if layer.group:
                    item.setBackground(QColor(70, 105, 150, 60))
                    item.setToolTip(f"Group: {layer.group}")
                if layer.adjustment is not None:
                    item.setForeground(QColor(150, 200, 255))
                    item.setToolTip("Adjustment layer (non-destructive)")
                item.setCheckState(
                    Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
                )
                state = "visible" if layer.visible else "hidden"
                kind = ("adjustment" if layer.adjustment is not None else
                        "text" if layer.text_data else
                        "vector" if layer.vector_data is not None else "raster")
                item.setData(
                    Qt.ItemDataRole.AccessibleTextRole,
                    f"{layer.name}, {kind} layer, {state}, "
                    f"{round(layer.opacity * 100)} percent opacity, "
                    f"position {position} of {total}",
                )
                item.setData(
                    Qt.ItemDataRole.AccessibleDescriptionRole,
                    "Checked means visible. Press F2 to rename or Space to toggle visibility.",
                )
                self.list.addItem(item)
            if self.doc.active_index >= 0:
                self.list.setCurrentRow(self._row_to_index(self.doc.active_index))
            self._sync_active_controls()
        self._updating = False

    def _refresh_thumbs(self) -> None:
        if self.doc is None or self._updating:
            return
        self._updating = True
        for row in range(self.list.count()):
            layer = self.doc.layers[self._row_to_index(row)]
            cached = self._thumb_cache.get(id(layer))
            if cached is None or cached[0] != self._thumb_key(layer):
                self.list.item(row).setIcon(self._thumb(layer))
        self._updating = False

    # -- user edits --

    def _sync_active_controls(self) -> None:
        active = self.doc.active_layer if self.doc is not None else None
        if active is None:
            return
        self.opacity.blockSignals(True)
        self.opacity.setValue(round(active.opacity * 100))
        self.opacity.blockSignals(False)
        self.opacity_label.setText(f"{round(active.opacity * 100)}%")
        self.blend.blockSignals(True)
        self.blend.setCurrentText(active.blend_mode)
        self.blend.blockSignals(False)

    def _on_row(self, row: int) -> None:
        if self.doc is None or self._updating or row < 0:
            return
        self.doc.active_index = self._row_to_index(row)
        self._sync_active_controls()

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self.doc is None or self._updating:
            return
        index = self._row_to_index(self.list.row(item))
        layer = self.doc.layers[index]
        visible = item.checkState() == Qt.CheckState.Checked
        name = item.text().strip() or layer.name
        if visible != layer.visible:
            self.doc.undo_stack.push(
                SetLayerPropertyCommand(self.doc, layer, "visible", visible))
        if name != layer.name:
            self.doc.undo_stack.push(
                SetLayerPropertyCommand(self.doc, layer, "name", name))
        elif not item.text().strip():
            self.rebuild()

    def _on_double_click(self, item: QListWidgetItem) -> None:
        if self.doc is None:
            return
        layer = self.doc.layers[self._row_to_index(self.list.row(item))]
        if layer.effects:
            self.appearanceRequested.emit()

    def _on_blend(self) -> None:
        if self.doc is None or self._updating:
            return
        layer = self.doc.active_layer
        if layer is not None:
            value = self.blend.currentText()
            if value != layer.blend_mode:
                self.doc.undo_stack.push(
                    SetLayerPropertyCommand(self.doc, layer, "blend_mode", value))

    def _on_opacity(self, value: int) -> None:
        if self.doc is None or self._updating:
            return
        layer = self.doc.active_layer
        if layer is not None:
            self.opacity_label.setText(f"{value}%")
            opacity = value / 100.0
            if opacity != layer.opacity:
                self.doc.undo_stack.push(
                    SetLayerPropertyCommand(self.doc, layer, "opacity", opacity))

    # -- stack ops --

    def add_layer(self) -> None:
        doc = self.doc
        if doc is None:
            return
        layer = Layer.blank(f"Layer {len(doc.layers) + 1}", doc.size)
        doc.undo_stack.push(InsertLayerCommand(doc, doc.active_index + 1, layer))

    def duplicate_layer(self) -> None:
        doc = self.doc
        if doc is None or doc.active_layer is None:
            return
        clone = doc.active_layer.clone(doc.active_layer.name + " copy")
        doc.undo_stack.push(
            InsertLayerCommand(doc, doc.active_index + 1, clone, "Duplicate Layer")
        )

    def delete_layer(self) -> None:
        doc = self.doc
        if doc is None or len(doc.layers) <= 1 or doc.active_layer is None:
            return
        doc.undo_stack.push(RemoveLayerCommand(doc, doc.active_index))

    def shift_layer(self, direction: int) -> None:
        doc = self.doc
        if doc is None:
            return
        src = doc.active_index
        dst = src + direction
        if 0 <= dst < len(doc.layers):
            doc.undo_stack.push(MoveLayerStackCommand(doc, src, dst))

    def merge_down(self) -> None:
        doc = self.doc
        if doc is not None and doc.active_index > 0:
            doc.undo_stack.push(MergeDownCommand(doc, doc.active_index))
