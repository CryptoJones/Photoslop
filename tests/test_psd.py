# SPDX-License-Identifier: Apache-2.0
"""Photoshop (.psd) open and export — round trip, interchange shape, limits."""

import struct
import zlib

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


def _flat(doc):
    img = doc.flatten()
    return view_u32(img).copy()


def test_psd_export_bakes_effects_and_adjustment_layers(qapp, tmp_path):
    from photoslop.appearance import new_effect

    doc = Document.new(QSize(40, 30), 72.0, "fx", QColor(90, 120, 150))
    dot = Layer.blank("dot", QSize(10, 10), QPoint(15, 10))
    dot.image.fill(QColor(255, 0, 0, 255))
    dot.effects = [new_effect("drop-shadow")]
    dot.fill_opacity = 0.5
    doc.layers.append(dot)
    invert = Layer.blank("invert", doc.size)
    invert.adjustment = np.tile(np.arange(255, -1, -1, dtype=np.uint8), (3, 1))
    doc.layers.append(invert)
    before = _flat(doc)

    path = str(tmp_path / "fx.psd")
    save_psd(doc, path)
    loaded = load_psd(path)
    assert [layer.name for layer in loaded.layers] == ["Background", "dot", "invert"]
    baked = loaded.layers[1]
    assert baked.offset.x() < 15 and baked.image.width() > 10  # padded by the shadow's reach
    assert baked.fill_opacity == pytest.approx(1.0)  # folded into the pixels, not carried twice
    assert baked.effects == [] and baked.adjustment is None
    assert loaded.layers[2].image.size() == doc.size and loaded.layers[2].adjustment is None
    after = _flat(loaded)
    diff = np.abs(before.view(np.uint8).astype(int) - after.view(np.uint8).astype(int))
    assert diff.max() <= 2


def _float_psd(compression: int, psb: bool = False) -> bytes:
    """A hand-written 32-bit float RGB document: 4×2, linear (0.5, 0.0, 1.0)
    at alpha 1 with its one layer in an ``Lr32`` block, as Photoshop writes."""
    w, h = 4, 2
    values = {0: 0.5, 1: 0.0, 2: 1.0, -1: 1.0}

    def plane(v: float) -> bytes:
        rows = np.full((h, w), v, dtype=">f4")
        if compression == 0:
            return b"\x00\x00" + rows.tobytes()
        raw = rows.tobytes()
        planar = np.frombuffer(raw, np.uint8).reshape(h, w, 4).transpose(0, 2, 1).reshape(h, w * 4)
        delta = np.diff(planar, axis=1, prepend=np.zeros((h, 1), np.uint8)).astype(np.uint8)
        return b"\x00\x03" + zlib.compress(delta.tobytes())

    channels = [(cid, plane(values[cid])) for cid in (-1, 0, 1, 2)]
    length = (lambda n: struct.pack(">Q", n)) if psb else (lambda n: struct.pack(">I", n))
    record = struct.pack(">iiii", 0, 0, h, w) + struct.pack(">H", len(channels))
    for cid, payload in channels:
        record += struct.pack(">h", cid) + length(len(payload))
    name = b"\x05Float\x00\x00"  # pascal name padded to 4
    extra = struct.pack(">I", 0) + struct.pack(">I", 0) + name  # no mask, no blending ranges
    record += b"8BIMnorm" + bytes([255, 0, 0, 0]) + struct.pack(">I", len(extra)) + extra
    layer_info = struct.pack(">h", -1) + record + b"".join(p for _, p in channels)
    if len(layer_info) % 2:
        layer_info += b"\0"
    key_len = struct.pack(">Q", len(layer_info)) if psb else struct.pack(">I", len(layer_info))
    block = b"8BIMLr32" + key_len + layer_info
    layer_and_mask = length(0) + struct.pack(">I", 0) + block  # empty main section, no global mask
    merged = b"\x00\x00" + b"".join(
        np.full((h, w), values[c], dtype=">f4").tobytes() for c in (0, 1, 2, -1)
    )
    header = SIGNATURE + struct.pack(">H6xHIIHH", 2 if psb else 1, 4, h, w, 32, 3)
    return (
        header
        + struct.pack(">I", 0)
        + struct.pack(">I", 0)
        + length(len(layer_and_mask))
        + layer_and_mask
        + merged
    )


@pytest.mark.parametrize("compression,psb", [(0, False), (3, False), (3, True)])
def test_psd_opens_32bit_float_layers_from_lr32(qapp, tmp_path, compression, psb):

    path = str(tmp_path / ("f.psb" if psb else "f.psd"))
    with open(path, "wb") as fh:
        fh.write(_float_psd(compression, psb))
    doc = load_psd(path)
    assert doc.size == QSize(4, 2)
    assert [layer.name for layer in doc.layers] == ["Float"]
    r, g, b, a = doc.layers[0].image.pixelColor(1, 1).getRgb()
    assert (abs(r - 188), g, b, a) <= (1, 0, 255, 255)  # linear 0.5 is sRGB 188
    composite, *_ = probe_psd(path)
    assert abs(composite.pixelColor(0, 0).red() - 188) <= 1
