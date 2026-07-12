# SPDX-License-Identifier: Apache-2.0
"""Main window: tabs of documents, tool/options toolbars, layer panel dock,
menus, clipboards (pixel + layer, both cross-document), status bar."""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRect, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPixmap,
    QUndoGroup,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QUndoView,
)

from photoslop import __version__, io_formats, units
from photoslop.accessibility import AccessibilityController
from photoslop.actionregistry import ActionRegistry
from photoslop.canvas import EditorView
from photoslop.commands import (
    FlipImageCommand,
    FlipLayerCommand,
    InsertLayerCommand,
    LayerRegionCommand,
    ResizeCanvasCommand,
    ResizeImageCommand,
    RotateImageCommand,
    RotateLayerCommand,
)
from photoslop.dialogs import CanvasSizeDialog, NewDocumentDialog, ResizeImageDialog
from photoslop.document import Document
from photoslop.exportdialog import ExportDialog
from photoslop.io_ora import load_ora, save_ora
from photoslop.io_raw import is_raw_path, load_raw
from photoslop.layer import BLEND_MODES, FORMAT, Layer, blank_image
from photoslop.opendialog import OpenImageDialog
from photoslop.propertiespanel import PropertiesPanel
from photoslop.svgicons import svg_icon
from photoslop.tasks import TaskService, snapshot_document
from photoslop.toolregistry import TOOL_GROUPS, TOOL_SPEC_BY_ID, TOOL_SPECS
from photoslop.tools import (
    BrushTool,
    BucketTool,
    BurnTool,
    CloneStampTool,
    CropTool,
    DodgeTool,
    EllipseSelectTool,
    EraserTool,
    EyedropperTool,
    GradientTool,
    HandTool,
    HealBrushTool,
    LassoTool,
    LiquifyTool,
    MagicWandTool,
    MagneticLassoTool,
    MoveTool,
    PatchTool,
    PencilTool,
    PenTool,
    PerspectiveTool,
    PolyLassoTool,
    PuppetTool,
    QuickSelectTool,
    RectSelectTool,
    ShapeTool,
    SmudgeTool,
    SpotHealTool,
    TextTool,
    ToolOptions,
    ZoomTool,
)
from photoslop.transform import TransformTool

CREDITS_TEXT = "Contributors: CryptoJones, GPT5.5, and Fable5"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Photoslop {__version__}")
        self.settings = QSettings("CryptoJones", "Photoslop")
        self.action_registry = ActionRegistry(self)
        self.task_service = TaskService(parent=self)
        unit = str(self.settings.value("units", "px"))
        self.unit = unit if unit in units.UNITS else "px"
        self.show_grid = self.settings.value("grid", "false") == "true"
        self.snap_enabled = self.settings.value("snap", "true") == "true"

        self.options = ToolOptions()
        self.tools = {
            tool.name: tool
            for tool in (
                BrushTool(self.options),
                PencilTool(self.options),
                EraserTool(self.options),
                BucketTool(self.options),
                GradientTool(self.options),
                EyedropperTool(self.options),
                RectSelectTool(self.options),
                EllipseSelectTool(self.options),
                LassoTool(self.options),
                PolyLassoTool(self.options),
                MagneticLassoTool(self.options),
                MagicWandTool(self.options),
                QuickSelectTool(self.options),
                CloneStampTool(self.options),
                SmudgeTool(self.options),
                SpotHealTool(self.options),
                HealBrushTool(self.options),
                PatchTool(self.options),
                LiquifyTool(self.options),
                PuppetTool(self.options),
                PerspectiveTool(self.options),
                TextTool(self.options),
                ShapeTool(self.options),
                PenTool(self.options),
                DodgeTool(self.options),
                CropTool(self.options),
                BurnTool(self.options),
                MoveTool(self.options),
                HandTool(self.options),
                ZoomTool(self.options),
                TransformTool(self.options),
            )
        }
        self._active_tool_name = "brush"
        self._pre_transform_tool = "brush"
        self.action_recording: list | None = None  # [(label, replay_fn)]
        self.recorded_action: list = []

        self.pixel_clip: tuple[QImage, QPoint] | None = None
        self.layer_clip: Layer | None = None
        self._clip_from_us = False
        QGuiApplication.clipboard().dataChanged.connect(self._on_system_clipboard)

        self.undo_group = QUndoGroup(self)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabCloseRequested.connect(self._on_tab_close)
        self.setCentralWidget(self.tabs)

        from photoslop.adjustpanel import AdjustPanel
        from photoslop.layerpanel import LayerPanel

        self.layer_panel = LayerPanel()
        self._layers_dock = QDockWidget("Layers")
        self._layers_dock.setObjectName("layers-dock")
        self._layers_dock.setWidget(self.layer_panel)
        self._layers_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._layers_dock)

        self.properties_panel = PropertiesPanel()
        self._properties_dock = QDockWidget("Properties")
        self._properties_dock.setObjectName("properties-dock")
        self._properties_dock.setWidget(self.properties_panel)
        self._properties_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._properties_dock)

        self.adjust_panel = AdjustPanel()
        self._adjust_dock = QDockWidget("Adjust")
        self._adjust_dock.setObjectName("adjust-dock")
        self._adjust_dock.setWidget(self.adjust_panel)
        self._adjust_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._adjust_dock)
        self.tabifyDockWidget(self._layers_dock, self._adjust_dock)
        self.tabifyDockWidget(self._layers_dock, self._properties_dock)

        self.history_view = QUndoView(self.undo_group)
        self.history_view.setEmptyLabel("Document opened")
        self._history_dock = QDockWidget("History")
        self._history_dock.setObjectName("history-dock")
        self._history_dock.setWidget(self.history_view)
        self._history_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._history_dock)
        self.tabifyDockWidget(self._adjust_dock, self._history_dock)

        self._layers_dock.raise_()

        self._build_tool_bar()
        self._build_options_bar()
        self._build_menus()
        self._build_status_bar()
        self.accessibility = AccessibilityController(self)
        self.statusBar().messageChanged.connect(self.accessibility.announce)
        self.task_service.taskAdded.connect(self._on_task_added)
        self.task_service.taskFinished.connect(self._on_task_finished)
        self._sync_option_visibility()
        self.accessibility.apply()

        self.setAcceptDrops(True)
        self.resize(1280, 800)

        # workspace: remember the built-in default, then apply a saved layout
        self._default_workspace = self.saveState()
        saved = self.settings.value("workspace/state")
        if saved is not None:
            self.restoreState(saved)
        geometry = self.settings.value("workspace/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        QTimer.singleShot(0, self._validate_workspace_geometry)

    def _validate_workspace_geometry(self) -> None:
        """Recover saved workspaces that no longer intersect a current screen."""
        frame = self.frameGeometry()
        if any(screen.availableGeometry().intersects(frame)
               for screen in QGuiApplication.screens()):
            return
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.resize(min(1280, available.width()), min(800, available.height()))
        self.move(available.center() - self.rect().center())

    # ------------------------------------------------------------------ tools

    @property
    def active_tool(self):
        return self.tools[self._active_tool_name]

    def _build_tool_bar(self) -> None:
        bar = QToolBar("Tools")
        bar.setObjectName("tools")
        bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, bar)
        group = QActionGroup(self)
        self._tool_actions = {}
        for spec in TOOL_SPECS:
            act = QAction(svg_icon(spec.icon), spec.label, self)
            act.setCheckable(True)
            act.setShortcut(spec.shortcut)
            act.setToolTip(f"{spec.label} ({spec.shortcut})")
            act.triggered.connect(lambda _=False, n=spec.tool_id: self._set_tool(n))
            group.addAction(act)
            self._tool_actions[spec.tool_id] = act

        self._tool_group_buttons = {}
        for group_id in TOOL_GROUPS:
            specs = [spec for spec in TOOL_SPECS if spec.group == group_id]
            button = QToolButton()
            button.setObjectName(f"tool-group-{group_id}")
            button.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
            button.setAccessibleName(f"{group_id.title()} tools")
            menu = QMenu(button)
            menu.setAccessibleName(f"{group_id.title()} tools")
            for spec in specs:
                menu.addAction(self._tool_actions[spec.tool_id])
            button.setMenu(menu)
            button.setDefaultAction(self._tool_actions[specs[0].tool_id])
            button.setToolTip(f"{specs[0].label} — open menu for related tools")
            bar.addWidget(button)
            self._tool_group_buttons[group_id] = button

        density = QToolButton()
        density.setText("⋯")
        density.setToolTip("Toolbox density")
        density.setAccessibleName("Toolbox density")
        density.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        density_menu = QMenu(density)
        density_group = QActionGroup(density_menu)
        for density_id, label in (("compact", "Compact icons"),
                                  ("comfortable", "Comfortable icons"),
                                  ("labels", "Icons and labels")):
            action = density_menu.addAction(label)
            action.setCheckable(True)
            action.setData(density_id)
            action.triggered.connect(
                lambda _=False, d=density_id: self._set_toolbox_density(d))
            density_group.addAction(action)
            if density_id == self.settings.value("toolbox/density", "comfortable"):
                action.setChecked(True)
        density.setMenu(density_menu)
        bar.addWidget(density)
        self._tools_bar = bar
        self._set_toolbox_density(str(self.settings.value(
            "toolbox/density", "comfortable")))
        self._tool_actions["brush"].setChecked(True)

        from PySide6.QtGui import QShortcut

        cycle = QShortcut(QKeySequence("G"), self)
        cycle.activated.connect(self._cycle_fill_tool)
        shape_cycle = QShortcut(QKeySequence("Shift+U"), self)
        shape_cycle.activated.connect(self._cycle_shape)

    def _set_toolbox_density(self, density: str) -> None:
        if density not in {"compact", "comfortable", "labels"}:
            density = "comfortable"
        self.settings.setValue("toolbox/density", density)
        sizes = {"compact": 20, "comfortable": 28, "labels": 24}
        self._tools_bar.setIconSize(QSize(sizes[density], sizes[density]))
        style = (Qt.ToolButtonStyle.ToolButtonTextBesideIcon
                 if density == "labels" else Qt.ToolButtonStyle.ToolButtonIconOnly)
        for button in self._tool_group_buttons.values():
            button.setToolButtonStyle(style)

    def _cycle_shape(self) -> None:
        """Shift+U: rect -> ellipse -> line, PS-style same-key variants."""
        order = ("rect", "ellipse", "line")
        self.options.shape = order[(order.index(self.options.shape) + 1) % 3]
        if self._active_tool_name != "shape":
            self._set_tool("shape")
            self._tool_actions["shape"].setChecked(True)
        self.statusBar().showMessage(f"Shape: {self.options.shape}", 3000)

    def _cycle_fill_tool(self) -> None:
        """G cycles Bucket <-> Gradient, PS-style same-key tool groups."""
        name = "gradient" if self._active_tool_name == "bucket" else "bucket"
        self._set_tool(name)
        self._tool_actions[name].setChecked(True)

    def _set_tool(self, name: str) -> None:
        self._active_tool_name = name
        if name in self._tool_actions:
            self._tool_actions[name].setChecked(True)
        spec = TOOL_SPEC_BY_ID.get(name)
        if spec is not None and hasattr(self, "_tool_group_buttons"):
            button = self._tool_group_buttons[spec.group]
            button.setDefaultAction(self._tool_actions[name])
            button.setToolTip(f"{spec.label} — open menu for related tools")
        self._sync_option_visibility()
        for i in range(self.tabs.count()):
            editor = self.tabs.widget(i)
            editor.canvas.refresh_cursor()
            editor.canvas.update()

    def _build_options_bar(self) -> None:
        bar = QToolBar("Tool Options")
        bar.setObjectName("tool-options")
        bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self._option_actions: dict[str, list] = {}

        self._tool_name_label = QLabel("Brush")
        self._tool_name_label.setObjectName("active-tool-name")
        self._tool_name_label.setAccessibleName("Active tool")
        bar.addWidget(self._tool_name_label)
        reset_options = QAction("Reset Tool Options", self)
        reset_options.setToolTip("Reset the active tool's options to defaults")
        reset_options.triggered.connect(self._reset_tool_options)
        bar.addAction(reset_options)
        bar.addSeparator()

        # Zoom In / Zoom Out pinned to the front of the top bar: always visible,
        # never hidden by _sync_option_visibility (not in _all_option_actions).
        from photoslop.icons import zoom_in_icon, zoom_out_icon

        zoom_in_btn = QAction(zoom_in_icon(), "Zoom In (Ctrl +)", self)
        zoom_in_btn.triggered.connect(lambda: self._zoom(+1))
        bar.addAction(zoom_in_btn)
        zoom_out_btn = QAction(zoom_out_icon(), "Zoom Out (Ctrl -)", self)
        zoom_out_btn.triggered.connect(lambda: self._zoom(-1))
        bar.addAction(zoom_out_btn)
        self.zoom_in_button = zoom_in_btn
        self.zoom_out_button = zoom_out_btn
        bar.addSeparator()

        self.color_btn = QToolButton()
        self.color_btn.setToolTip("Foreground colour (X swaps, D resets)")
        self.color_btn.clicked.connect(self._pick_foreground)
        color_act = bar.addWidget(self.color_btn)

        self.bg_btn = QToolButton()
        self.bg_btn.setToolTip("Background colour (X swaps, D resets)")
        self.bg_btn.clicked.connect(self._pick_background)
        bg_act = bar.addWidget(self.bg_btn)
        self.refresh_swatches()

        size = QSpinBox()
        size.setRange(1, 500)
        size.setValue(self.options.size)
        size.setSuffix(" px")
        size.setToolTip("Brush size")
        size.setAccessibleName("Size in pixels")
        size.valueChanged.connect(lambda v: setattr(self.options, "size", v))
        size_act = bar.addWidget(size)
        self._size_spin = size

        hardness = QSpinBox()
        hardness.setRange(0, 100)
        hardness.setValue(self.options.hardness)
        hardness.setSuffix("% hard")
        hardness.setToolTip("Brush hardness")
        hardness.setAccessibleName("Hardness percent")
        hardness.valueChanged.connect(lambda v: setattr(self.options, "hardness", v))
        hard_act = bar.addWidget(hardness)
        self._hardness_spin = hardness

        opacity = QSpinBox()
        opacity.setRange(1, 100)
        opacity.setValue(self.options.opacity)
        opacity.setSuffix("% opacity")
        opacity.setToolTip("Paint opacity")
        opacity.setAccessibleName("Opacity percent")
        opacity.valueChanged.connect(lambda v: setattr(self.options, "opacity", v))
        opacity_act = bar.addWidget(opacity)

        eraser = QCheckBox("Eraser")
        eraser.toggled.connect(lambda v: setattr(self.options, "eraser", v))
        eraser_act = bar.addWidget(eraser)

        tolerance = QSpinBox()
        tolerance.setRange(0, 255)
        tolerance.setValue(self.options.tolerance)
        tolerance.setPrefix("tol ")
        tolerance.setToolTip("Fill tolerance")
        tolerance.setAccessibleName("Tolerance")
        tolerance.valueChanged.connect(lambda v: setattr(self.options, "tolerance", v))
        tol_act = bar.addWidget(tolerance)

        shape = QComboBox()
        shape.addItems(["linear", "radial"])
        shape.setToolTip("Gradient shape")
        shape.setAccessibleName("Gradient shape")
        shape.currentTextChanged.connect(
            lambda v: setattr(self.options, "gradient_shape", v))
        shape_act = bar.addWidget(shape)

        flow = QSpinBox()
        flow.setRange(1, 100)
        flow.setValue(self.options.flow)
        flow.setSuffix("% flow")
        flow.setToolTip("Paint per stamp; opacity caps the whole stroke")
        flow.setAccessibleName("Flow percent")
        flow.valueChanged.connect(lambda v: setattr(self.options, "flow", v))
        flow_act = bar.addWidget(flow)

        scatter = QSpinBox()
        scatter.setRange(0, 200)
        scatter.setValue(self.options.scatter)
        scatter.setSuffix("% scatter")
        scatter.setToolTip("Random stamp offset as % of brush size")
        scatter.setAccessibleName("Scatter percent")
        scatter.valueChanged.connect(lambda v: setattr(self.options, "scatter", v))
        scatter_act = bar.addWidget(scatter)

        spacing = QSpinBox()
        spacing.setRange(5, 200)
        spacing.setValue(self.options.spacing)
        spacing.setSuffix("% gap")
        spacing.setToolTip("Stamp spacing as % of brush size (soft strokes)")
        spacing.setAccessibleName("Spacing percent")
        spacing.valueChanged.connect(lambda v: setattr(self.options, "spacing", v))
        spacing_act = bar.addWidget(spacing)

        fill_source = QComboBox()
        fill_source.addItems(["color", "pattern"])
        fill_source.setToolTip("Bucket fills with the foreground colour or "
                               "the defined pattern")
        fill_source.currentTextChanged.connect(
            lambda v: setattr(self.options, "fill_source", v))
        fill_source_act = bar.addWidget(fill_source)

        contiguous = QCheckBox("Contiguous")
        contiguous.setChecked(self.options.contiguous)
        contiguous.setToolTip("Off: select every pixel in colour range, "
                              "connected or not")
        contiguous.toggled.connect(lambda v: setattr(self.options, "contiguous", v))
        contig_act = bar.addWidget(contiguous)

        self._option_actions = {
            "brush": [color_act, bg_act, size_act, hard_act, opacity_act,
                      eraser_act, flow_act, spacing_act, scatter_act],
            "pencil": [color_act, bg_act, size_act, opacity_act, eraser_act],
            "eraser": [size_act, hard_act, opacity_act, flow_act, spacing_act,
                       scatter_act],
            "bucket": [color_act, bg_act, opacity_act, tol_act, fill_source_act],
            "gradient": [color_act, bg_act, opacity_act, shape_act],
            "eyedropper": [color_act, bg_act],
            "rect-select": [],
            "ellipse-select": [],
            "lasso": [],
            "poly-lasso": [],
            "magnetic-lasso": [],
            "wand": [tol_act, contig_act],
            "quick-select": [size_act, tol_act],
            "clone-stamp": [size_act, opacity_act],
            "smudge": [size_act, opacity_act],
            "spot-heal": [size_act],
            "heal": [size_act, opacity_act, spacing_act],
            "patch": [],
            "liquify": [size_act, opacity_act],
            "puppet": [],
            "perspective": [],
            "text": [color_act],
            "shape": [color_act, size_act],
            "pen": [color_act, size_act],
            "dodge": [size_act, hard_act, opacity_act, spacing_act],
            "burn": [size_act, hard_act, opacity_act, spacing_act],
            "crop": [],
            "move": [],
            "hand": [],
            "zoom": [],
            "transform": [],
        }
        self._all_option_actions = [
            color_act, bg_act, size_act, hard_act, opacity_act, eraser_act,
            tol_act, shape_act, contig_act, fill_source_act, flow_act,
            spacing_act, scatter_act,
        ]
        self._option_widgets = {
            "size": size, "hardness": hardness, "opacity": opacity,
            "tolerance": tolerance, "gradient_shape": shape, "flow": flow,
            "scatter": scatter, "spacing": spacing, "fill_source": fill_source,
            "contiguous": contiguous, "eraser": eraser,
        }

        # PS-style bracket shortcuts; window-level, invisible in menus
        for key, slot in (
            ("[", lambda: self._step_brush_size(-1)),
            ("]", lambda: self._step_brush_size(+1)),
            ("Shift+[", lambda: self._step_brush_hardness(-1)),
            ("Shift+]", lambda: self._step_brush_hardness(+1)),
        ):
            act = QAction(self)
            act.setShortcut(QKeySequence(key))
            act.triggered.connect(slot)
            self.addAction(act)

    def _step_brush_size(self, direction: int) -> None:
        size = self.options.size
        if size < 10 or (size == 10 and direction < 0):
            step = 1
        elif size < 50 or (size == 50 and direction < 0):
            step = 5
        else:
            step = 10
        self._size_spin.setValue(max(1, min(500, size + direction * step)))

    def _step_brush_hardness(self, direction: int) -> None:
        hardness = self.options.hardness + direction * 25
        self._hardness_spin.setValue(max(0, min(100, hardness)))

    def _reset_tool_options(self) -> None:
        defaults = ToolOptions()
        for name, widget in self._option_widgets.items():
            value = getattr(defaults, name)
            if isinstance(widget, QSpinBox):
                widget.setValue(value)
            elif isinstance(widget, QComboBox):
                widget.setCurrentText(value)
            else:
                widget.setChecked(value)
        self.statusBar().showMessage(f"{self._tool_name_label.text()} options reset", 3000)

    def _sync_option_visibility(self) -> None:
        spec = TOOL_SPEC_BY_ID.get(self._active_tool_name)
        self._tool_name_label.setText(spec.label if spec else self._active_tool_name.title())
        visible = set(self._option_actions[self._active_tool_name])
        for act in self._all_option_actions:
            act.setVisible(act in visible)
        self.action_registry.update()

    def _pick_foreground(self) -> None:
        color = QColorDialog.getColor(self.options.foreground, self, "Foreground colour")
        if color.isValid():
            self.options.foreground = color
            self.refresh_swatches()

    def _pick_background(self) -> None:
        color = QColorDialog.getColor(self.options.background, self, "Background colour")
        if color.isValid():
            self.options.background = color
            self.refresh_swatches()

    @staticmethod
    def _swatch_icon(color: QColor) -> QIcon:
        pm = QPixmap(20, 20)
        pm.fill(color)
        p = QPainter(pm)
        p.setPen(QColor(0, 0, 0))
        p.drawRect(0, 0, 19, 19)
        p.end()
        return QIcon(pm)

    def refresh_swatches(self) -> None:
        self.color_btn.setIcon(self._swatch_icon(self.options.foreground))
        self.bg_btn.setIcon(self._swatch_icon(self.options.background))

    def action_swap_colors(self) -> None:
        self.options.swap_colors()
        self.refresh_swatches()

    def action_reset_colors(self) -> None:
        self.options.reset_colors()
        self.refresh_swatches()

    # ------------------------------------------------------------------ menus

    def _build_menus(self) -> None:
        menu = self.menuBar()

        m_file = menu.addMenu("&File")
        m_file.addAction(self._act("&New…", "Ctrl+N", self.action_new))
        m_file.addAction(self._act("&Open…", "Ctrl+O", self.action_open))
        m_file.addSeparator()
        m_file.addAction(self._act("&Save", "Ctrl+S", self.action_save))
        m_file.addAction(self._act("Save &As…", "Ctrl+Shift+S", self.action_save_as))
        m_file.addAction(self._act("&Export…", "Ctrl+E", self.action_export))
        m_file.addSeparator()
        m_file.addAction(self._act("&Close Tab", "Ctrl+W", self.action_close_tab))
        m_file.addAction(self._act("&Quit", "Ctrl+Q", self.close,
                                   role=QAction.MenuRole.QuitRole))

        m_edit = menu.addMenu("&Edit")
        m_edit.addAction(self._act("Command &Palette…", "Ctrl+Shift+P",
                                   self.action_command_palette,
                                   prerequisite="always"))
        m_edit.addAction(self._act("Cancel Background Task", "Esc",
                                   self.action_cancel_tasks, prerequisite="task"))
        undo = self.undo_group.createUndoAction(self, "&Undo ")
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        redo = self.undo_group.createRedoAction(self, "&Redo ")
        redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        m_edit.addAction(undo)
        m_edit.addAction(redo)
        m_edit.addSeparator()
        m_edit.addAction(self._act("Cu&t Selection", "Ctrl+X", self.action_cut))
        m_edit.addAction(self._act("&Copy Selection", "Ctrl+C", self.action_copy))
        m_edit.addAction(self._act("&Paste as New Layer", "Ctrl+V", self.action_paste))
        m_edit.addAction(self._act("&Delete Selection", "Del", self.action_delete_selection))
        m_edit.addSeparator()
        m_edit.addAction(self._act("Generative &Fill… (Model)", None,
                                   self.action_generative_fill))
        m_action = m_edit.addMenu("Actio&ns")
        m_action.addAction(self._act("Start &Recording", None, self.action_record_start))
        m_action.addAction(self._act("Sto&p Recording", None, self.action_record_stop))
        m_action.addAction(self._act("&Play Action", "F9", self.action_play))
        m_edit.addSeparator()
        m_edit.addAction(self._act("&Fill Layer", "Alt+Backspace",
                                   self.action_fill_layer))
        m_edit.addAction(self._act("Fill Selection (Content-&Aware)", "Shift+F5",
                                   self.action_content_aware_fill))
        m_edit.addAction(self._act("Define &Pattern from Selection", None,
                                   self.action_define_pattern))
        m_edit.addSeparator()
        m_edit.addAction(self._act("Free &Transform", "Ctrl+T", self.action_free_transform))
        m_edit.addAction(self._act("&Warp…", "Ctrl+Shift+T", self.action_warp))
        m_edit.addAction(self._act("Rotate &90° CW", None,
                                   lambda: self._layer_cmd(RotateLayerCommand, 90)))
        m_edit.addAction(self._act("Rotate 9&0° CCW", None,
                                   lambda: self._layer_cmd(RotateLayerCommand, 270)))
        m_edit.addAction(self._act("Flip &Horizontal", None,
                                   lambda: self._layer_cmd(FlipLayerCommand, True)))
        m_edit.addAction(self._act("Flip &Vertical", None,
                                   lambda: self._layer_cmd(FlipLayerCommand, False)))
        m_edit.addSeparator()
        m_edit.addAction(self._act("S&wap Colours", "X", self.action_swap_colors))
        m_edit.addAction(self._act("Rese&t Colours", "D", self.action_reset_colors))
        m_edit.addSeparator()
        self._options_menu = m_edit.addMenu("&Options")
        self._rulers_menu = self._options_menu.addMenu("&Rulers")  # unit actions added below
        # PreferencesRole → native Photoslop → Preferences… (Cmd+,) on macOS;
        # Edit → Preferences… on Windows/Linux (the role only relocates on Mac).
        m_edit.addAction(self._act("&Preferences…", "Ctrl+,",
                                   self.action_preferences,
                                   role=QAction.MenuRole.PreferencesRole))

        m_select = menu.addMenu("&Select")
        m_select.addAction(self._act("&All", "Ctrl+A", self.action_select_all))
        m_select.addAction(self._act("&Deselect", "Ctrl+D", self.action_deselect))
        m_select.addSeparator()
        m_select.addAction(self._act("Su&bject (Model)", None,
                                     self.action_select_subject))
        m_select.addSeparator()
        m_select.addAction(self._act("Feat&her…", "Ctrl+Alt+D",
                                     self.action_feather_selection))
        m_select.addAction(self._act("&Refine…", "Ctrl+Alt+R",
                                     self.action_refine_selection))

        m_image = menu.addMenu("&Image")
        m_image.addAction(self._act("&Image Size…", "Ctrl+Alt+I", self.action_image_size))
        m_image.addAction(self._act("&Canvas Size…", "Ctrl+Alt+S", self.action_canvas_size))
        m_image.addAction(self._act("Content-A&ware Scale…", None,
                                    self.action_content_aware_scale))
        m_image.addAction(self._act("C&rop to Selection", "Ctrl+Alt+C", self.action_crop))
        m_image.addSeparator()
        m_boards = m_image.addMenu("Art&boards")
        m_boards.addAction(self._act("&Add Artboard from Selection", None,
                                     self.action_add_artboard))
        m_boards.addAction(self._act("&Clear Artboards", None,
                                     self.action_clear_artboards))
        m_boards.addAction(self._act("&Export Artboards…", None,
                                     self.action_export_artboards))
        m_image.addSeparator()
        m_adjustments = m_image.addMenu("&Adjustments")
        m_adjustments.addAction(self._act("&Levels…", "Ctrl+L", self.action_levels))
        m_adjustments.addAction(self._act("&Hue/Saturation…", "Ctrl+U",
                                          self.action_hue_saturation))
        m_adjustments.addAction(self._act("&Point Color…", "Ctrl+Shift+U",
                                          self.action_point_color))
        m_adjustments.addAction(self._act("Color &Balance…", "Ctrl+B",
                                          self.action_color_balance))
        m_adjustments.addAction(self._act("Cur&ves…", "Ctrl+M", self.action_curves))
        m_image.addSeparator()
        m_image.addAction(self._act("Assign &Profile…", None,
                                    self.action_assign_profile))
        m_image.addAction(self._act("Convert to Profi&le…", None,
                                    self.action_convert_profile))
        m_image.addSeparator()
        m_rotate = m_image.addMenu("Image &Rotation")
        m_rotate.addAction(self._act("Rotate 90° &CW", None,
                                     lambda: self._image_cmd(RotateImageCommand, 90)))
        m_rotate.addAction(self._act("Rotate 90° CC&W", None,
                                     lambda: self._image_cmd(RotateImageCommand, 270)))
        m_rotate.addAction(self._act("&Arbitrary…", None, self.action_rotate_arbitrary))
        m_rotate.addAction(self._act("Rotate &180°", None,
                                     lambda: self._image_cmd(RotateImageCommand, 180)))
        m_rotate.addSeparator()
        m_rotate.addAction(self._act("Flip Canvas &Horizontal", None,
                                     lambda: self._image_cmd(FlipImageCommand, True)))
        m_rotate.addAction(self._act("Flip Canvas &Vertical", None,
                                     lambda: self._image_cmd(FlipImageCommand, False)))

        m_layer = menu.addMenu("&Layer")
        m_layer.addAction(self._act("&New Layer", "Ctrl+Shift+N",
                                    lambda: self.layer_panel.add_layer()))
        m_layer.addAction(self._act("&Duplicate Layer", "Ctrl+J",
                                    lambda: self.layer_panel.duplicate_layer()))
        m_layer.addAction(self._act("Delete La&yer", None,
                                    lambda: self.layer_panel.delete_layer()))
        m_layer.addAction(self._act("Merge Do&wn", "Ctrl+E",
                                    lambda: self.layer_panel.merge_down()))
        m_layer.addAction(self._act("Merge &Visible", "Ctrl+Shift+E",
                                    self.action_merge_visible))
        m_layer.addAction(self._act("S&tamp Visible", "Ctrl+Shift+Alt+E",
                                    self.action_stamp_visible))
        m_layer.addSeparator()
        m_layer.addAction(self._act("Add Layer Mask (Reveal All)", None,
                                    lambda: self.action_add_mask(False)))
        m_layer.addAction(self._act("Add Layer Mask (From Selection)", None,
                                    lambda: self.action_add_mask(True)))
        m_layer.addAction(self._act("Apply Layer Mask", None, self.action_apply_mask))
        m_layer.addAction(self._act("Delete Layer Mask", None, self.action_delete_mask))
        m_layer.addAction(self._act("Clip to Layer Belo&w (toggle)", "Ctrl+Alt+G",
                                    self.action_toggle_clip))
        m_layer.addSeparator()
        m_layer.addAction(self._act("New Adjustment Layer: Le&vels…", None,
                                    self.action_adjustment_levels))
        m_layer.addSeparator()
        m_layer.addAction(self._act("Layer Style: Drop &Shadow…", None,
                                    self.action_drop_shadow))
        m_layer.addAction(self._act("Layer Style: Outer G&low…", None,
                                    self.action_outer_glow))
        m_layer.addAction(self._act("Layer Style: Strok&e…", None,
                                    self.action_stroke_style))
        m_layer.addAction(self._act("Layer Style: &Fill Opacity…", None,
                                    self.action_fill_opacity))
        m_layer.addAction(self._act("Layer Style: Clea&r", None,
                                    self.action_clear_style))
        m_layer.addSeparator()
        m_layer.addAction(self._act("&Group with Layer Below", "Ctrl+G",
                                    self.action_group_layer))
        m_layer.addAction(self._act("U&ngroup Layer", "Ctrl+Shift+G",
                                    self.action_ungroup_layer))
        m_layer.addAction(self._act("Group &Opacity/Blend…", None,
                                    self.action_group_props))
        m_layer.addSeparator()
        m_layer.addAction(self._act("Convert to Smart Ob&ject", None,
                                    self.action_convert_smart))
        m_layer.addAction(self._act("Restore Smart Object Or&iginal", None,
                                    self.action_restore_smart))
        m_layer.addAction(self._act("Re-apply Smart &Filters", None,
                                    self.action_reapply_smart_filters))
        m_layer.addSeparator()
        m_layer.addAction(self._act("&Copy Layer", "Ctrl+Shift+C", self.action_copy_layer))
        m_layer.addAction(self._act("&Paste Layer", "Ctrl+Shift+V", self.action_paste_layer))
        m_layer.addSeparator()
        m_layer.addAction(self._act("Raise Layer", "Ctrl+]",
                                    lambda: self.layer_panel.shift_layer(+1)))
        m_layer.addAction(self._act("Lower Layer", "Ctrl+[",
                                    lambda: self.layer_panel.shift_layer(-1)))
        m_layer.addSeparator()
        m_layer.addAction(self._act("Rotate Layer 90° CW", None,
                                    lambda: self._layer_cmd(RotateLayerCommand, 90)))
        m_layer.addAction(self._act("Rotate Layer 90° CCW", None,
                                    lambda: self._layer_cmd(RotateLayerCommand, 270)))
        m_layer.addAction(self._act("Rotate Layer 180°", None,
                                    lambda: self._layer_cmd(RotateLayerCommand, 180)))
        m_layer.addAction(self._act("Flip Layer Horizontal", None,
                                    lambda: self._layer_cmd(FlipLayerCommand, True)))
        m_layer.addAction(self._act("Flip Layer Vertical", None,
                                    lambda: self._layer_cmd(FlipLayerCommand, False)))

        m_view = menu.addMenu("&View")
        self.action_soft_proof = self._act("Soft &Proof", "Ctrl+Y",
                                           self._toggle_soft_proof)
        self.action_soft_proof.setCheckable(True)
        m_view.addAction(self.action_soft_proof)
        m_view.addSeparator()
        zoom_in = self._act("Zoom &In", "Ctrl++", lambda: self._zoom(+1))
        # a US keyboard's plus key is "=" unshifted — bind every physical form
        zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+="),
                              QKeySequence("Ctrl+Shift+=")])
        m_view.addAction(zoom_in)
        zoom_out = self._act("Zoom &Out", "Ctrl+-", lambda: self._zoom(-1))
        zoom_out.setShortcuts([QKeySequence("Ctrl+-"),
                               QKeySequence("Ctrl+Shift+-")])
        m_view.addAction(zoom_out)
        m_view.addAction(self._act("Zoom &100%", "Ctrl+1", lambda: self._zoom_to(1.0)))
        m_view.addAction(self._act("Zoom to &Fit", "Ctrl+0", self._zoom_fit))
        m_view.addSeparator()
        m_units = m_view.addMenu("&Units")
        unit_group = QActionGroup(self)
        self._unit_actions = {}
        for u in units.UNITS:
            act = QAction(units.unit_label(u), self)
            act.setCheckable(True)
            act.setChecked(u == self.unit)
            act.triggered.connect(lambda _=False, uu=u: self.set_unit(uu))
            unit_group.addAction(act)
            m_units.addAction(act)
            self._rulers_menu.addAction(act)  # same action: Edit → Options → Rulers
            self._unit_actions[u] = act
        m_view.addSeparator()
        self._grid_action = QAction("Show &Grid", self)
        self._grid_action.setCheckable(True)
        self._grid_action.setChecked(self.show_grid)
        self._grid_action.setShortcut(QKeySequence("Ctrl+'"))
        self._grid_action.toggled.connect(self._toggle_grid)
        m_view.addAction(self._grid_action)
        self._snap_action = QAction("S&nap", self)
        self._snap_action.setCheckable(True)
        self._snap_action.setChecked(self.snap_enabled)
        self._snap_action.setShortcut(QKeySequence("Ctrl+Shift+;"))
        self._snap_action.toggled.connect(self._toggle_snap)
        m_view.addAction(self._snap_action)
        m_view.addAction(self._act("Add Horizontal Guide at Center", "Alt+Shift+H",
                                   lambda: self.action_add_center_guide("h")))
        m_view.addAction(self._act("Add Vertical Guide at Center", "Alt+Shift+V",
                                   lambda: self.action_add_center_guide("v")))
        m_view.addAction(self._act("Clear &Guides", None, self.action_clear_guides))
        m_view.addSeparator()
        m_view.addAction(self._act("Rotate Vie&w 90\u00b0 CW", "R",
                                   lambda: self.action_rotate_view(90)))
        m_view.addAction(self._act("Rotate View 90\u00b0 CC&W", "Shift+R",
                                   lambda: self.action_rotate_view(-90)))
        m_view.addAction(self._act("Reset View Rotation", None,
                                   self.action_reset_view_rotation))
        m_view.addSeparator()
        m_workspace = m_view.addMenu("&Workspace")
        m_workspace.addAction(self._act("&Save Workspace", None, self.save_workspace))
        m_workspace.addAction(self._act("&Restore Saved", None, self.restore_workspace))
        m_workspace.addAction(self._act("Reset to &Default", None, self.reset_workspace))

        m_filter = menu.addMenu("Fi&lter")
        m_filter.addAction(self._act("Gaussian &Blur…", None, self.action_gaussian_blur))
        m_filter.addAction(self._act("&Unsharp Mask…", None, self.action_unsharp_mask))
        m_filter.addAction(self._act("&Tilt-Shift…", None, self.action_tilt_shift))
        m_filter.addAction(self._act("&Lens Correction (EXIF)…", None,
                                     self.action_lens_correct))
        m_filter.addAction(self._act("Denoise (&Model)…", None,
                                     self.action_denoise_model))
        from photoslop.filters import available_filters

        plugins = available_filters()
        if plugins:
            m_filter.addSeparator()
            for fname in sorted(plugins):
                cls = plugins[fname]
                m_filter.addAction(self._act(
                    f"{cls.label}…", None,
                    lambda checked=False, c=cls: self.action_plugin_filter(c)))

        m_help = menu.addMenu("&Help")
        m_help.addAction(self._act("&About Photoslop", None, self.action_about,
                                   role=QAction.MenuRole.AboutRole))

    def _act(self, text: str, shortcut: str | None, slot,
             role: QAction.MenuRole | None = None,
             prerequisite: str | None = None) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        # On macOS Qt otherwise applies TextHeuristicRole, silently relocating
        # any item whose text looks like About/Quit/Preferences into the
        # application menu. Pass an explicit role to pin placement per-platform.
        if role is not None:
            act.setMenuRole(role)
        act.triggered.connect(slot)
        self.action_registry.register(act, text, shortcut, slot, prerequisite)
        return act

    def action_command_palette(self) -> None:
        self.action_registry.palette(self).exec()

    def action_cancel_tasks(self) -> None:
        self.task_service.cancel_all()

    def _on_task_added(self, handle) -> None:
        self.statusBar().showMessage(f"{handle.label}…")
        handle.progressChanged.connect(
            lambda percent, message, h=handle: self.statusBar().showMessage(
                f"{h.label}: {percent}%{(' — ' + message) if message else ''}"))
        handle.failed.connect(
            lambda error, h=handle: self.statusBar().showMessage(
                f"{h.label} failed: {error.splitlines()[-1]}", 8000))
        handle.cancelled.connect(
            lambda h=handle: self.statusBar().showMessage(f"{h.label} cancelled", 4000))
        self.action_registry.update()

    def _on_task_finished(self, handle) -> None:
        if not self.task_service.active and handle.state.value == "succeeded":
            self.statusBar().showMessage(f"{handle.label} complete", 3000)
        self.action_registry.update()

    # ------------------------------------------------------------------ status

    def _build_status_bar(self) -> None:
        self.pos_label = QLabel("")
        self.zoom_label = QLabel("100%")
        self.mem_label = QLabel("")
        for lbl in (self.pos_label, self.zoom_label, self.mem_label):
            self.statusBar().addPermanentWidget(lbl)
        self._mem_timer = QTimer(self)
        self._mem_timer.setInterval(1000)
        self._mem_timer.timeout.connect(self._update_mem)
        self._mem_timer.start()

    def show_mouse_pos(self, doc: Document, pos) -> None:
        if pos is None:
            self.pos_label.setText("")
            return
        x = units.format_value(pos.x(), self.unit, doc.dpi)
        y = units.format_value(pos.y(), self.unit, doc.dpi)
        self.pos_label.setText(f"{x}, {y} {self.unit}")

    def show_zoom(self, zoom: float) -> None:
        self.zoom_label.setText(f"{zoom * 100:.0f}%")

    def show_guide_value(self, orient: str, pos: float, dpi: float) -> None:
        axis = "Y" if orient == "h" else "X"
        value = units.format_value_precise(pos, self.unit, dpi)
        self.statusBar().showMessage(f"Guide {axis}: {value}", 2000)

    def _update_mem(self) -> None:
        doc = self.current_doc()
        if doc is None:
            self.mem_label.setText("")
        else:
            self.mem_label.setText(f"layers: {doc.memory_bytes() / 1048576:.1f} MB")

    # ------------------------------------------------------------------ documents

    def current_editor(self) -> EditorView | None:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, EditorView) else None

    def current_doc(self) -> Document | None:
        editor = self.current_editor()
        return editor.doc if editor is not None else None

    def add_document(self, doc: Document) -> None:
        editor = EditorView(doc, self)
        editor.canvas.refresh_cursor()
        index = self.tabs.addTab(editor, doc.name)
        self.undo_group.addStack(doc.undo_stack)
        doc.undo_stack.cleanChanged.connect(lambda _clean, d=doc: self._refresh_tab(d))
        self.tabs.setCurrentIndex(index)
        doc.selectionChanged.connect(self.action_registry.update)
        doc.structureChanged.connect(self.action_registry.update)
        self.action_registry.update()
        self.accessibility.apply()

    def _editor_for(self, doc: Document) -> EditorView | None:
        for i in range(self.tabs.count()):
            editor = self.tabs.widget(i)
            if isinstance(editor, EditorView) and editor.doc is doc:
                return editor
        return None

    def _refresh_tab(self, doc: Document) -> None:
        editor = self._editor_for(doc)
        if editor is None:
            return
        index = self.tabs.indexOf(editor)
        star = "" if doc.undo_stack.isClean() else "*"
        self.tabs.setTabText(index, doc.name + star)
        if editor is self.current_editor():
            self.setWindowTitle(f"{doc.name}{star} — Photoslop {__version__}")

    def _on_tab_changed(self, index: int) -> None:
        editor = self.current_editor()
        if editor is None:
            self.layer_panel.set_document(None)
            self.adjust_panel.set_document(None)
            self.properties_panel.set_document(None)
            self.setWindowTitle(f"Photoslop {__version__}")
            self.action_registry.update()
            return
        doc = editor.doc
        self.undo_group.setActiveStack(doc.undo_stack)
        self.layer_panel.set_document(doc)
        self.adjust_panel.set_document(doc)
        self.properties_panel.set_document(doc)
        self._refresh_tab(doc)
        self.show_zoom(editor.canvas.zoom)
        editor.sync_rulers()
        self.action_registry.update()

    def _on_tab_close(self, index: int) -> None:
        editor = self.tabs.widget(index)
        if not isinstance(editor, EditorView):
            return
        doc = editor.doc
        if doc.is_dirty():
            self.tabs.setCurrentIndex(index)
            answer = QMessageBox.question(
                self, "Unsaved changes",
                f"Save changes to {doc.name} before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
            )
            if answer == QMessageBox.StandardButton.Cancel:
                return
            if answer == QMessageBox.StandardButton.Save and not self._save_doc(doc):
                return
        self.undo_group.removeStack(doc.undo_stack)
        self.layer_panel.set_document(None)
        self.adjust_panel.set_document(None)
        self.tabs.removeTab(index)
        editor.deleteLater()

    def closeEvent(self, ev) -> None:
        for i in range(self.tabs.count()):
            editor = self.tabs.widget(i)
            if isinstance(editor, EditorView) and editor.doc.is_dirty():
                self.tabs.setCurrentIndex(i)
                answer = QMessageBox.question(
                    self, "Unsaved changes",
                    f"Save changes to {editor.doc.name} before quitting?",
                    QMessageBox.StandardButton.Save
                    | QMessageBox.StandardButton.Discard
                    | QMessageBox.StandardButton.Cancel,
                )
                if answer == QMessageBox.StandardButton.Cancel:
                    ev.ignore()
                    return
                if answer == QMessageBox.StandardButton.Save and not self._save_doc(editor.doc):
                    ev.ignore()
                    return
        self.settings.setValue("workspace/geometry", self.saveGeometry())
        ev.accept()

    # ------------------------------------------------------------------ file actions

    def _clip_size_hint(self) -> QSize | None:
        """The size of whatever image is on the clipboard, if any — so
        File→New can default to exactly what a paste will drop in."""
        if self.pixel_clip is not None:
            return self.pixel_clip[0].size()
        img = QGuiApplication.clipboard().image()
        return img.size() if not img.isNull() else None

    def action_new(self) -> None:
        dialog = NewDocumentDialog(self, initial_size=self._clip_size_hint())
        if dialog.exec():
            name, size, dpi, background = dialog.values()
            self.add_document(Document.new(size, dpi, name, background))

    def action_open(self) -> None:
        gui_thread = self.thread()
        for path in OpenImageDialog.get_paths(self):
            if is_raw_path(path):
                from photoslop.rawdialog import RawDevelopDialog

                dialog = RawDevelopDialog(path, self)
                values = dialog.values() if dialog.exec() else None

                def develop(context, source=path, params=values):
                    from photoslop.io_raw import develop_raw

                    context.progress(5, "Decoding RAW")
                    image = (develop_raw(source, **params) if params is not None
                             else load_raw(source))
                    doc = Document.from_image(image, os.path.basename(source), 72.0)
                    doc.moveToThread(gui_thread)
                    context.progress(100, "Developed")
                    return doc

                handle = self.task_service.submit(
                    "file.raw-develop", f"Develop {os.path.basename(path)}", develop,
                    512 * 1024 * 1024)
                handle.succeeded.connect(self.add_document)
                continue

            def operation(context, source=path):
                context.progress(5, "Reading")
                if source.lower().endswith(".ora"):
                    doc = load_ora(source)
                elif io_formats.is_extra_path(source):
                    image = io_formats.load_extra(source)
                    doc = Document.from_image(image, os.path.basename(source), 72.0)
                else:
                    image = QImage(source)
                    if image.isNull():
                        raise ValueError(f"Could not open {source}")
                    dpm = image.dotsPerMeterX()
                    dpi = round(dpm * 0.0254) if dpm > 0 else 72
                    doc = Document.from_image(image, os.path.basename(source), float(dpi))
                doc.moveToThread(gui_thread)
                context.progress(100, "Decoded")
                return doc

            handle = self.task_service.submit(
                "file.open", f"Open {os.path.basename(path)}", operation,
                256 * 1024 * 1024)
            handle.succeeded.connect(self.add_document)

    def open_path(self, path: str) -> bool:
        try:
            if path.lower().endswith(".ora"):
                doc = load_ora(path)
            elif is_raw_path(path):
                from photoslop.io_raw import probe_raw
                from photoslop.rawdialog import RawDevelopDialog

                probe_raw(path)  # junk raises -> graceful failure below
                dialog = RawDevelopDialog(path, self)
                # cancelled = camera defaults
                img = (dialog.developed() if dialog.exec()
                       else load_raw(path))
                doc = Document.from_image(img, os.path.basename(path), 72.0)
            elif io_formats.is_extra_path(path):
                if not io_formats.available(path):
                    self.statusBar().showMessage(io_formats.missing_hint(path), 8000)
                    return False
                img = io_formats.load_extra(path)
                if img is None or img.isNull():
                    self.statusBar().showMessage(f"Could not open {path}", 5000)
                    return False
                doc = Document.from_image(img, os.path.basename(path), 72.0)
            else:
                img = QImage(path)
                if img.isNull():
                    self.statusBar().showMessage(f"Could not open {path}", 5000)
                    return False
                dpm = img.dotsPerMeterX()
                dpi = round(dpm * 0.0254) if dpm > 0 else 72
                doc = Document.from_image(img, os.path.basename(path), float(dpi))
        except Exception as exc:  # zip/XML errors from damaged files
            self.statusBar().showMessage(f"Could not open {path}: {exc}", 8000)
            return False
        self.add_document(doc)
        return True

    def _save_doc(self, doc: Document, background: bool = False) -> bool:
        path = doc.path
        if path is None or not path.lower().endswith(".ora"):
            suggested = os.path.splitext(doc.name)[0] + ".ora"
            path, _ = QFileDialog.getSaveFileName(
                self, "Save as OpenRaster", suggested, "OpenRaster (*.ora)"
            )
            if not path:
                return False
            if not path.lower().endswith(".ora"):
                path += ".ora"
        if background:
            snapshot = snapshot_document(doc)
            undo_index = doc.undo_stack.index()
            estimated = max(doc.memory_bytes() * 2, 1)

            def operation(context):
                context.progress(5, "Encoding layers")
                save_ora(snapshot, path)
                context.progress(100, "Written")
                return path

            handle = self.task_service.submit("file.save", f"Save {os.path.basename(path)}",
                                              operation, estimated)

            def installed(saved_path):
                doc.path = saved_path
                doc.name = os.path.basename(saved_path)
                if doc.undo_stack.index() == undo_index:
                    doc.undo_stack.setClean()
                self._refresh_tab(doc)

            handle.succeeded.connect(installed)
            return True
        save_ora(doc, path)
        doc.path = path
        doc.name = os.path.basename(path)
        doc.undo_stack.setClean()
        self._refresh_tab(doc)
        self.statusBar().showMessage(f"Saved {path}", 4000)
        return True

    def action_save(self) -> None:
        doc = self.current_doc()
        if doc is not None:
            self._save_doc(doc, background=True)

    def action_save_as(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        old_path = doc.path
        doc.path = None
        if not self._save_doc(doc, background=True):
            doc.path = old_path

    def action_export(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        dialog = ExportDialog(doc, self)
        if not dialog.exec():
            return
        fmt = dialog.chosen_format()
        suffix = dialog.suggested_suffix()
        suggested = os.path.splitext(doc.name)[0] + suffix
        path, _ = QFileDialog.getSaveFileName(
            self, "Export As", suggested, f"{fmt} (*{suffix})")
        if not path:
            return
        if not path.lower().endswith(suffix):
            path += suffix
        from photoslop import color

        base = QImage(dialog._flat)
        if fmt in {"JPEG", "BMP"}:
            base = doc.flatten(QColor(255, 255, 255))
        size = dialog.export_size()
        quality = dialog.chosen_quality()
        snapshot = snapshot_document(doc)

        def operation(context):
            context.progress(10, "Scaling")
            img = (base if size == base.size() else base.scaled(
                size, Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            img.setDotsPerMeterX(round(snapshot.dpi / 0.0254))
            img.setDotsPerMeterY(round(snapshot.dpi / 0.0254))
            color.tag_for_export(img, snapshot)
            context.progress(60, "Encoding")
            if fmt in {"AVIF", "JPEG XL"}:
                ok = io_formats.save_extra(img, path, max(1, quality))
            else:
                ok = img.save(path, fmt, quality)
            if not ok:
                raise ValueError(f"Export failed: {path}")
            context.progress(100, "Written")
            return path

        self.task_service.submit(
            "file.export", f"Export {os.path.basename(path)}", operation,
            max(1, base.sizeInBytes() * 3))

    def action_close_tab(self) -> None:
        if self.tabs.count():
            self._on_tab_close(self.tabs.currentIndex())

    # ------------------------------------------------------------------ edit actions

    def _on_system_clipboard(self) -> None:
        if self._clip_from_us:
            self._clip_from_us = False
        else:
            self.pixel_clip = None  # a copy from another app wins

    def action_copy(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        if doc.selection is None:
            # whole layer: shared (copy-on-write) reference, zero pixel copies
            img = QImage(layer.image)
            origin = QPoint(layer.offset)
        else:
            region = doc.selection_bounds()
            if region is None:
                return
            img = blank_image(region.size())
            p = QPainter(img)
            p.setClipPath(doc.selection.translated(-region.x(), -region.y()))
            p.drawImage(layer.offset - region.topLeft(), layer.image)
            p.end()
            origin = region.topLeft()
        self.pixel_clip = (img, origin)
        self._clip_from_us = True
        QGuiApplication.clipboard().setImage(img)
        self.statusBar().showMessage("Copied", 2000)

    def action_cut(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        if doc.selection is None:
            self.statusBar().showMessage("Cut needs a selection", 4000)
            return
        self.action_copy()
        doc.undo_stack.beginMacro("Cut")
        self.action_delete_selection()
        doc.undo_stack.endMacro()

    def action_paste(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        if self.pixel_clip is not None:
            img, origin = self.pixel_clip
        else:
            img = QGuiApplication.clipboard().image()
            if img.isNull():
                return
            origin = QPoint(0, 0)
        if not QRect(origin, img.size()).intersects(doc.canvas_rect()):
            origin = QPoint(0, 0)
        layer = Layer("Pasted", img.convertToFormat(FORMAT), origin)
        doc.undo_stack.push(
            InsertLayerCommand(doc, doc.active_index + 1, layer, "Paste")
        )

    def action_delete_selection(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None or doc.selection is None:
            return
        layer = doc.active_layer
        region = doc.selection_bounds()
        if region is None:
            return
        region = region.intersected(layer.bounds())
        if region.isEmpty():
            return
        local = region.translated(-layer.offset)
        before = layer.image.copy(local)
        p = QPainter(layer.image)
        p.setClipPath(doc.selection.translated(-layer.offset.x(), -layer.offset.y()))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(local, Qt.GlobalColor.black)
        p.end()
        after = layer.image.copy(local)
        doc.undo_stack.push(
            LayerRegionCommand(doc, layer, local, before, after, "Delete Selection")
        )
        doc.notify_pixels(region)

    def _record_step(self, label: str, replay) -> None:
        if self.action_recording is not None:
            self.action_recording.append((label, replay))

    def _record_smart_filter(self, tag: tuple) -> None:
        """Filters applied to a smart-object layer stack up for re-apply."""
        doc = self.current_doc()
        layer = doc.active_layer if doc else None
        if (layer is not None and layer.source is not None
                and not getattr(self, "_replaying_smart", False)):
            layer.smart_filters.append(tag)

    def action_reapply_smart_filters(self) -> None:
        doc = self.current_doc()
        layer = doc.active_layer if doc else None
        if layer is None or layer.source is None:
            if doc is not None:
                self.statusBar().showMessage(
                    "Not a smart object — Convert to Smart Object first", 4000)
            return
        if not layer.smart_filters:
            self.statusBar().showMessage("No smart filters recorded", 4000)
            return
        doc.undo_stack.beginMacro("Re-apply Smart Filters")
        self._replaying_smart = True
        try:
            self.action_restore_smart()
            for tag in layer.smart_filters:
                kind, *params = tag
                if kind == "gaussian":
                    self.action_gaussian_blur_direct(*params)
                elif kind == "unsharp":
                    self.action_unsharp_direct(*params)
                elif kind == "tilt-shift":
                    self.apply_tilt_shift(doc, layer, *params)
                elif kind == "filter":
                    self.apply_plugin_filter(params[0], dict(params[1]))
        finally:
            self._replaying_smart = False
            doc.undo_stack.endMacro()
        self.statusBar().showMessage(
            f"Smart filters re-applied ({len(layer.smart_filters)})", 4000)

    def action_gaussian_blur_direct(self, radius: int) -> None:
        from photoslop import npimage

        self._run_filter("Gaussian Blur",
                         lambda img, m: npimage.gaussian_blur(img, radius, m))
        self._record_step(f"Gaussian Blur {radius}px",
                          lambda w: w.action_gaussian_blur_direct(radius))
        self._record_smart_filter(("gaussian", radius))

    def action_unsharp_direct(self, amount: int) -> None:
        from photoslop import npimage

        self._run_filter("Unsharp Mask",
                         lambda img, m: npimage.unsharp_mask(img, 4, amount / 100.0, m))
        self._record_step(f"Unsharp Mask {amount}%",
                          lambda w: w.action_unsharp_direct(amount))
        self._record_smart_filter(("unsharp", amount))

    def action_plugin_filter(self, cls) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from photoslop.filterdialog import FilterParamsDialog

        dialog = FilterParamsDialog(cls, self)
        if cls.params and not dialog.exec():
            return
        self.apply_plugin_filter(cls.name, dialog.values())

    def apply_plugin_filter(self, name: str, params: dict) -> None:
        """Run a registered filter plugin through the shared plumbing."""
        from photoslop.filters import available_filters

        cls = available_filters().get(name)
        if cls is None:
            self.statusBar().showMessage(f"Filter not installed: {name}", 5000)
            return
        self._run_filter(cls.label,
                         lambda img, m: cls().apply(img, params))
        self._record_step(f"{cls.label} {params}",
                          lambda w: w.apply_plugin_filter(name, params))
        self._record_smart_filter(("filter", name, tuple(sorted(params.items()))))

    def action_record_start(self) -> None:
        self.action_recording = []
        self.statusBar().showMessage(
            "Recording action — apply filters/adjustments, then Stop", 5000)

    def action_record_stop(self) -> None:
        if self.action_recording is None:
            return
        self.recorded_action = self.action_recording
        self.action_recording = None
        names = ", ".join(label for label, _fn in self.recorded_action) or "empty"
        self.statusBar().showMessage(
            f"Action recorded ({len(self.recorded_action)} steps): {names}", 6000)

    def action_play(self) -> None:
        doc = self.current_doc()
        if doc is None or not self.recorded_action:
            if doc is not None:
                self.statusBar().showMessage("No recorded action to play", 4000)
            return
        doc.undo_stack.beginMacro("Play Action")
        try:
            for _label, replay in self.recorded_action:
                replay(self)
        finally:
            doc.undo_stack.endMacro()
        self.statusBar().showMessage(
            f"Action played ({len(self.recorded_action)} steps)", 4000)

    def _run_filter(self, title: str, apply, force_sync: bool = False) -> None:
        """Shared filter plumbing: selection-aware, full undo step."""
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from photoslop import npimage

        layer = doc.active_layer
        mask = None
        weights = None
        if doc.selection is not None:
            if doc.selection_feather > 0:
                weights = npimage.feathered_weights(
                    doc.selection, layer.image.size(), layer.offset,
                    doc.selection_feather)
            else:
                mask = npimage.selection_mask(doc.selection, layer.image.size(),
                                              layer.offset)
                if not mask.any():
                    mask = None
        before = QImage(layer.image)
        # Small operations remain immediate; large layers take the bounded COW
        # worker path so dialogs/tests stay deterministic without freezing real
        # camera-sized documents.
        estimated = max(1, before.sizeInBytes() * 3)
        if not force_sync and before.width() * before.height() >= 1_000_000:
            source_key = layer.image.cacheKey()

            def operation(context):
                context.progress(5, "Preparing snapshot")
                image = QImage(before)
                apply(image, mask)
                if weights is not None:
                    npimage.blend_by_weights(image, before, weights)
                context.progress(100, "Ready")
                return image

            handle = self.task_service.submit(
                f"filter.{title.lower().replace(' ', '-')}", title, operation, estimated)

            def install(image):
                if layer.image.cacheKey() != source_key:
                    self.statusBar().showMessage(
                        f"{title} result discarded because the layer changed", 6000)
                    return
                rect = image.rect()
                layer.image = image
                doc.undo_stack.push(LayerRegionCommand(
                    doc, layer, rect, before.copy(rect), image.copy(rect),
                    title, applied=True))
                doc.notify_pixels(layer.bounds())

            handle.succeeded.connect(install)
            return
        layer.image = QImage(before)  # fresh COW handle; filter write detaches
        apply(layer.image, mask)
        if weights is not None:
            npimage.blend_by_weights(layer.image, before, weights)
        rect = layer.image.rect()
        doc.undo_stack.push(LayerRegionCommand(
            doc, layer, rect, before.copy(rect), layer.image.copy(rect),
            title, applied=True))
        doc.notify_pixels(layer.bounds())

    def action_lens_correct(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        if not doc.path:
            self.statusBar().showMessage(
                "Lens correction reads EXIF from the opened file — "
                "save/open a camera file first", 6000)
            return
        from photoslop import lens

        try:
            corrected = lens.correct_lens(doc.active_layer.image, doc.path)
        except ValueError as exc:
            self.statusBar().showMessage(f"Lens correction: {exc}", 8000)
            return
        self._run_filter("Lens Correction", lambda img, m: (
            None, img.swap(corrected))[0])

    def action_denoise_model(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        adapter = self._model_adapter()
        if adapter is None:
            self.statusBar().showMessage(
                "Set a backend first: Edit → Options → Model Backend", 6000)
            return
        strength, ok = QInputDialog.getInt(self, "Denoise (Model)",
                                           "Strength (1–100):", 40, 1, 100)
        if not ok:
            return
        layer = doc.active_layer
        snapshot = QImage(layer.image)
        source_key = layer.image.cacheKey()

        def operation(context):
            context.progress(10, "Sending to backend")
            result = adapter.denoise(snapshot, strength)
            context.progress(100, "Received")
            return result.convertToFormat(snapshot.format())

        handle = self.task_service.submit(
            "model.denoise", "Denoise (Model)", operation, snapshot.sizeInBytes() * 3)

        def install(result):
            if layer.image.cacheKey() != source_key:
                self.statusBar().showMessage("Denoise result discarded after layer edit", 6000)
                return
            self._run_filter("Denoise (Model)",
                             lambda img, _mask: (None, img.swap(result))[0], True)

        handle.succeeded.connect(install)

    def action_gaussian_blur(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        radius, ok = QInputDialog.getInt(self, "Gaussian Blur", "Radius (px):",
                                         8, 1, 100)
        if not ok:
            return
        from photoslop import npimage

        self._run_filter("Gaussian Blur",
                         lambda img, m: npimage.gaussian_blur(img, radius, m))
        self._record_step(f"Gaussian Blur {radius}px",
                          lambda w: w.action_gaussian_blur_direct(radius))

    def action_unsharp_mask(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        amount, ok = QInputDialog.getInt(self, "Unsharp Mask", "Amount (%):",
                                         80, 10, 500)
        if not ok:
            return
        from photoslop import npimage

        self._run_filter("Unsharp Mask",
                         lambda img, m: npimage.unsharp_mask(img, 4, amount / 100.0, m))
        self._record_step(f"Unsharp Mask {amount}%",
                          lambda w: w.action_unsharp_direct(amount))

    def action_tilt_shift(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Tilt-Shift")
        form = QFormLayout(dialog)
        spins = {}
        h = layer.image.height()
        for key, lo, hi, default, suffix in (
                ("centre", 0, h, h // 2, " px"),
                ("band", 4, h, max(8, h // 4), " px sharp"),
                ("transition", 2, h, max(8, h // 6), " px"),
                ("radius", 2, 60, 12, " px blur")):
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(default)
            spin.setSuffix(suffix)
            form.addRow(key.capitalize(), spin)
            spins[key] = spin
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        self.apply_tilt_shift(doc, layer, spins["centre"].value(),
                              spins["band"].value(), spins["transition"].value(),
                              spins["radius"].value())

    def apply_tilt_shift(self, doc, layer, centre: int, band: int,
                         transition: int, radius: int) -> None:
        import numpy as np

        from photoslop import npimage

        before = QImage(layer.image)
        blurred = QImage(before)
        npimage.gaussian_blur(blurred, radius)

        h, w = layer.image.height(), layer.image.width()
        ys = np.abs(np.arange(h, dtype=np.float32) - centre)
        row_w = np.clip((ys - band / 2.0) / max(1, transition), 0.0, 1.0)
        weights = np.repeat(row_w[:, None], w, axis=1)
        npimage.blend_by_weights(blurred, before, weights)

        layer.image = blurred
        rect = layer.image.rect()
        doc.undo_stack.push(LayerRegionCommand(
            doc, layer, rect, before.copy(rect), blurred.copy(rect),
            "Tilt-Shift", applied=True))
        doc.notify_pixels(layer.bounds())
        self._record_step(
            f"Tilt-Shift {radius}px",
            lambda w: w.apply_tilt_shift(w.current_doc(),
                                         w.current_doc().active_layer,
                                         centre, band, transition, radius))
        if (layer.source is not None
                and not getattr(self, "_replaying_smart", False)):
            layer.smart_filters.append(
                ("tilt-shift", centre, band, transition, radius))

    def action_content_aware_fill(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        if doc.selection is None:
            self.statusBar().showMessage("Content-Aware Fill needs a selection", 4000)
            return
        from photoslop import npimage

        layer = doc.active_layer
        mask = npimage.selection_mask(doc.selection, layer.image.size(),
                                      layer.offset)
        if not mask.any():
            return
        before = QImage(layer.image)  # COW; first write below detaches
        dirty = npimage.inpaint_diffuse(layer.image, mask)
        doc.undo_stack.push(LayerRegionCommand(
            doc, layer, dirty, before.copy(dirty), layer.image.copy(dirty),
            "Content-Aware Fill", applied=True))
        doc.notify_pixels(dirty.translated(layer.offset))

    def action_define_pattern(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        region = doc.selection_bounds()
        if region is None:
            self.statusBar().showMessage("Define Pattern needs a selection", 4000)
            return
        self.options.pattern = doc.flatten().copy(region)
        self.statusBar().showMessage(
            f"Pattern defined: {region.width()}\u00d7{region.height()} px", 4000)

    def action_free_transform(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        tool = self.tools["transform"]
        if tool.session is not None:  # already transforming: commit instead
            editor = self.current_editor()
            tool.commit(editor.canvas if editor else None)
            return
        self._pre_transform_tool = self._active_tool_name
        tool.begin(doc, doc.active_layer)
        self._set_tool("transform")
        self.statusBar().showMessage(
            "Free Transform: drag inside to move, handles to scale, outside "
            "to rotate — Enter/double-click commits, Esc cancels", 6000)

    def action_warp(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        tool = self.tools["transform"]
        if tool.session is not None:
            tool.session.enter_warp()
            return
        self._pre_transform_tool = self._active_tool_name
        tool.begin(doc, doc.active_layer)
        tool.session.enter_warp()
        self._set_tool("transform")
        self.statusBar().showMessage(
            "Warp: drag the 3\u00d73 grid points — Enter commits, Esc cancels", 6000)

    def end_transform(self) -> None:
        """Called after a transform commit/cancel: restore the prior tool."""
        if self._active_tool_name == "transform":
            self._set_tool(self._pre_transform_tool)
            action = self._tool_actions.get(self._pre_transform_tool)
            if action is not None:
                action.setChecked(True)

    def action_feather_selection(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.selection is None:
            if doc is not None:
                self.statusBar().showMessage("Feather needs a selection", 4000)
            return
        from PySide6.QtWidgets import QInputDialog

        radius, ok = QInputDialog.getInt(
            self, "Feather Selection", "Feather radius (px):",
            max(1, int(doc.selection_feather)) or 8, 0, 100)
        if not ok:
            return
        doc.selection_feather = float(radius)
        self.statusBar().showMessage(
            f"Selection feathered {radius} px — filters and fills blend softly",
            5000)

    def action_refine_selection(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        if doc.selection is None:
            self.statusBar().showMessage("Refine Selection needs a selection", 4000)
            return
        from photoslop.refinedialog import RefineSelectionDialog

        RefineSelectionDialog(doc, self).exec()

    def action_select_all(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        path = QPainterPath()
        path.addRect(QRect(QPoint(0, 0), doc.size))
        doc.set_selection(path)

    def action_deselect(self) -> None:
        doc = self.current_doc()
        if doc is not None:
            doc.set_selection(None)

    # ------------------------------------------------------------------ layer clipboard

    def action_copy_layer(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        self.layer_clip = doc.active_layer.clone()
        self.statusBar().showMessage(f"Copied layer “{self.layer_clip.name}”", 3000)

    def action_paste_layer(self) -> None:
        doc = self.current_doc()
        if doc is None or self.layer_clip is None:
            return
        layer = self.layer_clip.clone()
        if not layer.bounds().intersects(doc.canvas_rect()):
            layer.offset = QPoint(0, 0)
        doc.undo_stack.push(
            InsertLayerCommand(doc, doc.active_index + 1, layer, "Paste Layer")
        )

    def action_add_mask(self, from_selection: bool) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        if from_selection and doc.selection is None:
            self.statusBar().showMessage("Add Mask From Selection needs a selection",
                                         4000)
            return
        mask = QImage(layer.image.size(), QImage.Format.Format_Grayscale8)
        if from_selection:
            mask.fill(0)
            p = QPainter(mask)
            p.fillPath(doc.selection.translated(-layer.offset.x(),
                                                -layer.offset.y()),
                       QColor(255, 255, 255))
            p.end()
        else:
            mask.fill(255)
        from photoslop.commands import SetLayerMaskCommand

        doc.undo_stack.push(SetLayerMaskCommand(doc, layer, mask, "Add Layer Mask"))

    def action_apply_mask(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None or doc.active_layer.mask is None:
            return
        from photoslop.commands import ApplyLayerMaskCommand

        doc.undo_stack.push(ApplyLayerMaskCommand(doc, doc.active_layer))

    def action_delete_mask(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None or doc.active_layer.mask is None:
            return
        from photoslop.commands import SetLayerMaskCommand

        doc.undo_stack.push(SetLayerMaskCommand(doc, doc.active_layer, None,
                                                "Delete Layer Mask"))

    def action_adjustment_levels(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        import numpy as np
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox

        from photoslop.adjust import levels_lut

        layer = Layer("Levels adjustment", blank_image(QSize(1, 1)))
        layer.adjustment = np.tile(np.arange(256, dtype=np.uint8), (3, 1))
        doc.undo_stack.push(InsertLayerCommand(
            doc, doc.active_index + 1, layer, "New Adjustment Layer"))

        dialog = QDialog(self)
        dialog.setWindowTitle("Levels (adjustment layer)")
        form = QFormLayout(dialog)
        spins = {}
        for key, lo, hi, default in (("in_black", 0, 253, 0), ("in_white", 2, 255, 255),
                                     ("gamma_x100", 10, 999, 100),
                                     ("out_black", 0, 255, 0), ("out_white", 0, 255, 255)):
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(default)
            form.addRow(key.replace("_", " "), spin)
            spins[key] = spin

        def refresh() -> None:
            lut = levels_lut(spins["in_black"].value(),
                             max(spins["in_white"].value(),
                                 spins["in_black"].value() + 2),
                             spins["gamma_x100"].value() / 100.0,
                             spins["out_black"].value(),
                             spins["out_white"].value())
            layer.adjustment = np.tile(lut, (3, 1))
            doc.notify_pixels(doc.canvas_rect())

        for spin in spins.values():
            spin.valueChanged.connect(lambda _v: refresh())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        refresh()
        if not dialog.exec():
            doc.undo_stack.undo()  # remove the inserted adjustment layer

    def action_drop_shadow(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Drop Shadow")
        form = QFormLayout(dialog)
        spins = {}
        for key, lo, hi, default, suffix in (
                ("offset_x", -50, 50, 6, " px"), ("offset_y", -50, 50, 6, " px"),
                ("blur", 0, 50, 8, " px"), ("opacity", 1, 100, 60, " %")):
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(default)
            spin.setSuffix(suffix)
            form.addRow(key.replace("_", " ").capitalize(), spin)
            spins[key] = spin
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        from photoslop.commands import SetLayerStyleCommand

        effect = ("drop-shadow", spins["offset_x"].value(),
                  spins["offset_y"].value(), spins["blur"].value(),
                  [0, 0, 0, round(spins["opacity"].value() * 2.55)])
        doc.undo_stack.push(SetLayerStyleCommand(
            doc, layer, [*layer.effects, effect], layer.fill_opacity,
            "Drop Shadow"))

    def apply_drop_shadow(self, doc, layer, dx: int, dy: int, blur: int,
                          opacity: int) -> None:
        from photoslop import npimage

        color = QColor(0, 0, 0, round(opacity * 2.55))
        shadow_img = npimage.drop_shadow_image(layer.image, color, blur)
        pad = max(0, blur)
        shadow = Layer(f"{layer.name} shadow", shadow_img,
                       layer.offset + QPoint(dx - pad, dy - pad))
        index = doc.layers.index(layer)
        doc.undo_stack.push(InsertLayerCommand(doc, index, shadow, "Drop Shadow"))

    def action_outer_glow(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        from PySide6.QtWidgets import QColorDialog, QInputDialog

        size, ok = QInputDialog.getInt(self, "Outer Glow", "Glow size (px):",
                                       10, 1, 50)
        if not ok:
            return
        color = QColorDialog.getColor(QColor(255, 220, 120), self, "Glow colour")
        if not color.isValid():
            return

        color.setAlpha(200)
        from photoslop.commands import SetLayerStyleCommand

        effect = ("glow", size, [color.red(), color.green(), color.blue(),
                                 color.alpha()])
        doc.undo_stack.push(SetLayerStyleCommand(
            doc, layer, [*layer.effects, effect], layer.fill_opacity,
            "Outer Glow"))

    def action_stroke_style(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        from PySide6.QtWidgets import QColorDialog, QInputDialog

        width, ok = QInputDialog.getInt(self, "Stroke", "Stroke width (px):",
                                        3, 1, 30)
        if not ok:
            return
        color = QColorDialog.getColor(self.options.foreground, self, "Stroke colour")
        if not color.isValid():
            return
        from photoslop.commands import SetLayerStyleCommand

        effect = ("stroke", width, [color.red(), color.green(), color.blue(),
                                    color.alpha()])
        doc.undo_stack.push(SetLayerStyleCommand(
            doc, layer, [*layer.effects, effect], layer.fill_opacity,
            "Stroke"))

    def apply_stroke_style(self, doc, layer, width: int, color) -> None:
        from photoslop import npimage

        outline = npimage.stroke_outline_image(layer.image, color, width)
        pad = max(1, width)
        stroke = Layer(f"{layer.name} stroke", outline,
                       layer.offset - QPoint(pad, pad))
        index = doc.layers.index(layer)
        doc.undo_stack.push(InsertLayerCommand(doc, index, stroke, "Stroke"))

    def action_group_layer(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None or doc.active_index == 0:
            return
        layer = doc.active_layer
        below = doc.layers[doc.active_index - 1]
        group = below.group
        if group is None:
            existing = {lyr.group for lyr in doc.layers if lyr.group}
            group = f"Group {len(existing) + 1}"
        from photoslop.commands import SetLayerGroupCommand

        doc.undo_stack.beginMacro("Group Layers")
        if below.group is None:
            doc.undo_stack.push(SetLayerGroupCommand(doc, below, group))
        doc.undo_stack.push(SetLayerGroupCommand(doc, layer, group))
        doc.undo_stack.endMacro()
        self.statusBar().showMessage(f"Grouped into “{group}”", 3000)

    def action_ungroup_layer(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None or doc.active_layer.group is None:
            return
        from photoslop.commands import SetLayerGroupCommand

        doc.undo_stack.push(SetLayerGroupCommand(doc, doc.active_layer, None))

    def action_add_artboard(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        bounds = doc.selection_bounds()
        if bounds is None or bounds.isEmpty():
            self.statusBar().showMessage(
                "Make a selection first — it becomes the artboard", 4000)
            return
        name = f"Artboard {len(doc.artboards) + 1}"
        doc.artboards.append((name, QRect(bounds)))
        doc.set_selection(None)
        self.statusBar().showMessage(
            f"{name}: {bounds.width()}×{bounds.height()} at "
            f"({bounds.x()}, {bounds.y()})", 4000)
        editor = self.current_editor()
        if editor is not None:
            editor.canvas.update()

    def action_clear_artboards(self) -> None:
        doc = self.current_doc()
        if doc is None or not doc.artboards:
            return
        doc.artboards.clear()
        self.statusBar().showMessage("Artboards cleared", 3000)
        editor = self.current_editor()
        if editor is not None:
            editor.canvas.update()

    def action_export_artboards(self, directory: str | None = None) -> list:
        doc = self.current_doc()
        if doc is None or not doc.artboards:
            if doc is not None:
                self.statusBar().showMessage("No artboards to export", 4000)
            return []
        if directory is None:
            from PySide6.QtWidgets import QFileDialog

            directory = QFileDialog.getExistingDirectory(
                self, "Export Artboards to Folder")
            if not directory:
                return []
        flat = doc.flatten()
        written = []
        for name, rect in doc.artboards:
            region = rect.intersected(doc.canvas_rect())
            if region.isEmpty():
                continue
            safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                           for c in name).strip() or "artboard"
            out = f"{directory}/{safe}.png"
            flat.copy(region).save(out, "PNG")
            written.append(out)
        self.statusBar().showMessage(
            f"Exported {len(written)} artboard(s) to {directory}", 5000)
        return written

    def _model_adapter(self):
        from PySide6.QtCore import QSettings

        from photoslop.modeladapter import create_adapter

        s = QSettings("CryptoJones", "Photoslop")
        name = s.value("model/adapter", "")
        if not name:
            return None
        return create_adapter(name, {"url": s.value("model/http_url", "")})

    def action_preferences(self) -> None:
        from photoslop.preferences import PreferencesDialog

        PreferencesDialog(self).exec()
        self.accessibility.apply()
        editor = self.current_editor()
        if editor is not None:  # colour settings may change the viewport
            editor.canvas.update()

    def action_generative_fill(self, prompt: str | None = None) -> None:
        from photoslop.modeladapter import GENERATIVE_FILL

        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        if doc.selection is None:
            self.statusBar().showMessage(
                "Make a selection — it becomes the fill region", 5000)
            return
        adapter = self._model_adapter()
        if adapter is None:
            self.statusBar().showMessage(
                "No model backend configured — Edit → Options → Model Backend…", 5000)
            return
        if GENERATIVE_FILL not in adapter.capabilities():
            self.statusBar().showMessage(
                f"“{adapter.label}” does not support Generative Fill", 5000)
            return
        if prompt is None:
            from PySide6.QtWidgets import QInputDialog

            prompt, ok = QInputDialog.getText(
                self, "Generative Fill", "Prompt (what should appear?):")
            if not ok:
                return
        import numpy as np

        from photoslop import npimage

        flat = doc.flatten()
        sel = npimage.selection_mask(doc.selection, doc.size, QPoint(0, 0))
        mask_img = QImage(doc.size, QImage.Format.Format_Grayscale8)
        mask_img.fill(0)
        buf = np.frombuffer(mask_img.bits(), np.uint8,
                            count=doc.size.height() * mask_img.bytesPerLine())
        view = buf.reshape(doc.size.height(), mask_img.bytesPerLine())
        view[:, : doc.size.width()][sel] = 255
        layer = doc.active_layer
        offset = QPoint(layer.offset)
        source_key = layer.image.cacheKey()

        def operation(context):
            context.progress(10, "Sending image and mask")
            result = adapter.generative_fill(flat, mask_img, prompt)
            if result.size() != doc.size:
                raise ValueError("Backend returned an image of the wrong size")
            context.progress(100, "Received")
            return result.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)

        handle = self.task_service.submit(
            "model.generative-fill", "Generative Fill", operation,
            max(1, flat.sizeInBytes() * 4))

        def install(result):
            if layer.image.cacheKey() != source_key:
                self.statusBar().showMessage(
                    "Generative Fill result discarded after layer edit", 6000)
                return

            def paste(img: QImage, mask) -> None:
                aligned = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
                aligned.fill(0)
                p = QPainter(aligned)
                p.drawImage(-offset, result)
                p.end()
                src = npimage.view_u32(aligned)
                dst = npimage.view_u32(img)
                if mask is None:
                    dst[:] = src
                else:
                    dst[mask] = src[mask]

            self._run_filter("Generative Fill", paste, True)

        handle.succeeded.connect(install)

    def action_select_subject(self) -> None:
        from photoslop.modeladapter import SELECT_SUBJECT

        doc = self.current_doc()
        if doc is None:
            return
        adapter = self._model_adapter()
        if adapter is None:
            self.statusBar().showMessage(
                "No model backend configured — Edit → Options → Model Backend…", 5000)
            return
        if SELECT_SUBJECT not in adapter.capabilities():
            self.statusBar().showMessage(
                f"“{adapter.label}” does not support Select Subject", 5000)
            return
        snapshot = doc.flatten()
        generation = tuple(layer.image.cacheKey() for layer in doc.layers)

        def operation(context):
            context.progress(10, "Sending composite")
            result = adapter.select_subject(snapshot)
            context.progress(100, "Received")
            return result

        handle = self.task_service.submit(
            "model.select-subject", "Select Subject", operation,
            max(1, snapshot.sizeInBytes() * 3))

        def install(mask_img):
            if generation != tuple(layer.image.cacheKey() for layer in doc.layers):
                self.statusBar().showMessage(
                    "Select Subject result discarded after document edit", 6000)
                return
            self._install_subject_mask(doc, mask_img)

        handle.succeeded.connect(install)

    def _install_subject_mask(self, doc, mask_img) -> None:
        import numpy as np

        from photoslop import npimage

        gray = mask_img.convertToFormat(QImage.Format.Format_Grayscale8)
        h, w = gray.height(), gray.width()
        buf = np.frombuffer(gray.constBits(), np.uint8,
                            count=h * gray.bytesPerLine())
        mask = buf.reshape(h, gray.bytesPerLine())[:, :w] > 127
        if not mask.any():
            self.statusBar().showMessage("Backend found no subject", 5000)
            return
        doc.set_selection(npimage.mask_to_path(mask))
        self.statusBar().showMessage("Subject selected", 3000)

    def action_fill_opacity(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from PySide6.QtWidgets import QInputDialog

        from photoslop.commands import SetLayerStyleCommand

        layer = doc.active_layer
        value, ok = QInputDialog.getInt(
            self, "Fill Opacity", "Fill opacity (%) — effects keep full "
            "strength:", round(layer.fill_opacity * 100), 0, 100)
        if not ok:
            return
        doc.undo_stack.push(SetLayerStyleCommand(
            doc, layer, layer.effects, value / 100.0, "Fill Opacity"))

    def action_clear_style(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        if not layer.effects and layer.fill_opacity == 1.0:
            return
        from photoslop.commands import SetLayerStyleCommand

        doc.undo_stack.push(SetLayerStyleCommand(
            doc, layer, [], 1.0, "Clear Layer Style"))

    def action_convert_smart(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        layer.source = QImage(layer.image)  # COW pristine snapshot
        doc.notify_structure()
        self.statusBar().showMessage(
            f"“{layer.name}” is now a smart object — its current pixels are "
            "the restorable original", 5000)

    def action_restore_smart(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        if layer.source is None:
            self.statusBar().showMessage(
                "Not a smart object — Convert to Smart Object first", 4000)
            return
        from photoslop.transform import TransformLayerCommand

        command = TransformLayerCommand(
            doc, layer, QImage(layer.image), QPoint(layer.offset),
            QImage(layer.source), QPoint(layer.offset))
        command.setText("Restore Smart Object")
        layer.image = QImage(layer.source)
        doc.undo_stack.push(command)
        doc.notify_pixels(doc.canvas_rect())

    def action_group_props(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None or not doc.active_layer.group:
            if doc is not None:
                self.statusBar().showMessage(
                    "Group Opacity/Blend needs a grouped layer (Ctrl+G)", 4000)
            return
        group = doc.active_layer.group
        current = doc.group_props.get(group, {})
        from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Group: {group}")
        form = QFormLayout(dialog)
        opacity = QSpinBox()
        opacity.setRange(0, 100)
        opacity.setValue(round(current.get("opacity", 1.0) * 100))
        opacity.setSuffix(" %")
        blend = QComboBox()
        blend.addItems(list(BLEND_MODES))
        blend.setCurrentText(current.get("blend_mode", "normal"))
        form.addRow("Group opacity", opacity)
        form.addRow("Group blend", blend)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        from photoslop.commands import SetGroupPropsCommand

        props = {"opacity": opacity.value() / 100.0,
                 "blend_mode": blend.currentText()}
        if props == {"opacity": 1.0, "blend_mode": "normal"}:
            props = None  # defaults: back to the pass-through fast path
        doc.undo_stack.push(SetGroupPropsCommand(doc, group, props))

    def action_toggle_clip(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None or doc.active_index == 0:
            return  # the bottom layer has nothing to clip to
        from photoslop.commands import SetLayerClippedCommand

        layer = doc.active_layer
        doc.undo_stack.push(SetLayerClippedCommand(doc, layer, not layer.clipped))

    def action_merge_visible(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        visible = [layer for layer in doc.layers if layer.visible]
        if len(visible) < 2:
            self.statusBar().showMessage("Merge Visible needs 2+ visible layers", 4000)
            return
        from photoslop.commands import MergeVisibleCommand

        doc.undo_stack.push(MergeVisibleCommand(doc))

    def action_stamp_visible(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        layer = Layer("Stamp", doc.flatten())
        doc.undo_stack.push(
            InsertLayerCommand(doc, len(doc.layers), layer, "Stamp Visible"))

    # ------------------------------------------------------------------ image actions

    def _image_cmd(self, command, arg) -> None:
        doc = self.current_doc()
        if doc is not None:
            doc.undo_stack.push(command(doc, arg))

    def _layer_cmd(self, command, arg) -> None:
        doc = self.current_doc()
        if doc is not None and doc.active_layer is not None:
            doc.undo_stack.push(command(doc, doc.active_layer, arg))

    def action_rotate_arbitrary(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        from PySide6.QtWidgets import QInputDialog

        angle, ok = QInputDialog.getDouble(
            self, "Rotate Canvas", "Angle (\u00b0 clockwise, negative = CCW):",
            0.0, -359.99, 359.99, 2)
        if not ok or angle == 0.0:
            return
        from photoslop.commands import ArbitraryRotateCommand

        doc.undo_stack.push(ArbitraryRotateCommand(doc, angle))

    def action_crop(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        region = doc.selection_bounds()
        if region is None:
            self.statusBar().showMessage("Crop needs a selection", 4000)
            return
        doc.undo_stack.push(
            ResizeCanvasCommand(doc, region.size(), -region.topLeft(), "Crop")
        )

    def action_levels(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from photoslop.levelsdialog import LevelsDialog

        LevelsDialog(doc, self).exec()

    def action_hue_saturation(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from photoslop.huesatdialog import HueSatDialog

        HueSatDialog(doc, self).exec()

    def action_point_color(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from photoslop.pointcolordialog import PointColorDialog

        PointColorDialog(doc, self).exec()

    def _toggle_soft_proof(self) -> None:
        from photoslop import color

        color.settings["proof_on"] = self.action_soft_proof.isChecked()
        if color.settings["proof_on"] and color.settings["proof"] is None:
            self.statusBar().showMessage(
                "Set a proof profile first: Preferences → Color",
                5000)
        editor = self.current_editor()
        if editor is not None:
            editor.canvas.update()

    def action_assign_profile(self) -> None:
        self._profile_action(assign=True)

    def action_convert_profile(self) -> None:
        self._profile_action(assign=False)

    def _profile_action(self, assign: bool) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        from photoslop import color
        from photoslop.colordialog import ProfilePickerDialog

        dialog = ProfilePickerDialog(
            "Assign Profile" if assign else "Convert to Profile", self)
        if not dialog.exec():
            return
        space = dialog.space()
        if space is None:
            return
        if assign:
            color.assign_profile(doc, space)
        else:
            color.convert_profile(doc, space)
        self.statusBar().showMessage(
            f"Document profile: {color.describe(doc.icc_space)}", 4000)

    def action_curves(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from photoslop.curvesdialog import CurvesDialog

        CurvesDialog(doc, self).exec()

    def action_color_balance(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        from photoslop.colorbalancedialog import ColorBalanceDialog

        ColorBalanceDialog(doc, self).exec()

    def action_content_aware_scale(self) -> None:
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QSpinBox

        dialog = QDialog(self)
        dialog.setWindowTitle("Content-Aware Scale")
        form = QFormLayout(dialog)
        w_spin = QSpinBox()
        w_spin.setRange(2, 4 * layer.image.width())
        w_spin.setValue(layer.image.width())
        w_spin.setSuffix(" px")
        h_spin = QSpinBox()
        h_spin.setRange(2, 4 * layer.image.height())
        h_spin.setValue(layer.image.height())
        h_spin.setSuffix(" px")
        form.addRow("Target width", w_spin)
        form.addRow("Target height", h_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if not dialog.exec():
            return
        target_w, target_h = w_spin.value(), h_spin.value()
        if (target_w, target_h) == (layer.image.width(), layer.image.height()):
            return
        self.apply_content_aware_scale(doc, layer, target_w, target_h)

    def apply_content_aware_scale(self, doc, layer, target_w: int,
                                  target_h: int) -> None:
        from photoslop import npimage
        from photoslop.transform import TransformLayerCommand

        old_image = QImage(layer.image)
        carved = npimage.seam_carve(layer.image, target_w, target_h)
        dirty = layer.bounds()
        layer.image = carved
        cmd = TransformLayerCommand(
            doc, layer, old_image, layer.offset, QImage(carved), layer.offset)
        cmd.setText("Content-Aware Scale")
        doc.undo_stack.push(cmd)
        doc.notify_pixels(dirty)

    def action_image_size(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        dialog = ResizeImageDialog(doc.size, self)
        if dialog.exec() and dialog.value() != doc.size:
            doc.undo_stack.push(ResizeImageCommand(doc, dialog.value()))

    def action_canvas_size(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        dialog = CanvasSizeDialog(doc.size, self)
        if dialog.exec():
            new_size, delta = dialog.value()
            if new_size != doc.size:
                doc.undo_stack.push(ResizeCanvasCommand(doc, new_size, delta))

    # ------------------------------------------------------------------ view actions

    def _zoom(self, direction: int) -> None:
        editor = self.current_editor()
        if editor is not None:
            editor.zoom_step(direction)

    def _zoom_to(self, zoom: float) -> None:
        editor = self.current_editor()
        if editor is not None:
            editor.set_zoom(zoom)

    def _zoom_fit(self) -> None:
        editor = self.current_editor()
        if editor is not None:
            editor.zoom_fit()

    def set_unit(self, unit: str) -> None:
        self.unit = unit
        self.settings.setValue("units", unit)
        self._unit_actions[unit].setChecked(True)
        for i in range(self.tabs.count()):
            editor = self.tabs.widget(i)
            if isinstance(editor, EditorView):
                editor.sync_rulers()

    def _toggle_grid(self, checked: bool) -> None:
        self.show_grid = checked
        self.settings.setValue("grid", "true" if checked else "false")
        for i in range(self.tabs.count()):
            editor = self.tabs.widget(i)
            if isinstance(editor, EditorView):
                editor.canvas.update()

    def _toggle_snap(self, checked: bool) -> None:
        self.snap_enabled = checked
        self.settings.setValue("snap", "true" if checked else "false")

    def action_rotate_view(self, delta: int) -> None:
        editor = self.current_editor()
        if editor is None:
            return
        editor.canvas.rotate_view(delta)
        rotation = editor.canvas.view_rotation
        self.statusBar().showMessage(
            f"View rotated {rotation}\u00b0 (display only \u2014 pixels untouched; "
            "rulers show unrotated space)", 4000)

    def action_reset_view_rotation(self) -> None:
        editor = self.current_editor()
        if editor is not None and editor.canvas.view_rotation:
            editor.canvas.rotate_view(-editor.canvas.view_rotation)

    def save_workspace(self) -> None:
        self.settings.setValue("workspace/state", self.saveState())
        self.settings.setValue("workspace/geometry", self.saveGeometry())
        self.statusBar().showMessage("Workspace saved", 3000)

    def restore_workspace(self) -> None:
        saved = self.settings.value("workspace/state")
        if saved is not None:
            self.restoreState(saved)
            self.statusBar().showMessage("Workspace restored", 3000)
        else:
            self.statusBar().showMessage("No saved workspace yet", 3000)

    def reset_workspace(self) -> None:
        self.restoreState(self._default_workspace)
        self.statusBar().showMessage("Workspace reset to default", 3000)

    def action_clear_guides(self) -> None:
        doc = self.current_doc()
        if doc is not None:
            doc.clear_guides()

    def action_add_center_guide(self, orientation: str) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        pos = doc.size.height() / 2 if orientation == "h" else doc.size.width() / 2
        doc.add_guide(orientation, pos)
        axis = "horizontal" if orientation == "h" else "vertical"
        self.statusBar().showMessage(f"Added {axis} guide at center", 3000)

    def action_fill_layer(self) -> None:
        """Fill the whole active layer with the foreground colour."""
        doc = self.current_doc()
        if doc is None or doc.active_layer is None:
            return
        layer = doc.active_layer
        before = QImage(layer.image)
        filled = QImage(layer.image.size(),
                        QImage.Format.Format_ARGB32_Premultiplied)
        filled.fill(self.options.foreground)
        layer.image = filled
        rect = layer.image.rect()
        doc.undo_stack.push(LayerRegionCommand(
            doc, layer, rect, before.copy(rect), filled.copy(rect),
            "Fill Layer", applied=True))
        doc.notify_pixels(layer.bounds())

    def _build_about(self) -> QMessageBox:
        from photoslop.appicon import mascot_pixmap

        box = QMessageBox(self)
        box.setWindowTitle("About Photoslop")
        # Le Basilisk himself — the QPainter original, not the FLUX render
        box.setIconPixmap(mascot_pixmap(128))
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(
            f"<h3>Photoslop {__version__}</h3>"
            "<p>A memory-frugal, multiplatform, layered raster image editor.</p>"
            "<p>Apache-2.0 · <a href='https://github.com/CryptoJones/Photoslop'>"
            "github.com/CryptoJones/Photoslop</a></p>"
            "<p>Proudly Made in Nebraska. Go Big Red! 🌽</p>")
        ok = box.addButton(QMessageBox.StandardButton.Ok)
        credits = box.addButton("&Credits",
                                QMessageBox.ButtonRole.ActionRole)
        credits.clicked.connect(self.action_credits)
        # place Credits immediately left of OK regardless of platform style
        from PySide6.QtWidgets import QDialogButtonBox

        row = box.findChild(QDialogButtonBox).layout()
        row.removeWidget(credits)
        row.removeWidget(ok)
        row.addWidget(credits)
        row.addWidget(ok)
        return box

    def action_about(self) -> None:
        self._build_about().exec()

    def action_credits(self) -> None:
        QMessageBox.information(self, "Credits", CREDITS_TEXT)

    # ------------------------------------------------------------------ drag & drop

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        for url in ev.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())
