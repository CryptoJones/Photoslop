# SPDX-License-Identifier: Apache-2.0
"""Zero-copy numpy views over QImage buffers, plus the flood fill.

The fill is an iterative scanline algorithm: span expansion and neighbour-run
discovery are vectorised, so no per-pixel Python runs even on large regions,
and the only allocations are the boolean masks.
"""

from __future__ import annotations

from collections import deque

import numpy as np
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QPainter, QPainterPath, Qt


def view_u32(img: QImage) -> np.ndarray:
    """Writable (h, w) uint32 view of a 32-bpp QImage. No copy."""
    h, w = img.height(), img.width()
    bpl = img.bytesPerLine()
    if bpl != w * 4:  # 32-bpp scanlines are always 4-byte aligned, so this never triggers
        raise ValueError(f"unexpected scanline padding: bpl={bpl} w={w}")
    arr = np.frombuffer(img.bits(), dtype=np.uint8, count=h * bpl)
    return arr.view(np.uint32).reshape(h, w)


def premultiplied_u32(r: int, g: int, b: int, a: int) -> int:
    """Premultiplied QRgb value as stored in Format_ARGB32_Premultiplied."""
    pr = r * a // 255
    pg = g * a // 255
    pb = b * a // 255
    return (a << 24) | (pr << 16) | (pg << 8) | pb


def selection_mask(path, size, offset) -> np.ndarray:
    """Rasterise a QPainterPath (canvas coords) to a bool mask in layer coords."""
    w, h = size.width(), size.height()
    mask_img = QImage(w, h, QImage.Format.Format_Grayscale8)
    mask_img.fill(0)
    p = QPainter(mask_img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    p.fillPath(path.translated(-offset.x(), -offset.y()), Qt.GlobalColor.white)
    p.end()
    bpl = mask_img.bytesPerLine()
    arr = np.frombuffer(mask_img.bits(), dtype=np.uint8, count=h * bpl).reshape(h, bpl)
    return arr[:, :w] > 127


def _tolerance_mask(arr: np.ndarray, target: int, tolerance: int) -> np.ndarray:
    if tolerance <= 0:
        return arr == np.uint32(target)
    tb, tg = target & 0xFF, (target >> 8) & 0xFF
    tr, ta = (target >> 16) & 0xFF, (target >> 24) & 0xFF
    db = np.abs((arr & 0xFF).astype(np.int16) - tb)
    dg = np.abs(((arr >> np.uint32(8)) & 0xFF).astype(np.int16) - tg)
    dr = np.abs(((arr >> np.uint32(16)) & 0xFF).astype(np.int16) - tr)
    da = np.abs((arr >> np.uint32(24)).astype(np.int16) - ta)
    return np.maximum(np.maximum(db, dg), np.maximum(dr, da)) <= tolerance


def _mask_bbox(mask: np.ndarray) -> QRect:
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    return QRect(int(cols[0]), int(rows[0]),
                 int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))


def global_mask(
    img: QImage,
    x: int,
    y: int,
    tolerance: int = 0,
    sel_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, QRect] | None:
    """Mask of ALL pixels within tolerance of the seed colour, connected or
    not — the wand's non-contiguous / colour-range mode."""
    arr = view_u32(img)
    h, w = arr.shape
    if not (0 <= x < w and 0 <= y < h):
        return None
    mask = _tolerance_mask(arr, int(arr[y, x]), tolerance)
    if sel_mask is not None:
        mask = mask & sel_mask
    if not mask[y, x]:
        return None
    return mask, _mask_bbox(mask)


def flood_mask(
    img: QImage,
    x: int,
    y: int,
    tolerance: int = 0,
    sel_mask: np.ndarray | None = None,
) -> tuple[np.ndarray, QRect] | None:
    """Boolean mask of the region connected to (x, y) whose pixels are within
    tolerance of the seed. Non-destructive; returns (mask, bbox) or None."""
    arr = view_u32(img)
    h, w = arr.shape
    if not (0 <= x < w and 0 <= y < h):
        return None

    fillable = _tolerance_mask(arr, int(arr[y, x]), tolerance)
    if sel_mask is not None:
        fillable &= sel_mask
    if not fillable[y, x]:
        return None

    filled = np.zeros((h, w), dtype=bool)
    queue: deque[tuple[int, int]] = deque([(x, y)])
    minx = maxx = x
    miny = maxy = y

    while queue:
        sx, sy = queue.popleft()
        if filled[sy, sx] or not fillable[sy, sx]:
            continue
        blocked = ~(fillable[sy] & ~filled[sy])
        left_blocks = np.flatnonzero(blocked[:sx])
        left = int(left_blocks[-1]) + 1 if left_blocks.size else 0
        right_blocks = np.flatnonzero(blocked[sx:])
        right = sx + int(right_blocks[0]) - 1 if right_blocks.size else w - 1

        filled[sy, left : right + 1] = True
        minx = min(minx, left)
        maxx = max(maxx, right)
        miny = min(miny, sy)
        maxy = max(maxy, sy)

        for ny in (sy - 1, sy + 1):
            if 0 <= ny < h:
                runs = fillable[ny, left : right + 1] & ~filled[ny, left : right + 1]
                idx = np.flatnonzero(runs)
                if idx.size:
                    starts = idx[np.concatenate(([True], np.diff(idx) > 1))]
                    for s in starts:
                        queue.append((left + int(s), ny))

    return filled, QRect(minx, miny, maxx - minx + 1, maxy - miny + 1)


def flood_fill(
    img: QImage,
    x: int,
    y: int,
    color: int,
    tolerance: int = 0,
    sel_mask: np.ndarray | None = None,
) -> QRect | None:
    """Fill the region connected to (x, y) whose pixels are within tolerance
    of the seed pixel. Returns the dirty rect in image coords, or None if
    nothing changed.
    """
    arr = view_u32(img)
    h, w = arr.shape
    if not (0 <= x < w and 0 <= y < h):
        return None
    new = np.uint32(color & 0xFFFFFFFF)
    if int(arr[y, x]) == int(new):
        return None  # nothing to do; avoids re-filling with the same value
    result = flood_mask(img, x, y, tolerance, sel_mask)
    if result is None:
        return None
    mask, bbox = result
    arr[mask] = new
    return bbox


def mask_to_path(mask: np.ndarray, offset: QPoint | None = None) -> QPainterPath:
    """Convert a boolean mask to a selection QPainterPath. Identical row
    runs are merged into vertical bands first, so the path stays small."""
    ox = offset.x() if offset is not None else 0
    oy = offset.y() if offset is not None else 0
    rects: list[QRect] = []
    open_bands: dict[tuple[int, int], list[int]] = {}  # span -> [y0, last_y]
    for row in np.flatnonzero(mask.any(axis=1)):
        y = int(row)
        row_idx = np.flatnonzero(mask[y])
        starts = row_idx[np.concatenate(([True], np.diff(row_idx) > 1))]
        ends = row_idx[np.concatenate((np.diff(row_idx) > 1, [True]))]
        spans = {(int(s), int(e)) for s, e in zip(starts, ends, strict=True)}
        for span in list(open_bands):
            y0, last = open_bands[span]
            if span not in spans or y != last + 1:
                rects.append(QRect(span[0] + ox, y0 + oy,
                                   span[1] - span[0] + 1, last - y0 + 1))
                del open_bands[span]
        for span in spans:
            if span in open_bands:
                open_bands[span][1] = y
            else:
                open_bands[span] = [y, y]
    for (s, e), (y0, last) in open_bands.items():
        rects.append(QRect(s + ox, y0 + oy, e - s + 1, last - y0 + 1))
    path = QPainterPath()
    for rect in rects:
        path.addRect(rect)
    return path.simplified()
