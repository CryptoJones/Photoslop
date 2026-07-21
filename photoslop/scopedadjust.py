# SPDX-License-Identifier: Apache-2.0
"""Shared scope handling for the adjustment dialogs: apply to the active
layer (default) or to every visible layer ("full image"), with live preview
from pristine copies and a single undo macro on OK."""

from __future__ import annotations

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QCheckBox

from photoslop.commands import LayerRegionCommand


class ScopedAdjustMixin:
    """Mix into an adjustment QDialog. The dialog must call init_scope()
    after storing self._doc/self._layer, implement transform(img) applying
    the current settings in place, and route preview/accept/reject through
    preview_scope/accept_scope/reject_scope."""

    def init_scope(self, form) -> None:
        self._pristines: dict = {self._layer: QImage(self._layer.image)}
        self.scope_all = QCheckBox("Apply to all layers (full image)")
        self.scope_all.toggled.connect(self._scope_toggled)
        form.addRow(self.scope_all)

    def targets(self) -> list:
        if self.scope_all.isChecked():
            return [
                layer
                for layer in self._doc.layers
                if layer.visible and layer.adjustment is None and not layer.image.isNull()
            ]
        return [self._layer]

    def _pristine_for(self, layer) -> QImage:
        if layer not in self._pristines:
            self._pristines[layer] = QImage(layer.image)
        return self._pristines[layer]

    def _scope_toggled(self, _on: bool) -> None:
        # restore everything, then re-preview at the new scope
        self._restore_all()
        self.preview_scope()

    def _restore_all(self) -> None:
        for layer, pristine in self._pristines.items():
            layer.image = QImage(pristine)
            self._doc.notify_pixels(layer.bounds())

    def preview_scope(self) -> None:
        for layer in self.targets():
            img = QImage(self._pristine_for(layer))
            self.transform(img)  # first write detaches the COW copy
            layer.image = img
            self._doc.notify_pixels(layer.bounds())

    def accept_scope(self, text: str) -> None:
        self.preview_scope()
        changed = [
            (layer, pristine)
            for layer, pristine in self._pristines.items()
            if layer.image != pristine
        ]
        if changed:
            self._doc.undo_stack.beginMacro(text)
            for layer, pristine in changed:
                self._doc.undo_stack.push(
                    LayerRegionCommand(
                        self._doc,
                        layer,
                        layer.image.rect(),
                        QImage(pristine),
                        QImage(layer.image),
                        text,
                        applied=True,
                    )
                )
            self._doc.undo_stack.endMacro()

    def reject_scope(self) -> None:
        self._restore_all()
