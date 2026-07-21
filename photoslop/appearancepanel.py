# SPDX-License-Identifier: Apache-2.0
"""Dockable Appearance editor for ordered, non-destructive layer effects."""

from __future__ import annotations

import copy
import json
from contextlib import suppress

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from photoslop.appearance import (
    BUILTIN_PRESETS,
    EFFECT_LABELS,
    new_effect,
    normalize_effects,
)
from photoslop.layer import BLEND_MODES

_OPTIONS = {
    "source": ["edge", "center"],
    "position": ["outside", "center", "inside"],
    "style": ["inner-bevel", "emboss"],
}


class AppearancePanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.doc = None
        self._updating = False
        self._settings = QSettings("CryptoJones", "Photoslop")
        self._selected_id = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        self.status = QLabel("No active layer")
        root.addWidget(self.status)

        preset_row = QHBoxLayout()
        self.presets = QComboBox()
        self.apply_preset_btn = QPushButton("Apply")
        self.save_preset_btn = QToolButton()
        self.save_preset_btn.setText("Save")
        self.delete_preset_btn = QToolButton()
        self.delete_preset_btn.setText("Delete")
        preset_row.addWidget(self.presets, 1)
        preset_row.addWidget(self.apply_preset_btn)
        preset_row.addWidget(self.save_preset_btn)
        preset_row.addWidget(self.delete_preset_btn)
        root.addLayout(preset_row)

        add_row = QHBoxLayout()
        self.effect_kind = QComboBox()
        for kind, label in EFFECT_LABELS.items():
            self.effect_kind.addItem(label, kind)
        self.add_btn = QPushButton("Add Effect")
        add_row.addWidget(self.effect_kind, 1)
        add_row.addWidget(self.add_btn)
        root.addLayout(add_row)

        self.effects = QListWidget()
        self.effects.setAccessibleName("Appearance effect stack")
        self.effects.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.effects.setDefaultDropAction(Qt.DropAction.MoveAction)
        root.addWidget(self.effects, 1)

        actions = QHBoxLayout()
        self.duplicate_btn = QToolButton()
        self.duplicate_btn.setText("Duplicate")
        self.up_btn = QToolButton()
        self.up_btn.setText("Up")
        self.down_btn = QToolButton()
        self.down_btn.setText("Down")
        self.delete_btn = QToolButton()
        self.delete_btn.setText("Delete")
        for button in (self.duplicate_btn, self.up_btn, self.down_btn, self.delete_btn):
            actions.addWidget(button)
        root.addLayout(actions)

        self.form_widget = QWidget()
        self.form = QFormLayout(self.form_widget)
        root.addWidget(self.form_widget)

        self.fill_opacity = QDoubleSpinBox()
        self.fill_opacity.setRange(0, 100)
        self.fill_opacity.setSuffix(" %")
        self.fill_opacity.setAccessibleName("Fill opacity")
        root.addWidget(QLabel("Fill Opacity"))
        root.addWidget(self.fill_opacity)

        self.add_btn.clicked.connect(self.add_effect)
        self.effects.currentItemChanged.connect(self._selection_changed)
        self.effects.itemChanged.connect(self._enabled_changed)
        self.effects.model().rowsMoved.connect(self._rows_moved)
        self.duplicate_btn.clicked.connect(self.duplicate_effect)
        self.delete_btn.clicked.connect(self.delete_effect)
        self.up_btn.clicked.connect(lambda: self.move_effect(-1))
        self.down_btn.clicked.connect(lambda: self.move_effect(1))
        self.fill_opacity.valueChanged.connect(self._fill_changed)
        self.apply_preset_btn.clicked.connect(self.apply_preset)
        self.save_preset_btn.clicked.connect(self.save_preset)
        self.delete_preset_btn.clicked.connect(self.delete_preset)
        self._load_presets()
        self.refresh()

    def _custom_presets(self) -> dict[str, list[dict]]:
        try:
            raw = json.loads(str(self._settings.value("appearance/presets/v1", "{}")))
            if not isinstance(raw, dict):
                return {}
            return {
                str(name): normalize_effects(stack)
                for name, stack in raw.items()
                if isinstance(stack, list)
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def _load_presets(self) -> None:
        current = self.presets.currentText()
        self.presets.clear()
        for name in BUILTIN_PRESETS:
            self.presets.addItem(name, ("builtin", name))
        for name in sorted(self._custom_presets()):
            self.presets.addItem(name, ("custom", name))
        index = self.presets.findText(current)
        if index >= 0:
            self.presets.setCurrentIndex(index)

    def set_document(self, doc) -> None:
        if self.doc is not None:
            with suppress(RuntimeError):
                self.doc.structureChanged.disconnect(self.refresh)
        self.doc = doc
        if doc is not None:
            doc.structureChanged.connect(self.refresh)
        self.refresh()

    def _layer(self):
        return self.doc.active_layer if self.doc is not None else None

    def refresh(self, selected_id=None) -> None:
        layer = self._layer()
        self._updating = True
        self.effects.clear()
        enabled = layer is not None
        for widget in (
            self.effects,
            self.add_btn,
            self.effect_kind,
            self.fill_opacity,
            self.apply_preset_btn,
            self.save_preset_btn,
        ):
            widget.setEnabled(enabled)
        if layer is None:
            self.status.setText("No active layer")
            self.fill_opacity.setValue(100)
        else:
            layer.effects = normalize_effects(layer.effects)
            self.status.setText(layer.name)
            for effect in layer.effects:
                item = QListWidgetItem(EFFECT_LABELS[effect["type"]])
                item.setData(Qt.ItemDataRole.UserRole, effect["id"])
                item.setFlags(
                    item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled
                )
                item.setCheckState(
                    Qt.CheckState.Checked if effect["enabled"] else Qt.CheckState.Unchecked
                )
                self.effects.addItem(item)
            self.fill_opacity.setValue(layer.fill_opacity * 100)
        self._updating = False
        wanted = selected_id or self._selected_id
        row = next(
            (
                row
                for row in range(self.effects.count())
                if self.effects.item(row).data(Qt.ItemDataRole.UserRole) == wanted
            ),
            0,
        )
        if self.effects.count():
            self.effects.setCurrentRow(row)
        else:
            self._build_form(None)

    def _stack(self) -> list[dict]:
        layer = self._layer()
        return copy.deepcopy(normalize_effects(layer.effects if layer else []))

    def _commit(
        self,
        stack: list[dict],
        text: str,
        selected_id=None,
        fill_opacity=None,
        *,
        refresh=True,
        merge_key=None,
    ) -> None:
        layer = self._layer()
        if layer is None:
            return
        from photoslop.commands import SetLayerStyleCommand

        self.doc.undo_stack.push(
            SetLayerStyleCommand(
                self.doc,
                layer,
                stack,
                layer.fill_opacity if fill_opacity is None else fill_opacity,
                text,
                merge_key=merge_key,
            )
        )
        if refresh:
            self.refresh(selected_id)

    def add_effect(self) -> None:
        effect = new_effect(str(self.effect_kind.currentData()))
        self._commit([*self._stack(), effect], f"Add {EFFECT_LABELS[effect['type']]}", effect["id"])

    def _selected_index(self) -> int:
        return self.effects.currentRow()

    def duplicate_effect(self) -> None:
        row, stack = self._selected_index(), self._stack()
        if not 0 <= row < len(stack):
            return
        duplicate = new_effect(stack[row]["type"], **stack[row]["parameters"])
        duplicate["blend_mode"] = stack[row]["blend_mode"]
        duplicate["opacity"] = stack[row]["opacity"]
        stack.insert(row + 1, duplicate)
        self._commit(stack, "Duplicate Effect", duplicate["id"])

    def delete_effect(self) -> None:
        row, stack = self._selected_index(), self._stack()
        if 0 <= row < len(stack):
            del stack[row]
            self._commit(stack, "Delete Effect")

    def move_effect(self, delta: int) -> None:
        row, stack = self._selected_index(), self._stack()
        target = row + delta
        if not (0 <= row < len(stack) and 0 <= target < len(stack)):
            return
        effect = stack.pop(row)
        stack.insert(target, effect)
        self._commit(stack, "Reorder Effects", effect["id"])

    def _rows_moved(self, *_args) -> None:
        if self._updating:
            return
        by_id = {effect["id"]: effect for effect in self._stack()}
        stack = [
            by_id[self.effects.item(row).data(Qt.ItemDataRole.UserRole)]
            for row in range(self.effects.count())
        ]
        self._commit(stack, "Reorder Effects", self._selected_id)

    def _selection_changed(self, current, _previous) -> None:
        self._selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        stack = self._stack()
        effect = next((item for item in stack if item["id"] == self._selected_id), None)
        self._build_form(effect)

    def _enabled_changed(self, item) -> None:
        if self._updating:
            return
        stack = self._stack()
        effect_id = item.data(Qt.ItemDataRole.UserRole)
        for effect in stack:
            if effect["id"] == effect_id:
                effect["enabled"] = item.checkState() == Qt.CheckState.Checked
        self._commit(stack, "Toggle Effect", effect_id)

    def _clear_form(self) -> None:
        while self.form.count():
            item = self.form.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _build_form(self, effect) -> None:
        self._clear_form()
        if effect is None:
            return
        blend = QComboBox()
        blend.addItems(BLEND_MODES)
        blend.setCurrentText(effect["blend_mode"])
        blend.currentTextChanged.connect(
            lambda value: self._set_common(effect["id"], "blend_mode", value)
        )
        self.form.addRow("Blend", blend)
        opacity = QDoubleSpinBox()
        opacity.setRange(0, 100)
        opacity.setSuffix(" %")
        opacity.setValue(effect["opacity"] * 100)
        opacity.valueChanged.connect(
            lambda value: self._set_common(effect["id"], "opacity", value / 100)
        )
        self.form.addRow("Opacity", opacity)
        for key, value in effect["parameters"].items():
            label = key.replace("_", " ").title()
            if key.endswith("color") or key in {"color", "color1", "color2"}:
                button = QPushButton(QColor(*value).name())
                button.setStyleSheet(f"background-color:{QColor(*value).name()}")
                button.clicked.connect(
                    lambda _checked=False, eid=effect["id"], field=key, initial=value: (
                        self._pick_color(eid, field, initial)
                    )
                )
                self.form.addRow(label, button)
            elif key in _OPTIONS:
                combo = QComboBox()
                combo.addItems(_OPTIONS[key])
                combo.setCurrentText(str(value))
                combo.currentTextChanged.connect(
                    lambda text, eid=effect["id"], field=key: self._set_parameter(eid, field, text)
                )
                self.form.addRow(label, combo)
            elif isinstance(value, bool):
                check = QCheckBox()
                check.setChecked(value)
                check.toggled.connect(
                    lambda checked, eid=effect["id"], field=key: self._set_parameter(
                        eid, field, checked
                    )
                )
                self.form.addRow(label, check)
            else:
                spin = QDoubleSpinBox()
                spin.setRange(
                    -10000 if key.startswith("offset_") else 0,
                    10000 if key.startswith("offset_") else 1000,
                )
                spin.setDecimals(1)
                spin.setValue(float(value))
                spin.valueChanged.connect(
                    lambda number, eid=effect["id"], field=key: self._set_parameter(
                        eid, field, number
                    )
                )
                self.form.addRow(label, spin)

    def _set_common(self, effect_id, key, value) -> None:
        if self._updating:
            return
        stack = self._stack()
        for effect in stack:
            if effect["id"] == effect_id:
                effect[key] = value
        kind = next(effect["type"] for effect in stack if effect["id"] == effect_id)
        self._commit(
            stack,
            f"Edit {EFFECT_LABELS[kind]}",
            effect_id,
            refresh=False,
            merge_key=(effect_id, key),
        )

    def _set_parameter(self, effect_id, key, value) -> None:
        if self._updating:
            return
        stack = self._stack()
        for effect in stack:
            if effect["id"] == effect_id:
                effect["parameters"][key] = value
        refresh = key.endswith("color") or key in {"color", "color1", "color2"}
        self._commit(stack, "Edit Effect", effect_id, refresh=refresh, merge_key=(effect_id, key))

    def _pick_color(self, effect_id, key, initial) -> None:
        color = QColorDialog.getColor(
            QColor(*initial), self, "Effect Color", QColorDialog.ColorDialogOption.ShowAlphaChannel
        )
        if color.isValid():
            self._set_parameter(
                effect_id, key, [color.red(), color.green(), color.blue(), color.alpha()]
            )

    def _fill_changed(self, value: float) -> None:
        if not self._updating and self._layer() is not None:
            self._commit(
                self._stack(),
                "Fill Opacity",
                self._selected_id,
                value / 100,
                refresh=False,
                merge_key="fill-opacity",
            )

    def apply_preset(self) -> None:
        data = self.presets.currentData()
        if not data:
            return
        source, name = data
        stack = BUILTIN_PRESETS[name] if source == "builtin" else self._custom_presets()[name]
        # Preset instances receive fresh IDs so stacks can be safely duplicated.
        fresh = [new_effect(effect["type"], **effect["parameters"]) for effect in stack]
        for target, original in zip(fresh, stack, strict=True):
            target["blend_mode"] = original["blend_mode"]
            target["opacity"] = original["opacity"]
        self._commit(fresh, f"Apply {name} Appearance")

    def save_preset(self) -> None:
        if self._layer() is None:
            return
        name, ok = QInputDialog.getText(self, "Save Appearance Preset", "Name:")
        name = name.strip()
        if not ok or not name or name in BUILTIN_PRESETS:
            return
        custom = self._custom_presets()
        custom[name] = self._stack()
        self._settings.setValue("appearance/presets/v1", json.dumps(custom, separators=(",", ":")))
        self._load_presets()
        self.presets.setCurrentText(name)

    def delete_preset(self) -> None:
        data = self.presets.currentData()
        if not data or data[0] != "custom":
            return
        custom = self._custom_presets()
        custom.pop(data[1], None)
        self._settings.setValue("appearance/presets/v1", json.dumps(custom, separators=(",", ":")))
        self._load_presets()
