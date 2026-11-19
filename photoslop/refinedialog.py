# SPDX-License-Identifier: Apache-2.0
"""Select and Mask / Refine Selection dialog: Guided Filter edge matting,
adaptive smart radius, global refinements (smooth, feather, contrast, shift edge),
and color decontamination with live preview (#417)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from photoslop import npimage
from photoslop.commands import LayerRegionCommand
from photoslop.document import Document


class RefineSelectionDialog(QDialog):
    """Full Select and Mask modal workspace dialog (#417)."""

    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select and Mask")
        self._doc = doc
        self._original = doc.selection  # QPainterPath (immutable by copy)
        self._original_feather = doc.selection_feather
        self._layer = doc.active_layer
        self._pristine = QImage(self._layer.image) if self._layer else None
        self._decontaminated_image: QImage | None = None
        self._base_mask = npimage.selection_mask(self._original, doc.size, QPoint(0, 0))

        main_layout = QVBoxLayout(self)

        # ----- 1. Edge Detection Group -----
        edge_group = QGroupBox("Edge Detection")
        edge_form = QFormLayout(edge_group)

        # Radius (0..100 px)
        self.radius_slider = QSlider(Qt.Orientation.Horizontal)
        self.radius_slider.setRange(0, 100)
        self.radius_slider.setValue(0)
        self.radius = QSpinBox()
        self.radius.setRange(0, 100)
        self.radius.setValue(0)
        self.radius.setSuffix(" px")
        self.radius_slider.valueChanged.connect(self.radius.setValue)
        self.radius.valueChanged.connect(self.radius_slider.setValue)
        self.radius_slider.valueChanged.connect(self._changed)

        r_row = QHBoxLayout()
        r_row.addWidget(self.radius_slider)
        r_row.addWidget(self.radius)
        edge_form.addRow("Radius:", r_row)

        # Smart Radius toggle
        self.smart_radius = QCheckBox("Smart Radius")
        self.smart_radius.setToolTip(
            "Adapts edge bandwidth locally to the image's observed transition width"
        )
        self.smart_radius.toggled.connect(self._changed)
        edge_form.addRow("", self.smart_radius)

        main_layout.addWidget(edge_group)

        # ----- 2. Global Refinements Group -----
        refine_group = QGroupBox("Global Refinements")
        refine_form = QFormLayout(refine_group)

        # Smooth (0..100 px)
        self.smooth_slider = QSlider(Qt.Orientation.Horizontal)
        self.smooth_slider.setRange(0, 100)
        self.smooth_slider.setValue(0)
        self.smooth = QSpinBox()
        self.smooth.setRange(0, 100)
        self.smooth.setValue(0)
        self.smooth.setSuffix(" px")
        self.smooth_slider.valueChanged.connect(self.smooth.setValue)
        self.smooth.valueChanged.connect(self.smooth_slider.setValue)
        self.smooth_slider.valueChanged.connect(self._changed)

        s_row = QHBoxLayout()
        s_row.addWidget(self.smooth_slider)
        s_row.addWidget(self.smooth)
        refine_form.addRow("Smooth:", s_row)

        # Feather (0..100 px)
        self.feather_slider = QSlider(Qt.Orientation.Horizontal)
        self.feather_slider.setRange(0, 100)
        self.feather_slider.setValue(0)
        self.feather = QSpinBox()
        self.feather.setRange(0, 100)
        self.feather.setValue(0)
        self.feather.setSuffix(" px")
        self.feather_slider.valueChanged.connect(self.feather.setValue)
        self.feather.valueChanged.connect(self.feather_slider.setValue)
        self.feather_slider.valueChanged.connect(self._changed)

        f_row = QHBoxLayout()
        f_row.addWidget(self.feather_slider)
        f_row.addWidget(self.feather)
        refine_form.addRow("Feather:", f_row)

        # Contrast (0..100 %)
        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(0, 100)
        self.contrast_slider.setValue(0)
        self.contrast = QSpinBox()
        self.contrast.setRange(0, 100)
        self.contrast.setValue(0)
        self.contrast.setSuffix(" %")
        self.contrast_slider.valueChanged.connect(self.contrast.setValue)
        self.contrast.valueChanged.connect(self.contrast_slider.setValue)
        self.contrast_slider.valueChanged.connect(self._changed)

        c_row = QHBoxLayout()
        c_row.addWidget(self.contrast_slider)
        c_row.addWidget(self.contrast)
        refine_form.addRow("Contrast:", c_row)

        # Shift Edge / Expand (-100..+100 %)
        self.shift_slider = QSlider(Qt.Orientation.Horizontal)
        self.shift_slider.setRange(-100, 100)
        self.shift_slider.setValue(0)
        self.shift = QSpinBox()
        self.shift.setRange(-100, 100)
        self.shift.setValue(0)
        self.shift.setSuffix(" %")
        self.shift.setToolTip("Positive expands, negative contracts")
        self.shift_slider.valueChanged.connect(self.shift.setValue)
        self.shift.valueChanged.connect(self.shift_slider.setValue)
        self.shift_slider.valueChanged.connect(self._changed)

        # Backward compatibility alias: self.expand points to self.shift
        self.expand = self.shift

        sh_row = QHBoxLayout()
        sh_row.addWidget(self.shift_slider)
        sh_row.addWidget(self.shift)
        refine_form.addRow("Shift Edge:", sh_row)

        main_layout.addWidget(refine_group)

        # ----- 3. Output / Decontamination Group -----
        decontam_group = QGroupBox("Output Settings")
        decontam_form = QFormLayout(decontam_group)

        self.decontaminate = QCheckBox("Decontaminate Colors")
        self.decontaminate.setToolTip(
            "Replaces background fringe bleed with extrapolated interior color"
        )
        self.decontaminate.toggled.connect(self._changed)
        decontam_form.addRow("", self.decontaminate)

        self.amount_slider = QSlider(Qt.Orientation.Horizontal)
        self.amount_slider.setRange(0, 100)
        self.amount_slider.setValue(100)
        self.decontaminate_amount = QSpinBox()
        self.decontaminate_amount.setRange(0, 100)
        self.decontaminate_amount.setValue(100)
        self.decontaminate_amount.setSuffix(" %")
        self.amount_slider.valueChanged.connect(self.decontaminate_amount.setValue)
        self.decontaminate_amount.valueChanged.connect(self.amount_slider.setValue)
        self.amount_slider.valueChanged.connect(self._changed)

        a_row = QHBoxLayout()
        a_row.addWidget(self.amount_slider)
        a_row.addWidget(self.decontaminate_amount)
        decontam_form.addRow("Amount:", a_row)

        main_layout.addWidget(decontam_group)

        # Preview toggle
        self.preview_cb = QCheckBox("Preview")
        self.preview_cb.setChecked(True)
        self.preview_cb.toggled.connect(self._on_preview_toggled)
        main_layout.addWidget(self.preview_cb)

        # Dialog buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        # Debounce timer for responsive preview
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(40)
        self._debounce.timeout.connect(self._preview)

    def _changed(self) -> None:
        if self.preview_cb.isChecked():
            self._debounce.start()

    def _on_preview_toggled(self, checked: bool) -> None:
        if checked:
            self._preview()
        else:
            self._debounce.stop()
            self._restore_preview()

    def _restore_preview(self) -> None:
        self._doc.set_selection(self._original)
        self._doc.selection_feather = self._original_feather
        if self._layer and self._pristine:
            self._layer.image = QImage(self._pristine)
            self._doc.notify_pixels(self._layer.bounds())

    def _preview(self) -> None:
        if not self.preview_cb.isChecked():
            return

        r = self.radius.value()
        smart = self.smart_radius.isChecked()
        sm = self.smooth.value()
        fth = self.feather.value()
        cnt = self.contrast.value()
        sh = self.shift.value()
        dec = self.decontaminate.isChecked()
        amt = self.decontaminate_amount.value() / 100.0

        refined_bool, _refined_alpha, dec_img = npimage.refine_selection(
            self._base_mask,
            image=self._pristine,
            radius=r,
            smart_radius=smart,
            smooth=sm,
            feather=fth,
            contrast=cnt,
            shift=sh,
            decontaminate=dec,
            decontaminate_amount=amt,
        )

        if refined_bool.any():
            self._doc.set_selection(npimage.mask_to_path(refined_bool))
            self._doc.selection_feather = float(fth)
        else:
            self._doc.set_selection(None)
            self._doc.selection_feather = 0.0

        if dec and dec_img is not None and self._layer:
            self._layer.image = dec_img
            self._decontaminated_image = dec_img
            self._doc.notify_pixels(self._layer.bounds())
        elif self._layer and self._pristine:
            self._layer.image = QImage(self._pristine)
            self._decontaminated_image = None
            self._doc.notify_pixels(self._layer.bounds())

    def accept(self) -> None:
        self._debounce.stop()
        self._preview()
        if self._decontaminated_image is not None and self._layer and self._pristine:
            cmd = LayerRegionCommand(
                self._doc,
                self._layer,
                self._layer.image.rect(),
                self._pristine,
                self._decontaminated_image,
                "Select and Mask Decontamination",
                applied=True,
            )
            self._doc.undo_stack.push(cmd)
        super().accept()

    def reject(self) -> None:
        self._debounce.stop()
        self._restore_preview()
        super().reject()
