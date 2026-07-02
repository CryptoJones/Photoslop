# SPDX-License-Identifier: Apache-2.0
"""The Adjust panel — Lightroom-style Basic sliders, tabbed with Layers.

Working model: moving any slider starts a preview session against a pristine
copy of the active layer; the preview recomputes live (debounced) from that
pristine state, so sliders stay absolute, not compounding. Apply commits the
whole session as ONE undo step; Reset discards it. If the undo stack moves
mid-session (external edit), the session is discarded and current pixels
become the new baseline.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
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
        self._pristine: QImage | None = None
        self._layer = None
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
        if self._pristine is not None and not self._committing:
            self._discard_session()

    # ----- session ---------------------------------------------------------

    _committing = False

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
        if self._pristine is None:
            self._pristine = QImage(layer.image)  # copy-on-write reference
            self._layer = layer
        self.apply_btn.setEnabled(True)
        self.reset_btn.setEnabled(True)
        self._debounce.start()

    def _recompute(self) -> None:
        if self._pristine is None or self.doc is None or self._layer is None:
            return
        img = QImage(self._pristine)
        apply_settings(img, self.settings())  # first write detaches the copy
        self._layer.image = img
        self.doc.notify_pixels(self._layer.bounds())

    def apply(self) -> None:
        if self._pristine is None or self.doc is None or self._layer is None:
            return
        self._debounce.stop()
        self._recompute()
        if not self.settings().is_identity():
            self._committing = True
            try:
                self.doc.undo_stack.push(LayerRegionCommand(
                    self.doc, self._layer, self._layer.image.rect(),
                    QImage(self._pristine), QImage(self._layer.image),
                    "Adjust", applied=True,
                ))
            finally:
                self._committing = False
        self._discard_session()

    def reset(self) -> None:
        if self._pristine is not None and self._layer is not None and self.doc is not None:
            self._debounce.stop()
            self._layer.image = QImage(self._pristine)
            self.doc.notify_pixels(self._layer.bounds())
        self._discard_session()

    def _discard_session(self) -> None:
        self._pristine = None
        self._layer = None
        self._updating = True
        for key, _label, _extent, _div in _SLIDERS:
            self._sliders[key].setValue(0)
            self._values[key].setText("0")
        self._updating = False
        self.apply_btn.setEnabled(False)
        self.reset_btn.setEnabled(False)
