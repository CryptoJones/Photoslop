# SPDX-License-Identifier: Apache-2.0
"""Measurement units for rulers, dialogs, and the status bar.

All positions are stored internally in canvas pixels; these helpers convert
to and from display units using the document's DPI.
"""

from __future__ import annotations

UNITS = ("px", "in", "mm", "pc")

_LABELS = {"px": "pixels", "in": "freedom units", "mm": "millimetres", "pc": "picas"}


def unit_label(unit: str) -> str:
    return _LABELS[unit]


def px_per_unit(unit: str, dpi: float) -> float:
    """Canvas pixels per one display unit at the given DPI."""
    if unit == "px":
        return 1.0
    if unit == "in":
        return dpi
    if unit == "mm":
        return dpi / 25.4
    if unit == "pc":  # 1 pica = 1/6 inch
        return dpi / 6.0
    raise ValueError(f"unknown unit {unit!r}")


def px_to_unit(px: float, unit: str, dpi: float) -> float:
    return px / px_per_unit(unit, dpi)


def unit_to_px(value: float, unit: str, dpi: float) -> float:
    return value * px_per_unit(unit, dpi)


def format_value(px: float, unit: str, dpi: float) -> str:
    if unit == "px":
        return f"{int(round(px))}"
    return f"{px_to_unit(px, unit, dpi):.2f}"


def format_value_precise(px: float, unit: str, dpi: float) -> str:
    """Float readout with the unit suffix — used for live guide positions."""
    if unit == "px":
        return f"{px:.1f} px"
    return f"{px_to_unit(px, unit, dpi):.2f} {unit}"


# Candidate tick steps, in display units. Sub-unit steps let inch/pica rulers
# subdivide when zoomed in.
_STEPS = (
    0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 25, 50, 100,
    250, 500, 1000, 2500, 5000, 10000, 25000, 50000,
)


def pick_tick_step(unit: str, dpi: float, zoom: float, min_label_px: float = 60.0) -> float:
    """Smallest step (in display units) whose on-screen spacing >= min_label_px."""
    screen_px_per_unit = px_per_unit(unit, dpi) * zoom
    for step in _STEPS:
        if step * screen_px_per_unit >= min_label_px:
            return float(step)
    return float(_STEPS[-1])


def minor_tick_step(unit: str, dpi: float, zoom: float) -> float:
    """Minor-tick spacing in display units — shared by ruler drawing and
    guide snapping, so guides snap exactly to the ticks you can see."""
    step = pick_tick_step(unit, dpi, zoom)
    screen_px_per_unit = px_per_unit(unit, dpi) * zoom
    return step / 5.0 if step * screen_px_per_unit >= 30.0 else step / 2.0


def snap_px(px: float, unit: str, dpi: float, zoom: float) -> float:
    """Snap a canvas-pixel position to the nearest visible minor ruler tick."""
    step_px = minor_tick_step(unit, dpi, zoom) * px_per_unit(unit, dpi)
    if step_px <= 0:
        return px
    return round(px / step_px) * step_px


def format_tick(value: float) -> str:
    """Trim trailing zeros: 2.0 -> '2', 2.50 -> '2.5'."""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"
