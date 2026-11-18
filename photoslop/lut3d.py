# SPDX-License-Identifier: Apache-2.0
"""3D and 1D Lookup Table (LUT) support for Color Lookup adjustment.

Supports:
- Adobe `.cube` format (1D and 3D tables, domain min/max, comments, titles).
- Autodesk Lustre `.3dl` format (mesh size headers, 10/12/16-bit integer or float data).
- Fast vectorized trilinear interpolation with compact float32 grid representations.
- Built-in cinematic / film presets: "Warm Film", "Cool Crisp", "Bleach Bypass",
  "Teal & Orange", "Faded Monochrome".
- Memory Frugality (DD-001): stream-processed over row chunks (CHUNK_ROWS = 256),
  bounding transient memory allocation regardless of layer resolution.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage

from photoslop.npimage import view_u32

CHUNK_ROWS = 256


@dataclass
class LUT3D:
    """In-memory 3D or 1D Lookup Table.

    For 3D LUTs: `table` has shape `(size, size, size, 3)` where axes are (R, G, B)
    and elements are output [R, G, B] in [0.0, 1.0].
    For 1D LUTs: `table` has shape `(size, 3)` and `is_1d` is True.
    """

    name: str
    size: int
    table: np.ndarray  # float32 array in [0.0, 1.0]
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0)
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0)
    is_1d: bool = False

    def __post_init__(self) -> None:
        if self.table is not None:
            self.table = np.ascontiguousarray(self.table, dtype=np.float32)


# ---------------------------------------------------------------------------
# Built-in Presets
# ---------------------------------------------------------------------------


def _preset_warm_film(
    r: np.ndarray, g: np.ndarray, b: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Golden-amber warmth, gentle film contrast, lifted shadows with amber warmth."""
    cr = 0.75 * r + 0.25 * (r * r * (3.0 - 2.0 * r))
    cg = 0.75 * g + 0.25 * (g * g * (3.0 - 2.0 * g))
    cb = 0.75 * b + 0.25 * (b * b * (3.0 - 2.0 * b))
    ro = cr * 1.06 + 0.03 * (1.0 - cr)
    go = cg * 1.01 + 0.01 * (1.0 - cg)
    bo = cb * (0.88 + 0.12 * cb) + 0.01 * (1.0 - cb)
    return np.clip(ro, 0.0, 1.0), np.clip(go, 0.0, 1.0), np.clip(bo, 0.0, 1.0)


def _preset_cool_crisp(
    r: np.ndarray, g: np.ndarray, b: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """High contrast, cool shadows/midtones, punchy clean whites."""
    sr = r * r * (3.0 - 2.0 * r)
    sg = g * g * (3.0 - 2.0 * g)
    sb = b * b * (3.0 - 2.0 * b)
    cr = 0.6 * r + 0.4 * sr
    cg = 0.6 * g + 0.4 * sg
    cb = 0.6 * b + 0.4 * sb
    ro = cr * (0.92 + 0.08 * cr)
    go = cg * 1.01
    bo = cb * 1.08 + 0.02 * (1.0 - cb)
    return np.clip(ro, 0.0, 1.0), np.clip(go, 0.0, 1.0), np.clip(bo, 0.0, 1.0)


def _preset_bleach_bypass(
    r: np.ndarray, g: np.ndarray, b: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Classic cinema bleach bypass look: high contrast, desaturated silver retention."""
    y = 0.299 * r + 0.587 * g + 0.114 * b
    dr = 0.35 * r + 0.65 * y
    dg = 0.35 * g + 0.65 * y
    db = 0.35 * b + 0.65 * y
    y_curve = y * y * (3.0 - 2.0 * y)
    ro = (1.0 - 2.0 * y_curve) * (dr * dr) + 2.0 * y_curve * dr
    go = (1.0 - 2.0 * y_curve) * (dg * dg) + 2.0 * y_curve * dg
    bo = (1.0 - 2.0 * y_curve) * (db * db) + 2.0 * y_curve * db
    return np.clip(ro, 0.0, 1.0), np.clip(go, 0.0, 1.0), np.clip(bo, 0.0, 1.0)


def _preset_teal_orange(
    r: np.ndarray, g: np.ndarray, b: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Hollywood blockbuster teal shadows and warm orange midtones/highlights."""
    y = 0.299 * r + 0.587 * g + 0.114 * b
    wo = np.clip((y - 0.35) / 0.65, 0.0, 1.0)
    ro = r + 0.18 * wo * (1.0 - r)
    go = g + 0.05 * wo * (1.0 - g)
    bo = b - 0.14 * wo * b

    wt = np.clip((0.65 - y) / 0.65, 0.0, 1.0)
    ro = ro - 0.12 * wt * ro
    go = go + 0.05 * wt * (1.0 - go)
    bo = bo + 0.20 * wt * (1.0 - bo)

    ro = 0.8 * ro + 0.2 * (ro * ro * (3.0 - 2.0 * ro))
    go = 0.8 * go + 0.2 * (go * go * (3.0 - 2.0 * go))
    bo = 0.8 * bo + 0.2 * (bo * bo * (3.0 - 2.0 * bo))
    return np.clip(ro, 0.0, 1.0), np.clip(go, 0.0, 1.0), np.clip(bo, 0.0, 1.0)


def _preset_faded_monochrome(
    r: np.ndarray, g: np.ndarray, b: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Matte black vintage monochrome film: lifted charcoal blacks, compressed highlights."""
    y = 0.299 * r + 0.587 * g + 0.114 * b
    y_fade = 0.08 + 0.84 * y
    ro = y_fade * 1.02 + 0.01
    go = y_fade * 1.00
    bo = y_fade * 0.96
    return np.clip(ro, 0.0, 1.0), np.clip(go, 0.0, 1.0), np.clip(bo, 0.0, 1.0)


PRESET_FUNCS = {
    "Warm Film": _preset_warm_film,
    "Cool Crisp": _preset_cool_crisp,
    "Bleach Bypass": _preset_bleach_bypass,
    "Teal & Orange": _preset_teal_orange,
    "Faded Monochrome": _preset_faded_monochrome,
}

PRESET_NAMES = list(PRESET_FUNCS.keys())

_PRESET_CACHE: dict[tuple[str, int], LUT3D] = {}


def _normalize_name(name: str) -> str:
    cleaned = re.sub(r"[_\s\-]+", " ", name.strip().lower())
    for standard in PRESET_NAMES:
        std_norm = re.sub(r"[_\s\-]+", " ", standard.lower())
        if cleaned == std_norm:
            return standard
        if cleaned.replace("&", "and") == std_norm.replace("&", "and"):
            return standard
    return name


def get_preset_lut(name: str, size: int = 17) -> LUT3D:
    """Construct or retrieve a cached built-in 3D LUT preset."""
    std_name = _normalize_name(name)
    if std_name not in PRESET_FUNCS:
        raise ValueError(f"Unknown LUT preset: {name!r}. Available: {', '.join(PRESET_NAMES)}")

    key = (std_name, size)
    if key in _PRESET_CACHE:
        return _PRESET_CACHE[key]

    fn = PRESET_FUNCS[std_name]
    coords = np.linspace(0.0, 1.0, size, dtype=np.float32)
    rg, gg, bg = np.meshgrid(coords, coords, coords, indexing="ij")
    ro, go, bo = fn(rg, gg, bg)
    table = np.stack([ro, go, bo], axis=-1).astype(np.float32)

    lut = LUT3D(name=std_name, size=size, table=table)
    _PRESET_CACHE[key] = lut
    return lut


# ---------------------------------------------------------------------------
# Adobe .cube Parser
# ---------------------------------------------------------------------------


def parse_cube(content_or_path: str | os.PathLike | bytes | io.StringIO) -> LUT3D:
    """Parse Adobe .cube LUT file (1D or 3D)."""
    if isinstance(content_or_path, (str, os.PathLike)) and os.path.isfile(content_or_path):
        with open(content_or_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        default_title = Path(content_or_path).stem
    elif isinstance(content_or_path, bytes):
        text = content_or_path.decode("utf-8", errors="replace")
        default_title = "Untitled"
    elif isinstance(content_or_path, io.StringIO):
        text = content_or_path.getvalue()
        default_title = "Untitled"
    elif isinstance(content_or_path, str):
        text = content_or_path
        default_title = "Untitled"
    else:
        raise ValueError(f"Unsupported content type for .cube: {type(content_or_path)}")

    title = default_title
    lut_1d_size: int | None = None
    lut_3d_size: int | None = None
    domain_min = (0.0, 0.0, 0.0)
    domain_max = (1.0, 1.0, 1.0)

    data_triplets: list[list[float]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        tag = parts[0].upper()

        if tag == "TITLE":
            # Extract everything after TITLE, stripping quotes
            val = line[5:].strip()
            if val.startswith('"') and val.endswith('"') and len(val) >= 2:
                val = val[1:-1]
            title = val
        elif tag == "LUT_1D_SIZE":
            lut_1d_size = int(parts[1])
        elif tag == "LUT_3D_SIZE":
            lut_3d_size = int(parts[1])
        elif tag == "DOMAIN_MIN":
            domain_min = (float(parts[1]), float(parts[2]), float(parts[3]))
        elif tag == "DOMAIN_MAX":
            domain_max = (float(parts[1]), float(parts[2]), float(parts[3]))
        else:
            if len(parts) == 3:
                try:
                    data_triplets.append([float(parts[0]), float(parts[1]), float(parts[2])])
                except ValueError:
                    continue

    if not data_triplets:
        raise ValueError("No table data found in .cube file")

    raw = np.array(data_triplets, dtype=np.float32)

    is_1d = lut_1d_size is not None or (
        lut_3d_size is None and raw.shape[0] != round(raw.shape[0] ** (1 / 3)) ** 3
    )
    if is_1d:
        # 1D LUT
        n = lut_1d_size if lut_1d_size is not None else raw.shape[0]
        if raw.shape[0] != n:
            raise ValueError(f"Expected {n} entries for 1D LUT, got {raw.shape[0]}")
        return LUT3D(
            name=title,
            size=n,
            table=raw,
            domain_min=domain_min,
            domain_max=domain_max,
            is_1d=True,
        )

    # 3D LUT
    n = lut_3d_size if lut_3d_size is not None else int(round(raw.shape[0] ** (1.0 / 3.0)))
    expected_count = n * n * n
    if raw.shape[0] != expected_count:
        raise ValueError(
            f"Expected {expected_count} entries for 3D LUT size {n}, got {raw.shape[0]}"
        )

    # In Adobe .cube, order is Blue slowest, Green middle, Red fastest.
    # Reshaping raw as (N_b, N_g, N_r, 3) and transposing (2, 1, 0, 3) yields (N_r, N_g, N_b, 3).
    table = raw.reshape((n, n, n, 3)).transpose(2, 1, 0, 3)

    return LUT3D(
        name=title,
        size=n,
        table=table,
        domain_min=domain_min,
        domain_max=domain_max,
        is_1d=False,
    )


# ---------------------------------------------------------------------------
# Autodesk Lustre .3dl Parser
# ---------------------------------------------------------------------------


def parse_3dl(content_or_path: str | os.PathLike | bytes | io.StringIO) -> LUT3D:
    """Parse Autodesk Lustre .3dl format."""
    if isinstance(content_or_path, (str, os.PathLike)) and os.path.isfile(content_or_path):
        with open(content_or_path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        title = Path(content_or_path).stem
    elif isinstance(content_or_path, bytes):
        text = content_or_path.decode("utf-8", errors="replace")
        title = "Untitled"
    elif isinstance(content_or_path, io.StringIO):
        text = content_or_path.getvalue()
        title = "Untitled"
    elif isinstance(content_or_path, str):
        text = content_or_path
        title = "Untitled"
    else:
        raise ValueError(f"Unsupported content type for .3dl: {type(content_or_path)}")

    declared_bit_depth: int | None = None
    data_triplets: list[list[float]] = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        upper_line = line.upper()

        if "3DMESH" in upper_line or "MESH" in upper_line:
            # Header line like "3DMESH Mesh 4 12" or "Mesh 4 12"
            for token in parts:
                if token.isdigit():
                    num = int(token)
                    if num in (8, 10, 12, 14, 16):
                        declared_bit_depth = num
            continue

        if len(parts) == 3:
            try:
                data_triplets.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except ValueError:
                continue

    if not data_triplets:
        raise ValueError("No table data found in .3dl file")

    raw = np.array(data_triplets, dtype=np.float32)
    total = raw.shape[0]
    n = int(round(total ** (1.0 / 3.0)))
    if n * n * n != total:
        raise ValueError(f"Invalid .3dl table length {total}; not a perfect cube")

    # In Autodesk Lustre .3dl, order is Red slowest, Green middle, Blue fastest.
    # Reshaping to (N_r, N_g, N_b, 3) places Red in axis 0, Green in 1, Blue in 2.
    table = raw.reshape((n, n, n, 3))

    max_val = float(table.max())
    if max_val > 1.0:
        if declared_bit_depth is not None:
            table /= float((1 << declared_bit_depth) - 1)
        elif max_val <= 255.0:
            table /= 255.0
        elif max_val <= 1023.0:
            table /= 1023.0
        elif max_val <= 4095.0:
            table /= 4095.0
        elif max_val <= 65535.0:
            table /= 65535.0
        else:
            table /= max_val

    table = np.clip(table, 0.0, 1.0)

    return LUT3D(name=title, size=n, table=table, is_1d=False)


# ---------------------------------------------------------------------------
# General Loader
# ---------------------------------------------------------------------------


def load_lut(target: str | os.PathLike | LUT3D) -> LUT3D:
    """Load a LUT from a preset name, .cube / .3dl file path, or return existing LUT3D."""
    if isinstance(target, LUT3D):
        return target

    str_target = str(target).strip()

    # Check built-in preset names
    std_preset = _normalize_name(str_target)
    if std_preset in PRESET_FUNCS:
        return get_preset_lut(std_preset)

    # Check file path
    path = Path(str_target)
    if path.is_file():
        suffix = path.suffix.lower()
        if suffix == ".cube":
            return parse_cube(path)
        if suffix == ".3dl":
            return parse_3dl(path)
        # Try cube first, then 3dl
        try:
            return parse_cube(path)
        except Exception:
            return parse_3dl(path)

    # If it is raw file content in string
    if "LUT_3D_SIZE" in str_target or "LUT_1D_SIZE" in str_target:
        return parse_cube(str_target)
    if "3DMESH" in str_target.upper() or "MESH" in str_target.upper():
        return parse_3dl(str_target)

    raise ValueError(
        f"Cannot resolve LUT target: {str_target!r}. Not a known preset or valid file."
    )


# ---------------------------------------------------------------------------
# Trilinear and 1D Interpolation Engine
# ---------------------------------------------------------------------------


def _interp_3d(
    table: np.ndarray,
    rf: np.ndarray,
    gf: np.ndarray,
    bf: np.ndarray,
    domain_min: tuple[float, float, float],
    domain_max: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorized trilinear interpolation over table of shape (N, N, N, 3)."""
    n = table.shape[0]
    max_idx = n - 1

    # Normalize through domain min / max
    if domain_min != (0.0, 0.0, 0.0) or domain_max != (1.0, 1.0, 1.0):
        dmin_r, dmin_g, dmin_b = domain_min
        dmax_r, dmax_g, dmax_b = domain_max
        rf = (rf - dmin_r) / max(dmax_r - dmin_r, 1e-6)
        gf = (gf - dmin_g) / max(dmax_g - dmin_g, 1e-6)
        bf = (bf - dmin_b) / max(dmax_b - dmin_b, 1e-6)

    rx = np.clip(rf * max_idx, 0.0, max_idx)
    gx = np.clip(gf * max_idx, 0.0, max_idx)
    bx = np.clip(bf * max_idx, 0.0, max_idx)

    r0 = np.floor(rx).astype(np.int32)
    r1 = np.minimum(r0 + 1, max_idx)
    dr = (rx - r0)[..., None]

    g0 = np.floor(gx).astype(np.int32)
    g1 = np.minimum(g0 + 1, max_idx)
    dg = (gx - g0)[..., None]

    b0 = np.floor(bx).astype(np.int32)
    b1 = np.minimum(b0 + 1, max_idx)
    db = (bx - b0)[..., None]

    # Sample 8 lattice corners
    c000 = table[r0, g0, b0]
    c100 = table[r1, g0, b0]
    c010 = table[r0, g1, b0]
    c110 = table[r1, g1, b0]
    c001 = table[r0, g0, b1]
    c101 = table[r1, g0, b1]
    c011 = table[r0, g1, b1]
    c111 = table[r1, g1, b1]

    # Lerp along R
    c00 = c000 + (c100 - c000) * dr
    c10 = c010 + (c110 - c010) * dr
    c01 = c001 + (c101 - c001) * dr
    c11 = c011 + (c111 - c011) * dr

    # Lerp along G
    c0 = c00 + (c10 - c00) * dg
    c1 = c01 + (c11 - c01) * dg

    # Lerp along B
    out = c0 + (c1 - c0) * db
    return out[..., 0], out[..., 1], out[..., 2]


def _interp_1d(
    table: np.ndarray,
    rf: np.ndarray,
    gf: np.ndarray,
    bf: np.ndarray,
    domain_min: tuple[float, float, float],
    domain_max: tuple[float, float, float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """1D linear interpolation per channel."""
    n = table.shape[0]
    xr = np.linspace(domain_min[0], domain_max[0], n, dtype=np.float32)
    xg = np.linspace(domain_min[1], domain_max[1], n, dtype=np.float32)
    xb = np.linspace(domain_min[2], domain_max[2], n, dtype=np.float32)

    shape = rf.shape
    out_r = np.interp(rf.ravel(), xr, table[:, 0]).reshape(shape)
    out_g = np.interp(gf.ravel(), xg, table[:, 1]).reshape(shape)
    out_b = np.interp(bf.ravel(), xb, table[:, 2]).reshape(shape)
    return out_r, out_g, out_b


# ---------------------------------------------------------------------------
# Apply LUT3D to QImage or NumPy Array
# ---------------------------------------------------------------------------


def apply_lut3d(
    image: QImage | np.ndarray,
    lut: LUT3D,
    intensity: float = 1.0,
    mask: np.ndarray | None = None,
) -> QImage | np.ndarray:
    """Apply a 3D or 1D LUT to a QImage or NumPy array with row streaming and opacity blending.

    Memory Frugality contract (DD-001):
    Processed in chunks of CHUNK_ROWS (256) to ensure bounded transient float memory
    even on multi-megapixel documents.
    """
    intensity = float(np.clip(intensity, 0.0, 1.0))
    if intensity <= 0.0:
        return image

    is_qimage = isinstance(image, QImage)
    if is_qimage:
        arr = view_u32(image)
    elif isinstance(image, np.ndarray) and image.dtype == np.uint32 and image.ndim == 2:
        arr = image
    else:
        # Generic numpy array (RGB or RGBA uint8 or float32)
        return _apply_lut3d_numpy(image, lut, intensity, mask)

    h, w = arr.shape
    interp_fn = _interp_1d if lut.is_1d else _interp_3d

    for y0 in range(0, h, CHUNK_ROWS):
        chunk = arr[y0 : y0 + CHUNK_ROWS]
        a = (chunk >> np.uint32(24)).astype(np.uint16)
        r = ((chunk >> np.uint32(16)) & 0xFF).astype(np.uint16)
        g = ((chunk >> np.uint32(8)) & 0xFF).astype(np.uint16)
        b = (chunk & 0xFF).astype(np.uint16)

        opaque = bool((a == 255).all())
        if not opaque:
            safe_a = np.maximum(a, 1)
            r = np.minimum(255, r * 255 // safe_a)
            g = np.minimum(255, g * 255 // safe_a)
            b = np.minimum(255, b * 255 // safe_a)

        rf = r.astype(np.float32) / 255.0
        gf = g.astype(np.float32) / 255.0
        bf = b.astype(np.float32) / 255.0

        out_r, out_g, out_b = interp_fn(lut.table, rf, gf, bf, lut.domain_min, lut.domain_max)

        if intensity < 1.0:
            out_r = rf * (1.0 - intensity) + out_r * intensity
            out_g = gf * (1.0 - intensity) + out_g * intensity
            out_b = bf * (1.0 - intensity) + out_b * intensity

        r_mapped = np.clip(np.round(out_r * 255.0), 0, 255).astype(np.uint16)
        g_mapped = np.clip(np.round(out_g * 255.0), 0, 255).astype(np.uint16)
        b_mapped = np.clip(np.round(out_b * 255.0), 0, 255).astype(np.uint16)

        if not opaque:
            r_mapped = r_mapped * a // 255
            g_mapped = g_mapped * a // 255
            b_mapped = b_mapped * a // 255

        mapped = (
            (a.astype(np.uint32) << np.uint32(24))
            | (r_mapped.astype(np.uint32) << np.uint32(16))
            | (g_mapped.astype(np.uint32) << np.uint32(8))
            | b_mapped.astype(np.uint32)
        )

        if mask is None:
            chunk[:] = mapped
        else:
            band = mask[y0 : y0 + CHUNK_ROWS]
            chunk[band] = mapped[band]

    return image


def _apply_lut3d_numpy(
    arr: np.ndarray,
    lut: LUT3D,
    intensity: float,
    mask: np.ndarray | None,
) -> np.ndarray:
    """Fallback applier for general RGB/RGBA numpy arrays."""
    interp_fn = _interp_1d if lut.is_1d else _interp_3d
    is_float = np.issubdtype(arr.dtype, np.floating)

    h = arr.shape[0]
    out = arr.copy()

    for y0 in range(0, h, CHUNK_ROWS):
        chunk = out[y0 : y0 + CHUNK_ROWS]
        if is_float:
            rf = np.clip(chunk[..., 0], 0.0, 1.0)
            gf = np.clip(chunk[..., 1], 0.0, 1.0)
            bf = np.clip(chunk[..., 2], 0.0, 1.0)
        else:
            rf = chunk[..., 0].astype(np.float32) / 255.0
            gf = chunk[..., 1].astype(np.float32) / 255.0
            bf = chunk[..., 2].astype(np.float32) / 255.0

        ro, go, bo = interp_fn(lut.table, rf, gf, bf, lut.domain_min, lut.domain_max)

        if intensity < 1.0:
            ro = rf * (1.0 - intensity) + ro * intensity
            go = gf * (1.0 - intensity) + go * intensity
            bo = bf * (1.0 - intensity) + bo * intensity

        if is_float:
            new_r, new_g, new_b = ro, go, bo
        else:
            new_r = np.clip(np.round(ro * 255.0), 0, 255).astype(arr.dtype)
            new_g = np.clip(np.round(go * 255.0), 0, 255).astype(arr.dtype)
            new_b = np.clip(np.round(bo * 255.0), 0, 255).astype(arr.dtype)

        if mask is None:
            chunk[..., 0] = new_r
            chunk[..., 1] = new_g
            chunk[..., 2] = new_b
        else:
            band = mask[y0 : y0 + CHUNK_ROWS]
            chunk[..., 0][band] = new_r[band]
            chunk[..., 1][band] = new_g[band]
            chunk[..., 2][band] = new_b[band]

    return out


# ---------------------------------------------------------------------------
# Exporters
# ---------------------------------------------------------------------------


def write_cube(lut: LUT3D, dest: str | os.PathLike | io.StringIO) -> None:
    """Write a LUT3D to Adobe .cube format."""
    lines: list[str] = [
        "# Created by Photoslop v2.44.0",
        f'TITLE "{lut.name}"',
    ]
    if lut.domain_min != (0.0, 0.0, 0.0):
        d0, d1, d2 = lut.domain_min
        lines.append(f"DOMAIN_MIN {d0:.6f} {d1:.6f} {d2:.6f}")
    if lut.domain_max != (1.0, 1.0, 1.0):
        d0, d1, d2 = lut.domain_max
        lines.append(f"DOMAIN_MAX {d0:.6f} {d1:.6f} {d2:.6f}")

    if lut.is_1d:
        lines.append(f"LUT_1D_SIZE {lut.size}")
        for i in range(lut.size):
            r, g, b = lut.table[i]
            lines.append(f"{r:.6f} {g:.6f} {b:.6f}")
    else:
        lines.append(f"LUT_3D_SIZE {lut.size}")
        # Traversal order: Blue slowest, Green middle, Red fastest
        n = lut.size
        for b in range(n):
            for g in range(n):
                for r in range(n):
                    out_r, out_g, out_b = lut.table[r, g, b]
                    lines.append(f"{out_r:.6f} {out_g:.6f} {out_b:.6f}")

    text = "\n".join(lines) + "\n"
    if isinstance(dest, io.StringIO):
        dest.write(text)
    else:
        Path(dest).write_text(text, encoding="utf-8")


def write_3dl(lut: LUT3D, dest: str | os.PathLike | io.StringIO, bit_depth: int = 12) -> None:
    """Write a 3D LUT to Autodesk Lustre .3dl format."""
    if lut.is_1d:
        raise ValueError("Cannot write 1D LUT to .3dl format")

    max_val = float((1 << bit_depth) - 1)
    n = lut.size
    lines: list[str] = [
        "# Created by Photoslop v2.44.0",
        f"3DMESH Mesh {n} {bit_depth}",
    ]
    # Traversal order: Red slowest, Green middle, Blue fastest
    for r in range(n):
        for g in range(n):
            for b in range(n):
                out_r, out_g, out_b = lut.table[r, g, b]
                ir = int(round(out_r * max_val))
                ig = int(round(out_g * max_val))
                ib = int(round(out_b * max_val))
                lines.append(f"{ir} {ig} {ib}")

    text = "\n".join(lines) + "\n"
    if isinstance(dest, io.StringIO):
        dest.write(text)
    else:
        Path(dest).write_text(text, encoding="utf-8")
