# SPDX-License-Identifier: Apache-2.0
"""Contextual properties for the active layer or vector-backed object."""

from __future__ import annotations

from contextlib import suppress

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from photoslop.layer import BLEND_MODES


class PropertiesPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.doc = None
        self._updating = False
        self.kind = QLabel("No document")
        self.name = QLineEdit()
        self.name.setAccessibleName("Layer name")
        self.visible = QCheckBox("Visible")
        self.opacity = QSpinBox()
        self.opacity.setRange(0, 100)
        self.opacity.setSuffix(" %")
        self.opacity.setAccessibleName("Layer opacity")
        self.blend = QComboBox()
        self.blend.addItems(list(BLEND_MODES))
        self.blend.setAccessibleName("Layer blend mode")
        layout = QFormLayout(self)
        layout.addRow(self.kind)
        layout.addRow("Name", self.name)
        layout.addRow("", self.visible)
        layout.addRow("Opacity", self.opacity)
        layout.addRow("Blend", self.blend)
        self.name.editingFinished.connect(self.apply)
        self.visible.toggled.connect(self.apply)
        self.opacity.valueChanged.connect(self.apply)
        self.blend.currentTextChanged.connect(self.apply)
        self.refresh()

    def set_document(self, doc) -> None:
        if self.doc is not None:
            with suppress(RuntimeError):
                self.doc.structureChanged.disconnect(self.refresh)
        self.doc = doc
        if doc is not None:
            doc.structureChanged.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self._updating = True
        layer = self.doc.active_layer if self.doc is not None else None
        enabled = layer is not None
        for widget in (self.name, self.visible, self.opacity, self.blend):
            widget.setEnabled(enabled)
        if layer is None:
            self.kind.setText("No active layer")
            self.name.clear()
        else:
            vector_type = (layer.vector_data or {}).get("type")
            if layer.text_data:
                label = "Text object"
            elif vector_type:
                label = f"{vector_type.title()} object"
            else:
                label = "Raster layer"
            if layer.effects:
                label += f" · {len(layer.effects)} effect(s)"
            self.kind.setText(label)
            self.name.setText(layer.name)
            self.visible.setChecked(layer.visible)
            self.opacity.setValue(round(layer.opacity * 100))
            self.blend.setCurrentText(layer.blend_mode)
        self._updating = False

    def apply(self, *_args) -> None:
        if self._updating or self.doc is None or self.doc.active_layer is None:
            return
        layer = self.doc.active_layer
        layer.name = self.name.text().strip() or layer.name
        layer.visible = self.visible.isChecked()
        layer.opacity = self.opacity.value() / 100.0
        layer.blend_mode = self.blend.currentText()
        self.doc.notify_structure()
