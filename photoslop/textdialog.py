# SPDX-License-Identifier: Apache-2.0
"""Text tool dialog: a small rich-text editor. Type text, pick a font/size,
toggle bold/italic, and colour the whole block *or individual letters* (select
a run, then pick a colour). The editor is WYSIWYG — what you type shows in the
font and colour you chose. On accept it rasterises the styled text onto a new
layer at the clicked position (raster, like flattening PS type)."""

from __future__ import annotations

import copy
import json
import math

from PySide6.QtCore import QPoint, QRectF, QSettings, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QPainter,
    QTextCharFormat,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFontComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
)

from photoslop.layer import Layer


def render_text_layer(text: str, font: QFont, color: QColor, anchor: QPoint) -> Layer | None:
    """Rasterise plain text into a tight layer whose top-left sits at `anchor`.

    The single-font/single-colour path used by the CLI `--text` op and by
    callers that don't need per-letter styling. For rich text (per-letter
    colour, mixed fonts) build a QTextDocument and use `render_text_document`.
    """
    text = text.rstrip("\n")
    if not text.strip():
        return None
    metrics = QFontMetricsF(font)
    lines = text.split("\n")
    width = max(metrics.horizontalAdvance(line) for line in lines)
    height = metrics.lineSpacing() * len(lines)
    pad = 2
    layer = Layer.blank(
        lines[0][:24] or "Text",
        # ceil via int()+1 keeps antialiased edges inside
        _size(int(width) + 2 * pad + 1, int(height) + 2 * pad + 1),
        QPoint(anchor),
    )
    p = QPainter(layer.image)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    p.setFont(font)
    p.setPen(color)
    y = float(pad)
    for line in lines:
        p.drawText(
            QRectF(pad, y, width + 1, metrics.lineSpacing()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            line,
        )
        y += metrics.lineSpacing()
    p.end()
    layer.text_data = {
        "text": text,
        "family": font.family(),
        "size": font.pointSize(),
        "color": [color.red(), color.green(), color.blue(), color.alpha()],
    }
    return layer


def render_text_document(document: QTextDocument, anchor: QPoint, pad: int = 2) -> Layer | None:
    """Rasterise a rich QTextDocument (per-letter colour, mixed fonts, bold/
    italic) into a tight layer whose top-left sits at `anchor`.

    The document is cloned first, so the caller's live editor document is left
    untouched. The layer stores the document's HTML in `text_data` so the text
    tool can re-open it with all its styling intact.
    """
    document = document.clone()
    if not document.toPlainText().strip():
        return None
    document.setDocumentMargin(pad)
    document.setTextWidth(-1)  # -1 → lay out at the natural width, no wrapping
    size = document.size()
    width = int(math.ceil(size.width())) + 1
    height = int(math.ceil(size.height())) + 1
    plain = document.toPlainText()
    layer = Layer.blank(plain.split("\n")[0][:24] or "Text", _size(width, height), QPoint(anchor))
    p = QPainter(layer.image)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
    document.drawContents(p)
    p.end()
    base = document.defaultFont()
    layer.text_data = {
        "text": plain,
        "html": document.toHtml(),
        "family": base.family(),
        "size": base.pointSize(),
        "color": [0, 0, 0, 255],  # legacy fallback; real colours live in html
    }
    return layer


def _size(w: int, h: int) -> QSize:
    return QSize(max(1, w), max(1, h))


class TextDialog(QDialog):
    """Rich-text entry for the Text tool.

    Backwards-compatible constructor: `TextDialog(color, parent, text, font)`
    still seeds a single-colour/single-font block. Pass `html` instead to
    restore a previously styled block for editing.
    """

    def __init__(
        self,
        color: QColor,
        parent=None,
        text: str = "",
        font: QFont | None = None,
        html: str | None = None,
        effects=None,
        fill_opacity: float = 1.0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Text" if (text or html) else "Add Text")
        self.color = QColor(color)
        self._syncing = False
        from photoslop.appearance import normalize_effects

        self.appearance_effects = normalize_effects(effects)
        self.appearance_fill_opacity = max(0.0, min(1.0, float(fill_opacity)))

        layout = QVBoxLayout(self)

        # --- formatting toolbar -------------------------------------------
        bar = QFrame()
        bar.setObjectName("textToolbar")
        bar.setStyleSheet(
            "#textToolbar { border: 1px solid palette(mid); border-radius: 6px; }"
            "#textToolbar QToolButton { border: none; padding: 4px 8px; }"
            "#textToolbar QToolButton:checked {"
            " background: palette(highlight); border-radius: 4px; }"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(6, 4, 6, 4)
        row.setSpacing(6)

        self.font_box = QFontComboBox()
        self.size = QSpinBox()
        self.size.setRange(6, 999)
        self.size.setValue(32)
        self.size.setSuffix(" pt")

        self.bold_btn = QToolButton()
        self.bold_btn.setText("B")
        self.bold_btn.setCheckable(True)
        self.bold_btn.setToolTip("Bold")
        bfont = self.bold_btn.font()
        bfont.setBold(True)
        self.bold_btn.setFont(bfont)

        self.italic_btn = QToolButton()
        self.italic_btn.setText("I")
        self.italic_btn.setCheckable(True)
        self.italic_btn.setToolTip("Italic")
        ifont = self.italic_btn.font()
        ifont.setItalic(True)
        self.italic_btn.setFont(ifont)

        self.color_button = QPushButton()
        self.color_button.setToolTip(
            "Text colour — colours the selection, or new typing if nothing is selected"
        )
        self.color_button.setFixedSize(40, self.size.sizeHint().height())
        self.color_button.clicked.connect(self.pick_color)

        row.addWidget(self.font_box, 1)
        row.addWidget(self.size)
        row.addWidget(self.bold_btn)
        row.addWidget(self.italic_btn)
        row.addWidget(self.color_button)
        layout.addWidget(bar)

        appearance_row = QHBoxLayout()
        appearance_row.addWidget(QLabel("Appearance"))
        self.appearance_preset = QComboBox()
        self.appearance_preset.addItem("None", None)
        from photoslop.appearance import BUILTIN_PRESETS

        for name in BUILTIN_PRESETS:
            self.appearance_preset.addItem(name, ("builtin", name))
        try:
            custom = json.loads(
                str(QSettings("CryptoJones", "Photoslop").value("appearance/presets/v1", "{}"))
            )
        except (TypeError, json.JSONDecodeError):
            custom = {}
        if not isinstance(custom, dict):
            custom = {}
        for name in sorted(custom):
            self.appearance_preset.addItem(name, ("custom", name))
        self._appearance_custom = custom
        if self.appearance_effects:
            self.appearance_preset.addItem("Custom (Appearance panel)", "keep")
            self.appearance_preset.setCurrentIndex(self.appearance_preset.count() - 1)
        self.appearance_preset.currentIndexChanged.connect(self._appearance_changed)
        appearance_row.addWidget(self.appearance_preset, 1)
        layout.addLayout(appearance_row)

        # --- editor -------------------------------------------------------
        self.edit = QTextEdit()
        self.edit.setAcceptRichText(True)
        self.edit.setPlaceholderText("Type your text…")
        self.edit.setMinimumSize(360, 140)
        layout.addWidget(self.edit, 1)

        hint = QLabel("Tip: select individual letters, then pick a colour to tint just those.")
        hint.setStyleSheet("color: palette(mid); font-size: 11px;")
        layout.addWidget(hint)

        # seed the starting font/size so the very first keystroke previews it
        if font is not None:
            self.font_box.setCurrentFont(font)
            if font.pointSize() > 0:
                self.size.setValue(font.pointSize())
        seed_font = self.chosen_font()
        self.edit.document().setDefaultFont(seed_font)
        seed = QTextCharFormat()
        seed.setFont(seed_font)
        seed.setForeground(self.color)
        self.edit.setCurrentCharFormat(seed)

        # restore prior content
        if html is not None:
            self.edit.setHtml(html)
        elif text:
            cursor = self.edit.textCursor()
            cursor.insertText(text, seed)

        self._update_swatch()

        # live formatting wiring
        self.font_box.currentFontChanged.connect(self._on_font)
        self.size.valueChanged.connect(self._on_size)
        self.bold_btn.toggled.connect(self._on_bold)
        self.italic_btn.toggled.connect(self._on_italic)
        self.edit.currentCharFormatChanged.connect(self._sync_controls)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.edit.setFocus()

    # -- formatting helpers ------------------------------------------------
    def _merge(self, fmt: QTextCharFormat, return_focus: bool = False) -> None:
        """Apply `fmt` to the selection, or to subsequent typing if there is
        no selection (mergeCurrentCharFormat handles both cases).

        Numeric/font controls must keep focus while the user types a value.
        Toolbar buttons and the colour picker can explicitly return it to the
        editor once their one-shot action is complete.
        """
        if self._syncing:
            return
        self.edit.mergeCurrentCharFormat(fmt)
        if return_focus:
            self.edit.setFocus()

    def _on_font(self, font: QFont) -> None:
        fmt = QTextCharFormat()
        fmt.setFontFamilies([font.family()])
        self._merge(fmt)

    def _on_size(self, value: int) -> None:
        fmt = QTextCharFormat()
        fmt.setFontPointSize(float(value))
        self._merge(fmt)

    def _on_bold(self, on: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Weight.Bold if on else QFont.Weight.Normal)
        self._merge(fmt, return_focus=True)

    def _on_italic(self, on: bool) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(on)
        self._merge(fmt, return_focus=True)

    def _sync_controls(self, fmt: QTextCharFormat) -> None:
        """Reflect the format under the cursor back into the toolbar so the
        controls always show what the caret (or selection) is styled as."""
        self._syncing = True
        try:
            font = fmt.font()
            self.font_box.setCurrentFont(font)
            point = fmt.fontPointSize() or font.pointSizeF()
            if point > 0:
                self.size.setValue(int(round(point)))
            self.bold_btn.setChecked(font.bold())
            self.italic_btn.setChecked(font.italic())
            brush = fmt.foreground()
            if brush.style() != Qt.BrushStyle.NoBrush:
                self.color = brush.color()
                self._update_swatch()
        finally:
            self._syncing = False

    def keyPressEvent(self, event) -> None:
        """Commit a typed point size without letting the dialog accept itself."""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            focused = self.focusWidget()
            if focused in (self.size, self.size.lineEdit()):
                self.size.interpretText()
                event.accept()
                return
        super().keyPressEvent(event)

    def pick_color(self) -> None:
        picked = QColorDialog.getColor(
            self.color, self, "Text Colour", QColorDialog.ColorDialogOption.ShowAlphaChannel
        )
        if picked.isValid():
            self.color = picked
            self._update_swatch()
            fmt = QTextCharFormat()
            fmt.setForeground(picked)
            self._merge(fmt, return_focus=True)

    def _update_swatch(self) -> None:
        self.color_button.setStyleSheet(
            f"background-color: {self.color.name()}; border: 1px solid gray;"
        )

    # -- results -----------------------------------------------------------
    def chosen_font(self) -> QFont:
        font = self.font_box.currentFont()
        font.setPointSize(self.size.value())
        return font

    def text(self) -> str:
        return self.edit.toPlainText()

    def document(self) -> QTextDocument:
        return self.edit.document()

    def build_layer(self, anchor: QPoint) -> Layer | None:
        """Rasterise the styled text into a layer anchored at `anchor`."""
        layer = render_text_document(self.edit.document(), anchor)
        if layer is not None:
            layer.effects = copy.deepcopy(self.appearance_effects)
            layer.fill_opacity = self.appearance_fill_opacity
        return layer

    def _appearance_changed(self) -> None:
        data = self.appearance_preset.currentData()
        if data == "keep":
            return
        if data is None:
            self.appearance_effects = []
            return
        from photoslop.appearance import BUILTIN_PRESETS, new_effect, normalize_effects

        source, name = data
        stack = BUILTIN_PRESETS[name] if source == "builtin" else self._appearance_custom[name]
        normalized = normalize_effects(stack)
        self.appearance_effects = [
            new_effect(effect["type"], **effect["parameters"]) for effect in normalized
        ]
