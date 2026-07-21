# SPDX-License-Identifier: Apache-2.0
"""Semantics, preferences, announcements, and keyboard-only alternatives."""

from PySide6.QtCore import QEvent, QPointF, QSize, Qt
from PySide6.QtGui import QAccessible, QColor, QKeyEvent, QPainterPath
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFormLayout,
    QLineEdit,
)

from photoslop.document import Document
from photoslop.mainwindow import MainWindow
from photoslop.preferences import AccessibilityPanel


def _window(qapp):
    win = MainWindow()
    win.add_document(Document.new(QSize(100, 80), 72, "a11y", QColor("white")))
    win.accessibility.apply()
    return win


def test_custom_canvas_and_rulers_have_accessible_interfaces(qapp):
    win = _window(qapp)
    editor = win.current_editor()
    for widget, expected in ((editor.canvas, "Image canvas"),
                             (editor.hruler, "Horizontal ruler"),
                             (editor.vruler, "Vertical ruler")):
        assert widget.accessibleName() == expected
        interface = QAccessible.queryAccessibleInterface(widget)
        assert interface is not None and interface.isValid()


def test_canvas_exposes_dynamic_state_and_registered_assistive_actions(qapp):
    win = _window(qapp)
    canvas = win.current_editor().canvas
    canvas.hover_pos = QPointF(12, 7)
    interface = QAccessible.queryAccessibleInterface(canvas)

    assert interface.role() == QAccessible.Role.Client
    assert "100 by 80 pixels" in interface.text(QAccessible.Text.Description)
    assert "Active tool brush" in interface.text(QAccessible.Text.Description)
    assert "x 12, y 7" in canvas.accessible_summary()

    describe_spec, describe_action = win.action_registry.entries["describe.canvas"]
    deselect_spec, deselect_action = win.action_registry.entries["deselect"]
    assert describe_spec.shortcut == "Ctrl+Alt+Shift+D"
    assert deselect_spec.shortcut == "Ctrl+D"
    win.show()
    qapp.processEvents()
    describe_action.trigger()
    assert canvas.hasFocus()
    assert "Editable document canvas" in win.statusBar().currentMessage()

    selection = QPainterPath()
    selection.addRect(10, 10, 20, 15)
    win.current_doc().set_selection(selection)
    deselect_action.trigger()
    assert win.current_doc().selection is None


def test_icon_buttons_receive_unique_useful_names(qapp):
    win = _window(qapp)
    buttons = [button for button in win.findChildren(QAbstractButton)
               if button.isVisible() or button.toolTip()]
    assert buttons
    assert all(button.accessibleName() for button in buttons)


def test_accessibility_preferences_apply_high_contrast_scale_and_motion(qapp):
    win = _window(qapp)
    panel = AccessibilityPanel()
    panel.high_contrast.setChecked(True)
    panel.reduced_motion.setChecked(True)
    panel.scale.setCurrentIndex(panel.scale.findData(200))
    panel.apply()
    win.accessibility.apply()
    assert win.property("reducedMotion") is True
    assert not win.current_editor().canvas._ants.isActive()
    assert "min-height: 48px" in win.styleSheet()
    assert "font-size:" in win.styleSheet()
    assert "width: 32px" in win.styleSheet()
    assert "border: 3px solid #ff0" in win.styleSheet()
    assert "border: 3px double #fff" in win.styleSheet()
    assert "background: #000" in win.styleSheet()
    selection = QPainterPath()
    selection.addRect(5, 5, 30, 20)
    win.current_doc().set_selection(selection)
    assert not win.current_editor().canvas._ants.isActive()

    win.show()
    canvas = win.current_editor().canvas
    canvas.setFocus(Qt.FocusReason.ShortcutFocusReason)
    qapp.processEvents()
    image = canvas.grab().toImage()
    perimeter = [
        image.pixelColor(x, y)
        for y in range(min(6, image.height()))
        for x in range(image.width())
    ]
    assert any(color.red() > 230 and color.green() > 230 and color.blue() < 30
               for color in perimeter)


def test_dynamic_dialog_controls_are_named_from_form_labels(qapp):
    win = _window(qapp)
    dialog = QDialog(win)
    form = QFormLayout(dialog)
    value = QLineEdit()
    form.addRow("Layer name", value)
    dialog.show()
    qapp.processEvents()

    assert value.accessibleName() == "Layer name"
    interface = QAccessible.queryAccessibleInterface(value)
    assert interface is not None
    assert interface.role() == QAccessible.Role.EditableText


def test_keyboard_actions_add_and_clear_guides(qapp):
    win = _window(qapp)
    doc = win.current_doc()
    win.action_add_center_guide("h")
    win.action_add_center_guide("v")
    assert doc.guides_h == [40.0]
    assert doc.guides_v == [50.0]
    win.action_clear_guides()
    assert not doc.guides_h and not doc.guides_v


def test_status_messages_support_accessible_announcements(qapp):
    win = _window(qapp)
    win.accessibility.announce("Selection changed")


def test_escape_cancels_interaction_before_clearing_selection(qapp):
    win = _window(qapp)
    doc = win.current_doc()
    canvas = win.current_editor().canvas
    original = QPainterPath()
    original.addRect(3, 4, 30, 20)
    doc.set_selection(original)
    win._set_tool("rect-select")
    tool = win.active_tool
    tool.press(doc, canvas, QPointF(40, 30), None)
    tool.move(doc, canvas, QPointF(70, 60), None)
    escape = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape,
        Qt.KeyboardModifier.NoModifier,
    )

    canvas.keyPressEvent(escape)
    assert doc.selection_bounds() == original.boundingRect().toAlignedRect()
    assert not tool.has_active_interaction()
    canvas.keyPressEvent(escape)
    assert doc.selection is None


def test_transform_has_keyboard_nudge_and_shift_acceleration(qapp):
    win = _window(qapp)
    canvas = win.current_editor().canvas
    win.action_free_transform()
    session = win.active_tool.session

    canvas.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Right,
        Qt.KeyboardModifier.NoModifier,
    ))
    canvas.keyPressEvent(QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Down,
        Qt.KeyboardModifier.ShiftModifier,
    ))
    assert session.translation == QPointF(1, 10)


def test_layer_stack_exposes_order_visibility_type_and_opacity(qapp):
    win = _window(qapp)
    item = win.layer_panel.list.item(0)
    text = item.data(Qt.ItemDataRole.AccessibleTextRole)
    description = item.data(Qt.ItemDataRole.AccessibleDescriptionRole)
    assert "raster layer" in text
    assert "visible" in text
    assert "100 percent opacity" in text
    assert "position 1 of 1" in text
    assert "F2 to rename" in description


def test_command_palette_preserves_search_focus_and_result_semantics(qapp):
    win = _window(qapp)
    palette = win.action_registry.palette(win)
    palette.show()
    qapp.processEvents()
    palette.search.setText("transform")
    qapp.processEvents()

    assert palette.search.hasFocus()
    assert palette.results.count() > 0
    item = palette.results.item(0)
    assert item.data(Qt.ItemDataRole.AccessibleTextRole)
    assert item.data(Qt.ItemDataRole.AccessibleDescriptionRole)


def test_keyboard_focus_tree_exposes_roles_names_and_editable_values(qapp):
    win = _window(qapp)
    win.show()
    qapp.processEvents()
    controls = [control for control in win.findChildren(QLineEdit)
                if control.isEnabled()]
    assert controls
    for control in controls:
        interface = QAccessible.queryAccessibleInterface(control)
        assert interface is not None and interface.isValid()
        if control.objectName() == "qt_spinbox_lineedit":
            parent = QAccessible.queryAccessibleInterface(control.parentWidget())
            assert parent is not None and parent.role() == QAccessible.Role.SpinBox
        else:
            assert interface.role() == QAccessible.Role.EditableText
            assert (control.accessibleName() or control.placeholderText()
                    or control.toolTip())


def test_vector_workflow_has_keyboard_tool_alternatives(qapp):
    win = _window(qapp)
    assert win._tool_actions["vector-select"].shortcut().toString() == "A"
    assert win._tool_actions["vector-node"].shortcut().toString() == "Shift+A"
    win._tool_actions["vector-select"].trigger()
    assert win.active_tool.name == "vector-select"
    win._tool_actions["vector-node"].trigger()
    assert win.active_tool.name == "vector-node"
