# SPDX-License-Identifier: Apache-2.0
"""Color swatch palettes (#421): Adobe .aco and .ase parser, writer, and Qt UI."""

from __future__ import annotations

import colorsys
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# ==============================================================================
# Color space conversion utilities (sRGB, CIE Lab D65, CMYK, HSB, Grayscale)
# ==============================================================================


def lab_to_rgb(l_val: float, a_val: float, b_val: float) -> tuple[int, int, int]:
    """CIE L*a*b* to sRGB (D65 reference white, standard companding)."""
    fy = (l_val + 16.0) / 116.0
    fx = a_val / 500.0 + fy
    fz = fy - b_val / 200.0

    delta = 6.0 / 29.0
    factor = 3.0 * (delta**2)

    xr = fx**3 if fx > delta else (fx - 4.0 / 29.0) * factor
    yr = fy**3 if fy > delta else (fy - 4.0 / 29.0) * factor
    zr = fz**3 if fz > delta else (fz - 4.0 / 29.0) * factor

    x = xr * 0.95047
    y = yr * 1.00000
    z = zr * 1.08883

    # Linear sRGB matrix
    r_lin = 3.2404542 * x - 1.5371385 * y - 0.4985314 * z
    g_lin = -0.9692660 * x + 1.8760108 * y + 0.0415560 * z
    b_lin = 0.0556434 * x - 0.2040259 * y + 1.0572252 * z

    def compand(c: float) -> float:
        if c <= 0.0031308:
            return 12.92 * c
        return 1.055 * (max(0.0, c) ** (1.0 / 2.4)) - 0.055

    r = round(max(0.0, min(1.0, compand(r_lin))) * 255.0)
    g = round(max(0.0, min(1.0, compand(g_lin))) * 255.0)
    b = round(max(0.0, min(1.0, compand(b_lin))) * 255.0)
    return int(r), int(g), int(b)


def rgb_to_lab(r_int: int, g_int: int, b_int: int) -> tuple[float, float, float]:
    """sRGB to CIE L*a*b* (D65)."""

    def inv_compand(c: float) -> float:
        if c <= 0.04045:
            return c / 12.92
        return ((c + 0.055) / 1.055) ** 2.4

    r_lin = inv_compand(r_int / 255.0)
    g_lin = inv_compand(g_int / 255.0)
    b_lin = inv_compand(b_int / 255.0)

    x = (0.4124564 * r_lin + 0.3575761 * g_lin + 0.1804375 * b_lin) / 0.95047
    y = (0.2126729 * r_lin + 0.7151522 * g_lin + 0.0721750 * b_lin) / 1.00000
    z = (0.0193339 * r_lin + 0.1191920 * g_lin + 0.9503041 * b_lin) / 1.08883

    delta = 6.0 / 29.0
    delta3 = delta**3
    inv_factor = 1.0 / (3.0 * (delta**2))

    def f(t: float) -> float:
        if t > delta3:
            return t ** (1.0 / 3.0)
        return t * inv_factor + 4.0 / 29.0

    fx, fy, fz = f(x), f(y), f(z)
    l_val = 116.0 * fy - 16.0
    a_val = 500.0 * (fx - fy)
    b_val = 200.0 * (fy - fz)
    return l_val, a_val, b_val


def cmyk_to_rgb(c: float, m: float, y: float, k: float) -> tuple[int, int, int]:
    """CMYK (0.0..1.0) to sRGB (0..255)."""
    r = round(255.0 * (1.0 - c) * (1.0 - k))
    g = round(255.0 * (1.0 - m) * (1.0 - k))
    b = round(255.0 * (1.0 - y) * (1.0 - k))
    return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))


def rgb_to_cmyk(r: int, g: int, b: int) -> tuple[float, float, float, float]:
    """sRGB (0..255) to CMYK (0.0..1.0)."""
    r_norm, g_norm, b_norm = r / 255.0, g / 255.0, b / 255.0
    k = 1.0 - max(r_norm, g_norm, b_norm)
    if k >= 0.99999:
        return 0.0, 0.0, 0.0, 1.0
    c = (1.0 - r_norm - k) / (1.0 - k)
    m = (1.0 - g_norm - k) / (1.0 - k)
    y = (1.0 - b_norm - k) / (1.0 - k)
    return (
        max(0.0, min(1.0, c)),
        max(0.0, min(1.0, m)),
        max(0.0, min(1.0, y)),
        max(0.0, min(1.0, k)),
    )


def hsb_to_rgb(h: float, s: float, b: float) -> tuple[int, int, int]:
    """HSB/HSV (0.0..1.0) to sRGB (0..255)."""
    r, g, bl = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, b)))
    return round(r * 255.0), round(g * 255.0), round(bl * 255.0)


# ==============================================================================
# Swatch Data Structures
# ==============================================================================


@dataclass
class Swatch:
    name: str = ""
    color_model: str = "RGB"  # "RGB", "CMYK", "LAB", "GRAY", "HSB"
    values: tuple[float, ...] = (0.0, 0.0, 0.0)
    color_type: str = "process"  # "global", "spot", "process"

    def to_rgb(self) -> tuple[int, int, int]:
        model = self.color_model.upper().strip()
        if model == "RGB":
            r = round(max(0.0, min(1.0, self.values[0])) * 255.0)
            g = round(max(0.0, min(1.0, self.values[1])) * 255.0)
            b = round(max(0.0, min(1.0, self.values[2])) * 255.0)
            return int(r), int(g), int(b)
        elif model == "CMYK":
            c, m, y, k = self.values[:4]
            return cmyk_to_rgb(c, m, y, k)
        elif model == "LAB":
            l_val, a_val, b_val = self.values[:3]
            return lab_to_rgb(l_val, a_val, b_val)
        elif model == "GRAY":
            g_val = round(max(0.0, min(1.0, self.values[0])) * 255.0)
            return g_val, g_val, g_val
        elif model == "HSB":
            h, s, v = self.values[:3]
            return hsb_to_rgb(h, s, v)
        return 0, 0, 0

    def to_rgba(self) -> tuple[int, int, int, int]:
        r, g, b = self.to_rgb()
        return r, g, b, 255

    def to_hex(self) -> str:
        r, g, b = self.to_rgb()
        return f"#{r:02X}{g:02X}{b:02X}"

    def to_qcolor(self) -> QColor:
        r, g, b = self.to_rgb()
        return QColor(r, g, b)

    def to_dict(self) -> dict[str, Any]:
        r, g, b = self.to_rgb()
        return {
            "name": self.name,
            "hex": f"#{r:02X}{g:02X}{b:02X}",
            "rgba": [r, g, b, 255],
            "color_model": self.color_model,
            "color_type": self.color_type,
            "values": [round(v, 4) for v in self.values],
        }

    @classmethod
    def from_rgb(cls, r: int, g: int, b: int, name: str = "") -> Swatch:
        r_f = max(0.0, min(1.0, r / 255.0))
        g_f = max(0.0, min(1.0, g / 255.0))
        b_f = max(0.0, min(1.0, b / 255.0))
        return cls(name=name, color_model="RGB", values=(r_f, g_f, b_f), color_type="process")

    @classmethod
    def from_hex(cls, hex_str: str, name: str = "") -> Swatch:
        cleaned = hex_str.strip().lstrip("#")
        if len(cleaned) == 3:
            cleaned = "".join(c * 2 for c in cleaned)
        if len(cleaned) == 6:
            r = int(cleaned[0:2], 16)
            g = int(cleaned[2:4], 16)
            b = int(cleaned[4:6], 16)
            return cls.from_rgb(r, g, b, name=name)
        raise ValueError(f"Invalid hex color string: {hex_str!r}")

    @classmethod
    def from_qcolor(cls, color: QColor, name: str = "") -> Swatch:
        return cls.from_rgb(color.red(), color.green(), color.blue(), name=name)


@dataclass
class SwatchGroup:
    name: str
    swatches: list[Swatch] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "swatches": [s.to_dict() for s in self.swatches],
        }


@dataclass
class SwatchPalette:
    name: str = "Swatches"
    swatches: list[Swatch] = field(default_factory=list)
    groups: list[SwatchGroup] = field(default_factory=list)

    def all_swatches(self) -> list[Swatch]:
        all_list = list(self.swatches)
        for g in self.groups:
            all_list.extend(g.swatches)
        return all_list

    def add_swatch(self, swatch: Swatch, group_name: str | None = None) -> None:
        if group_name:
            for g in self.groups:
                if g.name == group_name:
                    g.swatches.append(swatch)
                    return
            grp = SwatchGroup(name=group_name, swatches=[swatch])
            self.groups.append(grp)
        else:
            self.swatches.append(swatch)

    def to_dict(self) -> dict[str, Any]:
        all_s = self.all_swatches()
        return {
            "name": self.name,
            "count": len(all_s),
            "swatches": [s.to_dict() for s in all_s],
            "groups": [g.to_dict() for g in self.groups],
        }

    # --------------------------------------------------------------------------
    # ACO Serialization / Deserialization
    # --------------------------------------------------------------------------

    def to_aco(self, version: int = 2) -> bytes:
        """Write Adobe Color Swatches (.aco) binary stream.

        Writes Version 1 and Version 2 sections for maximum cross-application
        compatibility.
        """
        all_s = self.all_swatches()
        count = len(all_s)
        if count > 65535:
            raise ValueError(f"Too many swatches for ACO format: {count} (max 65535)")

        v1_bytes = bytearray()
        v1_bytes.extend(struct.pack(">HH", 1, count))

        v2_bytes = bytearray()
        if version >= 2:
            v2_bytes.extend(struct.pack(">HH", 2, count))

        for idx, swatch in enumerate(all_s, 1):
            model = swatch.color_model.upper().strip()
            if model == "RGB":
                space_id = 0
                w = round(max(0.0, min(1.0, swatch.values[0])) * 65535.0)
                x = round(max(0.0, min(1.0, swatch.values[1])) * 65535.0)
                y = round(max(0.0, min(1.0, swatch.values[2])) * 65535.0)
                z = 0
            elif model == "HSB":
                space_id = 1
                w = round((swatch.values[0] % 1.0) * 36000.0)
                x = round(max(0.0, min(1.0, swatch.values[1])) * 10000.0)
                y = round(max(0.0, min(1.0, swatch.values[2])) * 10000.0)
                z = 0
            elif model == "CMYK":
                space_id = 2
                w = round(max(0.0, min(1.0, swatch.values[0])) * 65535.0)
                x = round(max(0.0, min(1.0, swatch.values[1])) * 65535.0)
                y = round(max(0.0, min(1.0, swatch.values[2])) * 65535.0)
                z = round(max(0.0, min(1.0, swatch.values[3])) * 65535.0)
            elif model == "LAB":
                space_id = 7
                w = round(max(0.0, min(100.0, swatch.values[0])) * 100.0)
                # signed short -12800..12700
                a_signed = round(max(-128.0, min(127.0, swatch.values[1])) * 100.0)
                b_signed = round(max(-128.0, min(127.0, swatch.values[2])) * 100.0)
                x = struct.unpack(">H", struct.pack(">h", a_signed))[0]
                y = struct.unpack(">H", struct.pack(">h", b_signed))[0]
                z = 0
            elif model == "GRAY":
                space_id = 8
                w = round(max(0.0, min(1.0, swatch.values[0])) * 10000.0)
                x = y = z = 0
            else:
                # Default to RGB
                space_id = 0
                r, g, b = swatch.to_rgb()
                w = round((r / 255.0) * 65535.0)
                x = round((g / 255.0) * 65535.0)
                y = round((b / 255.0) * 65535.0)
                z = 0

            color_block = struct.pack(">HHHHH", space_id, w, x, y, z)
            v1_bytes.extend(color_block)

            if version >= 2:
                v2_bytes.extend(color_block)
                name = swatch.name or f"Swatch {idx}"
                name_chars = len(name) + 1  # includes trailing null char
                name_encoded = name.encode("utf-16-be") + b"\x00\x00"
                v2_bytes.extend(struct.pack(">I", name_chars))
                v2_bytes.extend(name_encoded)

        return bytes(v1_bytes + v2_bytes)

    @classmethod
    def from_aco(cls, data: bytes) -> SwatchPalette:
        """Parse Adobe Color Swatches (.aco) binary stream."""
        if len(data) < 4:
            raise ValueError("ACO file too short: minimum 4 bytes required")

        version, count = struct.unpack_from(">HH", data, 0)
        if version not in (1, 2):
            raise ValueError(f"Invalid or unsupported ACO version: {version}")

        if count > 32768:
            raise ValueError(f"Absurdly large swatch count: {count}")

        # Helper to decode a 10-byte color entry
        def decode_entry(color_data: bytes) -> tuple[str, tuple[float, ...]]:
            if len(color_data) < 10:
                raise ValueError("Truncated color entry")
            space_id, w, x, y, z = struct.unpack_from(">HHHHH", color_data, 0)
            if space_id == 0:  # RGB
                return "RGB", (w / 65535.0, x / 65535.0, y / 65535.0)
            elif space_id == 1:  # HSB
                return "HSB", ((w / 100.0) / 360.0, (x / 100.0) / 100.0, (y / 100.0) / 100.0)
            elif space_id == 2:  # CMYK
                return "CMYK", (w / 65535.0, x / 65535.0, y / 65535.0, z / 65535.0)
            elif space_id == 7:  # Lab
                l_val = w / 100.0
                a_signed = struct.unpack(">h", struct.pack(">H", x))[0] / 100.0
                b_signed = struct.unpack(">h", struct.pack(">H", y))[0] / 100.0
                return "LAB", (l_val, a_signed, b_signed)
            elif space_id == 8:  # Grayscale
                return "GRAY", (w / 10000.0,)
            else:
                # Fallback to RGB
                return "RGB", (w / 65535.0, x / 65535.0, y / 65535.0)

        swatches: list[Swatch] = []

        if version == 1:
            min_v1_size = 4 + count * 10
            if len(data) < min_v1_size:
                raise ValueError(
                    f"Truncated ACO version 1 color data: needs {min_v1_size} bytes, "
                    f"got {len(data)}"
                )

            v1_swatches: list[Swatch] = []
            for i in range(count):
                entry_offset = 4 + i * 10
                model, vals = decode_entry(data[entry_offset : entry_offset + 10])
                v1_swatches.append(Swatch(name=f"Swatch {i + 1}", color_model=model, values=vals))

            # Check if there is a version 2 stream following version 1
            v2_offset = 4 + count * 10
            if len(data) >= v2_offset + 4:
                v2_ver, v2_count = struct.unpack_from(">HH", data, v2_offset)
                if v2_ver == 2 and v2_count <= 32768:
                    try:
                        v2_swatches = cls._parse_aco_v2(data, v2_offset + 4, v2_count, decode_entry)
                        return cls(name="Adobe Swatches", swatches=v2_swatches)
                    except ValueError:
                        pass  # fallback to v1_swatches
            return cls(name="Adobe Swatches", swatches=v1_swatches)

        elif version == 2:
            v2_swatches = cls._parse_aco_v2(data, 4, count, decode_entry)
            return cls(name="Adobe Swatches", swatches=v2_swatches)

        return cls(name="Adobe Swatches", swatches=swatches)

    @staticmethod
    def _parse_aco_v2(data: bytes, offset: int, count: int, decode_entry) -> list[Swatch]:
        swatches: list[Swatch] = []
        curr = offset
        for i in range(count):
            if curr + 10 > len(data):
                raise ValueError("Truncated ACO version 2 color block")
            model, vals = decode_entry(data[curr : curr + 10])
            curr += 10
            if curr + 4 > len(data):
                raise ValueError("Truncated ACO version 2 name length header")
            name_len = struct.unpack_from(">I", data, curr)[0]
            curr += 4
            if name_len < 1 or name_len > 4096:
                raise ValueError(f"Invalid swatch name length in ACO v2: {name_len}")
            name_bytes_len = name_len * 2
            if curr + name_bytes_len > len(data):
                raise ValueError("Truncated ACO version 2 name data")
            name_raw = data[curr : curr + name_bytes_len]
            name = name_raw.decode("utf-16-be", errors="replace").rstrip("\x00")
            curr += name_bytes_len
            swatches.append(Swatch(name=name or f"Swatch {i + 1}", color_model=model, values=vals))
        return swatches

    # --------------------------------------------------------------------------
    # ASE Serialization / Deserialization
    # --------------------------------------------------------------------------

    def to_ase(self) -> bytes:
        """Write Adobe Swatch Exchange (.ase) binary stream."""
        body = bytearray()
        block_count = 0

        # Helper to encode color block
        def make_color_block(swatch: Swatch) -> bytes:
            name = swatch.name or "Swatch"
            name_encoded = name.encode("utf-16-be") + b"\x00\x00"
            name_len = len(name) + 1

            model = swatch.color_model.upper().strip()
            if model == "RGB":
                model_bytes = b"RGB "
                floats = struct.pack(">fff", swatch.values[0], swatch.values[1], swatch.values[2])
            elif model == "CMYK":
                model_bytes = b"CMYK"
                floats = struct.pack(
                    ">ffff",
                    swatch.values[0],
                    swatch.values[1],
                    swatch.values[2],
                    swatch.values[3],
                )
            elif model == "LAB":
                model_bytes = b"LAB "
                l_val = swatch.values[0] / 100.0  # ASE standard normalized 0..1
                floats = struct.pack(">fff", l_val, swatch.values[1], swatch.values[2])
            elif model == "GRAY":
                model_bytes = b"GRAY"
                floats = struct.pack(">f", swatch.values[0])
            else:
                model_bytes = b"RGB "
                r, g, b = swatch.to_rgb()
                floats = struct.pack(">fff", r / 255.0, g / 255.0, b / 255.0)

            c_type = (
                0 if swatch.color_type == "global" else (1 if swatch.color_type == "spot" else 2)
            )
            payload = (
                struct.pack(">H", name_len)
                + name_encoded
                + model_bytes
                + floats
                + struct.pack(">H", c_type)
            )
            return struct.pack(">HI", 0x0001, len(payload)) + payload

        # Root swatches
        for s in self.swatches:
            body.extend(make_color_block(s))
            block_count += 1

        # Groups
        for grp in self.groups:
            # Group Start: 0xC001
            g_name = grp.name or "Group"
            g_name_enc = g_name.encode("utf-16-be") + b"\x00\x00"
            g_payload = struct.pack(">H", len(g_name) + 1) + g_name_enc
            body.extend(struct.pack(">HI", 0xC001, len(g_payload)) + g_payload)
            block_count += 1

            for s in grp.swatches:
                body.extend(make_color_block(s))
                block_count += 1

            # Group End: 0xC002
            body.extend(struct.pack(">HI", 0xC002, 0))
            block_count += 1

        header = b"ASEF" + struct.pack(">HHI", 1, 0, block_count)
        return bytes(header + body)

    @classmethod
    def from_ase(cls, data: bytes) -> SwatchPalette:
        """Parse Adobe Swatch Exchange (.ase) binary stream."""
        if len(data) < 12:
            raise ValueError("ASE file too short: minimum 12 bytes required")

        if data[:4] != b"ASEF":
            raise ValueError(f"Invalid ASE header signature: {data[:4]!r}")

        major, minor, block_count = struct.unpack_from(">HHI", data, 4)
        if major != 1:
            raise ValueError(f"Unsupported ASE major version: {major}.{minor}")

        if block_count > 65536:
            raise ValueError(f"Absurdly large block count in ASE file: {block_count}")

        palette = cls(name="Adobe Swatch Exchange")
        current_group: SwatchGroup | None = None
        offset = 12

        for i in range(block_count):
            if offset >= len(data):
                raise ValueError(
                    f"Truncated ASE file: expected {block_count} blocks, reached EOF at block {i}"
                )
            if offset + 6 > len(data):
                raise ValueError("Truncated ASE block header")

            block_type, block_len = struct.unpack_from(">HI", data, offset)
            offset += 6

            if offset + block_len > len(data):
                raise ValueError(f"Truncated ASE block payload: expected {block_len} bytes")

            block_data = data[offset : offset + block_len]
            offset += block_len

            if block_type == 0xC001:  # Group Start
                if len(block_data) < 2:
                    raise ValueError("Truncated ASE group start block")
                name_len = struct.unpack_from(">H", block_data, 0)[0]
                if name_len < 1 or 2 + (name_len * 2) > len(block_data):
                    raise ValueError("Truncated ASE group name")
                name_bytes = block_data[2 : 2 + (name_len - 1) * 2]
                grp_name = name_bytes.decode("utf-16-be", errors="replace").rstrip("\x00")
                current_group = SwatchGroup(name=grp_name or "Group")
                palette.groups.append(current_group)

            elif block_type in (0xC002, 0xC000):  # Group End
                current_group = None

            elif block_type == 0x0001:  # Color Entry
                if len(block_data) < 2:
                    raise ValueError("Truncated ASE color entry block")
                name_len = struct.unpack_from(">H", block_data, 0)[0]
                if name_len < 1:
                    raise ValueError("Invalid color name length in ASE")
                name_bytes_len = (name_len - 1) * 2
                pos = 2 + (name_len * 2)
                if pos > len(block_data):
                    raise ValueError("Truncated color name in ASE")

                name_bytes = block_data[2 : 2 + name_bytes_len]
                color_name = name_bytes.decode("utf-16-be", errors="replace").rstrip("\x00")

                if pos + 4 > len(block_data):
                    raise ValueError("Missing color model in ASE color entry")

                model_bytes = block_data[pos : pos + 4]
                pos += 4

                if model_bytes == b"RGB ":
                    if pos + 12 > len(block_data):
                        raise ValueError("Truncated RGB color values in ASE")
                    r, g, b = struct.unpack_from(">fff", block_data, pos)
                    pos += 12
                    vals = (r, g, b)
                    model_str = "RGB"
                elif model_bytes == b"CMYK":
                    if pos + 16 > len(block_data):
                        raise ValueError("Truncated CMYK color values in ASE")
                    c, m, y, k = struct.unpack_from(">ffff", block_data, pos)
                    pos += 16
                    vals = (c, m, y, k)
                    model_str = "CMYK"
                elif model_bytes == b"LAB ":
                    if pos + 12 > len(block_data):
                        raise ValueError("Truncated LAB color values in ASE")
                    l_val, a_val, b_val = struct.unpack_from(">fff", block_data, pos)
                    pos += 12
                    if 0.0 <= l_val <= 1.0 and (a_val != 0.0 or b_val != 0.0):
                        l_val *= 100.0
                    vals = (l_val, a_val, b_val)
                    model_str = "LAB"
                elif model_bytes == b"GRAY":
                    if pos + 4 > len(block_data):
                        raise ValueError("Truncated GRAY color value in ASE")
                    gray_val = struct.unpack_from(">f", block_data, pos)[0]
                    pos += 4
                    vals = (gray_val,)
                    model_str = "GRAY"
                else:
                    raise ValueError(f"Unsupported color model in ASE: {model_bytes!r}")

                color_type_int = 2
                if pos + 2 <= len(block_data):
                    color_type_int = struct.unpack_from(">H", block_data, pos)[0]

                c_type_str = (
                    "global"
                    if color_type_int == 0
                    else ("spot" if color_type_int == 1 else "process")
                )
                swatch = Swatch(
                    name=color_name or f"Swatch {len(palette.all_swatches()) + 1}",
                    color_model=model_str,
                    values=vals,
                    color_type=c_type_str,
                )

                if current_group is not None:
                    current_group.swatches.append(swatch)
                else:
                    palette.swatches.append(swatch)

        return palette

    # --------------------------------------------------------------------------
    # File I/O & Presets
    # --------------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        p = Path(path)
        ext = p.suffix.lower()
        if ext == ".ase":
            data = self.to_ase()
        elif ext == ".aco":
            data = self.to_aco()
        else:
            raise ValueError(f"Unsupported swatch file extension: {ext!r} (expected .aco or .ase)")
        with open(p, "wb") as f:
            f.write(data)

    @classmethod
    def load(cls, path: str | Path) -> SwatchPalette:
        p = Path(path)
        with open(p, "rb") as f:
            data = f.read()
        return cls.from_bytes(data, filename=p.name)

    @classmethod
    def from_bytes(cls, data: bytes, filename: str = "") -> SwatchPalette:
        if not data:
            raise ValueError("Empty palette data")
        if data.startswith(b"ASEF") or filename.lower().endswith(".ase"):
            pal = cls.from_ase(data)
        elif (
            len(data) >= 4 and struct.unpack_from(">H", data, 0)[0] in (1, 2)
        ) or filename.lower().endswith(".aco"):
            pal = cls.from_aco(data)
        else:
            # Try ASE then ACO
            try:
                pal = cls.from_ase(data)
            except Exception:
                pal = cls.from_aco(data)
        if filename:
            pal.name = Path(filename).stem
        return pal

    @classmethod
    def default_palette(cls) -> SwatchPalette:
        """Standard default digital painting palette."""
        colors = [
            ("Black", 0, 0, 0),
            ("Dark Gray", 64, 64, 64),
            ("Gray", 128, 128, 128),
            ("Light Gray", 192, 192, 192),
            ("White", 255, 255, 255),
            ("Dark Red", 139, 0, 0),
            ("Red", 255, 0, 0),
            ("Light Coral", 240, 128, 128),
            ("Orange", 255, 128, 0),
            ("Gold", 255, 215, 0),
            ("Yellow", 255, 255, 0),
            ("Lime", 0, 255, 0),
            ("Green", 34, 139, 34),
            ("Dark Green", 0, 100, 0),
            ("Cyan", 0, 255, 255),
            ("Sky Blue", 135, 206, 235),
            ("Blue", 0, 0, 255),
            ("Navy", 0, 0, 128),
            ("Purple", 128, 0, 128),
            ("Magenta", 255, 0, 255),
            ("Hot Pink", 255, 105, 180),
            ("Saddle Brown", 139, 69, 19),
            ("Chocolate", 210, 105, 30),
            ("Wheat", 245, 222, 179),
        ]
        swatches = [Swatch.from_rgb(r, g, b, name=name) for name, r, g, b in colors]
        return cls(name="Default Palette", swatches=swatches)


def load_palette(path: str | Path) -> SwatchPalette:
    """Convenience function to load a palette from an .aco or .ase file."""
    return SwatchPalette.load(path)


# ==============================================================================
# Desktop Qt UI Widgets
# ==============================================================================


class SwatchCell(QToolButton):
    """A single interactive swatch cell button."""

    swatchSelected = Signal(QColor, bool)  # color, is_foreground

    def __init__(self, swatch: Swatch, parent=None) -> None:
        super().__init__(parent)
        self.swatch = swatch
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        qcolor = swatch.to_qcolor()
        r, g, b = swatch.to_rgb()
        name = swatch.name or swatch.to_hex()
        tip = (
            f"{name}\nHex: {swatch.to_hex()}\nRGB: ({r}, {g}, {b})\n"
            "Left-click: Foreground | Right-click: Background"
        )
        self.setToolTip(tip)
        self.setAccessibleName(name)

        # Draw icon
        pm = QPixmap(20, 20)
        pm.fill(qcolor)
        p = QPainter(pm)
        p.setPen(QColor(80, 80, 80))
        p.drawRect(0, 0, 19, 19)
        p.end()
        self.setIcon(QIcon(pm))
        self.setIconSize(QSize(20, 20))
        self.setStyleSheet("border: 1px solid #444; margin: 1px; padding: 0px;")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            is_fg = not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.swatchSelected.emit(self.swatch.to_qcolor(), is_fg)
        elif event.button() == Qt.MouseButton.RightButton:
            self.swatchSelected.emit(self.swatch.to_qcolor(), False)
        super().mousePressEvent(event)


class SwatchesWidget(QWidget):
    """Grid of color swatches with import, export, and color selection."""

    colorSelected = Signal(QColor, bool)  # color, is_foreground

    def __init__(self, palette: SwatchPalette | None = None, parent=None) -> None:
        super().__init__(parent)
        self.palette = palette or SwatchPalette.default_palette()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(6)

        # Header toolbar
        top_bar = QHBoxLayout()
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(4)

        self.import_btn = QPushButton("Import…")
        self.import_btn.setToolTip("Import swatches from Adobe .aco or .ase")
        self.import_btn.clicked.connect(self._on_import)
        top_bar.addWidget(self.import_btn)

        self.export_btn = QPushButton("Export…")
        self.export_btn.setToolTip("Export swatches to Adobe .aco or .ase")
        self.export_btn.clicked.connect(self._on_export)
        top_bar.addWidget(self.export_btn)

        self.add_btn = QPushButton("+")
        self.add_btn.setFixedWidth(28)
        self.add_btn.setToolTip("Add current color as a swatch")
        self.add_btn.clicked.connect(self._on_add)
        top_bar.addWidget(self.add_btn)

        main_layout.addLayout(top_bar)

        # Palette name / count label
        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: #888; font-size: 10px;")
        main_layout.addWidget(self.info_label)

        # Scroll area for swatch cells
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(2, 2, 2, 2)
        self.grid_layout.setSpacing(2)
        self.scroll.setWidget(self.grid_container)

        main_layout.addWidget(self.scroll, 1)

        self.refresh_grid()

    def set_palette(self, palette: SwatchPalette) -> None:
        self.palette = palette
        self.refresh_grid()

    def refresh_grid(self) -> None:
        # Clear existing cells
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        all_swatches = self.palette.all_swatches()
        self.info_label.setText(f"{self.palette.name} ({len(all_swatches)} swatches)")

        cols = max(1, min(12, max(6, self.width() // 26)))
        for idx, swatch in enumerate(all_swatches):
            cell = SwatchCell(swatch, self)
            cell.swatchSelected.connect(self.colorSelected)
            row = idx // cols
            col = idx % cols
            self.grid_layout.addWidget(cell, row, col)

    def _on_import(self) -> None:
        filters = (
            "Adobe Swatches (*.aco *.ase);;"
            "Adobe Color Swatches (*.aco);;"
            "Adobe Swatch Exchange (*.ase);;"
            "All Files (*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, "Import Swatches", "", filters)
        if path:
            self.import_palette(path)

    def import_palette(self, path: str) -> None:
        try:
            pal = SwatchPalette.load(path)
            self.set_palette(pal)
        except Exception as exc:
            msg = f"Could not import swatches from {path!r}:\n{exc}"
            QMessageBox.warning(self, "Import Failed", msg)

    def _on_export(self) -> None:
        path, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export Swatches",
            "swatches.aco",
            "Adobe Color Swatches (*.aco);;Adobe Swatch Exchange (*.ase)",
        )
        if path:
            self.export_palette(path)

    def export_palette(self, path: str) -> None:
        try:
            p = Path(path)
            if not p.suffix:
                path = path + ".aco"
            self.palette.save(path)
        except Exception as exc:
            msg = f"Could not export swatches to {path!r}:\n{exc}"
            QMessageBox.warning(self, "Export Failed", msg)

    def _on_add(self) -> None:
        # Request host window options or color dialog
        host = getattr(self.window(), "options", None)
        fg = getattr(host, "foreground", QColor(0, 0, 0))
        swatch = Swatch.from_qcolor(fg, name=f"Color {len(self.palette.all_swatches()) + 1}")
        self.palette.add_swatch(swatch)
        self.refresh_grid()


class SwatchesPanel(QWidget):
    """Dock-widget wrapper for Swatches palette management."""

    colorSelected = Signal(QColor, bool)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.widget = SwatchesWidget(parent=self)
        self.widget.colorSelected.connect(self.colorSelected)
        layout.addWidget(self.widget)

    def import_swatches(self, path: str) -> None:
        self.widget.import_palette(path)

    def export_swatches(self, path: str) -> None:
        self.widget.export_palette(path)


class SwatchesDialog(QDialog):
    """Color swatch dialog with palette picker and import/export."""

    def __init__(self, palette: SwatchPalette | None = None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Color Swatches")
        self.resize(340, 420)
        self._chosen_color: QColor | None = None

        layout = QVBoxLayout(self)
        self.swatches_widget = SwatchesWidget(palette=palette, parent=self)
        self.swatches_widget.colorSelected.connect(self._on_color_selected)
        layout.addWidget(self.swatches_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_color_selected(self, color: QColor, is_foreground: bool) -> None:
        self._chosen_color = color

    def selected_color(self) -> QColor | None:
        return self._chosen_color
