# SPDX-License-Identifier: Apache-2.0
"""Layer panel: stack list (top layer first), visibility checkboxes, rename,
opacity slider, and the stack operations."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
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
)
from photoslop.document import Document
from photoslop.layer import Layer

_THUMB = 36


class LayerPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.doc: Document | None = None
        self._updating = False

        self.list = QListWidget()
        self.list.setIconSize(QSize(_THUMB, _THUMB))
        self.list.currentRowChanged.connect(self._on_row)
        self.list.itemChanged.connect(self._on_item_changed)

        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setValue(100)
        self.opacity.valueChanged.connect(self._on_opacity)
        self.opacity_label = QLabel("100%")

        buttons = QHBoxLayout()
        self._buttons: dict[str, QPushButton] = {}
        for key, text, tip in (
            ("add", "+", "New layer"),
            ("dup", "⧉", "Duplicate layer"),
            ("del", "−", "Delete layer"),
            ("up", "↑", "Raise layer"),
            ("down", "↓", "Lower layer"),
            ("merge", "⤵", "Merge down"),
        ):
            btn = QPushButton(text)
            btn.setToolTip(tip)
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

        opacity_row = QHBoxLayout()
        opacity_row.addWidget(QLabel("Opacity"))
        opacity_row.addWidget(self.opacity, 1)
        opacity_row.addWidget(self.opacity_label)

        box = QVBoxLayout(self)
        box.setContentsMargins(4, 4, 4, 4)
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
        assert self.doc is not None
        return len(self.doc.layers) - 1 - row

    def _thumb(self, layer: Layer) -> QIcon:
        img = layer.image.scaled(
            _THUMB, _THUMB, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        return QIcon(QPixmap.fromImage(img))

    def rebuild(self) -> None:
        self._updating = True
        self.list.clear()
        if self.doc is not None:
            for layer in reversed(self.doc.layers):
                item = QListWidgetItem(self._thumb(layer), layer.name)
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsEditable
                )
                item.setCheckState(
                    Qt.CheckState.Checked if layer.visible else Qt.CheckState.Unchecked
                )
                self.list.addItem(item)
            if self.doc.active_index >= 0:
                self.list.setCurrentRow(self._row_to_index(self.doc.active_index))
            active = self.doc.active_layer
            if active is not None:
                self.opacity.blockSignals(True)
                self.opacity.setValue(round(active.opacity * 100))
                self.opacity.blockSignals(False)
                self.opacity_label.setText(f"{round(active.opacity * 100)}%")
        self._updating = False

    def _refresh_thumbs(self) -> None:
        if self.doc is None or self._updating:
            return
        self._updating = True
        for row in range(self.list.count()):
            layer = self.doc.layers[self._row_to_index(row)]
            self.list.item(row).setIcon(self._thumb(layer))
        self._updating = False

    # -- user edits --

    def _on_row(self, row: int) -> None:
        if self.doc is None or self._updating or row < 0:
            return
        self.doc.active_index = self._row_to_index(row)
        active = self.doc.active_layer
        if active is not None:
            self.opacity.blockSignals(True)
            self.opacity.setValue(round(active.opacity * 100))
            self.opacity.blockSignals(False)
            self.opacity_label.setText(f"{round(active.opacity * 100)}%")

    def _on_item_changed(self, item: QListWidgetItem) -> None:
        if self.doc is None or self._updating:
            return
        index = self._row_to_index(self.list.row(item))
        layer = self.doc.layers[index]
        visible = item.checkState() == Qt.CheckState.Checked
        name = item.text().strip() or layer.name
        if visible != layer.visible:
            layer.visible = visible
            self.doc.notify_pixels(layer.bounds())
        if name != layer.name:
            layer.name = name

    def _on_opacity(self, value: int) -> None:
        if self.doc is None or self._updating:
            return
        layer = self.doc.active_layer
        if layer is not None:
            layer.opacity = value / 100.0
            self.opacity_label.setText(f"{value}%")
            self.doc.notify_pixels(layer.bounds())

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
