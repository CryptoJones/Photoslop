# SPDX-License-Identifier: Apache-2.0
"""Adobe Photoshop (.psd / .psb) open and export.

A self-contained codec for the documented parts of the format: 8- and
16-bit RGB, Grayscale, CMYK, Indexed, Duotone and Bitmap composites; layers
with offsets, opacity, fill opacity, blend modes, visibility, clipping,
user masks and group folders (``lsct`` section dividers). Writing produces
8-bit RGB with per-layer RLE (PackBits) channels and a merged RGBA composite,
which is the subset every other PSD reader (Photoshop, GIMP, Krita,
Affinity, psd-tools) agrees on.

Photoshop-only constructs — adjustment layers, live effects, smart objects,
editable text — have no portable encoding, so they are baked on export: a
layer with live effects is written as the pixels it composites to (padded by
the effects' reach), an adjustment layer as the composite below it with the
adjustment applied, and a smart object as its filtered pixels. ``.ora``
remains the lossless native format.

32-bit float documents open too: Photoshop stores them in linear light, so
colour channels are clipped to 0..1 and sRGB-encoded to 8-bit; alpha and
masks scale linearly. 16- and 32-bit layers live in a global ``Lr16``/``Lr32``
block rather than the main layer section, and both are read.
"""

from __future__ import annotations

import contextlib
import mmap
import os
import struct
import zlib
from types import SimpleNamespace

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QImage, QPainter

from photoslop.atomicio import WriteTicket, atomic_write
from photoslop.document import Document
from photoslop.layer import FORMAT, Layer
from photoslop.resources import (
    DESKTOP_BUDGET,
    ResourceLimitError,
    validate_dimensions,
    validate_dpi,
)

SIGNATURE = b"8BPS"
_PSB_LIMIT = 30_000  # PSD rects are capped at 30 000 px; beyond that is PSB

# Photoslop blend-mode name <-> Photoshop 4-byte blend key.
BLEND_KEYS: dict[str, bytes] = {
    "normal": b"norm",
    "multiply": b"mul ",
    "screen": b"scrn",
    "overlay": b"over",
    "darken": b"dark",
    "lighten": b"lite",
    "color-dodge": b"div ",
    "color-burn": b"idiv",
    "hard-light": b"hLit",
    "soft-light": b"sLit",
    "difference": b"diff",
    "exclusion": b"smud",
    "addition": b"lddg",
}
BLEND_KEYS_REVERSE: dict[bytes, str] = {v: k for k, v in BLEND_KEYS.items()}
BLEND_KEYS_REVERSE[b"pass"] = "normal"  # pass-through folders composite as normal

_RES_RESOLUTION = 0x03ED
_RES_ICC = 0x040F
_MODE_BITMAP, _MODE_GRAY, _MODE_INDEXED, _MODE_RGB, _MODE_CMYK = 0, 1, 2, 3, 4
_MODE_DUOTONE, _MODE_LAB = 8, 9
_SUPPORTED_MODES = frozenset(
    {_MODE_BITMAP, _MODE_GRAY, _MODE_INDEXED, _MODE_RGB, _MODE_CMYK, _MODE_DUOTONE, _MODE_LAB}
)
_DIVIDER_NAME = "</Layer group>"
# Additional-info keys whose length field widens to 8 bytes in a PSB.
_PSB_WIDE_KEYS = frozenset(
    {
        b"LMsk", b"Lr16", b"Lr32", b"Layr", b"Mt16", b"Mt32", b"Mtrn",
        b"Alph", b"FMsk", b"lnk2", b"FEid", b"FXid", b"PxSD",
    }
)  # fmt: skip


class PSDError(ValueError):
    """The file is not a PSD/PSB Photoslop can decode."""


# ---------------------------------------------------------------------------
# PackBits
# ---------------------------------------------------------------------------


def _packbits_row(row: np.ndarray) -> bytes:
    """PackBits-encode one row of uint8. Runs of three or more repeat."""
    n = row.size
    if n == 0:
        return b""
    out = bytearray()
    change = np.flatnonzero(row[1:] != row[:-1]) + 1
    starts = np.concatenate(([0], change))
    lengths = np.diff(np.concatenate((starts, [n])))
    repeats = np.flatnonzero(lengths >= 3)
    row_bytes = row.tobytes()

    def literal(a: int, b: int) -> None:
        for k in range(a, b, 128):
            end = min(k + 128, b)
            out.append(end - k - 1)
            out.extend(row_bytes[k:end])

    cursor = 0
    for ri in repeats.tolist():
        s = int(starts[ri])
        ln = int(lengths[ri])
        if s > cursor:
            literal(cursor, s)
        value = row_bytes[s]
        cursor = s + ln
        while ln > 0:
            chunk = min(ln, 128)
            out.append(257 - chunk)
            out.append(value)
            ln -= chunk
    if cursor < n:
        literal(cursor, n)
    return bytes(out)


def _unpackbits(src: memoryview, expected: int) -> bytes:
    out = bytearray()
    i, n = 0, len(src)
    while i < n and len(out) < expected:
        header = src[i]
        i += 1
        if header < 128:
            count = header + 1
            out.extend(src[i : i + count])
            i += count
        elif header > 128:
            if i >= n:
                break
            out.extend(bytes((src[i],)) * (257 - header))
            i += 1
    if len(out) < expected:
        raise PSDError("Photoshop: truncated RLE scanline")
    return bytes(out[:expected])


# ---------------------------------------------------------------------------
# Binary cursor
# ---------------------------------------------------------------------------


class _Reader:
    __slots__ = ("data", "pos", "psb")

    def __init__(self, data, pos: int = 0, psb: bool = False) -> None:
        self.data = data
        self.pos = pos
        self.psb = psb

    def take(self, n: int) -> memoryview:
        if n < 0 or self.pos + n > len(self.data):
            raise PSDError("Photoshop: truncated file")
        view = memoryview(self.data)[self.pos : self.pos + n]
        self.pos += n
        return view

    def _unpack(self, fmt: str):
        return struct.unpack(fmt, self.take(struct.calcsize(fmt)))[0]

    def u8(self) -> int:
        return self._unpack(">B")

    def u16(self) -> int:
        return self._unpack(">H")

    def i16(self) -> int:
        return self._unpack(">h")

    def u32(self) -> int:
        return self._unpack(">I")

    def i32(self) -> int:
        return self._unpack(">i")

    def u64(self) -> int:
        return self._unpack(">Q")

    def length(self) -> int:
        """A section length: 4 bytes in a PSD, 8 in a PSB."""
        return self.u64() if self.psb else self.u32()

    def pascal(self, pad: int) -> str:
        n = self.u8()
        raw = bytes(self.take(n))
        total = 1 + n
        if total % pad:
            self.take(pad - total % pad)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("mac_roman", errors="replace")


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _pascal(name: str, pad: int) -> bytes:
    raw = name.encode("utf-8")[:255]
    out = bytes((len(raw),)) + raw
    if len(out) % pad:
        out += b"\0" * (pad - len(out) % pad)
    return out


def _info_block(key: bytes, payload: bytes) -> bytes:
    if len(payload) % 2:
        payload += b"\0"
    return b"8BIM" + key + struct.pack(">I", len(payload)) + payload


def _unicode_block(name: str) -> bytes:
    utf16 = name.encode("utf-16-be")
    return _info_block(b"luni", struct.pack(">I", len(utf16) // 2) + utf16)


def _straight_channels(img: QImage) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(R, G, B, A) uint8 planes, un-premultiplied, from a premultiplied QImage."""
    if img.format() != FORMAT:
        img = img.convertToFormat(FORMAT)
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=h * bpl).reshape(h, bpl)
    px = raw[:, : w * 4].reshape(h, w, 4)  # little-endian ARGB32 = B, G, R, A
    a = px[:, :, 3]
    a32 = a.astype(np.uint32)
    safe = np.maximum(a32, 1)

    def straight(c: np.ndarray) -> np.ndarray:
        scaled = (c.astype(np.uint32) * 255 + a32 // 2) // safe
        return np.where(a32 > 0, scaled, 0).astype(np.uint8)

    return (
        straight(px[:, :, 2]),
        straight(px[:, :, 1]),
        straight(px[:, :, 0]),
        np.ascontiguousarray(a),
    )


def _rle_rows(planes, psb: bool) -> tuple[bytes, bytes]:
    """(row-count table, packed data) across every row of every plane given."""
    rows = [
        _packbits_row(np.ascontiguousarray(plane[y]))
        for plane in planes
        for y in range(plane.shape[0])
    ]
    counts = struct.pack(f">{len(rows)}{'I' if psb else 'H'}", *(len(r) for r in rows))
    return counts, b"".join(rows)


def _rle_channel(plane: np.ndarray, psb: bool) -> bytes:
    """compression word + row counts + PackBits data for one channel."""
    counts, data = _rle_rows((plane,), psb)
    return b"\x00\x01" + counts + data


def _mask_plane(mask: QImage) -> np.ndarray:
    gray8 = QImage.Format.Format_Grayscale8
    gray = mask if mask.format() == gray8 else mask.convertToFormat(gray8)
    h, w, bpl = gray.height(), gray.width(), gray.bytesPerLine()
    raw = np.frombuffer(gray.constBits(), dtype=np.uint8, count=h * bpl).reshape(h, bpl)
    return np.ascontiguousarray(raw[:, :w])


def _rect_bytes(rect: QRect) -> bytes:
    return struct.pack(
        ">iiii", rect.top(), rect.left(), rect.top() + rect.height(), rect.left() + rect.width()
    )


def _layer_record(
    *,
    rect: QRect,
    channels: list[tuple[int, bytes]],
    blend: str,
    opacity: float,
    clipped: bool,
    visible: bool,
    name: str,
    mask_rect: QRect | None,
    section: int | None,
    fill_opacity: float,
    psb: bool,
) -> bytes:
    rec = _rect_bytes(rect) + struct.pack(">H", len(channels))
    for cid, payload in channels:
        rec += struct.pack(">h", cid) + struct.pack(">Q" if psb else ">I", len(payload))
    flags = (0 if visible else 0x02) | (0x18 if section is not None else 0x08)
    rec += b"8BIM" + BLEND_KEYS.get(blend, b"norm")
    alpha = int(round(max(0.0, min(1.0, opacity)) * 255))
    rec += struct.pack(">BBBB", alpha, 1 if clipped else 0, flags, 0)
    extra = b""
    if mask_rect is not None:
        extra += struct.pack(">I", 20) + _rect_bytes(mask_rect) + struct.pack(">BBH", 255, 0, 0)
    else:
        extra += struct.pack(">I", 0)
    extra += struct.pack(">I", 0)  # blending ranges
    extra += _pascal(name, 4)
    extra += _unicode_block(name)
    if section is not None:
        extra += _info_block(
            b"lsct", struct.pack(">I", section) + b"8BIM" + BLEND_KEYS.get(blend, b"pass")
        )
    if fill_opacity < 1.0:
        fill = int(round(max(0.0, fill_opacity) * 255))
        extra += _info_block(b"iOpa", struct.pack(">B", fill) + b"\0\0\0")
    return rec + struct.pack(">I", len(extra)) + extra


def _baked(doc: Document, index: int) -> tuple[QImage, QPoint] | None:
    """(pixels, offset) for a layer whose look is not its pixels, or None when
    ``layer.image`` is already faithful.

    Live effects are rendered into the layer — padded by how far they reach,
    clipped to the canvas — with its mask, clipping and fill opacity applied,
    so the record carries no mask and a fill opacity of 1. An adjustment layer
    becomes the composite below it with the adjustment applied; a reader draws
    that over the same composite, which is exact wherever the composite is
    opaque. Smart filters already live in ``layer.image``."""
    from photoslop.appearance import effect_margin
    from photoslop.document import draw_layer, render_region
    from photoslop.layer import blank_image

    layer = doc.layers[index]
    canvas = doc.canvas_rect()
    if layer.adjustment is not None:
        from photoslop.adjust import apply_luts

        below = SimpleNamespace(layers=doc.layers[:index], group_props=doc.group_props)
        out = render_region(below, canvas)
        apply_luts(out, layer.adjustment)
        return out, canvas.topLeft()
    if not layer.effects:
        return None
    margin = effect_margin(layer.effects)
    region = layer.bounds().adjusted(-margin, -margin, margin, margin).intersected(canvas)
    if region.isEmpty():
        return None
    out = blank_image(region.size())
    p = QPainter(out)
    p.translate(-region.topLeft())
    draw_layer(p, doc, layer, region)
    p.end()
    return out, region.topLeft()


def _pixel_layer(doc: Document, index: int, psb: bool) -> tuple[bytes, bytes]:
    """(record, channel data) for one raster layer."""
    layer = doc.layers[index]
    baked = _baked(doc, index)
    if baked is None:
        img, offset, mask = layer.image, layer.offset, layer.mask
        fill_opacity = float(getattr(layer, "fill_opacity", 1.0))
    else:
        (img, offset), mask, fill_opacity = baked, None, 1.0
    rect = QRect(offset, img.size())
    r, g, b, a = _straight_channels(img)
    channels: list[tuple[int, bytes]] = [
        (-1, _rle_channel(a, psb)),
        (0, _rle_channel(r, psb)),
        (1, _rle_channel(g, psb)),
        (2, _rle_channel(b, psb)),
    ]
    mask_rect = None
    if mask is not None and not mask.isNull():
        mask_rect = QRect(offset, mask.size())
        channels.append((-2, _rle_channel(_mask_plane(mask), psb)))
    record = _layer_record(
        rect=rect,
        channels=channels,
        blend=layer.blend_mode,
        opacity=layer.opacity,
        clipped=bool(layer.clipped),
        visible=bool(layer.visible),
        name=layer.name,
        mask_rect=mask_rect,
        section=None,
        fill_opacity=fill_opacity,
        psb=psb,
    )
    return record, b"".join(payload for _, payload in channels)


def _section_layer(
    name: str, section: int, blend: str, opacity: float, psb: bool
) -> tuple[bytes, bytes]:
    empty = b"\x00\x00"  # raw compression, zero bytes: the rect is empty
    channels = [(-1, empty), (0, empty), (1, empty), (2, empty)]
    record = _layer_record(
        rect=QRect(0, 0, 0, 0),
        channels=channels,
        blend=blend,
        opacity=opacity,
        clipped=False,
        visible=True,
        name=name,
        mask_rect=None,
        section=section,
        fill_opacity=1.0,
        psb=psb,
    )
    return record, empty * 4


def _resource_block(rid: int, payload: bytes) -> bytes:
    block = b"8BIM" + struct.pack(">H", rid) + b"\0\0" + struct.pack(">I", len(payload)) + payload
    return block + (b"\0" if len(payload) % 2 else b"")


def _resolution_block(dpi: float) -> bytes:
    fixed = int(round(dpi * 65536))
    return _resource_block(_RES_RESOLUTION, struct.pack(">ihhihh", fixed, 1, 1, fixed, 1, 1))


def _icc_block(doc: Document) -> bytes:
    space = getattr(doc, "icc_space", None)
    if space is None or not space.isValid():
        return b""
    icc = bytes(space.iccProfile())
    return _resource_block(_RES_ICC, icc) if icc else b""


def encode_psd(doc: Document) -> bytes:
    """Serialise a document to PSD bytes (PSB when a side exceeds 30 000 px)."""
    w, h = doc.size.width(), doc.size.height()
    psb = w > _PSB_LIMIT or h > _PSB_LIMIT
    records: list[bytes] = []
    pixels: list[bytes] = []
    open_group: str | None = None

    def emit(pair: tuple[bytes, bytes]) -> None:
        records.append(pair[0])
        pixels.append(pair[1])

    def close_group(name: str) -> None:
        props = doc.group_props.get(name, {})
        blend = str(props.get("blend_mode", "normal"))
        emit(_section_layer(name, 1, blend, float(props.get("opacity", 1.0)), psb))

    for index, layer in enumerate(doc.layers):  # bottom first, which is the file order too
        group = layer.group
        if group != open_group:
            if open_group is not None:
                close_group(open_group)
            if group is not None:
                emit(_section_layer(_DIVIDER_NAME, 3, "normal", 1.0, psb))
            open_group = group
        emit(_pixel_layer(doc, index, psb))
    if open_group is not None:
        close_group(open_group)

    layer_info = struct.pack(">h", -len(records)) + b"".join(records) + b"".join(pixels)
    if len(layer_info) % 2:
        layer_info += b"\0"
    length_fmt = ">Q" if psb else ">I"
    layer_and_mask = struct.pack(length_fmt, len(layer_info)) + layer_info + struct.pack(">I", 0)

    counts, data = _rle_rows(_straight_channels(doc.flatten()), psb)
    image_data = b"\x00\x01" + counts + data

    resources = _resolution_block(doc.dpi) + _icc_block(doc)
    header = SIGNATURE + struct.pack(">H6xHIIHH", 2 if psb else 1, 4, h, w, 8, _MODE_RGB)
    return (
        header
        + struct.pack(">I", 0)
        + struct.pack(">I", len(resources))
        + resources
        + struct.pack(length_fmt, len(layer_and_mask))
        + layer_and_mask
        + image_data
    )


def save_psd(
    doc: Document, path: str, *, ticket: WriteTicket | None = None, before_commit=None
) -> None:
    def writer(temporary: str) -> None:
        with open(temporary, "wb") as fh:
            fh.write(encode_psd(doc))

    if ticket is None:
        atomic_write(path, writer, before_commit=before_commit, durable=True)
    else:
        ticket.write(writer, before_commit=before_commit, durable=True)


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


class _Header:
    __slots__ = ("psb", "channels", "height", "width", "depth", "mode")

    def __init__(self, rd: _Reader) -> None:
        if bytes(rd.take(4)) != SIGNATURE:
            raise PSDError("Photoshop: not a PSD file (bad signature)")
        version = rd.u16()
        if version not in (1, 2):
            raise PSDError(f"Photoshop: unsupported version {version}")
        self.psb = version == 2
        rd.psb = self.psb
        rd.take(6)
        self.channels = rd.u16()
        self.height = rd.u32()
        self.width = rd.u32()
        self.depth = rd.u16()
        self.mode = rd.u16()
        if self.depth not in (1, 8, 16, 32):
            raise PSDError(f"Photoshop: {self.depth}-bit documents are not supported")
        if self.mode not in _SUPPORTED_MODES:
            raise PSDError(f"Photoshop: colour mode {self.mode} is not supported")

    @property
    def colour_channels(self) -> int:
        return {_MODE_CMYK: 4, _MODE_RGB: 3, _MODE_LAB: 3}.get(self.mode, 1)


def _bytes_per_sample(depth: int) -> int:
    return {16: 2, 32: 4}.get(depth, 1)


def _row_bytes(width: int, depth: int) -> int:
    return (width + 7) // 8 if depth == 1 else width * _bytes_per_sample(depth)


def _float_to_u8(plane: np.ndarray, srgb: bool) -> np.ndarray:
    """A 32-bit float plane as 8-bit: clipped to 0..1 and, for colour,
    sRGB-encoded (Photoshop keeps 32-bit documents in linear light)."""
    f = np.clip(np.nan_to_num(plane.astype(np.float32), nan=0.0, posinf=1.0, neginf=0.0), 0.0, 1.0)
    if srgb:
        f = np.where(f <= 0.0031308, f * 12.92, 1.055 * np.power(f, 1.0 / 2.4) - 0.055)
    return (f * 255.0 + 0.5).astype(np.uint8)


def _decode_channel(
    rd: _Reader,
    compression: int,
    width: int,
    height: int,
    depth: int,
    data_len: int,
    srgb: bool = False,
) -> np.ndarray:
    """One channel as a (height, width) uint8 plane. ``srgb`` marks a colour
    channel of a 32-bit document, which is linear and needs encoding."""
    bps = _bytes_per_sample(depth)
    row_bytes = _row_bytes(width, depth)
    expected = row_bytes * height
    if compression == 0:
        raw = bytes(rd.take(expected))
    elif compression == 1:
        count_fmt = f">{height}{'I' if rd.psb else 'H'}"
        counts = struct.unpack(count_fmt, rd.take(struct.calcsize(count_fmt)))
        raw = b"".join(_unpackbits(rd.take(count), row_bytes) for count in counts)
    elif compression in (2, 3):
        try:
            raw = zlib.decompress(bytes(rd.take(data_len)), bufsize=expected)
        except zlib.error as exc:
            raise PSDError(f"Photoshop: bad zip channel ({exc})") from exc
        if len(raw) < expected:
            raise PSDError("Photoshop: short zip channel")
        raw = raw[:expected]
        if compression == 3:
            if bps == 4:
                # Prediction on a float row is a byte delta over the row,
                # whose bytes are stored plane-by-plane: all first bytes,
                # then all second bytes, and so on.
                arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, row_bytes)
                arr = np.cumsum(arr, axis=1, dtype=np.uint8)
                raw = arr.reshape(height, 4, width).transpose(0, 2, 1).tobytes()
            elif bps == 2:
                arr = np.frombuffer(raw, dtype=">u2").reshape(height, width).astype(np.uint16)
                raw = np.cumsum(arr, axis=1, dtype=np.uint16).astype(">u2").tobytes()
            else:
                arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, row_bytes)
                raw = np.cumsum(arr, axis=1, dtype=np.uint8).tobytes()
    else:
        raise PSDError(f"Photoshop: unknown compression {compression}")
    if depth == 1:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(height, row_bytes)
        bits = np.unpackbits(packed, axis=1)[:, :width]
        return ((1 - bits) * 255).astype(np.uint8)  # bitmap mode: 1 = black
    if bps == 4:
        return _float_to_u8(np.frombuffer(raw, dtype=">f4").reshape(height, width), srgb)
    if bps == 2:
        return (np.frombuffer(raw, dtype=">u2").reshape(height, width) >> 8).astype(np.uint8)
    return np.frombuffer(raw, dtype=np.uint8).reshape(height, width).copy()


def _to_rgb(
    mode: int, planes: dict[int, np.ndarray], shape: tuple[int, int], palette: bytes | None
):
    """(R, G, B) planes from decoded colour channels in the document's mode."""
    h, w = shape

    def plane(i: int) -> np.ndarray:
        p = planes.get(i)
        return p if p is not None else np.zeros((h, w), np.uint8)

    if mode == _MODE_RGB:
        return plane(0), plane(1), plane(2)
    if mode == _MODE_CMYK:
        k = plane(3).astype(np.uint16)  # stored inverted: 255 = no ink
        return tuple(((plane(i).astype(np.uint16) * k) // 255).astype(np.uint8) for i in range(3))
    if mode == _MODE_INDEXED and palette is not None and len(palette) >= 768:
        idx = plane(0)
        pal = np.frombuffer(palette[:768], dtype=np.uint8).reshape(3, 256)
        return pal[0][idx], pal[1][idx], pal[2][idx]
    gray = plane(0)  # Grayscale, Duotone, Bitmap, Lab's L, or an unpaletted index
    return gray, gray, gray


def _compose(r: np.ndarray, g: np.ndarray, b: np.ndarray, a: np.ndarray | None) -> QImage:
    h, w = r.shape
    img = QImage(w, h, FORMAT)
    img.fill(0)
    bpl = img.bytesPerLine()
    dst = np.frombuffer(img.bits(), dtype=np.uint8, count=h * bpl).reshape(h, bpl)[:, : w * 4]
    dst = dst.reshape(h, w, 4)
    if a is None:
        dst[:, :, 0], dst[:, :, 1], dst[:, :, 2], dst[:, :, 3] = b, g, r, 255
        return img
    a16 = a.astype(np.uint16)
    for i, plane in enumerate((b, g, r)):
        dst[:, :, i] = ((plane.astype(np.uint16) * a16 + 127) // 255).astype(np.uint8)
    dst[:, :, 3] = a
    return img


class _LayerRec:
    __slots__ = (
        "rect", "channels", "blend", "opacity", "clipping", "flags", "name", "mask_rect",
        "mask_default", "mask_flags", "section", "fill_opacity", "section_blend",
    )  # fmt: skip

    def __init__(self) -> None:
        self.channels: list[tuple[int, int]] = []
        self.name = ""
        self.mask_rect: QRect | None = None
        self.mask_default = 255
        self.mask_flags = 0
        self.section: int | None = None
        self.fill_opacity = 1.0
        self.section_blend = "normal"

    @property
    def hidden(self) -> bool:
        return bool(self.flags & 0x02)


def _read_rect(rd: _Reader) -> QRect:
    top, left, bottom, right = rd.i32(), rd.i32(), rd.i32(), rd.i32()
    return QRect(left, top, max(0, right - left), max(0, bottom - top))


def _read_layer_record(rd: _Reader) -> _LayerRec:
    rec = _LayerRec()
    rec.rect = _read_rect(rd)
    for _ in range(rd.u16()):
        cid = rd.i16()
        rec.channels.append((cid, rd.length()))
    if bytes(rd.take(4)) != b"8BIM":
        raise PSDError("Photoshop: bad layer record signature")
    rec.blend = BLEND_KEYS_REVERSE.get(bytes(rd.take(4)), "normal")
    rec.opacity = rd.u8() / 255.0
    rec.clipping = rd.u8()
    rec.flags = rd.u8()
    rd.u8()
    extra = _Reader(rd.take(rd.u32()), 0, rd.psb)
    mask_len = extra.u32()
    if mask_len >= 20:
        mask = _Reader(extra.take(mask_len), 0, rd.psb)
        rec.mask_rect = _read_rect(mask)
        rec.mask_default = mask.u8()
        rec.mask_flags = mask.u8()
    elif mask_len:
        extra.take(mask_len)
    extra.take(extra.u32())  # blending ranges
    rec.name = extra.pascal(4)
    while extra.pos + 12 <= len(extra.data):
        if bytes(extra.take(4)) not in (b"8BIM", b"8B64"):
            break
        key = bytes(extra.take(4))
        size = extra.u64() if (rd.psb and key in _PSB_WIDE_KEYS) else extra.u32()
        payload = _Reader(extra.take(size), 0, rd.psb)
        if size % 2 and extra.pos < len(extra.data):
            extra.take(1)
        if key == b"luni":
            count = payload.u32()
            rec.name = bytes(payload.take(count * 2)).decode("utf-16-be", errors="replace")
        elif key == b"lsct":
            rec.section = payload.u32()
            if size >= 12:
                payload.take(4)
                rec.section_blend = BLEND_KEYS_REVERSE.get(bytes(payload.take(4)), "normal")
        elif key == b"iOpa":
            rec.fill_opacity = payload.u8() / 255.0
    return rec


@contextlib.contextmanager
def _mapped(path: str):
    """The file's bytes as a read-only memory map, bounded by the file budget."""
    if os.path.getsize(path) > DESKTOP_BUDGET.max_file_bytes:
        raise ResourceLimitError("Photoshop: file exceeds 1 GiB")
    with open(path, "rb") as fh:
        try:
            mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:  # empty file
            raise PSDError("Photoshop: empty file") from None
        try:
            yield mm
        finally:
            mm.close()


def _read_resources(rd: _Reader) -> tuple[float, bytes | None]:
    """(dpi, icc bytes) from the image-resources section."""
    length = rd.u32()
    section = _Reader(rd.take(length), 0, rd.psb)
    dpi, icc = 72.0, None
    while section.pos + 12 <= length:
        if bytes(section.take(4)) != b"8BIM":
            break
        rid = section.u16()
        section.pascal(2)
        size = section.u32()
        payload = section.take(size)
        if size % 2:
            section.take(1)
        if rid == _RES_RESOLUTION and size >= 4:
            dpi = struct.unpack(">i", payload[:4])[0] / 65536.0
            if size >= 6 and struct.unpack(">h", payload[4:6])[0] == 2:
                dpi *= 2.54  # pixels per centimetre
        elif rid == _RES_ICC:
            icc = bytes(payload)
    return dpi, icc


def _merged_image(rd: _Reader, hdr: _Header, has_alpha: bool, palette: bytes | None) -> QImage:
    compression = rd.u16()
    w, h = hdr.width, hdr.height
    planes: dict[int, np.ndarray] = {}
    if compression == 1:
        count_fmt = f">{h * hdr.channels}{'I' if rd.psb else 'H'}"
        counts = struct.unpack(count_fmt, rd.take(struct.calcsize(count_fmt)))
        row_bytes = _row_bytes(w, hdr.depth)
        for c in range(hdr.channels):
            rows = b"".join(_unpackbits(rd.take(counts[c * h + y]), row_bytes) for y in range(h))
            srgb = hdr.depth == 32 and c < hdr.colour_channels
            planes[c] = _decode_channel(_Reader(rows, 0, rd.psb), 0, w, h, hdr.depth, 0, srgb)
    else:
        for c in range(hdr.channels):
            srgb = hdr.depth == 32 and c < hdr.colour_channels
            planes[c] = _decode_channel(rd, compression, w, h, hdr.depth, 0, srgb)
    r, g, b = _to_rgb(hdr.mode, planes, (h, w), palette)
    colour = hdr.colour_channels
    alpha = planes.get(colour) if (has_alpha and hdr.channels > colour) else None
    return _compose(r, g, b, alpha)


def _layer_mask(rec: _LayerRec, plane: np.ndarray, w: int, h: int) -> QImage:
    """A layer-sized Grayscale8 mask from the stored mask rect."""
    full = np.full((h, w), rec.mask_default, np.uint8)
    mr = rec.mask_rect
    # Mask rects are in canvas coordinates unless flagged layer-relative.
    ox, oy = (0, 0) if (rec.mask_flags & 0x01) else (rec.rect.left(), rec.rect.top())
    local = QRect(mr.left() - ox, mr.top() - oy, mr.width(), mr.height())
    inter = local.intersected(QRect(0, 0, w, h))
    if not inter.isEmpty():
        sy, sx = inter.top() - local.top(), inter.left() - local.left()
        full[
            inter.top() : inter.top() + inter.height(), inter.left() : inter.left() + inter.width()
        ] = plane[sy : sy + inter.height(), sx : sx + inter.width()]
    if rec.mask_flags & 0x04:
        full = 255 - full
    mask = QImage(w, h, QImage.Format.Format_Grayscale8)
    bpl = mask.bytesPerLine()
    np.frombuffer(mask.bits(), dtype=np.uint8, count=h * bpl).reshape(h, bpl)[:, :w] = full
    return mask


def _layer_image(
    rd: _Reader, hdr: _Header, rec: _LayerRec, palette: bytes | None
) -> tuple[QImage | None, QImage | None]:
    """(pixels, mask) for a layer record; pixels is None for an empty rect."""
    planes: dict[int, np.ndarray] = {}
    mask_plane: np.ndarray | None = None
    w, h = rec.rect.width(), rec.rect.height()
    for cid, length in rec.channels:
        sub = _Reader(rd.take(length), 0, rd.psb)
        if length < 2:
            continue
        compression = sub.u16()
        if cid == -2 and rec.mask_rect is not None:
            mw, mh = rec.mask_rect.width(), rec.mask_rect.height()
            if mw and mh:
                validate_dimensions(mw, mh, operation="Photoshop layer mask", allow_large=True)
                mask_plane = _decode_channel(sub, compression, mw, mh, hdr.depth, length - 2)
        elif cid >= -1 and w and h:
            srgb = hdr.depth == 32 and cid >= 0
            planes[cid] = _decode_channel(sub, compression, w, h, hdr.depth, length - 2, srgb)
    if not (w and h):
        return None, None
    r, g, b = _to_rgb(hdr.mode, planes, (h, w), palette)
    image = _compose(r, g, b, planes.get(-1))
    mask = None
    if mask_plane is not None and not (rec.mask_flags & 0x02):
        mask = _layer_mask(rec, mask_plane, w, h)
    return image, mask


def _skip_channels(rd: _Reader, rec: _LayerRec) -> None:
    for _cid, length in rec.channels:
        rd.take(length)


def _read_layers(
    rd: _Reader, hdr: _Header, palette: bytes | None, allow_large: bool
) -> tuple[list[Layer], dict[str, dict], bool]:
    """(layers bottom-first, group props, merged-has-alpha) from the layer info section."""
    count = rd.i16()
    merged_has_alpha = count < 0
    count = abs(count)
    if count > DESKTOP_BUDGET.max_layers:
        raise ResourceLimitError(f"Photoshop: more than {DESKTOP_BUDGET.max_layers} layers")
    records = [_read_layer_record(rd) for _ in range(count)]
    layers: list[Layer] = []
    group_props: dict[str, dict] = {}
    pending: list[list[Layer]] = []  # open groups, innermost last
    for rec in records:
        if rec.section == 3:  # bounding divider: a group begins (the file is bottom-first)
            _skip_channels(rd, rec)
            pending.append([])
            continue
        if rec.section in (1, 2):  # folder record: the group ends
            _skip_channels(rd, rec)
            members = pending.pop() if pending else []
            base = rec.name or "Group"
            name, n = base, 2
            while name in group_props:
                name = f"{base} {n}"
                n += 1
            for member in members:
                if member.group is None:
                    member.group = name
                if rec.hidden:
                    member.visible = False
            blend = rec.section_blend if rec.section_blend != "normal" else rec.blend
            group_props[name] = {"opacity": rec.opacity, "blend_mode": blend}
            if pending:
                pending[-1].extend(members)
            continue
        if rec.rect.width() and rec.rect.height():
            validate_dimensions(
                rec.rect.width(),
                rec.rect.height(),
                operation="Photoshop layer",
                allow_large=allow_large,
            )
        image, mask = _layer_image(rd, hdr, rec, palette)
        if image is None:
            image = QImage(1, 1, FORMAT)
            image.fill(0)
        layer = Layer(
            rec.name or f"Layer {len(layers) + 1}",
            image,
            QPoint(rec.rect.left(), rec.rect.top()),
            visible=not rec.hidden,
            opacity=rec.opacity,
            blend_mode=rec.blend,
        )
        layer.clipped = rec.clipping == 1
        layer.fill_opacity = rec.fill_opacity
        layer.mask = mask
        layers.append(layer)
        if pending:
            pending[-1].append(layer)
    return layers, group_props, merged_has_alpha


def _deep_layer_block(rd: _Reader, end: int) -> _Reader | None:
    """A reader over the ``Lr16``/``Lr32`` global block, where Photoshop keeps
    a 16- or 32-bit document's layers (the main layer section is left
    empty). ``rd`` sits just past the layer info; ``end`` closes the layer
    and mask section."""
    if rd.pos + 4 > end:
        return None
    skip = rd.u32()  # global layer mask info
    rd.pos += skip
    pad = 4 if rd.psb else 2
    while rd.pos + 12 <= end:
        if bytes(rd.take(4)) not in (b"8BIM", b"8B64"):
            return None
        key = bytes(rd.take(4))
        length = rd.u64() if (rd.psb and key in _PSB_WIDE_KEYS) else rd.u32()
        length = min(length, end - rd.pos)
        data = rd.take(length)
        if key in (b"Lr16", b"Lr32"):
            return _Reader(data, 0, rd.psb)
        rd.pos += (-length) % pad
    return None


def load_psd(path: str, *, allow_large: bool = False) -> Document:
    with _mapped(path) as mm:
        rd = _Reader(mm)
        hdr = _Header(rd)
        validate_dimensions(
            hdr.width, hdr.height, operation="Photoshop canvas", buffers=2, allow_large=allow_large
        )
        palette = bytes(rd.take(rd.u32())) or None
        dpi, icc = _read_resources(rd)
        validate_dpi(dpi, operation="Photoshop")

        lm_len = rd.length()
        lm_end = rd.pos + lm_len
        layers: list[Layer] = []
        group_props: dict[str, dict] = {}
        merged_has_alpha = False
        if lm_len:
            li_len = rd.length()
            li_end = rd.pos + li_len
            if li_len:
                layers, group_props, merged_has_alpha = _read_layers(rd, hdr, palette, allow_large)
            rd.pos = li_end
            if not layers and hdr.depth in (16, 32):
                deep = _deep_layer_block(rd, lm_end)
                if deep is not None:
                    layers, group_props, merged_has_alpha = _read_layers(
                        deep, hdr, palette, allow_large
                    )
                    deep = None  # drop the view into the map before it closes
        rd.pos = lm_end
        if not layers:
            layers = [Layer("Background", _merged_image(rd, hdr, merged_has_alpha, palette))]

    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    doc = Document(QSize(hdr.width, hdr.height), dpi, name)
    doc.embedded_name = name
    doc.layers = layers
    doc.group_props.update(group_props)
    if icc:
        from PySide6.QtGui import QColorSpace

        space = QColorSpace.fromIccProfile(icc)
        if space.isValid():
            doc.icc_space = space
    doc.active_index = len(doc.layers) - 1
    doc.path = path
    return doc


def probe_psd(path: str) -> tuple[QImage, int, int, int]:
    """(merged composite, width, height, layer count) without decoding layers."""
    with _mapped(path) as mm:
        rd = _Reader(mm)
        hdr = _Header(rd)
        validate_dimensions(hdr.width, hdr.height, operation="Photoshop preview", allow_large=True)
        palette = bytes(rd.take(rd.u32())) or None
        _read_resources(rd)
        lm_len = rd.length()
        lm_end = rd.pos + lm_len
        count, has_alpha = 0, False
        if lm_len and rd.length():
            count = rd.i16()
            has_alpha = count < 0
            count = abs(count)
        rd.pos = lm_end
        return _merged_image(rd, hdr, has_alpha, palette), hdr.width, hdr.height, count
