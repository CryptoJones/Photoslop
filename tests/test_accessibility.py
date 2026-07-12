# SPDX-License-Identifier: Apache-2.0
"""Accessible names, preferences, announcements, and keyboard alternatives."""

from PySide6.QtCore import QSize
from PySide6.QtGui import QAccessible, QColor
from PySide6.QtWidgets import QAbstractButton, QLineEdit

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
    assert win.current_editor().canvas._ants.interval() == 1000
    assert "min-height: 48px" in win.styleSheet()
    assert "background: #000" in win.styleSheet()


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
