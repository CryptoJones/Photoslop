# SPDX-License-Identifier: Apache-2.0
"""Main window: tabs of documents, tool/options toolbars, layer panel dock,
menus, clipboards (pixel + layer, both cross-document), status bar."""

from __future__ import annotations

import os

from PySide6.QtCore import QPoint, QRect, QSettings, Qt, QTimer
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
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
    QUndoView,
)

from photoslop import __version__, units
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
from photoslop.icons import TOOL_ICONS
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import FORMAT, Layer, blank_image
from photoslop.opendialog import OpenImageDialog
from photoslop.tools import (
    BrushTool,
    BucketTool,
    BurnTool,
    CloneStampTool,
    CropTool,
    DodgeTool,
    EraserTool,
    EyedropperTool,
    GradientTool,
    HandTool,
    HealBrushTool,
    LassoTool,
    MagicWandTool,
    MagneticLassoTool,
    MoveTool,
    PatchTool,
    PencilTool,
    PolyLassoTool,
    QuickSelectTool,
    RectSelectTool,
    SmudgeTool,
    SpotHealTool,
    TextTool,
    ToolOptions,
    ZoomTool,
)
from photoslop.transform import TransformTool


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Photoslop {__version__}")
        self.settings = QSettings("CryptoJones", "Photoslop")
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
                TextTool(self.options),
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

        self.adjust_panel = AdjustPanel()
        self._adjust_dock = QDockWidget("Adjust")
        self._adjust_dock.setObjectName("adjust-dock")
        self._adjust_dock.setWidget(self.adjust_panel)
        self._adjust_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._adjust_dock)
        self.tabifyDockWidget(self._layers_dock, self._adjust_dock)

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
        self._sync_option_visibility()

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
        shortcuts = {
            "brush": "B", "pencil": "Shift+B", "eraser": "E",
            "bucket": "G (cycles)", "gradient": "Shift+G",
            "eyedropper": "I", "rect-select": "M", "lasso": "L",
            "poly-lasso": "Shift+L", "magnetic-lasso": "Alt+L",
            "wand": "W", "quick-select": "Shift+W",
            "clone-stamp": "S", "smudge": "Shift+S", "spot-heal": "J",
            "heal": "Shift+J", "patch": "Alt+Shift+J", "text": "T",
            "dodge": "O", "burn": "Shift+O", "crop": "C",
            "move": "V", "hand": "H", "zoom": "Z",
        }
        labels = {
            "brush": "Brush", "pencil": "Pencil", "eraser": "Eraser",
            "bucket": "Paint Bucket",
            "gradient": "Gradient", "eyedropper": "Eyedropper",
            "rect-select": "Rectangle Select",
            "lasso": "Lasso Select", "poly-lasso": "Polygonal Lasso",
            "magnetic-lasso": "Magnetic Lasso (edges attract the path)",
            "wand": "Magic Wand", "quick-select": "Quick Selection",
            "clone-stamp": "Clone Stamp (Alt+click sets source)",
            "smudge": "Smudge / Mixer (drags colour)",
            "spot-heal": "Spot Healing (paint a blemish)",
            "heal": "Healing Brush (Alt+click source, tone-matched)",
            "patch": "Patch (drag a selection to its source)",
            "text": "Text (click to place)",
            "dodge": "Dodge (lighten)", "burn": "Burn (darken)",
            "crop": "Crop (drag, Enter commits)",
            "move": "Move", "hand": "Hand (pan)", "zoom": "Zoom",
        }
        self._tool_actions = {}
        for name in ("brush", "pencil", "eraser", "bucket", "gradient", "eyedropper",
                     "rect-select", "lasso", "poly-lasso", "magnetic-lasso", "wand",
                     "quick-select", "clone-stamp", "smudge", "spot-heal", "heal",
                     "patch", "text",
                     "dodge", "burn", "crop",
                     "move", "hand", "zoom"):
            act = QAction(TOOL_ICONS[name](), labels[name], self)
            act.setCheckable(True)
            if " " not in shortcuts[name]:
                act.setShortcut(shortcuts[name])
            act.setToolTip(f"{labels[name]} ({shortcuts[name]})")
            act.triggered.connect(lambda _=False, n=name: self._set_tool(n))
            group.addAction(act)
            bar.addAction(act)
            self._tool_actions[name] = act
        self._tool_actions["brush"].setChecked(True)

        from PySide6.QtGui import QShortcut

        cycle = QShortcut(QKeySequence("G"), self)
        cycle.activated.connect(self._cycle_fill_tool)

    def _cycle_fill_tool(self) -> None:
        """G cycles Bucket <-> Gradient, PS-style same-key tool groups."""
        name = "gradient" if self._active_tool_name == "bucket" else "bucket"
        self._set_tool(name)
        self._tool_actions[name].setChecked(True)

    def _set_tool(self, name: str) -> None:
        self._active_tool_name = name
        self._sync_option_visibility()
        for i in range(self.tabs.count()):
            editor = self.tabs.widget(i)
            editor.canvas.setCursor(self.active_tool.cursor)
            editor.canvas.update()

    def _build_options_bar(self) -> None:
        bar = QToolBar("Tool Options")
        bar.setObjectName("tool-options")
        bar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, bar)
        self._option_actions: dict[str, list] = {}

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
        size.valueChanged.connect(lambda v: setattr(self.options, "size", v))
        size_act = bar.addWidget(size)
        self._size_spin = size

        hardness = QSpinBox()
        hardness.setRange(0, 100)
        hardness.setValue(self.options.hardness)
        hardness.setSuffix("% hard")
        hardness.setToolTip("Brush hardness")
        hardness.valueChanged.connect(lambda v: setattr(self.options, "hardness", v))
        hard_act = bar.addWidget(hardness)
        self._hardness_spin = hardness

        opacity = QSpinBox()
        opacity.setRange(1, 100)
        opacity.setValue(self.options.opacity)
        opacity.setSuffix("% opacity")
        opacity.setToolTip("Paint opacity")
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
        tolerance.valueChanged.connect(lambda v: setattr(self.options, "tolerance", v))
        tol_act = bar.addWidget(tolerance)

        shape = QComboBox()
        shape.addItems(["linear", "radial"])
        shape.setToolTip("Gradient shape")
        shape.currentTextChanged.connect(
            lambda v: setattr(self.options, "gradient_shape", v))
        shape_act = bar.addWidget(shape)

        flow = QSpinBox()
        flow.setRange(1, 100)
        flow.setValue(self.options.flow)
        flow.setSuffix("% flow")
        flow.setToolTip("Paint per stamp; opacity caps the whole stroke")
        flow.valueChanged.connect(lambda v: setattr(self.options, "flow", v))
        flow_act = bar.addWidget(flow)

        scatter = QSpinBox()
        scatter.setRange(0, 200)
        scatter.setValue(self.options.scatter)
        scatter.setSuffix("% scatter")
        scatter.setToolTip("Random stamp offset as % of brush size")
        scatter.valueChanged.connect(lambda v: setattr(self.options, "scatter", v))
        scatter_act = bar.addWidget(scatter)

        spacing = QSpinBox()
        spacing.setRange(5, 200)
        spacing.setValue(self.options.spacing)
        spacing.setSuffix("% gap")
        spacing.setToolTip("Stamp spacing as % of brush size (soft strokes)")
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
            "text": [color_act],
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

    def _sync_option_visibility(self) -> None:
        visible = set(self._option_actions[self._active_tool_name])
        for act in self._all_option_actions:
            act.setVisible(act in visible)

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
        m_file.addAction(self._act("&Quit", "Ctrl+Q", self.close))

        m_edit = menu.addMenu("&Edit")
        undo = self.undo_group.createUndoAction(self, "&Undo ")
        undo.setShortcut(QKeySequence.StandardKey.Undo)
        redo = self.undo_group.createRedoAction(self, "&Redo ")
        redo.setShortcuts([QKeySequence("Ctrl+Shift+Z"), QKeySequence("Ctrl+Y")])
        m_edit.addAction(undo)
        m_edit.addAction(redo)
        m_edit.addSeparator()
        m_edit.addAction(self._act("&Copy Selection", "Ctrl+C", self.action_copy))
        m_edit.addAction(self._act("&Paste as New Layer", "Ctrl+V", self.action_paste))
        m_edit.addAction(self._act("&Delete Selection", "Del", self.action_delete_selection))
        m_edit.addSeparator()
        m_edit.addAction(self._act("Select &All", "Ctrl+A", self.action_select_all))
        m_edit.addAction(self._act("&Refine Selection…", "Ctrl+Alt+R",
                                   self.action_refine_selection))
        m_edit.addAction(self._act("D&eselect", "Ctrl+D", self.action_deselect))
        m_edit.addSeparator()
        m_edit.addAction(self._act("Fill Selection (Content-&Aware)", "Shift+F5",
                                   self.action_content_aware_fill))
        m_edit.addAction(self._act("Define &Pattern from Selection", None,
                                   self.action_define_pattern))
        m_edit.addSeparator()
        m_edit.addAction(self._act("Free &Transform", "Ctrl+T", self.action_free_transform))
        m_edit.addSeparator()
        m_edit.addAction(self._act("S&wap Colours", "X", self.action_swap_colors))
        m_edit.addAction(self._act("Rese&t Colours", "D", self.action_reset_colors))
        m_edit.addSeparator()
        self._options_menu = m_edit.addMenu("&Options")
        self._rulers_menu = self._options_menu.addMenu("&Rulers")  # unit actions added below

        m_image = menu.addMenu("&Image")
        m_image.addAction(self._act("&Image Size…", "Ctrl+Alt+I", self.action_image_size))
        m_image.addAction(self._act("&Canvas Size…", "Ctrl+Alt+S", self.action_canvas_size))
        m_image.addAction(self._act("Content-A&ware Scale…", None,
                                    self.action_content_aware_scale))
        m_image.addAction(self._act("C&rop to Selection", "Ctrl+Alt+C", self.action_crop))
        m_image.addSeparator()
        m_adjustments = m_image.addMenu("&Adjustments")
        m_adjustments.addAction(self._act("&Levels…", "Ctrl+L", self.action_levels))
        m_adjustments.addAction(self._act("&Hue/Saturation…", "Ctrl+U",
                                          self.action_hue_saturation))
        m_adjustments.addAction(self._act("Color &Balance…", "Ctrl+B",
                                          self.action_color_balance))
        m_adjustments.addAction(self._act("Cur&ves…", "Ctrl+M", self.action_curves))
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
        m_layer.addAction(self._act("Layer Style: Drop &Shadow…", None,
                                    self.action_drop_shadow))
        m_layer.addAction(self._act("Layer Style: Outer G&low…", None,
                                    self.action_outer_glow))
        m_layer.addAction(self._act("Layer Style: Strok&e…", None,
                                    self.action_stroke_style))
        m_layer.addSeparator()
        m_layer.addAction(self._act("&Group with Layer Below", "Ctrl+G",
                                    self.action_group_layer))
        m_layer.addAction(self._act("U&ngroup Layer", "Ctrl+Shift+G",
                                    self.action_ungroup_layer))
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
        m_view.addAction(self._act("Zoom &In", "Ctrl++", lambda: self._zoom(+1)))
        m_view.addAction(self._act("Zoom &Out", "Ctrl+-", lambda: self._zoom(-1)))
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

        m_help = menu.addMenu("&Help")
        m_help.addAction(self._act("&About Photoslop", None, self.action_about))

    def _act(self, text: str, shortcut: str | None, slot) -> QAction:
        act = QAction(text, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(slot)
        return act

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
        editor.canvas.setCursor(self.active_tool.cursor)
        index = self.tabs.addTab(editor, doc.name)
        self.undo_group.addStack(doc.undo_stack)
        doc.undo_stack.cleanChanged.connect(lambda _clean, d=doc: self._refresh_tab(d))
        self.tabs.setCurrentIndex(index)

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
            self.setWindowTitle(f"Photoslop {__version__}")
            return
        doc = editor.doc
        self.undo_group.setActiveStack(doc.undo_stack)
        self.layer_panel.set_document(doc)
        self.adjust_panel.set_document(doc)
        self._refresh_tab(doc)
        self.show_zoom(editor.canvas.zoom)
        editor.sync_rulers()

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

    def action_new(self) -> None:
        dialog = NewDocumentDialog(self)
        if dialog.exec():
            name, size, dpi, background = dialog.values()
            self.add_document(Document.new(size, dpi, name, background))

    def action_open(self) -> None:
        for path in OpenImageDialog.get_paths(self):
            self.open_path(path)

    def open_path(self, path: str) -> bool:
        try:
            if path.lower().endswith(".ora"):
                doc = load_ora(path)
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

    def _save_doc(self, doc: Document) -> bool:
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
            self._save_doc(doc)

    def action_save_as(self) -> None:
        doc = self.current_doc()
        if doc is None:
            return
        old_path = doc.path
        doc.path = None
        if not self._save_doc(doc):
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
        img = dialog.export_image()
        img.setDotsPerMeterX(round(doc.dpi / 0.0254))
        img.setDotsPerMeterY(round(doc.dpi / 0.0254))
        if img.save(path, fmt, dialog.chosen_quality()):
            self.statusBar().showMessage(f"Exported {path}", 4000)
        else:
            self.statusBar().showMessage(f"Export failed: {path}", 6000)

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

    def end_transform(self) -> None:
        """Called after a transform commit/cancel: restore the prior tool."""
        if self._active_tool_name == "transform":
            self._set_tool(self._pre_transform_tool)
            action = self._tool_actions.get(self._pre_transform_tool)
            if action is not None:
                action.setChecked(True)

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
        self.apply_drop_shadow(doc, layer, spins["offset_x"].value(),
                               spins["offset_y"].value(), spins["blur"].value(),
                               spins["opacity"].value())

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
        from photoslop import npimage

        color.setAlpha(200)
        glow_img = npimage.drop_shadow_image(layer.image, color, size)
        glow = Layer(f"{layer.name} glow", glow_img,
                     layer.offset - QPoint(size, size))
        index = doc.layers.index(layer)
        doc.undo_stack.push(InsertLayerCommand(doc, index, glow, "Outer Glow"))

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
        self.apply_stroke_style(doc, layer, width, color)

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
        dialog.setWindowTitle("Content-Aware Scale (shrink)")
        form = QFormLayout(dialog)
        w_spin = QSpinBox()
        w_spin.setRange(2, layer.image.width())
        w_spin.setValue(layer.image.width())
        w_spin.setSuffix(" px")
        h_spin = QSpinBox()
        h_spin.setRange(2, layer.image.height())
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

    def action_about(self) -> None:
        QMessageBox.about(
            self, "About Photoslop",
            f"<h3>Photoslop {__version__}</h3>"
            "<p>A memory-frugal, multiplatform, layered raster image editor.</p>"
            "<p>Apache-2.0 · <a href='https://github.com/CryptoJones/Photoslop'>"
            "github.com/CryptoJones/Photoslop</a></p>"
            "<p>Proudly Made in Nebraska. Go Big Red! 🌽</p>",
        )

    # ------------------------------------------------------------------ drag & drop

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        for url in ev.mimeData().urls():
            if url.isLocalFile():
                self.open_path(url.toLocalFile())
