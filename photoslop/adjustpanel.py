# SPDX-License-Identifier: Apache-2.0
"""The Adjust panel — Lightroom-style Basic sliders, tabbed with Layers.

Working model: moving any slider starts a preview session against pristine
copies of the target layers; the preview recomputes live (debounced) from
that pristine state, so sliders stay absolute, not compounding. The scope
checkbox switches targets between the active layer (default) and every
visible layer ("full image") — same semantics as the adjustment dialogs.
Apply commits the whole session as ONE undo step (a macro when several
layers changed); Reset discards it. If the undo stack moves mid-session
(external edit), the session is discarded and current pixels become the
new baseline.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from photoslop.adjust import AdjustSettings, apply_settings
from photoslop.commands import LayerRegionCommand
from photoslop.document import Document

# key, label, slider range, display divisor (exposure slider is in 1/100 stop)
_SLIDERS = (
    ("temperature", "Temp", 100, 1),
    ("tint", "Tint", 100, 1),
    ("exposure", "Exposure", 400, 100),
    ("contrast", "Contrast", 100, 1),
    ("highlights", "Highlights", 100, 1),
    ("shadows", "Shadows", 100, 1),
    ("whites", "Whites", 100, 1),
    ("blacks", "Blacks", 100, 1),
    ("vibrance", "Vibrance", 100, 1),
    ("saturation", "Saturation", 100, 1),
)


class AdjustPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.doc: Document | None = None
        self._pristines: dict = {}  # layer -> pristine QImage for the session
        self._layer = None  # active layer when the session started
        self._updating = False

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self._recompute)

        grid = QGridLayout()
        grid.setContentsMargins(4, 4, 4, 4)
        self._sliders: dict[str, QSlider] = {}
        self._values: dict[str, QLabel] = {}
        for row, (key, label, extent, _div) in enumerate(_SLIDERS):
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-extent, extent)
            slider.setValue(0)
            slider.valueChanged.connect(self._on_slider)
            value = QLabel("0")
            value.setMinimumWidth(36)
            value.setAlignment(Qt.AlignmentFlag.AlignRight)
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(value, row, 2)
            self._sliders[key] = slider
            self._values[key] = value

        self.scope_all = QCheckBox("Apply to all layers (full image)")
        self.scope_all.toggled.connect(self._scope_toggled)

        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.apply)
        self.reset_btn = QPushButton("Reset")
        self.reset_btn.setEnabled(False)
        self.reset_btn.clicked.connect(self.reset)
        buttons = QHBoxLayout()
        buttons.addWidget(self.apply_btn)
        buttons.addWidget(self.reset_btn)
        buttons.addStretch(1)

        box = QVBoxLayout(self)
        box.addLayout(grid)
        box.addWidget(self.scope_all)
        box.addLayout(buttons)
        box.addStretch(1)

    # ----- wiring ----------------------------------------------------------

    def set_document(self, doc: Document | None) -> None:
        if self.doc is not None:
            self.doc.undo_stack.indexChanged.disconnect(self._on_external_change)
            self.doc.structureChanged.disconnect(self._on_external_change)
        self._discard_session()
        self.doc = doc
        if doc is not None:
            doc.undo_stack.indexChanged.connect(self._on_external_change)
            doc.structureChanged.connect(self._on_external_change)

    def settings(self) -> AdjustSettings:
        values = {}
        for key, _label, _extent, div in _SLIDERS:
            values[key] = self._sliders[key].value() / div
        return AdjustSettings(**values)

    def _on_external_change(self) -> None:
        # An edit landed outside the preview session: current pixels become
        # the new baseline; slider positions no longer describe them.
        if self._pristines and not self._committing:
            self._discard_session()

    # ----- session ---------------------------------------------------------

    _committing = False

    def _targets(self) -> list:
        """Session layers under the current scope (mirrors the dialogs)."""
        if self.doc is None or self._layer is None:
            return []
        if self.scope_all.isChecked():
            return [layer for layer in self.doc.layers
                    if layer.visible and layer.adjustment is None
                    and not layer.image.isNull()]
        return [self._layer]

    def _pristine_for(self, layer) -> QImage:
        if layer not in self._pristines:
            self._pristines[layer] = QImage(layer.image)  # COW reference
        return self._pristines[layer]

    def _on_slider(self) -> None:
        if self._updating or self.doc is None:
            return
        for key, _label, _extent, div in _SLIDERS:
            value = self._sliders[key].value()
            self._values[key].setText(
                f"{value / div:+.2f}" if div != 1 else f"{value:+d}"
            )
        layer = self.doc.active_layer
        if layer is None:
            return
        if self._layer is None:
            self._layer = layer
            self._pristine_for(layer)
        self.apply_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        self._debounce.start()

    def _recompute(self) -> None:
        if self.doc is None or self._layer is None:
            return
        for layer in self._targets():
            img = QImage(self._pristine_for(layer))
            apply_settings(img, self.settings())  # first write detaches
            layer.image = img
            self.doc.notify_pixels(layer.bounds())

    def _scope_toggled(self, _on: bool) -> None:
        # restore everything, then re-preview at the new scope with the
        # same slider values
        if self.doc is None or not self._pristines:
            return
        self._debounce.stop()
        self._restore_all()
        self._recompute()

    def _restore_all(self) -> None:
        for layer, pristine in self._pristines.items():
            layer.image = QImage(pristine)
            self.doc.notify_pixels(layer.bounds())

    def apply(self) -> None:
        if self.doc is None or self._layer is None:
            return
        self._debounce.stop()
        self._recompute()
        changed = [(layer, pristine)
                   for layer, pristine in self._pristines.items()
                   if layer.image != pristine]
        if changed and not self.settings().is_identity():
            self._committing = True
            try:
                self.doc.undo_stack.beginMacro("Adjust")
                for layer, pristine in changed:
                    self.doc.undo_stack.push(LayerRegionCommand(
                        self.doc, layer, layer.image.rect(),
                        QImage(pristine), QImage(layer.image),
                        "Adjust", applied=True,
                    ))
                self.doc.undo_stack.endMacro()
            finally:
                self._committing = False
        self._discard_session()

    def reset(self) -> None:
        if self.doc is not None and self._pristines:
            self._debounce.stop()
            self._restore_all()
        self._discard_session()

    def _discard_session(self) -> None:
        self._pristines = {}
        self._layer = None
        self._updating = True
        for key, _label, _extent, _div in _SLIDERS:
            self._sliders[key].setValue(0)
            self._values[key].setText("0")
        self._updating = False
        self.apply_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
