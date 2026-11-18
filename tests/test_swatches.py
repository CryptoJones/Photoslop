# SPDX-License-Identifier: Apache-2.0
"""Unit tests for Adobe .aco and .ase swatch palette import and export (#421)."""

import struct

import pytest
from PySide6.QtGui import QColor

from photoslop.colordialog import ColorWithSwatchesDialog
from photoslop.swatches import (
    Swatch,
    SwatchesPanel,
    SwatchesWidget,
    SwatchGroup,
    SwatchPalette,
    cmyk_to_rgb,
    hsb_to_rgb,
    lab_to_rgb,
    rgb_to_cmyk,
    rgb_to_lab,
)


def test_color_space_conversions():
    # LAB roundtrip test
    test_colors = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 255),
        (0, 0, 0),
        (128, 64, 192),
    ]
    for r, g, b in test_colors:
        l_val, a_val, b_val = rgb_to_lab(r, g, b)
        r2, g2, b2 = lab_to_rgb(l_val, a_val, b_val)
        assert abs(r - r2) <= 1
        assert abs(g - g2) <= 1
        assert abs(b - b2) <= 1

    # CMYK roundtrip test
    for r, g, b in [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 255), (0, 0, 0)]:
        c, m, y, k = rgb_to_cmyk(r, g, b)
        r2, g2, b2 = cmyk_to_rgb(c, m, y, k)
        assert abs(r - r2) <= 1
        assert abs(g - g2) <= 1
        assert abs(b - b2) <= 1

    # HSB test
    assert hsb_to_rgb(0.0, 1.0, 1.0) == (255, 0, 0)
    assert hsb_to_rgb(120.0 / 360.0, 1.0, 1.0) == (0, 255, 0)
    assert hsb_to_rgb(240.0 / 360.0, 1.0, 1.0) == (0, 0, 255)


def test_aco_roundtrip_v1_and_v2(tmp_path):
    pal = SwatchPalette(name="Interchange")
    pal.add_swatch(Swatch.from_rgb(255, 0, 0, name="Crimson"))
    pal.add_swatch(Swatch.from_rgb(0, 128, 0, name="Forest Green"))
    pal.add_swatch(Swatch.from_rgb(0, 0, 255, name="Navy Blue"))

    aco_bytes = pal.to_aco()
    out_file = tmp_path / "test.aco"
    out_file.write_bytes(aco_bytes)

    loaded = SwatchPalette.load(out_file)
    swatches = loaded.all_swatches()
    assert len(swatches) == 3
    assert swatches[0].name == "Crimson"
    assert swatches[0].to_rgb() == (255, 0, 0)
    assert swatches[1].name == "Forest Green"
    assert swatches[1].to_rgb() == (0, 128, 0)
    assert swatches[2].name == "Navy Blue"
    assert swatches[2].to_rgb() == (0, 0, 255)


def test_aco_v1_only_stream():
    # Only v1 header (version 1, count 2)
    v1_raw = (
        struct.pack(">HH", 1, 2)
        + struct.pack(">HHHHH", 0, 65535, 0, 0, 0)  # RGB (255, 0, 0)
        + struct.pack(">HHHHH", 0, 0, 65535, 0, 0)  # RGB (0, 255, 0)
    )
    pal = SwatchPalette.from_aco(v1_raw)
    assert len(pal.swatches) == 2
    assert pal.swatches[0].to_rgb() == (255, 0, 0)
    assert pal.swatches[1].to_rgb() == (0, 255, 0)


def test_aco_v2_only_stream():
    name1 = "Pure Red".encode("utf-16-be") + b"\x00\x00"
    name2 = "Pure Blue".encode("utf-16-be") + b"\x00\x00"
    v2_raw = (
        struct.pack(">HH", 2, 2)
        + struct.pack(">HHHHH", 0, 65535, 0, 0, 0)
        + struct.pack(">I", len("Pure Red") + 1)
        + name1
        + struct.pack(">HHHHH", 0, 0, 0, 65535, 0)
        + struct.pack(">I", len("Pure Blue") + 1)
        + name2
    )
    pal = SwatchPalette.from_aco(v2_raw)
    assert len(pal.swatches) == 2
    assert pal.swatches[0].name == "Pure Red"
    assert pal.swatches[0].to_rgb() == (255, 0, 0)
    assert pal.swatches[1].name == "Pure Blue"
    assert pal.swatches[1].to_rgb() == (0, 0, 255)


def test_aco_color_models():
    pal = SwatchPalette(name="Models")
    pal.add_swatch(Swatch(name="RGB Red", color_model="RGB", values=(1.0, 0.0, 0.0)))
    pal.add_swatch(Swatch(name="HSB Cyan", color_model="HSB", values=(180.0 / 360.0, 1.0, 1.0)))
    pal.add_swatch(Swatch(name="CMYK Magenta", color_model="CMYK", values=(0.0, 1.0, 0.0, 0.0)))
    pal.add_swatch(Swatch(name="Lab Neutral", color_model="LAB", values=(50.0, 0.0, 0.0)))
    pal.add_swatch(Swatch(name="Gray Mid", color_model="GRAY", values=(0.5,)))

    aco_data = pal.to_aco()
    loaded = SwatchPalette.from_aco(aco_data)
    assert len(loaded.swatches) == 5
    assert loaded.swatches[0].color_model == "RGB"
    assert loaded.swatches[1].color_model == "HSB"
    assert loaded.swatches[2].color_model == "CMYK"
    assert loaded.swatches[3].color_model == "LAB"
    assert loaded.swatches[4].color_model == "GRAY"


def test_ase_roundtrip(tmp_path):
    pal = SwatchPalette(name="ExchangePalette")
    pal.add_swatch(Swatch.from_rgb(255, 128, 0, name="Amber"))
    pal.add_swatch(
        Swatch(name="Spot Cyan", color_model="CMYK", values=(1.0, 0.0, 0.0, 0.0), color_type="spot")
    )

    grp = SwatchGroup(name="Pastels")
    grp.swatches.append(Swatch.from_rgb(255, 200, 200, name="Pastel Pink"))
    grp.swatches.append(Swatch.from_rgb(200, 255, 200, name="Pastel Mint"))
    pal.groups.append(grp)

    ase_bytes = pal.to_ase()
    out_file = tmp_path / "test.ase"
    out_file.write_bytes(ase_bytes)

    loaded = SwatchPalette.load(out_file)
    assert len(loaded.swatches) == 2
    assert loaded.swatches[0].name == "Amber"
    assert loaded.swatches[0].to_rgb() == (255, 128, 0)
    assert loaded.swatches[1].name == "Spot Cyan"
    assert loaded.swatches[1].color_type == "spot"

    assert len(loaded.groups) == 1
    assert loaded.groups[0].name == "Pastels"
    assert len(loaded.groups[0].swatches) == 2
    assert loaded.groups[0].swatches[0].name == "Pastel Pink"
    assert loaded.groups[0].swatches[1].name == "Pastel Mint"


def test_ase_color_models():
    pal = SwatchPalette(name="ASE Models")
    pal.add_swatch(Swatch(name="RGB Blue", color_model="RGB", values=(0.0, 0.0, 1.0)))
    pal.add_swatch(Swatch(name="CMYK Yellow", color_model="CMYK", values=(0.0, 0.0, 1.0, 0.0)))
    pal.add_swatch(Swatch(name="Lab Greenish", color_model="LAB", values=(60.0, -40.0, 30.0)))
    pal.add_swatch(Swatch(name="Gray Light", color_model="GRAY", values=(0.8,)))

    ase_data = pal.to_ase()
    loaded = SwatchPalette.from_ase(ase_data)
    assert len(loaded.swatches) == 4
    assert loaded.swatches[0].color_model == "RGB"
    assert loaded.swatches[1].color_model == "CMYK"
    assert loaded.swatches[2].color_model == "LAB"
    assert loaded.swatches[3].color_model == "GRAY"


def test_bounds_checking_corrupt_aco():
    with pytest.raises(ValueError, match="too short"):
        SwatchPalette.from_aco(b"")

    with pytest.raises(ValueError, match="too short"):
        SwatchPalette.from_aco(b"\x00\x01\x00")

    with pytest.raises(ValueError, match="Invalid or unsupported ACO version"):
        SwatchPalette.from_aco(b"\x00\x03\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")

    with pytest.raises(ValueError, match="Absurdly large swatch count"):
        SwatchPalette.from_aco(b"\x00\x01\xff\xff")

    with pytest.raises(ValueError, match="Truncated ACO version 1 color data"):
        # Header says count=5, but data only has 10 bytes (1 color)
        SwatchPalette.from_aco(b"\x00\x01\x00\x05" + b"\x00" * 10)


def test_bounds_checking_corrupt_ase():
    with pytest.raises(ValueError, match="too short"):
        SwatchPalette.from_ase(b"")

    with pytest.raises(ValueError, match="Invalid ASE header signature"):
        SwatchPalette.from_ase(b"NOPE\x00\x01\x00\x00\x00\x00\x00\x01")

    with pytest.raises(ValueError, match="Unsupported ASE major version"):
        SwatchPalette.from_ase(b"ASEF\x00\x02\x00\x00\x00\x00\x00\x01")

    with pytest.raises(ValueError, match="Truncated ASE file"):
        # Header claims 1 block, but file ends right after header
        SwatchPalette.from_ase(b"ASEF\x00\x01\x00\x00\x00\x00\x00\x01")

    with pytest.raises(ValueError, match="Truncated ASE block payload"):
        # Header claims 1 block, block header says length 100, but data has only 2 bytes
        SwatchPalette.from_ase(
            b"ASEF\x00\x01\x00\x00\x00\x00\x00\x01\x00\x01\x00\x00\x00\x64\x00\x00"
        )


def test_desktop_swatches_ui(qapp, tmp_path):
    pal = SwatchPalette.default_palette()
    assert len(pal.all_swatches()) >= 16

    widget = SwatchesWidget(pal)
    assert widget.grid_layout.count() >= 16

    # Test clicking swatch
    selected = []
    widget.colorSelected.connect(lambda c, is_fg: selected.append((c, is_fg)))
    first_cell = widget.grid_layout.itemAt(0).widget()
    assert first_cell is not None
    first_cell.swatchSelected.emit(QColor(255, 0, 0), True)
    assert selected == [(QColor(255, 0, 0), True)]

    # Test import and export via widget methods
    export_aco = tmp_path / "exported.aco"
    widget.export_palette(str(export_aco))
    assert export_aco.exists()

    widget.import_palette(str(export_aco))
    assert len(widget.palette.all_swatches()) == len(pal.all_swatches())

    # Test SwatchesPanel
    panel = SwatchesPanel()
    assert panel.widget is not None

    # Test ColorWithSwatchesDialog
    dlg = ColorWithSwatchesDialog(initial_color=QColor(100, 150, 200))
    assert dlg.color() == QColor(100, 150, 200)
