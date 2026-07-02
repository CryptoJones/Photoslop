# SPDX-License-Identifier: Apache-2.0
import pytest

from photoslop import units


def test_px_per_unit():
    assert units.px_per_unit("px", 300) == 1.0
    assert units.px_per_unit("in", 300) == 300
    assert units.px_per_unit("mm", 254) == pytest.approx(10.0)
    assert units.px_per_unit("pc", 72) == pytest.approx(12.0)  # 6 picas per inch


def test_round_trip():
    for unit in units.UNITS:
        assert units.px_to_unit(units.unit_to_px(3.5, unit, 144), unit, 144) == pytest.approx(3.5)


def test_pick_tick_step_scales_with_zoom():
    coarse = units.pick_tick_step("px", 72, 0.125)
    fine = units.pick_tick_step("px", 72, 8.0)
    assert coarse > fine


def test_format_tick():
    assert units.format_tick(2.0) == "2"
    assert units.format_tick(2.5) == "2.5"
    assert units.format_tick(0.0) == "0"


def test_unit_labels():
    assert units.unit_label("in") == "freedom units"  # 🦅 by executive request
    assert units.unit_label("mm") == "millimetres"
    assert units.unit_label("pc") == "picas"
    assert units.unit_label("px") == "pixels"
