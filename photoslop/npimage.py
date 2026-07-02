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


def drop_shadow_image(img: QImage, color, blur: int) -> QImage:
    """A blurred, tinted silhouette of `img`'s alpha, padded by `blur` px on
    every side (so offsets never clip)."""
    pad = max(0, int(blur))
    h, w = img.height(), img.width()
    alpha = np.zeros((h + 2 * pad, w + 2 * pad), dtype=np.float32)
    src = view_u32(img)
    alpha[pad:pad + h, pad:pad + w] = (src >> np.uint32(24)).astype(np.float32)

    if pad:
        r = max(1, pad // 2)
        for _ in range(3):  # triple box blur ~ gaussian
            k = 2 * r + 1
            csum = np.cumsum(alpha, axis=0)
            alpha = (np.vstack((csum[r:], np.repeat(csum[-1:], r, axis=0)))
                     - np.vstack((np.zeros((r + 1, alpha.shape[1]), np.float32),
                                  csum[:-r - 1]))) / k
            csum = np.cumsum(alpha, axis=1)
            alpha = (np.hstack((csum[:, r:], np.repeat(csum[:, -1:], r, axis=1)))
                     - np.hstack((np.zeros((alpha.shape[0], r + 1), np.float32),
                                  csum[:, :-r - 1]))) / k

    a = np.clip(alpha * (color.alpha() / 255.0), 0, 255).astype(np.uint32)
    scale = a / 255.0
    out = QImage(alpha.shape[1], alpha.shape[0], img.format())
    view_u32(out)[:] = ((a << np.uint32(24))
                        | ((color.red() * scale).astype(np.uint32) << np.uint32(16))
                        | ((color.green() * scale).astype(np.uint32) << np.uint32(8))
                        | (color.blue() * scale).astype(np.uint32))
    return out


def _seam_energy(arr: np.ndarray) -> np.ndarray:
    r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
    g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
    b = (arr & 0xFF).astype(np.float32)
    gray = 0.299 * r + 0.587 * g + 0.114 * b
    dx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    dy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    return dx + dy


def _remove_one_seam(arr: np.ndarray) -> np.ndarray:
    """Remove the lowest-energy vertical seam from an (h, w) uint32 array."""
    h, w = arr.shape
    m = _seam_energy(arr)
    for y in range(1, h):
        prev = m[y - 1]
        left = np.concatenate(([np.inf], prev[:-1]))
        right = np.concatenate((prev[1:], [np.inf]))
        m[y] += np.minimum(np.minimum(left, prev), right)

    seam = np.empty(h, dtype=np.int64)
    seam[-1] = int(np.argmin(m[-1]))
    for y in range(h - 2, -1, -1):
        x = seam[y + 1]
        x0 = max(0, x - 1)
        seam[y] = x0 + int(np.argmin(m[y, x0:min(w, x + 2)]))

    keep = np.ones((h, w), dtype=bool)
    keep[np.arange(h), seam] = False
    return arr[keep].reshape(h, w - 1)


def seam_carve(img: QImage, target_w: int, target_h: int) -> QImage:
    """Content-aware shrink to (target_w, target_h): repeatedly remove the
    lowest-energy seam — vertical seams for width, horizontal (via
    transpose) for height. Detail survives; flat areas give way."""
    arr = view_u32(img).copy()
    target_w = max(2, min(target_w, arr.shape[1]))
    target_h = max(2, min(target_h, arr.shape[0]))
    while arr.shape[1] > target_w:
        arr = _remove_one_seam(arr)
    if arr.shape[0] > target_h:
        arr = np.ascontiguousarray(arr.T)
        while arr.shape[1] > target_h:
            arr = _remove_one_seam(arr)
        arr = np.ascontiguousarray(arr.T)

    out = QImage(arr.shape[1], arr.shape[0], img.format())
    view_u32(out)[:] = arr
    return out


def inpaint_diffuse(img: QImage, mask: np.ndarray, blend_passes: int = 3) -> QRect:
    """Fill the masked pixels by diffusing inward from the boundary (each
    unknown pixel takes the mean of its known 4-neighbours, layer by layer),
    then smooth the healed region. Operates on the mask's bbox only.
    Returns the dirty rect."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return QRect()
    pad = 2
    y0, y1 = max(0, ys.min() - pad), min(mask.shape[0], ys.max() + 1 + pad)
    x0, x1 = max(0, xs.min() - pad), min(mask.shape[1], xs.max() + 1 + pad)

    arr = view_u32(img)[y0:y1, x0:x1]
    hole = mask[y0:y1, x0:x1].copy()
    channels = [((arr >> np.uint32(shift)) & 0xFF).astype(np.float32)
                for shift in (24, 16, 8, 0)]
    known = ~hole

    shifts = (((slice(1, None), slice(None)), (slice(None, -1), slice(None))),
              ((slice(None, -1), slice(None)), (slice(1, None), slice(None))),
              ((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
              ((slice(None), slice(None, -1)), (slice(None), slice(1, None))))
    while not known.all():
        cnt = np.zeros_like(channels[0])
        for src, dst in shifts:
            cnt[dst] += known[src]
        newly = (~known) & (cnt > 0)
        if not newly.any():
            break
        for c in channels:
            acc = np.zeros_like(c)
            for src, dst in shifts:
                acc[dst] += c[src] * known[src]
            c[newly] = acc[newly] / cnt[newly]
        known |= newly

    healed = hole
    for _ in range(blend_passes):  # soften the fill against its surroundings
        for c in channels:
            blur = c.copy()
            blur[1:-1, 1:-1] = (c[:-2, 1:-1] + c[2:, 1:-1] + c[1:-1, :-2]
                                + c[1:-1, 2:] + c[1:-1, 1:-1]) / 5.0
            c[healed] = blur[healed]

    a, r, g, b = [np.clip(c + 0.5, 0, 255).astype(np.uint32) for c in channels]
    out = (a << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    arr[hole] = out[hole]
    return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def _dilate(mask: np.ndarray) -> np.ndarray:
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    out[1:, 1:] |= mask[:-1, :-1]
    out[1:, :-1] |= mask[:-1, 1:]
    out[:-1, 1:] |= mask[1:, :-1]
    out[:-1, :-1] |= mask[1:, 1:]
    return out


def _erode(mask: np.ndarray) -> np.ndarray:
    return ~_dilate(~mask)


def refine_mask(mask: np.ndarray, smooth: int = 0, expand: int = 0) -> np.ndarray:
    """Morphological selection refinement: `smooth` rounds corners and fills
    notches (close-then-open), `expand` grows (+) or contracts (-) by that
    many pixels. Exact 8-neighbour morphology, no dependencies."""
    out = mask
    for _ in range(max(0, smooth)):  # close
        out = _dilate(out)
    for _ in range(max(0, smooth) * 2):  # then open (erode past the close)
        out = _erode(out)
    for _ in range(max(0, smooth)):
        out = _dilate(out)
    if expand > 0:
        for _ in range(expand):
            out = _dilate(out)
    elif expand < 0:
        for _ in range(-expand):
            out = _erode(out)
    return out


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
