# SPDX-License-Identifier: Apache-2.0
"""Raw develop dialog (#112) — exposure/WB/tone before the image becomes a
document. The preview decodes at half size; per DD-007 all 16-bit work is
transient and OK hands an 8-bit layer to the caller."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSlider,
)

from photoslop.io_raw import DEVELOP_FIELDS, develop_raw

_PREVIEW = 320


class RawDevelopDialog(QDialog):
    def __init__(self, path: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Raw Develop")
        self._path = path
        form = QFormLayout(self)
        self.preview = QLabel("decoding…")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(_PREVIEW, _PREVIEW * 2 // 3)
        form.addRow(self.preview)

        self._sliders: dict[str, QSlider] = {}
        scale = {"exposure": 100.0, "temp": 1.0, "tint": 1.0, "highlights": 1.0, "shadows": 1.0}
        self._scale = scale
        labels = {
            "exposure": "Exposure (EV)",
            "temp": "Temp (K, 0=camera)",
            "tint": "Tint",
            "highlights": "Highlights",
            "shadows": "Shadows",
        }
        for key, (lo, hi, default) in DEVELOP_FIELDS.items():
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(int(lo * scale[key]), int(hi * scale[key]))
            slider.setValue(int(default * scale[key]))
            slider.valueChanged.connect(self._changed)
            form.addRow(labels[key], slider)
            self._sliders[key] = slider

        camera = QPushButton("Camera defaults")
        camera.clicked.connect(self._reset)
        form.addRow(camera)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(250)
        self._debounce.timeout.connect(self._render_preview)

    def showEvent(self, event) -> None:  # first preview only when visible
        super().showEvent(event)
        self._debounce.start()

    def values(self) -> dict[str, float]:
        return {key: slider.value() / self._scale[key] for key, slider in self._sliders.items()}

    def _reset(self) -> None:
        for key, (_lo, _hi, default) in DEVELOP_FIELDS.items():
            self._sliders[key].setValue(int(default * self._scale[key]))

    def _changed(self) -> None:
        self._debounce.start()

    def _render_preview(self) -> None:
        try:
            img = develop_raw(self._path, half_size=True, **self.values())
        except Exception as exc:  # unreadable raw: show why, keep dialog up
            self.preview.setText(str(exc)[:120])
            return
        self.preview.setPixmap(
            QPixmap.fromImage(
                img.scaled(
                    _PREVIEW,
                    _PREVIEW,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        )

    def developed(self) -> QImage:
        """Full-resolution develop with the chosen values (on OK)."""
        return develop_raw(self._path, **self.values())
