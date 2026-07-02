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
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QToolBar,
    QToolButton,
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
from photoslop.icons import TOOL_ICONS
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import FORMAT, Layer, blank_image
from photoslop.opendialog import OpenImageDialog
from photoslop.tools import (
    BrushTool,
    BucketTool,
    EyedropperTool,
    HandTool,
    LassoTool,
    MoveTool,
    RectSelectTool,
    ToolOptions,
    ZoomTool,
)

_EXPORT_FILTER = "PNG (*.png);;JPEG (*.jpg *.jpeg);;WebP (*.webp);;BMP (*.bmp)"


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
                BucketTool(self.options),
                EyedropperTool(self.options),
                RectSelectTool(self.options),
                LassoTool(self.options),
                MoveTool(self.options),
                HandTool(self.options),
                ZoomTool(self.options),
            )
        }
        self._active_tool_name = "brush"

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
        self._layers_dock.raise_()

        self._build_tool_bar()
        self._build_options_bar()
        self._build_menus()
        self._build_status_bar()
        self._sync_option_visibility()

        self.setAcceptDrops(True)
        self.resize(1280, 800)

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
            "brush": "B", "bucket": "G", "eyedropper": "I",
            "rect-select": "M", "lasso": "L", "move": "V",
            "hand": "H", "zoom": "Z",
        }
        labels = {
            "brush": "Brush", "bucket": "Paint Bucket", "eyedropper": "Eyedropper",
            "rect-select": "Rectangle Select", "lasso": "Lasso Select", "move": "Move",
            "hand": "Hand (pan)", "zoom": "Zoom",
        }
        self._tool_actions = {}
        for name in ("brush", "bucket", "eyedropper", "rect-select", "lasso", "move",
                     "hand", "zoom"):
            act = QAction(TOOL_ICONS[name](), labels[name], self)
            act.setCheckable(True)
            act.setShortcut(shortcuts[name])
            act.setToolTip(f"{labels[name]} ({shortcuts[name]})")
            act.triggered.connect(lambda _=False, n=name: self._set_tool(n))
            group.addAction(act)
            bar.addAction(act)
            self._tool_actions[name] = act
        self._tool_actions["brush"].setChecked(True)

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

        self._option_actions = {
            "brush": [color_act, bg_act, size_act, hard_act, opacity_act, eraser_act],
            "bucket": [color_act, bg_act, opacity_act, tol_act],
            "eyedropper": [color_act, bg_act],
            "rect-select": [],
            "lasso": [],
            "move": [],
            "hand": [],
            "zoom": [],
        }
        self._all_option_actions = [
            color_act, bg_act, size_act, hard_act, opacity_act, eraser_act, tol_act,
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
        m_edit.addAction(self._act("D&eselect", "Ctrl+D", self.action_deselect))
        m_edit.addSeparator()
        m_edit.addAction(self._act("S&wap Colours", "X", self.action_swap_colors))
        m_edit.addAction(self._act("Rese&t Colours", "D", self.action_reset_colors))
        m_edit.addSeparator()
        self._options_menu = m_edit.addMenu("&Options")
        self._rulers_menu = self._options_menu.addMenu("&Rulers")  # unit actions added below

        m_image = menu.addMenu("&Image")
        m_image.addAction(self._act("&Image Size…", "Ctrl+Alt+I", self.action_image_size))
        m_image.addAction(self._act("&Canvas Size…", "Ctrl+Alt+S", self.action_canvas_size))
        m_image.addAction(self._act("C&rop to Selection", "Ctrl+Alt+C", self.action_crop))
        m_image.addSeparator()
        m_rotate = m_image.addMenu("Image &Rotation")
        m_rotate.addAction(self._act("Rotate 90° &CW", None,
                                     lambda: self._image_cmd(RotateImageCommand, 90)))
        m_rotate.addAction(self._act("Rotate 90° CC&W", None,
                                     lambda: self._image_cmd(RotateImageCommand, 270)))
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
        m_layer.addAction(self._act("Merge Do&wn", "Ctrl+Shift+E",
                                    lambda: self.layer_panel.merge_down()))
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
        suggested = os.path.splitext(doc.name)[0] + ".png"
        path, chosen = QFileDialog.getSaveFileName(self, "Export", suggested, _EXPORT_FILTER)
        if not path:
            return
        ext = os.path.splitext(path)[1].lower()
        if not ext:
            ext = ".png"
            path += ext
        opaque = ext in (".jpg", ".jpeg", ".bmp")
        img = doc.flatten(QColor(255, 255, 255) if opaque else None)
        img.setDotsPerMeterX(round(doc.dpi / 0.0254))
        img.setDotsPerMeterY(round(doc.dpi / 0.0254))
        quality = 95 if ext in (".jpg", ".jpeg", ".webp") else -1
        if img.save(path, None, quality):
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

    # ------------------------------------------------------------------ image actions

    def _image_cmd(self, command, arg) -> None:
        doc = self.current_doc()
        if doc is not None:
            doc.undo_stack.push(command(doc, arg))

    def _layer_cmd(self, command, arg) -> None:
        doc = self.current_doc()
        if doc is not None and doc.active_layer is not None:
            doc.undo_stack.push(command(doc, doc.active_layer, arg))

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
