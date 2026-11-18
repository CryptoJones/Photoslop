# SPDX-License-Identifier: Apache-2.0
"""Dedicated modal Liquify dialog with interactive tool palette, brush
controls, live preview, and side-by-side comparison (#419).
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from photoslop.liquify import (
    LiquifyCommand,
    LiquifyGrid,
    LiquifyTool,
)


class LiquifyCanvas(QWidget):
    """Interactive canvas widget displaying deformed image and receiving brush strokes."""

    def __init__(
        self,
        source_image: QImage,
        grid: LiquifyGrid,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.source_image = source_image
        self.grid = grid

        # Working preview image
        self.preview_image = QImage(self.source_image)

        self.active_tool = LiquifyTool.FORWARD_WARP
        self.brush_size = 80.0
        self.brush_pressure = 0.5
        self.brush_density = 0.5

        self.show_preview = True
        self.side_by_side = False
        self.show_mask = True
        self.show_mesh = False

        self._mouse_pos: QPointF | None = None
        self._is_dragging = False
        self._last_point: tuple[float, float] | None = None

        self.setMinimumSize(400, 350)

    def set_active_tool(self, tool: LiquifyTool) -> None:
        self.active_tool = tool
        self.update()

    def set_brush_size(self, size: float) -> None:
        self.brush_size = max(5.0, min(500.0, float(size)))
        self.update()

    def set_brush_pressure(self, pressure: float) -> None:
        self.brush_pressure = max(0.01, min(1.0, float(pressure)))

    def set_brush_density(self, density: float) -> None:
        self.brush_density = max(0.01, min(1.0, float(density)))

    def set_show_preview(self, enabled: bool) -> None:
        self.show_preview = enabled
        self.update()

    def set_side_by_side(self, enabled: bool) -> None:
        self.side_by_side = enabled
        self.update()

    def set_show_mask(self, enabled: bool) -> None:
        self.show_mask = enabled
        self.update()

    def set_show_mesh(self, enabled: bool) -> None:
        self.show_mesh = enabled
        self.update()

    def reconstruct_all(self) -> None:
        self.grid.reconstruct_all()
        self.preview_image = QImage(self.source_image)
        self.update()

    def clear_freeze(self) -> None:
        self.grid.clear_freeze()
        self.update()

    def invert_freeze(self) -> None:
        self.grid.invert_freeze()
        self.update()

    # Coordinate mapping between widget and image pixels
    def _image_rect(self) -> QRectF:
        """Returns destination rectangle of image inside widget coordinates."""
        w, h = self.grid.width, self.grid.height
        if self.side_by_side:
            # Side by side: two panels
            avail_w = max(10, self.width() / 2.0 - 20)
            avail_h = max(10, self.height() - 40)
            scale = min(avail_w / w, avail_h / h, 1.0)
            rw = w * scale
            rh = h * scale
            rx = self.width() / 2.0 + 10  # right panel for interactive preview
            ry = (self.height() - rh) / 2.0
            return QRectF(rx, ry, rw, rh)

        avail_w = max(10, self.width() - 20)
        avail_h = max(10, self.height() - 20)
        scale = min(avail_w / w, avail_h / h, 1.0)
        rw = w * scale
        rh = h * scale
        rx = (self.width() - rw) / 2.0
        ry = (self.height() - rh) / 2.0
        return QRectF(rx, ry, rw, rh)

    def _widget_to_image(self, pt: QPointF) -> tuple[float, float] | None:
        rect = self._image_rect()
        if not rect.contains(pt):
            return None
        scale_x = self.grid.width / rect.width()
        scale_y = self.grid.height / rect.height()
        img_x = (pt.x() - rect.left()) * scale_x
        img_y = (pt.y() - rect.top()) * scale_y
        return (img_x, img_y)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            img_pt = self._widget_to_image(event.position())
            if img_pt is not None:
                self._is_dragging = True
                self._last_point = img_pt
                # Apply initial touch for single-click / stationary tools
                dirty = self.grid.apply_brush(
                    self.active_tool,
                    img_pt,
                    radius=self.brush_size / 2.0,
                    pressure=self.brush_pressure,
                    density=self.brush_density,
                )
                if dirty is not None:
                    self.grid.warp_image(
                        self.source_image,
                        rect=dirty,
                        target_image=self.preview_image,
                    )
                self.update()

    def mouseMoveEvent(self, event) -> None:
        self._mouse_pos = event.position()
        if self._is_dragging and self._last_point is not None:
            img_pt = self._widget_to_image(event.position())
            if img_pt is not None:
                dirty = self.grid.apply_stroke(
                    self.active_tool,
                    [self._last_point, img_pt],
                    size=self.brush_size,
                    pressure=self.brush_pressure,
                    density=self.brush_density,
                )
                self._last_point = img_pt
                if dirty is not None:
                    self.grid.warp_image(
                        self.source_image,
                        rect=dirty,
                        target_image=self.preview_image,
                    )
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dragging = False
            self._last_point = None
            self.update()

    def leaveEvent(self, event) -> None:
        self._mouse_pos = None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        # Background canvas checker pattern or dark fill
        p.fillRect(self.rect(), QColor(40, 40, 44))

        img_rect = self._image_rect()

        if self.side_by_side:
            # Draw Original on left
            left_x = 10
            left_rect = QRectF(left_x, img_rect.top(), img_rect.width(), img_rect.height())
            p.drawImage(left_rect, self.source_image)

            # Draw divider and labels
            p.setPen(QColor(100, 100, 108))
            divider_x = self.width() / 2.0
            p.drawLine(int(divider_x), 10, int(divider_x), self.height() - 10)

            font = QFont()
            font.setBold(True)
            font.setPointSize(11)
            p.setFont(font)
            p.setPen(QColor(200, 200, 210))
            p.drawText(int(left_rect.left()), int(left_rect.top() - 6), "Before (Original)")
            p.drawText(int(img_rect.left()), int(img_rect.top() - 6), "After (Liquify)")

            # Draw preview on right
            p.drawImage(img_rect, self.preview_image)
        else:
            display_img = self.preview_image if self.show_preview else self.source_image
            p.drawImage(img_rect, display_img)

        # Draw freeze mask overlay
        if self.show_mask and np.any(self.grid.freeze > 0.01):
            s = float(self.grid.spacing)
            scale_x = img_rect.width() / self.grid.width
            scale_y = img_rect.height() / self.grid.height

            # Red tint translucent overlay for frozen nodes
            for r in range(self.grid.rows):
                for c in range(self.grid.cols):
                    f = self.grid.freeze[r, c]
                    if f > 0.01:
                        alpha = int(f * 128)
                        px = img_rect.left() + (c * s) * scale_x
                        py = img_rect.top() + (r * s) * scale_y
                        p.fillRect(
                            QRectF(
                                px - s * scale_x * 0.5,
                                py - s * scale_y * 0.5,
                                s * scale_x,
                                s * scale_y,
                            ),
                            QColor(255, 0, 0, alpha),
                        )

        # Draw mesh lines overlay
        if self.show_mesh:
            p.setPen(QPen(QColor(0, 220, 255, 140), 1))
            s = float(self.grid.spacing)
            scale_x = img_rect.width() / self.grid.width
            scale_y = img_rect.height() / self.grid.height

            # Horizontal mesh lines
            for r in range(self.grid.rows):
                for c in range(self.grid.cols - 1):
                    x1 = img_rect.left() + (c * s + self.grid.dx[r, c]) * scale_x
                    y1 = img_rect.top() + (r * s + self.grid.dy[r, c]) * scale_y
                    x2 = img_rect.left() + ((c + 1) * s + self.grid.dx[r, c + 1]) * scale_x
                    y2 = img_rect.top() + (r * s + self.grid.dy[r, c + 1]) * scale_y
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            # Vertical mesh lines
            for c in range(self.grid.cols):
                for r in range(self.grid.rows - 1):
                    x1 = img_rect.left() + (c * s + self.grid.dx[r, c]) * scale_x
                    y1 = img_rect.top() + (r * s + self.grid.dy[r, c]) * scale_y
                    x2 = img_rect.left() + (c * s + self.grid.dx[r + 1, c]) * scale_x
                    y2 = img_rect.top() + ((r + 1) * s + self.grid.dy[r + 1, c]) * scale_y
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # Draw circular brush cursor outline
        if self._mouse_pos is not None and img_rect.contains(self._mouse_pos):
            scale_x = img_rect.width() / self.grid.width
            cur_r = (self.brush_size / 2.0) * scale_x
            p.setPen(QPen(QColor(255, 255, 255, 220), 1.5, Qt.PenStyle.DashLine))
            p.drawEllipse(self._mouse_pos, cur_r, cur_r)


class LiquifyDialog(QDialog):
    """Modal filter dialog for mesh displacement deformation."""

    def __init__(self, doc: Any, layer: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Liquify")
        self.resize(1000, 680)

        self._doc = doc
        self._layer = layer
        self._original_image = QImage(layer.image)

        # Initialize deformation grid
        self.grid = LiquifyGrid(
            width=self._original_image.width(),
            height=self._original_image.height(),
            spacing=8,
        )

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Left: Tool Palette
        tool_palette = QVBoxLayout()
        tool_palette.setSpacing(4)
        tool_palette.addWidget(QLabel("Tools:"))

        self.tool_group = QButtonGroup(self)
        self.tool_group.setExclusive(True)

        tools_spec = [
            (LiquifyTool.FORWARD_WARP, "Forward Warp", "W"),
            (LiquifyTool.RECONSTRUCT, "Reconstruct", "R"),
            (LiquifyTool.SMOOTH, "Smooth", "S"),
            (LiquifyTool.TWIRL_CW, "Twirl CW", "C"),
            (LiquifyTool.TWIRL_CCW, "Twirl CCW", "X"),
            (LiquifyTool.PUCKER, "Pucker", "P"),
            (LiquifyTool.BLOAT, "Bloat", "B"),
            (LiquifyTool.PUSH_LEFT, "Push Left", "O"),
            (LiquifyTool.FREEZE_MASK, "Freeze Mask", "F"),
            (LiquifyTool.THAW_MASK, "Thaw Mask", "D"),
        ]

        for tool_enum, label, shortcut in tools_spec:
            btn = QToolButton(self)
            btn.setText(f"{label} ({shortcut})")
            btn.setCheckable(True)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            btn.setToolTip(f"{label} (Shortcut: {shortcut})")
            if tool_enum == LiquifyTool.FORWARD_WARP:
                btn.setChecked(True)
            btn.clicked.connect(lambda _, t=tool_enum: self._on_tool_selected(t))
            self.tool_group.addButton(btn)
            tool_palette.addWidget(btn)

            # Global action shortcut
            act = QAction(self)
            act.setShortcut(QKeySequence(shortcut))
            act.triggered.connect(lambda _, b=btn, t=tool_enum: self._select_tool(b, t))
            self.addAction(act)

        tool_palette.addStretch()
        main_layout.addLayout(tool_palette)

        # Center: Interactive Canvas
        self.canvas = LiquifyCanvas(self._original_image, self.grid, self)
        main_layout.addWidget(self.canvas, stretch=1)

        # Right: Sliders, Preview, and Action Controls
        right_panel = QVBoxLayout()
        right_panel.setSpacing(8)
        right_panel.setContentsMargins(0, 0, 0, 0)

        # Brush settings group
        brush_group = QGroupBox("Brush Settings")
        brush_form = QFormLayout(brush_group)

        # Size slider + spinbox
        self.size_spin = QSpinBox()
        self.size_spin.setRange(5, 500)
        self.size_spin.setValue(80)
        self.size_spin.setSuffix(" px")
        self.size_slider = QSlider(Qt.Orientation.Horizontal)
        self.size_slider.setRange(5, 500)
        self.size_slider.setValue(80)
        self.size_spin.valueChanged.connect(self.size_slider.setValue)
        self.size_slider.valueChanged.connect(self.size_spin.setValue)
        self.size_slider.valueChanged.connect(self._on_size_changed)

        size_row = QHBoxLayout()
        size_row.addWidget(self.size_slider)
        size_row.addWidget(self.size_spin)
        brush_form.addRow("Size:", size_row)

        # Density slider + spinbox
        self.density_spin = QSpinBox()
        self.density_spin.setRange(1, 100)
        self.density_spin.setValue(50)
        self.density_spin.setSuffix(" %")
        self.density_slider = QSlider(Qt.Orientation.Horizontal)
        self.density_slider.setRange(1, 100)
        self.density_slider.setValue(50)
        self.density_spin.valueChanged.connect(self.density_slider.setValue)
        self.density_slider.valueChanged.connect(self.density_spin.setValue)
        self.density_slider.valueChanged.connect(self._on_density_changed)

        density_row = QHBoxLayout()
        density_row.addWidget(self.density_slider)
        density_row.addWidget(self.density_spin)
        brush_form.addRow("Density:", density_row)

        # Pressure slider + spinbox
        self.pressure_spin = QSpinBox()
        self.pressure_spin.setRange(1, 100)
        self.pressure_spin.setValue(50)
        self.pressure_spin.setSuffix(" %")
        self.pressure_slider = QSlider(Qt.Orientation.Horizontal)
        self.pressure_slider.setRange(1, 100)
        self.pressure_slider.setValue(50)
        self.pressure_spin.valueChanged.connect(self.pressure_slider.setValue)
        self.pressure_slider.valueChanged.connect(self.pressure_spin.setValue)
        self.pressure_slider.valueChanged.connect(self._on_pressure_changed)

        pressure_row = QHBoxLayout()
        pressure_row.addWidget(self.pressure_slider)
        pressure_row.addWidget(self.pressure_spin)
        brush_form.addRow("Pressure:", pressure_row)

        right_panel.addWidget(brush_group)

        # View & Preview Options group
        view_group = QGroupBox("View Options")
        view_layout = QVBoxLayout(view_group)

        self.preview_cb = QCheckBox("Preview (Toggle)")
        self.preview_cb.setChecked(True)
        self.preview_cb.toggled.connect(self.canvas.set_show_preview)
        view_layout.addWidget(self.preview_cb)

        self.side_by_side_cb = QCheckBox("Side by Side Preview")
        self.side_by_side_cb.setChecked(False)
        self.side_by_side_cb.toggled.connect(self.canvas.set_side_by_side)
        view_layout.addWidget(self.side_by_side_cb)

        self.mask_cb = QCheckBox("Show Freeze Mask")
        self.mask_cb.setChecked(True)
        self.mask_cb.toggled.connect(self.canvas.set_show_mask)
        view_layout.addWidget(self.mask_cb)

        self.mesh_cb = QCheckBox("Show Mesh Overlay")
        self.mesh_cb.setChecked(False)
        self.mesh_cb.toggled.connect(self.canvas.set_show_mesh)
        view_layout.addWidget(self.mesh_cb)

        right_panel.addWidget(view_group)

        # Mask & Reconstruction Actions group
        actions_group = QGroupBox("Reconstruction & Mask")
        actions_layout = QVBoxLayout(actions_group)

        self.reconstruct_btn = QPushButton("Reconstruct All")
        self.reconstruct_btn.clicked.connect(self.canvas.reconstruct_all)
        actions_layout.addWidget(self.reconstruct_btn)

        self.clear_mask_btn = QPushButton("Clear Freeze Mask")
        self.clear_mask_btn.clicked.connect(self.canvas.clear_freeze)
        actions_layout.addWidget(self.clear_mask_btn)

        self.invert_mask_btn = QPushButton("Invert Freeze Mask")
        self.invert_mask_btn.clicked.connect(self.canvas.invert_freeze)
        actions_layout.addWidget(self.invert_mask_btn)

        right_panel.addWidget(actions_group)

        right_panel.addStretch()

        # Dialog Buttons (OK / Cancel)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right_panel.addWidget(buttons)

        main_layout.addLayout(right_panel)

        # Brush size bracket shortcuts [ and ]
        dec_brush = QAction(self)
        dec_brush.setShortcut(QKeySequence("["))
        dec_brush.triggered.connect(lambda: self.size_slider.setValue(self.size_slider.value() - 5))
        self.addAction(dec_brush)

        inc_brush = QAction(self)
        inc_brush.setShortcut(QKeySequence("]"))
        inc_brush.triggered.connect(lambda: self.size_slider.setValue(self.size_slider.value() + 5))
        self.addAction(inc_brush)

    def _select_tool(self, button: QToolButton, tool: LiquifyTool) -> None:
        button.setChecked(True)
        self._on_tool_selected(tool)

    def _on_tool_selected(self, tool: LiquifyTool) -> None:
        self.canvas.set_active_tool(tool)

    def _on_size_changed(self, value: int) -> None:
        self.canvas.set_brush_size(float(value))

    def _on_density_changed(self, value: int) -> None:
        self.canvas.set_brush_density(float(value) / 100.0)

    def _on_pressure_changed(self, value: int) -> None:
        self.canvas.set_brush_pressure(float(value) / 100.0)

    def accept(self) -> None:
        """Bake the deformed image and commit a LiquifyCommand to the document."""
        # Ensure full layer is warped with high quality
        warped_final = self.grid.warp_image(self._original_image, interpolation="catmull-rom")
        cmd = LiquifyCommand(self._doc, self._layer, warped_final)
        self._doc.undo_stack.push(cmd)
        super().accept()
