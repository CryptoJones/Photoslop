# SPDX-License-Identifier: Apache-2.0
"""CLI I/O and error paths, plus the installed console entry point."""

import subprocess
import sys

import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage

from photoslop import cli
from photoslop.document import Document
from photoslop.io_ora import load_ora, save_ora
from photoslop.layer import Layer
from tests.test_camera_raw import FakeRawpy


def make_layered_ora(tmp_path) -> str:
    doc = Document.new(QSize(50, 40), 72.0, "io", QColor(255, 255, 255))
    chip = Layer.blank("chip", QSize(15, 15), QPoint(10, 10))
    chip.image.fill(QColor(255, 0, 0))
    chip.effects = [("stroke", 2, [0, 0, 255, 255])]
    chip.fill_opacity = 0.5
    doc.layers.append(chip)
    doc.artboards = [("Cover", QRect(0, 0, 25, 20))]
    path = str(tmp_path / "in.ora")
    save_ora(doc, path)
    return path


def test_ora_round_trip_preserves_everything(qapp, tmp_path):
    src = make_layered_ora(tmp_path)
    out = str(tmp_path / "out.ora")
    assert cli.main([src, "--levels", "10,240,1.1", "--output", out]) == 0
    loaded = load_ora(out)
    assert len(loaded.layers) == 2
    assert loaded.layers[1].effects == [("stroke", 2, (0, 0, 255, 255))] or \
        loaded.layers[1].effects == [("stroke", 2, [0, 0, 255, 255])]
    assert abs(loaded.layers[1].fill_opacity - 0.5) < 1e-6
    assert loaded.artboards[0][0] == "Cover"


def test_raster_output_flattens(qapp, tmp_path):
    src = make_layered_ora(tmp_path)
    out = str(tmp_path / "flat.png")
    assert cli.main([src, "--output", out]) == 0
    img = QImage(out)
    assert img.size() == QSize(50, 40)
    ring = img.pixelColor(9, 17)  # stroke effect baked into the raster
    assert ring.blue() > 180 and ring.red() < 100


def test_raw_input_via_fake_rawpy(qapp, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "rawpy", FakeRawpy())
    fake = tmp_path / "shot.nef"
    fake.write_bytes(b"raw-ish")
    out = str(tmp_path / "out.png")
    assert cli.main([str(fake), "--output", out]) == 0
    img = QImage(out)
    assert img.width() == 8 and img.height() == 6
    assert img.pixelColor(0, 0).red() == 200


def test_export_artboards_flag(qapp, tmp_path):
    src = make_layered_ora(tmp_path)
    boards = tmp_path / "boards"
    assert cli.main([src, "--export-artboards", str(boards)]) == 0
    assert QImage(str(boards / "Cover.png")).size() == QSize(25, 20)


def test_error_paths(qapp, tmp_path):
    out = str(tmp_path / "out.png")
    with pytest.raises(SystemExit) as exc:  # missing input
        cli.main(["nope.png", "--output", out])
    assert exc.value.code == 2

    src = make_layered_ora(tmp_path)
    with pytest.raises(SystemExit) as exc:  # unknown output extension
        cli.main([src, "--output", str(tmp_path / "out.xyz")])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:  # nothing to do
        cli.main([src])
    assert exc.value.code == 2

    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not an image")
    with pytest.raises(SystemExit) as exc:
        cli.main([str(junk), "--output", out])
    assert exc.value.code == 2

    # unreachable model backend is a runtime failure (1), not usage (2)
    assert cli.main([src, "--model-url", "http://127.0.0.1:1/x",
                     "--select-subject", "--output", out]) == 1


def test_console_entry_point_end_to_end(qapp, tmp_path):
    img = QImage(30, 20, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(QColor(90, 90, 90))
    src = str(tmp_path / "in.png")
    img.save(src)
    out = str(tmp_path / "out.png")

    proc = subprocess.run(
        ["uv", "run", "photoslop-cli", src, "--resize", "15x10",
         "--hue-sat", "0,0,40", "--output", out],
        capture_output=True, text=True, cwd="/home/hermes/Source/repos/Photoslop")
    assert proc.returncode == 0, proc.stderr
    result = QImage(out)
    assert result.size() == QSize(15, 10)
    assert result.pixelColor(5, 5).red() > 120

    proc = subprocess.run(
        ["uv", "run", "photoslop-cli", src, "--resize", "banana",
         "--output", out],
        capture_output=True, text=True, cwd="/home/hermes/Source/repos/Photoslop")
    assert proc.returncode == 2
    assert "WxH" in proc.stderr
