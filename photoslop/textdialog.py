# SPDX-License-Identifier: Apache-2.0
"""Text tool dialog: type text, pick font/size, and it renders onto a new
layer at the clicked position (raster, like flattening PS type)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import (
    QColorDialog,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
)

from photoslop.layer import Layer


def render_text_layer(text: str, font: QFont, color: QColor,
                      anchor: QPoint) -> Layer | None:
    """Rasterise text into a tight layer whose top-left sits at `anchor`."""
    text = text.rstrip("\n")
    if not text.strip():
        return None
    metrics = QFontMetricsF(font)
    lines = text.split("\n")
    width = max(metrics.horizontalAdvance(line) for line in lines)
    height = metrics.lineSpacing() * len(lines)
    pad = 2
    layer = Layer.blank(lines[0][:24] or "Text",
                        # ceil via int()+1 keeps antialiased edges inside
                        _size(int(width) + 2 * pad + 1, int(height) + 2 * pad + 1),
                        QPoint(anchor))
    p = QPainter(layer.image)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.setFont(font)
    p.setPen(color)
    y = float(pad)
    for line in lines:
        p.drawText(QRectF(pad, y, width + 1, metrics.lineSpacing()),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, line)
        y += metrics.lineSpacing()
    p.end()
    layer.text_data = {
        "text": text,
        "family": font.family(),
        "size": font.pointSize(),
        "color": [color.red(), color.green(), color.blue(), color.alpha()],
    }
    return layer


def _size(w: int, h: int):
    from PySide6.QtCore import QSize

    return QSize(max(1, w), max(1, h))


class TextDialog(QDialog):
    def __init__(self, color: QColor, parent=None, text: str = "",
                 font: QFont | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Text" if text else "Add Text")
        self.color = QColor(color)

        form = QFormLayout(self)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("Type your text…")
        self.edit.setMinimumSize(320, 100)
        self.edit.setPlainText(text)
        form.addRow(self.edit)

        row = QHBoxLayout()
        self.font_box = QFontComboBox()
        self.size = QSpinBox()
        self.size.setRange(6, 400)
        self.size.setValue(32)
        self.size.setSuffix(" pt")
        if font is not None:
            self.font_box.setCurrentFont(font)
            if font.pointSize() > 0:
                self.size.setValue(font.pointSize())
        self.color_button = QPushButton()
        self.color_button.setToolTip("Text colour")
        self.color_button.setFixedSize(40, self.size.sizeHint().height())
        self.color_button.clicked.connect(self.pick_color)
        self._update_swatch()
        row.addWidget(self.font_box, 1)
        row.addWidget(self.size)
        row.addWidget(self.color_button)
        form.addRow(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.edit.setFocus()

    def pick_color(self) -> None:
        picked = QColorDialog.getColor(
            self.color, self, "Text Colour",
            QColorDialog.ColorDialogOption.ShowAlphaChannel)
        if picked.isValid():
            self.color = picked
            self._update_swatch()

    def _update_swatch(self) -> None:
        self.color_button.setStyleSheet(
            f"background-color: {self.color.name()}; border: 1px solid gray;")

    def chosen_font(self) -> QFont:
        font = self.font_box.currentFont()
        font.setPointSize(self.size.value())
        return font

    def text(self) -> str:
        return self.edit.toPlainText()
