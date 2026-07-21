# SPDX-License-Identifier: Apache-2.0
"""Tool registry, SVG icon states, grouped flyouts, and density modes."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from photoslop.layerpanel import LayerPanel
from photoslop.mainwindow import MainWindow
from photoslop.svgicons import PATHS, svg_icon
from photoslop.toolregistry import TOOL_GROUPS, TOOL_SPEC_BY_ID, TOOL_SPECS


def test_registry_covers_every_interactive_toolbar_tool(qapp):
    win = MainWindow()
    assert set(TOOL_SPEC_BY_ID) == set(win.tools) - {"transform"}
    assert len(TOOL_GROUPS) == 14
    assert all(spec.icon in PATHS for spec in TOOL_SPECS)
    assert len({spec.tool_id for spec in TOOL_SPECS}) == len(TOOL_SPECS)


def test_svg_icons_supply_normal_disabled_and_hidpi_pixmaps(qapp):
    icon = svg_icon("brush")
    for mode in (QIcon.Mode.Normal, QIcon.Mode.Active, QIcon.Mode.Selected, QIcon.Mode.Disabled):
        pm = icon.pixmap(24, 24, mode)
        assert not pm.isNull()
        assert pm.devicePixelRatio() >= 1.0


def test_toolbox_groups_every_action_into_keyboard_named_flyouts(qapp):
    win = MainWindow()
    assert set(win._tool_group_buttons) == set(TOOL_GROUPS)
    action_ids = set()
    for group_id, button in win._tool_group_buttons.items():
        assert button.accessibleName()
        assert button.menu().accessibleName()
        ids = {spec.tool_id for spec in TOOL_SPECS if spec.group == group_id}
        grouped = {
            tool_id
            for tool_id, action in win._tool_actions.items()
            if action in button.menu().actions()
        }
        assert grouped == ids
        action_ids |= grouped
    assert action_ids == set(TOOL_SPEC_BY_ID)


def test_flyout_keeps_last_selected_tool_visible(qapp):
    win = MainWindow()
    win._set_tool("eraser")
    button = win._tool_group_buttons["paint"]
    assert button.defaultAction() is win._tool_actions["eraser"]
    assert "Eraser" in button.toolTip()
    assert win._tool_actions["eraser"].isChecked()


def test_density_modes_are_persisted_and_change_button_style(qapp):
    win = MainWindow()
    win._set_toolbox_density("labels")
    assert win.settings.value("toolbox/density") == "labels"
    assert all(
        button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for button in win._tool_group_buttons.values()
    )
    win._set_toolbox_density("compact")
    assert win._tools_bar.iconSize().width() == 20
    assert all(
        button.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly
        for button in win._tool_group_buttons.values()
    )


def test_layer_panel_uses_stable_named_icons_instead_of_font_glyphs(qapp):
    panel = LayerPanel()
    for button in panel._buttons.values():
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.accessibleName() == button.toolTip()
