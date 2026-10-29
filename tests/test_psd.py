# SPDX-License-Identifier: Apache-2.0
"""Photoshop (.psd) open and export — round trip, interchange shape, limits."""

import struct

import numpy as np
import pytest
from PySide6.QtCore import QPoint, QSize
from PySide6.QtGui import QColor, QImage

from photoslop.document import Document
from photoslop.io_psd import SIGNATURE, PSDError, encode_psd, load_psd, probe_psd, save_psd
from photoslop.layer import Layer
from photoslop.npimage import view_u32
from photoslop.resources import ResourceLimitError
from photoslop.services import FileService


def _doc():
    doc = Document.new(QSize(40, 30), 144.0, "art", QColor(10, 20, 30))
    top = Layer.blank("scribble ü", QSize(16, 12), QPoint(5, 7))
    top.image.fill(QColor(200, 100, 50, 128))
    top.opacity = 0.5
    top.blend_mode = "multiply"
    top.visible = False
    top.clipped = True
    top.fill_opacity = 0.25
    top.group = "Sketch"
    mask = QImage(16, 12, QImage.Format.Format_Grayscale8)
    mask.fill(255)
    for x in range(8):
        for y in range(12):
            mask.setPixel(x, y, 0)
    top.mask = mask
    doc.layers.append(top)
    doc.group_props["Sketch"] = {"opacity": 0.75, "blend_mode": "screen"}
    return doc


def test_psd_round_trip(qapp, tmp_path):
    path = str(tmp_path / "art.psd")
    save_psd(_doc(), path)
    with open(path, "rb") as fh:
        head = fh.read(26)
    assert head[:4] == SIGNATURE
    assert struct.unpack(">H6xHIIHH", head[4:]) == (1, 4, 30, 40, 8, 3)

    loaded = load_psd(path)
    assert loaded.size == QSize(40, 30)
    assert loaded.dpi == pytest.approx(144.0)
    assert [layer.name for layer in loaded.layers] == ["Background", "scribble ü"]
    assert loaded.layers[0].image.pixelColor(3, 3).getRgb() == (10, 20, 30, 255)
    top = loaded.layers[1]
    assert top.offset == QPoint(5, 7)
    assert top.image.size() == QSize(16, 12)
    r, g, b, a = top.image.pixelColor(0, 0).getRgb()
    assert (abs(r - 200), g, b, a) <= (1, 100, 50, 128)
    assert top.opacity == pytest.approx(0.5, abs=1 / 255)
    assert top.fill_opacity == pytest.approx(0.25, abs=1 / 255)
    assert top.blend_mode == "multiply"
    assert top.visible is False
    assert top.clipped is True
    assert top.group == "Sketch"
    assert loaded.group_props["Sketch"]["blend_mode"] == "screen"
    assert loaded.group_props["Sketch"]["opacity"] == pytest.approx(0.75, abs=1 / 255)
    assert top.mask.pixelColor(0, 0).red() == 0 and top.mask.pixelColor(10, 0).red() == 255
    assert loaded.active_index == 1 and loaded.path == path


def test_psd_probe_reads_only_the_composite(qapp, tmp_path):
    path = str(tmp_path / "art.psd")
    save_psd(_doc(), path)
    img, w, h, layers = probe_psd(path)
    assert (w, h, layers) == (40, 30, 4)  # two pixel layers + divider + folder
    assert img.pixelColor(3, 3).getRgb() == (10, 20, 30, 255)


def test_psd_noisy_pixels_survive_packbits(qapp, tmp_path):
    doc = Document.new(QSize(300, 200), 72.0, "noise", QColor(0, 0, 0))
    rng = np.random.default_rng(7)
    words = rng.integers(0, 1 << 24, (200, 300), dtype=np.uint32) | 0xFF000000
    view_u32(doc.layers[0].image)[:] = words
    path = str(tmp_path / "noise.psd")
    save_psd(doc, path)
    back = load_psd(path)
    assert np.array_equal(view_u32(back.layers[0].image), words)


def test_psd_flat_file_without_layers_opens_as_one_layer(qapp, tmp_path):
    # Header + empty colour mode + empty resources + empty layer section + raw RGB.
    w, h = 3, 2
    header = SIGNATURE + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3)
    planes = bytes([9] * (w * h)) + bytes([8] * (w * h)) + bytes([7] * (w * h))
    data = header + struct.pack(">I", 0) + struct.pack(">I", 0) + struct.pack(">I", 0)
    data += struct.pack(">H", 0) + planes
    path = tmp_path / "flat.psd"
    path.write_bytes(data)
    doc = load_psd(str(path))
    assert len(doc.layers) == 1
    assert doc.layers[0].image.pixelColor(1, 1).getRgb() == (9, 8, 7, 255)


def test_psd_rejects_garbage_and_huge_canvases(qapp, tmp_path):
    junk = tmp_path / "junk.psd"
    junk.write_bytes(b"not a psd at all")
    with pytest.raises(PSDError):
        load_psd(str(junk))
    huge = tmp_path / "huge.psd"
    huge.write_bytes(SIGNATURE + struct.pack(">H6xHIIHH", 1, 3, 200_000, 200_000, 8, 3))
    with pytest.raises(ResourceLimitError):
        load_psd(str(huge))
    truncated = tmp_path / "short.psd"
    truncated.write_bytes(encode_psd(_doc())[:400])
    with pytest.raises(PSDError):
        load_psd(str(truncated))


def test_file_service_routes_psd(qapp, tmp_path):
    path = str(tmp_path / "svc.psd")
    FileService.save(_doc(), path)
    doc = FileService.load(path)
    assert [layer.name for layer in doc.layers] == ["Background", "scribble ü"]
