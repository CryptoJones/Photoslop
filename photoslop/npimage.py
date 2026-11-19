# SPDX-License-Identifier: Apache-2.0
"""Zero-copy numpy views over QImage buffers, plus the flood fill.

The fill is an iterative scanline algorithm: span expansion and neighbour-run
discovery are vectorised, so no per-pixel Python runs even on large regions,
and the only allocations are the boolean masks.

The full-layer float paths (gaussian blur, unsharp mask, weighted blend,
puppet warp) walk the image in row bands of BAND_ROWS, so their transient
is a band's worth of planes rather than four float copies of the layer
(DD-001, #347) — the same discipline as adjust.CHUNK_ROWS.
"""

from __future__ import annotations

from collections import deque

import numpy as np
from PySide6.QtCore import QPoint, QRect
from PySide6.QtGui import QImage, QPainter, QPainterPath, Qt

BAND_ROWS = 256  # rows per float transient; twin of adjust.CHUNK_ROWS (adjust imports us)


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
    return QRect(
        int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1)
    )


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


def _compute_mixed_divergence(dest: np.ndarray, src: np.ndarray) -> np.ndarray:
    """Discrete divergence b = div v for mixed gradients max(|∇g|, |∇f_dest|)."""
    c, h, w = dest.shape
    b = np.zeros((c, h, w), dtype=np.float32)
    shifts = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    for dy, dx in shifts:
        sy_p = slice(1, h - 1)
        sx_p = slice(1, w - 1)
        sy_q = slice(1 + dy, h - 1 + dy if h - 1 + dy != 0 else None)
        sx_q = slice(1 + dx, w - 1 + dx if w - 1 + dx != 0 else None)
        dg = src[:, sy_p, sx_p] - src[:, sy_q, sx_q]
        df = dest[:, sy_p, sx_p] - dest[:, sy_q, sx_q]
        v = np.where(np.abs(dg) >= np.abs(df), dg, df)
        b[:, sy_p, sx_p] += v
    return b


def _restrict_plane_2x(
    img: np.ndarray, known: np.ndarray | None = None, linear: bool = True
) -> np.ndarray:
    """Injection restriction: coarse cell (i, j) is fine pixel (2i, 2j).

    Averaging 2x2 blocks would place each coarse value at a block centre
    (half a pixel off the coarse grid point) and, for inpainting, mix erased
    hole pixels into coarse boundary data. Injection keeps coarse boundary
    cells exact copies of real known pixels and keeps the grids aligned, so
    bilinear prolongation reproduces linear fields exactly at every level.

    With an even fine size n, plain injection's last coarse cell lands on
    fine n-2, which can sit inside the hole. Pinning that cell to the fine
    boundary value instead would break the coarse grid's uniform spacing:
    the solve (and prolongation) treat coarse index c-1 as fine 2(c-1), so
    boundary data from fine n-1 acting at that coordinate distorts the whole
    coarse solution. The fix is to extend the grid by one cell at fine
    position n carrying the linear extrapolation 2·v(n-1) − v(n-2): spacing
    stays uniform, the far boundary carries the true edge trend, and linear
    ramps restrict exactly. Where the n-2 row/column is erased hole (``known``
    marks real pixels), the trend is taken from the nearest known row/column
    instead (which may be the opposite ring when the hole spans the interior),
    so a linear ramp still restricts exactly; with no known pixel at all the
    extension replicates v(n-1) and garbage never leaks into coarse boundary
    data. ``linear=False`` replicates unconditionally: texture planes (clone
    source/destination) have no linear trend to extrapolate, and
    2·v(n-1) − v(n-2) on a checker boundary overshoots badly, poisoning the
    coarse harmonic-offset solve.
    """
    h, w = img.shape[1], img.shape[2]
    if h % 2 == 0:
        last = img[:, -1, :]
        if linear:
            if known is not None:
                # Nearest known row above the boundary, per column.
                k = np.where(known[:-1, :], np.arange(h - 1)[:, None], -1).max(axis=0)
                prev = img[:, np.maximum(k, 0), np.arange(w)]
                prev = np.where((k >= 0)[None, :], prev, last)
                step = np.where(k >= 0, (h - 1) - k, 1).astype(np.float32)
                extra = last + (last - prev) / step[None, :]
            else:
                extra = 2.0 * last - img[:, -2, :]
        else:
            extra = last
        img = np.concatenate([img, extra[:, None, :]], axis=1)
        if known is not None:
            known = np.concatenate([known, np.ones((1, w), dtype=bool)], axis=0)
    if w % 2 == 0:
        last = img[:, :, -1]
        if linear:
            if known is not None:
                # Nearest known column left of the boundary, per row.
                k = np.where(known[:, :-1], np.arange(w - 1)[None, :], -1).max(axis=1)
                prev = img[:, np.arange(img.shape[1]), np.maximum(k, 0)]
                prev = np.where((k >= 0)[None, :], prev, last)
                step = np.where(k >= 0, (w - 1) - k, 1).astype(np.float32)
                extra = last + (last - prev) / step[None, :]
            else:
                extra = 2.0 * last - img[:, :, -2]
        else:
            extra = last
        img = np.concatenate([img, extra[:, :, None]], axis=2)
    return img[:, ::2, ::2].copy()


def _restrict_texture_2x(img: np.ndarray) -> np.ndarray:
    """Aligned anti-aliased (full-weighting) restriction for clone texture.

    Injection (coarse ``i`` = fine ``2i``) keeps the grids aligned and ramps
    exact, but samples a single phase of a near-Nyquist texture: a 160/220
    single-pixel checkerboard restricts to 220 everywhere instead of its true
    mean 190, so the coarse harmonic offset carried to a large hole's centre is
    biased (−160 instead of −130) and the cloned tone comes out wrong. The 3×3
    full-weighting kernel ``[1 2 1; 2 4 2; 1 2 1] / 16`` centred on fine
    ``(2i, 2j)`` fixes the mean while keeping coarse ``i`` aligned with fine
    ``2i`` (so bilinear prolongation still reproduces linear fields), and keeps
    constant planes exact because the weights sum to 1. Border cells clamp
    (replicate) so no garbage leaks into coarse boundary data. Even fine sizes
    are extended by one replicated cell so the coarse shape matches the mask
    pyramid, which appends a far-boundary coarse cell for even levels.
    """
    if img.shape[1] % 2 == 0:
        img = np.concatenate([img, img[:, -1:, :]], axis=1)
    if img.shape[2] % 2 == 0:
        img = np.concatenate([img, img[:, :, -1:]], axis=2)
    pad = np.pad(img, ((0, 0), (1, 1), (1, 1)), mode="edge")
    out = (
        pad[:, 0:-2:2, 0:-2:2]
        + 2.0 * pad[:, 0:-2:2, 1:-1:2]
        + pad[:, 0:-2:2, 2::2]
        + 2.0 * pad[:, 1:-1:2, 0:-2:2]
        + 4.0 * pad[:, 1:-1:2, 1:-1:2]
        + 2.0 * pad[:, 1:-1:2, 2::2]
        + pad[:, 2::2, 0:-2:2]
        + 2.0 * pad[:, 2::2, 1:-1:2]
        + pad[:, 2::2, 2::2]
    ) / 16.0
    return out.astype(np.float32)


# Multigrid convergence controls: stop a level's SOR sweeps once the max
# residual on masked cells is below a quarter of a quantisation step (the
# result is rounded to u8 anyway), with sweep caps so a pathological patch
# cannot spin. The coarsest grid is tiny, so it gets a generous cap.
_MG_RESIDUAL_TOL = 0.02
_MG_MAX_SWEEPS = 80
_MG_COARSEST_SWEEPS = 400


def poisson_solve_multigrid(
    dest: np.ndarray,
    mask: np.ndarray,
    src: np.ndarray | None = None,
    mixed: bool = False,
    omega: float = 1.7,
    neumann: tuple[bool, bool, bool, bool] = (False, False, False, False),
) -> np.ndarray:
    """Cascadic multigrid Poisson solver with Successive Over-Relaxation (SOR).

    Solves Δf = div v over masked domain Ω with Dirichlet boundary conditions
    matching surrounding pixels:
    - If src is None: solves Laplace Δf = 0 (spot healing / inpainting).
    - If src is provided and mixed is False: guidance v = ∇g where g is src
      texture (seamless cloning via harmonic offset field u = f - g).
    - If src is provided and mixed is True: mixed gradient guidance
      v = argmax_mag(∇g, ∇f_dest).
    - neumann: (top, bottom, left, right) flags for reflective zero-gradient
      boundary conditions at canvas borders.

    Builds half-resolution levels until the coarsest grid's shorter side is
    below 8 px (so boundary information can reach every interior cell cheaply),
    solves the coarsest level with Red-Black SOR (omega ≈ 1.5-1.8), upsamples
    to warm-start finer levels, and smooths each level until its max residual
    drops below ``_MG_RESIDUAL_TOL`` or a per-level sweep cap is hit. The
    residual stop is what makes large masks converge: a fixed sweep budget
    cannot propagate boundary values to the centre of a big hole, but the
    coarse solve carries the low-frequency part and the fine levels only
    polish the interpolation error.

    Memory (DD-001): work is proportional to the patch it is given — callers
    pass the mask's bounding box plus padding, not the canvas. A selection
    that covers (nearly) the whole canvas therefore does allocate
    (nearly) canvas-sized planes; the bound is the crop, not a constant.
    """
    if not mask.any():
        return dest.copy()
    c, h, w = dest.shape
    if h < 3 or w < 3:
        return dest.copy()

    masks = [mask.copy()]
    dests = [dest.copy()]
    srcs = [src.copy()] if src is not None else None

    masks[0][0, :] = False
    masks[0][-1, :] = False
    masks[0][:, 0] = False
    masks[0][:, -1] = False

    # Coarsen while the grid is big enough that SOR alone would not reach the
    # interior, and while the hole still has an interior at the next level.
    while min(masks[-1].shape) >= 8 and len(masks) < 16:
        m_fine = masks[-1]
        m_coarse = m_fine[::2, ::2].copy()
        # Match _restrict_plane_2x's even-size extension: the appended coarse
        # row/column is the extrapolated far boundary, always known.
        if m_fine.shape[0] % 2 == 0:
            m_coarse = np.concatenate(
                [m_coarse, np.zeros((1, m_coarse.shape[1]), dtype=bool)], axis=0
            )
        if m_fine.shape[1] % 2 == 0:
            m_coarse = np.concatenate(
                [m_coarse, np.zeros((m_coarse.shape[0], 1), dtype=bool)], axis=1
            )
        h_next, w_next = m_coarse.shape
        m_coarse[0, :] = False
        m_coarse[-1, :] = False
        m_coarse[:, 0] = False
        m_coarse[:, -1] = False
        if h_next < 3 or w_next < 3 or not m_coarse[1:-1, 1:-1].any():
            break
        masks.append(m_coarse)
        if srcs is None:
            # Laplace fill: the boundary trend is smooth, so extrapolation
            # keeps ramps exact; erased hole cells fall back to replication.
            dests.append(_restrict_plane_2x(dests[-1], known=~m_fine))
        else:
            # Clone/mixed: both planes are real image texture. Full-weighting
            # restriction preserves each block's true mean (injection would
            # alias a near-Nyquist checkerboard to one phase and bias the
            # coarse harmonic offset), while staying grid-aligned.
            dests.append(_restrict_texture_2x(dests[-1]))
            srcs.append(_restrict_texture_2x(srcs[-1]))

    levels = len(masks)

    def upsample_to(f_coarse: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
        # Injection restriction puts coarse cell i at fine pixel 2i, so the
        # inverse map is u = x/2 (clamped), NOT an endpoint-aligned linspace.
        # This keeps linear fields exact across the prolongation.
        c_h, c_w = f_coarse.shape[1], f_coarse.shape[2]
        y = np.minimum(np.arange(target_h, dtype=np.float32) * 0.5, c_h - 1)
        x = np.minimum(np.arange(target_w, dtype=np.float32) * 0.5, c_w - 1)
        y0 = np.floor(y).astype(int)
        y1 = np.minimum(y0 + 1, c_h - 1)
        x0 = np.floor(x).astype(int)
        x1 = np.minimum(x0 + 1, c_w - 1)
        wy = (y - y0).reshape(1, -1, 1).astype(np.float32)
        wx = (x - x0).reshape(1, 1, -1).astype(np.float32)
        top = f_coarse[:, y0, :][:, :, x0] * (1.0 - wx) + f_coarse[:, y0, :][:, :, x1] * wx
        bottom = f_coarse[:, y1, :][:, :, x0] * (1.0 - wx) + f_coarse[:, y1, :][:, :, x1] * wx
        return top * (1.0 - wy) + bottom * wy

    def apply_neumann(arr: np.ndarray) -> None:
        if neumann[0]:
            arr[:, 0, :] = arr[:, 1, :]
        if neumann[1]:
            arr[:, -1, :] = arr[:, -2, :]
        if neumann[2]:
            arr[:, :, 0] = arr[:, :, 1]
        if neumann[3]:
            arr[:, :, -1] = arr[:, :, -2]

    coarsest = levels - 1
    m_c = masks[coarsest]
    d_c = dests[coarsest]
    s_c = srcs[coarsest] if srcs is not None else None

    if src is None:
        val = d_c.copy()
        valid_b = (~m_c).copy()
        if neumann[0]:
            valid_b[0, :] = False
        if neumann[1]:
            valid_b[-1, :] = False
        if neumann[2]:
            valid_b[:, 0] = False
        if neumann[3]:
            valid_b[:, -1] = False
        if valid_b.any():
            val[:, m_c] = np.mean(d_c[:, valid_b], axis=1, keepdims=True)
        elif (~m_c).any():
            val[:, m_c] = np.mean(d_c[:, ~m_c], axis=1, keepdims=True)
    elif not mixed:
        val = np.zeros_like(d_c)
        val[:, ~m_c] = (d_c - s_c)[:, ~m_c]
    else:
        val = d_c.copy()

    apply_neumann(val)

    for lvl in range(levels - 1, -1, -1):
        m = masks[lvl]
        d = dests[lvl]
        s = srcs[lvl] if srcs is not None else None
        h, w = m.shape

        if lvl < coarsest:
            val = upsample_to(val, h, w)
            if src is None or mixed:
                val[:, ~m] = d[:, ~m]
            else:
                val[:, ~m] = (d - s)[:, ~m]
            apply_neumann(val)

        if mixed and s is not None:
            b = _compute_mixed_divergence(d, s)
            b_inner = b[:, 1:-1, 1:-1]
        else:
            b_inner = 0.0

        interior = m[1:-1, 1:-1]
        if not interior.any():
            continue
        it_cap = _MG_COARSEST_SWEEPS if lvl == coarsest else _MG_MAX_SWEEPS
        yy, xx = np.ogrid[:h, :w]
        checker = (yy + xx) % 2
        red_inner = (m & (checker == 0))[1:-1, 1:-1]
        black_inner = (m & (checker == 1))[1:-1, 1:-1]
        core = val[:, 1:-1, 1:-1]

        for it in range(it_cap):
            apply_neumann(val)
            nbrs_r = val[:, :-2, 1:-1] + val[:, 2:, 1:-1] + val[:, 1:-1, :-2] + val[:, 1:-1, 2:]
            target_r = 0.25 * (nbrs_r + b_inner)
            core[:] = np.where(red_inner, (1.0 - omega) * core + omega * target_r, core)

            apply_neumann(val)
            nbrs_b = val[:, :-2, 1:-1] + val[:, 2:, 1:-1] + val[:, 1:-1, :-2] + val[:, 1:-1, 2:]
            target_b = 0.25 * (nbrs_b + b_inner)
            core[:] = np.where(black_inner, (1.0 - omega) * core + omega * target_b, core)
            apply_neumann(val)

            # Residual stop: r = b - (4·val - Σ neighbours) on masked cells.
            # Checked every few sweeps so small dabs stay cheap.
            if (it + 1) % 4 == 0 or it + 1 == it_cap:
                nbrs = val[:, :-2, 1:-1] + val[:, 2:, 1:-1] + val[:, 1:-1, :-2] + val[:, 1:-1, 2:]
                resid = np.abs(b_inner - (4.0 * core - nbrs))
                if float(resid[:, interior].max()) <= _MG_RESIDUAL_TOL:
                    break

    result = srcs[0] + val if src is not None and not mixed else val
    return np.clip(result, 0.0, 255.0)


def heal_patch(
    src: QImage, dst: QImage, mask: np.ndarray | None = None, mixed: bool = False
) -> QImage:
    """Healing-brush blend: seamless gradient-domain cloning using a cascadic
    multigrid SOR Poisson solver. Solves Δf = div v over the patch domain with
    Dirichlet boundary conditions matching the destination tone."""
    s = view_u32(src)
    d = view_u32(dst)
    h = min(s.shape[0], d.shape[0])
    w = min(s.shape[1], d.shape[1])
    s, d = s[:h, :w], d[:h, :w]
    if h < 3 or w < 3:
        # Too small to solve: no edit. Return the (cropped) destination, not the
        # source — the source may be opaque where the destination is transparent.
        return dst.copy(0, 0, w, h)

    if mask is None:
        mask = np.zeros((h, w), dtype=bool)
        cy, cx = (h - 1) / 2.0, (w - 1) / 2.0
        ry, rx = max(1.0, cy - 0.5), max(1.0, cx - 0.5)
        yy, xx = np.ogrid[:h, :w]
        mask = (((yy - cy) / ry) ** 2 + ((xx - cx) / rx) ** 2) <= 1.0
        mask[0, :] = False
        mask[-1, :] = False
        mask[:, 0] = False
        mask[:, -1] = False
    else:
        mask = mask[:h, :w].copy()

    def channels(arr):
        return np.stack(
            [((arr >> np.uint32(k)) & 0xFF).astype(np.float32) for k in (16, 8, 0)], axis=0
        )

    s_ch = channels(s)
    d_ch = channels(d)

    # The solver treats the patch's outer ring as Dirichlet boundary. An
    # explicit mask that touches a patch edge would otherwise be cleared and
    # left unhealed — give those edges a one-pixel ghost border (reflective,
    # like the canvas-edge treatment in patch_heal) and crop it back after.
    pad_top = 1 if mask[0, :].any() else 0
    pad_bottom = 1 if mask[-1, :].any() else 0
    pad_left = 1 if mask[:, 0].any() else 0
    pad_right = 1 if mask[:, -1].any() else 0
    edge_padded = bool(pad_top or pad_bottom or pad_left or pad_right)
    if edge_padded:
        widths = ((0, 0), (pad_top, pad_bottom), (pad_left, pad_right))
        d_ch = np.pad(d_ch, widths, mode="edge")
        s_ch = np.pad(s_ch, widths, mode="edge")
        mask = np.pad(mask, widths[1:], mode="constant", constant_values=False)

    solved = poisson_solve_multigrid(
        d_ch,
        mask,
        src=s_ch,
        mixed=mixed,
        neumann=(pad_top > 0, pad_bottom > 0, pad_left > 0, pad_right > 0),
    )

    if edge_padded:
        end_y = solved.shape[1] - pad_bottom if pad_bottom else solved.shape[1]
        end_x = solved.shape[2] - pad_right if pad_right else solved.shape[2]
        solved = solved[:, pad_top:end_y, pad_left:end_x]

    alpha = (d >> np.uint32(24)) & 0xFF  # destination alpha wins
    r, g, b = [np.clip(solved[i] + 0.5, 0, 255).astype(np.uint32) for i in range(3)]
    # premultiplied clamp: channels may not exceed alpha
    r = np.minimum(r, alpha)
    g = np.minimum(g, alpha)
    b = np.minimum(b, alpha)
    out = QImage(w, h, src.format())
    view_u32(out)[:] = (alpha << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    return out


def drop_shadow_image(img: QImage, color, blur: int) -> QImage:
    """A blurred, tinted silhouette of `img`'s alpha, padded by `blur` px on
    every side (so offsets never clip)."""
    pad = max(0, int(blur))
    h, w = img.height(), img.width()
    alpha = np.zeros((h + 2 * pad, w + 2 * pad), dtype=np.float32)
    src = view_u32(img)
    alpha[pad : pad + h, pad : pad + w] = (src >> np.uint32(24)).astype(np.float32)

    if pad:
        r = max(1, pad // 2)
        for _ in range(3):  # triple box blur ~ gaussian
            k = 2 * r + 1
            csum = np.cumsum(alpha, axis=0)
            alpha = (
                np.vstack((csum[r:], np.repeat(csum[-1:], r, axis=0)))
                - np.vstack((np.zeros((r + 1, alpha.shape[1]), np.float32), csum[: -r - 1]))
            ) / k
            csum = np.cumsum(alpha, axis=1)
            alpha = (
                np.hstack((csum[:, r:], np.repeat(csum[:, -1:], r, axis=1)))
                - np.hstack((np.zeros((alpha.shape[0], r + 1), np.float32), csum[:, : -r - 1]))
            ) / k

    a = np.clip(alpha * (color.alpha() / 255.0), 0, 255).astype(np.uint32)
    scale = a / 255.0
    out = QImage(alpha.shape[1], alpha.shape[0], img.format())
    view_u32(out)[:] = (
        (a << np.uint32(24))
        | ((color.red() * scale).astype(np.uint32) << np.uint32(16))
        | ((color.green() * scale).astype(np.uint32) << np.uint32(8))
        | (color.blue() * scale).astype(np.uint32)
    )
    return out


def warp_push(img: QImage, cx: float, cy: float, radius: float, dx: float, dy: float) -> QRect:
    """Liquify push: pixels inside the brush shift along (dx, dy) with a
    smooth falloff — bilinear backward resample over the local region only.
    Returns the dirty rect."""
    h, w = img.height(), img.width()
    pad = int(radius + max(abs(dx), abs(dy))) + 2
    x0, x1 = max(0, int(cx) - pad), min(w, int(cx) + pad + 1)
    y0, y1 = max(0, int(cy) - pad), min(h, int(cy) + pad + 1)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return QRect()

    arr = view_u32(img)
    sub = arr[y0:y1, x0:x1].copy()
    hh, ww = sub.shape
    yy, xx = np.mgrid[0:hh, 0:ww].astype(np.float32)
    rx, ry = xx - (cx - x0), yy - (cy - y0)
    dist = np.sqrt(rx * rx + ry * ry)
    weight = np.clip(1.0 - dist / max(radius, 1.0), 0.0, 1.0) ** 2
    sx = np.clip(xx - dx * weight, 0, ww - 1)
    sy = np.clip(yy - dy * weight, 0, hh - 1)

    fx0 = np.floor(sx).astype(np.int64)
    fy0 = np.floor(sy).astype(np.int64)
    fx1 = np.minimum(fx0 + 1, ww - 1)
    fy1 = np.minimum(fy0 + 1, hh - 1)
    tx = (sx - fx0)[..., None]
    ty = (sy - fy0)[..., None]

    def planes(a):
        return np.stack(
            [((a >> np.uint32(k)) & 0xFF).astype(np.float32) for k in (24, 16, 8, 0)], axis=-1
        )

    p00 = planes(sub[fy0, fx0])
    p01 = planes(sub[fy0, fx1])
    p10 = planes(sub[fy1, fx0])
    p11 = planes(sub[fy1, fx1])
    top = p00 * (1 - tx) + p01 * tx
    bot = p10 * (1 - tx) + p11 * tx
    out = top * (1 - ty) + bot * ty
    a, r, g, b = [np.clip(out[..., i] + 0.5, 0, 255).astype(np.uint32) for i in range(4)]
    packed = (a << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    changed = weight > 0.001
    target = arr[y0:y1, x0:x1]
    target[changed] = packed[changed]
    return QRect(x0, y0, x1 - x0, y1 - y0)


def puppet_warp(img: QImage, pins: list) -> QImage:
    """Pin-based deformation: `pins` is a list of ((sx, sy), (tx, ty)) pairs —
    anchors have source == target, moved pins pull their neighbourhood.
    The displacement field is inverse-distance-squared weighted over the
    pins' target positions; pixels resample backward bilinearly. Returns a
    new image the same size. The field and the resample are per-pixel over
    the whole source, so the work runs in row bands: the only full-size
    buffer is the result itself (#347)."""
    h, w = img.height(), img.width()
    src = view_u32(img)
    out = QImage(w, h, img.format())
    dst = view_u32(out)

    for y0 in range(0, h, BAND_ROWS):
        y1 = min(y0 + BAND_ROWS, h)
        yy, xx = np.mgrid[y0:y1, 0:w].astype(np.float32)
        num_x = np.zeros((y1 - y0, w), dtype=np.float32)
        num_y = np.zeros((y1 - y0, w), dtype=np.float32)
        den = np.zeros((y1 - y0, w), dtype=np.float32)
        for (sx, sy), (tx, ty) in pins:
            dx, dy = tx - sx, ty - sy
            dist2 = (xx - tx) ** 2 + (yy - ty) ** 2 + 4.0
            weight = 1.0 / dist2
            num_x += weight * dx
            num_y += weight * dy
            den += weight
        disp_x = num_x / den
        disp_y = num_y / den

        sx = np.clip(xx - disp_x, 0, w - 1)
        sy = np.clip(yy - disp_y, 0, h - 1)
        fx0 = np.floor(sx).astype(np.int64)
        fy0 = np.floor(sy).astype(np.int64)
        fx1 = np.minimum(fx0 + 1, w - 1)
        fy1 = np.minimum(fy0 + 1, h - 1)
        tx = sx - fx0
        ty = sy - fy0

        # gather the four bilinear taps once, then resample a channel at a time
        taps = (src[fy0, fx0], src[fy0, fx1], src[fy1, fx0], src[fy1, fx1])
        packed = np.zeros((y1 - y0, w), dtype=np.uint32)
        for shift in (24, 16, 8, 0):
            p00, p01, p10, p11 = (((t >> np.uint32(shift)) & 0xFF).astype(np.float32) for t in taps)
            top = p00 * (1 - tx) + p01 * tx
            bot = p10 * (1 - tx) + p11 * tx
            packed |= _round_u8(top * (1 - ty) + bot * ty) << np.uint32(shift)
        dst[y0:y1] = packed
    return out


def _box_blur_plane(c: np.ndarray, r: int) -> np.ndarray:
    # The cumsum/vstack trick needs r < the extent along the axis it blurs: with
    # r >= n the zero pad has more rows than the plane and the two stacks no
    # longer line up (a 1x1 plane under beam-dither's conditioning blur, #425).
    # A plane narrower than the radius is blurred by as much as it has.
    ry = max(0, min(r, c.shape[0] - 1))
    rx = max(0, min(r, c.shape[1] - 1))
    if ry:
        k = 2 * ry + 1
        csum = np.cumsum(c, axis=0)
        c = (
            np.vstack((csum[ry:], np.repeat(csum[-1:], ry, axis=0)))
            - np.vstack((np.zeros((ry + 1, c.shape[1]), np.float32), csum[: -ry - 1]))
        ) / k
    if rx:
        k = 2 * rx + 1
        csum = np.cumsum(c, axis=1)
        c = (
            np.hstack((csum[:, rx:], np.repeat(csum[:, -1:], rx, axis=1)))
            - np.hstack((np.zeros((c.shape[0], rx + 1), np.float32), csum[:, : -rx - 1]))
        ) / k
    return c


def _box_sum(c: np.ndarray, r: int, axis: int) -> np.ndarray:
    """Sum of each (2r+1)-wide window along `axis`, the window truncated at
    the array's edges (zero outside). Cumsum-based, so O(1) per element for
    any radius — including radii wider than the array, which the float32
    vstack trick in `_box_blur_plane` cannot balance. Exact on int64."""
    n = c.shape[axis]
    csum = np.cumsum(c, axis=axis)
    out = np.empty_like(csum)
    v_out = out.swapaxes(0, axis)  # views: one set of row slices serves both axes
    v_sum = csum.swapaxes(0, axis)
    keep = max(0, n - r)
    v_out[:keep] = v_sum[r : r + keep]
    v_out[keep:] = v_sum[-1]
    if n > r + 1:
        v_out[r + 1 :] -= v_sum[: n - r - 1]
    return out


def _blurred_plane(src: np.ndarray, shift: int, r: int, top: int, rows: int) -> np.ndarray:
    """Triple box blur of one 8-bit channel of `src` — a row band plus its
    halo, see `_halo_bands` — returning rows [top, top + rows) as float64.

    The three vertical passes run in exact int64 (window sums of bytes never
    leave the integers, so the result cannot depend on where the band
    boundaries fall); the horizontal passes are per-row and cannot see the
    boundaries at all. The single division by k**6 happens once, at the end.
    Net: banded output is bit-identical to the same maths over the whole
    image, and within 1 LSB of the float32 full-image version this replaced
    (#347)."""
    c = ((src >> np.uint32(shift)) & 0xFF).astype(np.int64)
    for _ in range(3):
        c = _box_sum(c, r, 0)
    c = c[top : top + rows].astype(np.float64)
    for _ in range(3):
        c = _box_sum(c, r, 1)
    return c / float((2 * r + 1) ** 6)


def _halo_bands(arr: np.ndarray, r: int):
    """Yield (y0, y1, src, top) per BAND_ROWS band of `arr`, for an in-place
    triple box blur of radius r: `src` is the band plus up to 3r rows of halo
    either side (as far as the image extends) and `top` is where the band
    starts inside it. The halo above comes from a carry of the *original*
    rows — the caller overwrites each band before the next is computed, so
    reading them back from `arr` would blur the blur. The carry is at most
    3r rows: bounded by the radius, not the image."""
    height = arr.shape[0]
    halo = 3 * r
    carry = arr[:0]
    for y0 in range(0, height, BAND_ROWS):
        y1 = min(y0 + BAND_ROWS, height)
        src = np.concatenate((carry, arr[y0 : min(height, y1 + halo)]))
        top = carry.shape[0]
        carry = src[max(0, top + y1 - y0 - halo) : top + y1 - y0].copy()  # rows [y1 - 3r, y1)
        yield y0, y1, src, top


def _round_u8(plane: np.ndarray) -> np.ndarray:
    return np.clip(plane + 0.5, 0, 255).astype(np.uint32)


def gaussian_blur(img: QImage, radius: int, mask: np.ndarray | None = None) -> None:
    """Approximate gaussian blur (triple box blur) on all four premultiplied
    channels, in place; when `mask` is given only masked pixels change.
    Processed in row bands so the float transient is bounded by the band
    (plus the blur halo), not the layer (DD-001, #347, #418)."""
    r = max(1, int(radius) // 2 + 1)
    arr = view_u32(img)
    for y0, y1, src, top in _halo_bands(arr, r):
        out = np.zeros((y1 - y0, arr.shape[1]), dtype=np.uint32)
        for shift in (24, 16, 8, 0):
            plane = _blurred_plane(src, shift, r, top, y1 - y0)
            out |= _round_u8(plane) << np.uint32(shift)
        band = arr[y0:y1]
        if mask is None:
            band[:] = out
        else:
            m = mask[y0:y1]
            band[m] = out[m]


def fast_blur(img: QImage, radius: int, mask: np.ndarray | None = None) -> None:
    """Fast large-radius blur: 3-pass running-sum box blur approximation of
    Gaussian blur in O(1) time per pixel independent of kernel radius R (DD-001, #418).

    By the Central Limit Theorem (CLT), three successive passes of an O(1)
    box blur approximate Gaussian convolution within ~1-2% error. Running-sum
    accumulators ensure O(1) time complexity per pixel regardless of radius.
    Processed in BAND_ROWS strips with a 3r halo for zero persistent allocation
    overhead."""
    gaussian_blur(img, radius, mask)


def unsharp_mask(img: QImage, radius: int, amount: float, mask: np.ndarray | None = None) -> None:
    """Sharpen: original + amount * (original - blur), premultiplied-safe
    (colour never exceeds alpha, alpha itself is untouched). Row-banded like
    `gaussian_blur`."""
    r = max(1, int(radius) // 2 + 1)
    arr = view_u32(img)
    for y0, y1, src, top in _halo_bands(arr, r):
        band = arr[y0:y1]
        alpha = band >> np.uint32(24)
        out = alpha << np.uint32(24)
        alpha = alpha.astype(np.float64)
        for shift in (16, 8, 0):
            c = ((band >> np.uint32(shift)) & 0xFF).astype(np.float64)
            blur = _blurred_plane(src, shift, r, top, y1 - y0)
            sharp = np.minimum(np.clip(c + amount * (c - blur), 0, 255), alpha)
            out |= _round_u8(sharp) << np.uint32(shift)
        if mask is None:
            band[:] = out
        else:
            m = mask[y0:y1]
            band[m] = out[m]


def livewire_path(
    img: QImage,
    a,
    b,
    margin: int = 20,
    max_area: int = 60000,
    width: int | None = None,
    contrast: float = 10.0,
    pull: float = 0.1,
) -> list:
    """Intelligent Scissors / live-wire minimum-cost 8-connected path from a to b
    (layer coords) where link costs combine:
      1) Gradient magnitude (Sobel/central differences, high gradient -> low cost,
         gated by edge contrast threshold).
      2) Edge direction (cost penalized when step deviates from the edge tangent unit vector).
      3) Non-maximum suppression (edge centering: local maximum along gradient normal).
      4) Gentle pull toward pointer guide line (penalty for deviating from line segment ab).

    Respects Memory Frugality (DD-001) by reading pixels lazily in 128px cached blocks
    along the pointer corridor.
    Falls back to straight segment [(ax, ay), (bx, by)] when corridor area exceeds max_area.
    """
    import heapq

    margin = int(width) if width is not None else int(margin)

    h, w = img.height(), img.width()
    ax, ay = int(a[0]), int(a[1])
    bx, by = int(b[0]), int(b[1])
    ax, ay = max(0, min(w - 1, ax)), max(0, min(h - 1, ay))
    bx, by = max(0, min(w - 1, bx)), max(0, min(h - 1, by))
    x0 = max(0, min(ax, bx) - margin)
    x1 = min(w, max(ax, bx) + margin + 1)
    y0 = max(0, min(ay, by) - margin)
    y1 = min(h, max(ay, by) + margin + 1)
    cw, ch = x1 - x0, y1 - y0
    if cw * ch > max_area or cw < 2 or ch < 2:
        return [(ax, ay), (bx, by)]

    # Lazy 128px cached block reading (DD-001)
    block_size = 128
    view = view_u32(img)
    gray = np.empty((ch, cw), dtype=np.float32)
    bx0, bx1 = x0 // block_size, (x1 - 1) // block_size
    by0, by1 = y0 // block_size, (y1 - 1) // block_size
    for by_idx in range(by0, by1 + 1):
        for bx_idx in range(bx0, bx1 + 1):
            tx0 = bx_idx * block_size
            tx1 = min(w, tx0 + block_size)
            ty0 = by_idx * block_size
            ty1 = min(h, ty0 + block_size)
            ox0, ox1 = max(x0, tx0), min(x1, tx1)
            oy0, oy1 = max(y0, ty0), min(y1, ty1)
            if ox0 >= ox1 or oy0 >= oy1:
                continue
            blk = view[ty0:ty1, tx0:tx1]
            r = ((blk >> np.uint32(16)) & 0xFF).astype(np.float32)
            g = ((blk >> np.uint32(8)) & 0xFF).astype(np.float32)
            bl = (blk & 0xFF).astype(np.float32)
            t_gray = 0.299 * r + 0.587 * g + 0.114 * bl
            gray[oy0 - y0 : oy1 - y0, ox0 - x0 : ox1 - x0] = t_gray[
                oy0 - ty0 : oy1 - ty0, ox0 - tx0 : ox1 - tx0
            ]

    # Central difference gradients
    gx = np.zeros((ch, cw), dtype=np.float32)
    gy = np.zeros((ch, cw), dtype=np.float32)
    if cw > 1:
        gx[:, 1:-1] = (gray[:, 2:] - gray[:, :-2]) * 0.5
        gx[:, 0] = gray[:, 1] - gray[:, 0]
        gx[:, -1] = gray[:, -1] - gray[:, -2]
    if ch > 1:
        gy[1:-1, :] = (gray[2:, :] - gray[:-2, :]) * 0.5
        gy[0, :] = gray[1, :] - gray[0, :]
        gy[-1, :] = gray[-1, :] - gray[-2, :]

    grad = np.sqrt(gx * gx + gy * gy)
    top = max(1.0, float(grad.max()))
    t_contrast = (float(contrast) / 100.0) * max(top, 25.5)

    # 1) Gradient magnitude cost: high gradient -> low cost
    eff_grad = np.maximum(0.0, grad - t_contrast)
    denom = max(1e-5, top - t_contrast)
    f_g = 1.0 - (eff_grad / denom)

    # 2) Edge direction: unit normal vectors (normal is perpendicular to edge tangent)
    grad_safe = np.maximum(grad, 1e-5)
    nx = gx / grad_safe
    ny = gy / grad_safe

    # 3) Non-maximum suppression along gradient direction (edge centering)
    f_z = np.ones((ch, cw), dtype=np.float32)
    if ch > 2 and cw > 2:
        g_inner = grad[1:-1, 1:-1]
        gx_inner = gx[1:-1, 1:-1]
        gy_inner = gy[1:-1, 1:-1]
        ax_val = np.abs(gx_inner)
        ay_val = np.abs(gy_inner)

        m_horiz = ax_val > 2.414 * ay_val
        m_vert = ay_val > 2.414 * ax_val
        m_diag = (~m_horiz) & (~m_vert) & (gx_inner * gy_inner > 0)
        m_anti = (~m_horiz) & (~m_vert) & (~m_diag)

        is_max = np.zeros_like(g_inner, dtype=bool)
        is_max |= m_horiz & (g_inner >= grad[1:-1, :-2]) & (g_inner >= grad[1:-1, 2:])
        is_max |= m_vert & (g_inner >= grad[:-2, 1:-1]) & (g_inner >= grad[2:, 1:-1])
        is_max |= m_diag & (g_inner >= grad[2:, 2:]) & (g_inner >= grad[:-2, :-2])
        is_max |= m_anti & (g_inner >= grad[:-2, 2:]) & (g_inner >= grad[2:, :-2])
        is_max &= g_inner >= t_contrast
        f_z[1:-1, 1:-1][is_max] = 0.0

    # 4) Gentle pull toward pointer guide line (distance to segment ab)
    ax_rel, ay_rel = ax - x0, ay - y0
    bx_rel, by_rel = bx - x0, by - y0
    vx, vy = bx_rel - ax_rel, by_rel - ay_rel
    len_sq = vx * vx + vy * vy
    ys, xs = np.indices((ch, cw))
    wx = xs - ax_rel
    wy = ys - ay_rel
    if len_sq > 0:
        t = np.clip((wx * vx + wy * vy) / len_sq, 0.0, 1.0)
        proj_x = ax_rel + t * vx
        proj_y = ay_rel + t * vy
        dist_line = np.sqrt((xs - proj_x) ** 2 + (ys - proj_y) ** 2)
    else:
        dist_line = np.sqrt(wx * wx + wy * wy)
    f_p = np.clip(dist_line / max(1.0, float(margin)), 0.0, 1.0)

    # Static node cost (G, Z, P)
    node_cost = 0.45 * f_g + 0.20 * f_z + float(pull) * f_p + 0.02

    # Graph search
    start = (ay - y0) * cw + (ax - x0)
    goal = (by - y0) * cw + (bx - x0)
    dist = np.full(cw * ch, np.inf, dtype=np.float64)
    parent = np.full(cw * ch, -1, dtype=np.int64)
    dist[start] = 0.0
    heap = [(0.0, start)]

    # 8-connected steps: (dx, dy, step_length, unit_dx, unit_dy)
    sqrt2 = 1.41421356237
    inv_sqrt2 = 0.70710678118
    steps = (
        (-1, -1, sqrt2, -inv_sqrt2, -inv_sqrt2),
        (0, -1, 1.0, 0.0, -1.0),
        (1, -1, sqrt2, inv_sqrt2, -inv_sqrt2),
        (-1, 0, 1.0, -1.0, 0.0),
        (1, 0, 1.0, 1.0, 0.0),
        (-1, 1, sqrt2, -inv_sqrt2, inv_sqrt2),
        (0, 1, 1.0, 0.0, 1.0),
        (1, 1, sqrt2, inv_sqrt2, inv_sqrt2),
    )

    flat_node_cost = node_cost.ravel()
    flat_nx = nx.ravel()
    flat_ny = ny.ravel()
    flat_grad = grad.ravel()

    while heap:
        d, u = heapq.heappop(heap)
        if u == goal:
            break
        if d > dist[u]:
            continue
        ux = u % cw
        uy = u // cw
        u_nx = flat_nx[u]
        u_ny = flat_ny[u]
        has_edge_dir = flat_grad[u] >= t_contrast

        for dx, dy, step_len, udx, udy in steps:
            vx_coord = ux + dx
            vy_coord = uy + dy
            if vx_coord < 0 or vx_coord >= cw or vy_coord < 0 or vy_coord >= ch:
                continue
            v = vy_coord * cw + vx_coord

            # Edge direction deviation
            f_d = abs(udx * u_nx + udy * u_ny) if has_edge_dir else 0.5
            w_edge = step_len * (flat_node_cost[v] + 0.30 * f_d)
            nd = d + w_edge
            if nd < dist[v]:
                dist[v] = nd
                parent[v] = u
                heapq.heappush(heap, (nd, v))

    if parent[goal] < 0 and goal != start:
        return [(ax, ay), (bx, by)]
    path = []
    curr = goal
    while curr >= 0:
        path.append((curr % cw + x0, curr // cw + y0))
        if curr == start:
            break
        curr = parent[curr]
    path.reverse()
    return path


def patch_heal(img: QImage, mask: np.ndarray, dx: int, dy: int, mixed: bool = False) -> QRect:
    """Patch-tool blend: fill the masked region with texture sampled at
    (dx, dy) away, tone-matched to the destination using a cascadic multigrid
    SOR Poisson solver over the mask's bounding box (DD-001). Returns dirty
    rect; an empty rect means the heal was refused because a masked pixel's
    source lies off-canvas (the solver halo around the source footprint is
    edge-replicated, not refused)."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return QRect()
    h, w = mask.shape
    # Validate the source footprint of the masked pixels themselves. The
    # solver halo (pad below) may cross the canvas edge even when every
    # sampled source pixel fits — that halo is edge-replicated, not refused.
    if (
        int(ys.min()) + dy < 0
        or int(ys.max()) + dy >= h
        or int(xs.min()) + dx < 0
        or int(xs.max()) + dx >= w
    ):
        return QRect()  # a masked pixel's source is off-canvas: refuse
    pad = 4
    y0, y1 = max(0, int(ys.min()) - pad), min(h, int(ys.max()) + 1 + pad)
    x0, x1 = max(0, int(xs.min()) - pad), min(w, int(xs.max()) + 1 + pad)
    sy0, sy1 = y0 + dy, y1 + dy
    sx0, sx1 = x0 + dx, x1 + dx

    arr = view_u32(img)
    dst_crop = arr[y0:y1, x0:x1]
    # Source window clipped to the canvas, then edge-replicated back to the
    # destination crop's shape so the solver halo always has boundary values.
    csy0, csy1 = max(0, sy0), min(h, sy1)
    csx0, csx1 = max(0, sx0), min(w, sx1)
    src_crop = arr[csy0:csy1, csx0:csx1]
    sp_top, sp_bottom = csy0 - sy0, sy1 - csy1
    sp_left, sp_right = csx0 - sx0, sx1 - csx1
    if sp_top or sp_bottom or sp_left or sp_right:
        src_crop = np.pad(src_crop, ((sp_top, sp_bottom), (sp_left, sp_right)), mode="edge")
    hole = mask[y0:y1, x0:x1].copy()

    top_pad = max(0, 1 - (int(ys.min()) - y0))
    bottom_pad = max(0, 1 - (y1 - 1 - int(ys.max())))
    left_pad = max(0, 1 - (int(xs.min()) - x0))
    right_pad = max(0, 1 - (x1 - 1 - int(xs.max())))

    def channels(a):
        return np.stack(
            [((a >> np.uint32(k)) & 0xFF).astype(np.float32) for k in (16, 8, 0)], axis=0
        )

    d_ch = channels(dst_crop)
    s_ch = channels(src_crop)

    if top_pad or bottom_pad or left_pad or right_pad:
        d_ch = np.pad(d_ch, ((0, 0), (top_pad, bottom_pad), (left_pad, right_pad)), mode="edge")
        s_ch = np.pad(s_ch, ((0, 0), (top_pad, bottom_pad), (left_pad, right_pad)), mode="edge")
        hole_padded = np.pad(
            hole,
            ((top_pad, bottom_pad), (left_pad, right_pad)),
            mode="constant",
            constant_values=False,
        )
    else:
        hole_padded = hole

    neumann = (top_pad > 0, bottom_pad > 0, left_pad > 0, right_pad > 0)
    solved = poisson_solve_multigrid(d_ch, hole_padded, src=s_ch, mixed=mixed, neumann=neumann)

    if top_pad or bottom_pad or left_pad or right_pad:
        end_y = solved.shape[1] - bottom_pad if bottom_pad > 0 else solved.shape[1]
        end_x = solved.shape[2] - right_pad if right_pad > 0 else solved.shape[2]
        solved = solved[:, top_pad:end_y, left_pad:end_x]

    alpha = (dst_crop >> np.uint32(24)) & 0xFF
    r, g, b = [np.clip(solved[i] + 0.5, 0, 255).astype(np.uint32) for i in range(3)]
    r = np.minimum(r, alpha)
    g = np.minimum(g, alpha)
    b = np.minimum(b, alpha)
    out = (alpha << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    dst_crop[hole] = out[hole]
    return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def stroke_outline_image(img: QImage, color, width: int) -> QImage:
    """A solid outline `width` px around `img`'s alpha silhouette, padded so
    the outline never clips (outside stroke)."""
    pad = max(1, int(width))
    h, w = img.height(), img.width()
    solid = np.zeros((h + 2 * pad, w + 2 * pad), dtype=bool)
    src = view_u32(img)
    solid[pad : pad + h, pad : pad + w] = (src >> np.uint32(24)) > 12
    grown = solid.copy()
    for _ in range(pad):
        grown = _dilate(grown)
    ring = grown & ~solid

    a = np.where(ring, np.uint32(color.alpha()), np.uint32(0))
    scale = color.alpha() / 255.0
    out = QImage(solid.shape[1], solid.shape[0], img.format())
    view_u32(out)[:] = (
        (a << np.uint32(24))
        | (np.where(ring, np.uint32(int(color.red() * scale)), 0) << np.uint32(16))
        | (np.where(ring, np.uint32(int(color.green() * scale)), 0) << np.uint32(8))
        | np.where(ring, np.uint32(int(color.blue() * scale)), 0)
    )
    return out


def _seam_energy(arr: np.ndarray) -> np.ndarray:
    r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
    g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
    b = (arr & 0xFF).astype(np.float32)
    gray = 0.299 * r + 0.587 * g + 0.114 * b
    dx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
    dy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
    return dx + dy


def _min_seam(arr: np.ndarray) -> np.ndarray:
    """Lowest-energy vertical seam of an (h, w) uint32 array: one x per row."""
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
        seam[y] = x0 + int(np.argmin(m[y, x0 : min(w, x + 2)]))
    return seam


def _remove_one_seam(arr: np.ndarray) -> np.ndarray:
    h, w = arr.shape
    seam = _min_seam(arr)
    keep = np.ones((h, w), dtype=bool)
    keep[np.arange(h), seam] = False
    return arr[keep].reshape(h, w - 1)


def _average_u32(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    out = np.zeros_like(a)
    for shift in (24, 16, 8, 0):
        av = (a >> np.uint32(shift)) & 0xFF
        bv = (b >> np.uint32(shift)) & 0xFF
        out |= (((av + bv) // 2) & 0xFF) << np.uint32(shift)
    return out


def _insert_seams(arr: np.ndarray, count: int) -> np.ndarray:
    """Grow width by `count` px: find the `count` lowest-energy DISTINCT
    seams (by removing them from a working copy while tracking original
    columns), then duplicate each — the new pixel averages the seam pixel
    with its right neighbour so no hard stripes appear."""
    h, w = arr.shape
    work = arr.copy()
    mapping = np.tile(np.arange(w, dtype=np.int64), (h, 1))
    seams = []
    for _ in range(count):
        seam = _min_seam(work)
        rows = np.arange(work.shape[0])
        seams.append(mapping[rows, seam])
        keep = np.ones(work.shape, dtype=bool)
        keep[rows, seam] = False
        new_w = work.shape[1] - 1
        work = work[keep].reshape(h, new_w)
        mapping = mapping[keep].reshape(h, new_w)

    per_row = np.stack(seams, axis=1)  # (h, count) original column indices
    out = np.empty((h, w + count), dtype=arr.dtype)
    for y in range(h):
        cols = np.sort(per_row[y])
        row = arr[y]
        right = row[np.minimum(cols + 1, w - 1)]
        values = _average_u32(row[cols], right)
        out[y] = np.insert(row, cols + 1, values)
    return out


def seam_carve(img: QImage, target_w: int, target_h: int) -> QImage:
    """Content-aware scale to (target_w, target_h): shrink by removing the
    lowest-energy seams, grow by duplicating them (blended) — vertical seams
    for width, horizontal via transpose for height. Detail survives; flat
    areas give way (or stretch)."""
    arr = view_u32(img).copy()
    target_w = max(2, min(target_w, 4 * arr.shape[1]))
    target_h = max(2, min(target_h, 4 * arr.shape[0]))
    while arr.shape[1] > target_w:
        arr = _remove_one_seam(arr)
    if arr.shape[1] < target_w:
        arr = _insert_seams(arr, target_w - arr.shape[1])
    if arr.shape[0] != target_h:
        arr = np.ascontiguousarray(arr.T)
        while arr.shape[1] > target_h:
            arr = _remove_one_seam(arr)
        if arr.shape[1] < target_h:
            arr = _insert_seams(arr, target_h - arr.shape[1])
        arr = np.ascontiguousarray(arr.T)

    out = QImage(arr.shape[1], arr.shape[0], img.format())
    view_u32(out)[:] = arr
    return out


def inpaint_poisson(img: QImage, mask: np.ndarray) -> QRect:
    """Poisson / Laplace inpainting: solve Δf = 0 with Dirichlet boundary
    conditions matching surrounding pixels using a cascadic multigrid SOR solver.
    Operates strictly on the mask's bounding box plus padding (DD-001).
    Returns the dirty rect."""
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return QRect()
    pad = 4
    h, w = mask.shape
    y0, y1 = max(0, int(ys.min()) - pad), min(h, int(ys.max()) + 1 + pad)
    x0, x1 = max(0, int(xs.min()) - pad), min(w, int(xs.max()) + 1 + pad)

    arr = view_u32(img)[y0:y1, x0:x1]
    hole = mask[y0:y1, x0:x1].copy()

    top_pad = max(0, 1 - (int(ys.min()) - y0))
    bottom_pad = max(0, 1 - (y1 - 1 - int(ys.max())))
    left_pad = max(0, 1 - (int(xs.min()) - x0))
    right_pad = max(0, 1 - (x1 - 1 - int(xs.max())))

    def channels(a):
        return np.stack(
            [((a >> np.uint32(k)) & 0xFF).astype(np.float32) for k in (24, 16, 8, 0)], axis=0
        )

    ch = channels(arr)

    if top_pad or bottom_pad or left_pad or right_pad:
        ch = np.pad(ch, ((0, 0), (top_pad, bottom_pad), (left_pad, right_pad)), mode="edge")
        hole_padded = np.pad(
            hole,
            ((top_pad, bottom_pad), (left_pad, right_pad)),
            mode="constant",
            constant_values=False,
        )
    else:
        hole_padded = hole

    neumann = (top_pad > 0, bottom_pad > 0, left_pad > 0, right_pad > 0)
    solved = poisson_solve_multigrid(ch, hole_padded, src=None, neumann=neumann)

    if top_pad or bottom_pad or left_pad or right_pad:
        end_y = solved.shape[1] - bottom_pad if bottom_pad > 0 else solved.shape[1]
        end_x = solved.shape[2] - right_pad if right_pad > 0 else solved.shape[2]
        solved = solved[:, top_pad:end_y, left_pad:end_x]

    a, r, g, b = [np.clip(solved[i] + 0.5, 0, 255).astype(np.uint32) for i in range(4)]
    r = np.minimum(r, a)
    g = np.minimum(g, a)
    b = np.minimum(b, a)
    out = (a << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    arr[hole] = out[hole]
    return QRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))


def inpaint_diffuse(img: QImage, mask: np.ndarray, blend_passes: int = 3) -> QRect:
    """Diffusion inpainting of masked pixels. Delegates to `inpaint_poisson`
    for multigrid Poisson / Laplace gradient-domain solving."""
    return inpaint_poisson(img, mask)


def blend_by_weights(filtered: QImage, original: QImage, weights: np.ndarray) -> None:
    """filtered = original*(1-w) + filtered*w, per premultiplied channel.
    Per-pixel, so it bands trivially: one (BAND_ROWS, w) float plane per
    channel instead of two (h, w, 4) stacks plus their product (#347)."""
    f = view_u32(filtered)
    o = view_u32(original)
    height = f.shape[0]
    for y0 in range(0, height, BAND_ROWS):
        y1 = min(y0 + BAND_ROWS, height)
        fb, ob = f[y0:y1], o[y0:y1]
        w = weights[y0:y1]
        out = np.zeros_like(fb)
        for shift in (24, 16, 8, 0):
            fp = ((fb >> np.uint32(shift)) & 0xFF).astype(np.float32)
            op = ((ob >> np.uint32(shift)) & 0xFF).astype(np.float32)
            out |= _round_u8(op * (1.0 - w) + fp * w) << np.uint32(shift)
        fb[:] = out


def feathered_weights(path, size, offset, feather: float) -> np.ndarray:
    """Float32 0..1 weights for a selection with a feathered (blurred) edge.
    Normalised by an identically-blurred ones-plane so image borders don't
    darken the weights (the box blur truncates its window at array edges)."""
    hard = selection_mask(path, size, offset).astype(np.float32)
    norm = np.ones_like(hard)
    r = max(1, int(feather) // 2 + 1)
    for _ in range(3):
        hard = _box_blur_plane(hard, r)
        norm = _box_blur_plane(norm, r)
    return np.clip(hard / np.maximum(norm, 1e-6), 0.0, 1.0)


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


def _box_blur_float(c: np.ndarray, r: int) -> np.ndarray:
    """Normalized box blur of a 2D float array with window radius r.
    Boundary-aware: normalized by the blurred ones-plane so image borders
    do not darken or artificially attenuate edge values."""
    if r <= 0:
        return c.astype(np.float32, copy=False)
    norm = np.ones_like(c, dtype=np.float32)
    norm = _box_blur_plane(norm, r)
    blurred = _box_blur_plane(c.astype(np.float32), r)
    return blurred / np.maximum(norm, 1e-6)


def _grey_dilate(mask: np.ndarray) -> np.ndarray:
    """3x3 8-connected grey morphological dilation (local maximum)."""
    out = mask.copy()
    out[1:, :] = np.maximum(out[1:, :], mask[:-1, :])
    out[:-1, :] = np.maximum(out[:-1, :], mask[1:, :])
    out[:, 1:] = np.maximum(out[:, 1:], mask[:, :-1])
    out[:, :-1] = np.maximum(out[:, :-1], mask[:, 1:])
    out[1:, 1:] = np.maximum(out[1:, 1:], mask[:-1, :-1])
    out[1:, :-1] = np.maximum(out[1:, :-1], mask[:-1, 1:])
    out[:-1, 1:] = np.maximum(out[:-1, 1:], mask[1:, :-1])
    out[:-1, :-1] = np.maximum(out[:-1, :-1], mask[1:, 1:])
    return out


def _grey_erode(mask: np.ndarray) -> np.ndarray:
    """3x3 8-connected grey morphological erosion (local minimum)."""
    out = mask.copy()
    out[1:, :] = np.minimum(out[1:, :], mask[:-1, :])
    out[:-1, :] = np.minimum(out[:-1, :], mask[1:, :])
    out[:, 1:] = np.minimum(out[:, 1:], mask[:, :-1])
    out[:, :-1] = np.minimum(out[:, :-1], mask[:, 1:])
    out[1:, 1:] = np.minimum(out[1:, 1:], mask[:-1, :-1])
    out[1:, :-1] = np.minimum(out[1:, :-1], mask[:-1, 1:])
    out[:-1, 1:] = np.minimum(out[:-1, 1:], mask[1:, :-1])
    out[:-1, :-1] = np.minimum(out[:-1, :-1], mask[1:, 1:])
    return out


def guided_filter(
    guide: np.ndarray,
    p: np.ndarray,
    radius: int,
    eps: float = 1e-3,
    smart_radius: bool = False,
) -> np.ndarray:
    """Guided Image Filter: local linear regression of mask `p` against
    underlying guide image `guide` (#417).
    `guide`: (H, W, 3) or (H, W) in [0..1] or [0..255].
    `p`: (H, W) in [0..1].
    `radius`: window radius in pixels (0..100).
    `eps`: regularization parameter.
    `smart_radius`: when True, adapts edge bandwidth locally to the image's
    observed transition width (local variance / gradient).
    """
    if radius <= 0:
        return np.clip(p.astype(np.float32), 0.0, 1.0)

    # Normalize guide to [0, 1] float32
    if guide.dtype == np.uint8:
        guide_arr = guide.astype(np.float32) / 255.0
    else:
        guide_arr = guide.astype(np.float32)
        if guide_arr.size > 0 and guide_arr.max() > 1.0:
            guide_arr = guide_arr / 255.0

    mask = np.clip(p.astype(np.float32), 0.0, 1.0)

    def _filter_core(r: int) -> np.ndarray:
        if guide_arr.ndim == 2:
            mean_guide = _box_blur_float(guide_arr, r)
            mean_mask = _box_blur_float(mask, r)
            mean_guide_mask = _box_blur_float(guide_arr * mask, r)
            cov_guide_mask = mean_guide_mask - mean_guide * mean_mask

            mean_guide_sq = _box_blur_float(guide_arr * guide_arr, r)
            var_guide = mean_guide_sq - mean_guide * mean_guide

            a = cov_guide_mask / (var_guide + eps)
            b = mean_mask - a * mean_guide

            mean_a = _box_blur_float(a, r)
            mean_b = _box_blur_float(b, r)

            return np.clip(mean_a * guide_arr + mean_b, 0.0, 1.0)

        # 3-channel color guidance
        red = guide_arr[..., 0]
        green = guide_arr[..., 1]
        blue = guide_arr[..., 2]

        mean_r = _box_blur_float(red, r)
        mean_g = _box_blur_float(green, r)
        mean_b = _box_blur_float(blue, r)
        mean_mask = _box_blur_float(mask, r)

        cov_r_mask = _box_blur_float(red * mask, r) - mean_r * mean_mask
        cov_g_mask = _box_blur_float(green * mask, r) - mean_g * mean_mask
        cov_b_mask = _box_blur_float(blue * mask, r) - mean_b * mean_mask

        var_rr = _box_blur_float(red * red, r) - mean_r * mean_r + eps
        var_rg = _box_blur_float(red * green, r) - mean_r * mean_g
        var_rb = _box_blur_float(red * blue, r) - mean_r * mean_b
        var_gg = _box_blur_float(green * green, r) - mean_g * mean_g + eps
        var_gb = _box_blur_float(green * blue, r) - mean_g * mean_b
        var_bb = _box_blur_float(blue * blue, r) - mean_b * mean_b + eps

        inv_00 = var_gg * var_bb - var_gb * var_gb
        inv_01 = var_gb * var_rb - var_rg * var_bb
        inv_02 = var_rg * var_gb - var_gg * var_rb

        inv_11 = var_rr * var_bb - var_rb * var_rb
        inv_12 = var_rb * var_rg - var_rr * var_gb

        inv_22 = var_rr * var_gg - var_rg * var_rg

        det = var_rr * inv_00 + var_rg * inv_01 + var_rb * inv_02
        det = np.where(det > 1e-10, det, 1.0)

        inv_00 /= det
        inv_01 /= det
        inv_02 /= det
        inv_11 /= det
        inv_12 /= det
        inv_22 /= det

        a_r = inv_00 * cov_r_mask + inv_01 * cov_g_mask + inv_02 * cov_b_mask
        a_g = inv_01 * cov_r_mask + inv_11 * cov_g_mask + inv_12 * cov_b_mask
        a_b = inv_02 * cov_r_mask + inv_12 * cov_g_mask + inv_22 * cov_b_mask

        b = mean_mask - (a_r * mean_r + a_g * mean_g + a_b * mean_b)

        mean_a_r = _box_blur_float(a_r, r)
        mean_a_g = _box_blur_float(a_g, r)
        mean_a_b = _box_blur_float(a_b, r)
        mean_b = _box_blur_float(b, r)

        q = mean_a_r * red + mean_a_g * green + mean_a_b * blue + mean_b
        return np.clip(q, 0.0, 1.0)

    q_full = _filter_core(radius)

    if not smart_radius:
        return q_full

    # Smart Radius: adapt bandwidth between r_small and r_full
    r_small = max(1, int(round(radius * 0.25)))
    if r_small >= radius:
        return q_full

    q_small = _filter_core(r_small)

    luma = (
        guide_arr
        if guide_arr.ndim == 2
        else 0.299 * guide_arr[..., 0] + 0.587 * guide_arr[..., 1] + 0.114 * guide_arr[..., 2]
    )

    gy = np.zeros_like(luma)
    gy[1:-1, :] = 0.5 * np.abs(luma[2:, :] - luma[:-2, :])
    gx = np.zeros_like(luma)
    gx[:, 1:-1] = 0.5 * np.abs(luma[:, 2:] - luma[:, :-2])
    grad = np.sqrt(gx * gx + gy * gy)
    peak_g = _box_blur_float(grad, 2)

    var = np.maximum(0.0, _box_blur_float(luma * luma, radius) - _box_blur_float(luma, radius) ** 2)
    sigma = np.sqrt(var)

    w = np.clip(1.0 - 2.0 * peak_g + sigma, 0.0, 1.0)
    w = _box_blur_float(w, max(1, r_small))

    return np.clip((1.0 - w) * q_small + w * q_full, 0.0, 1.0)


def decontaminate_colors(
    image: QImage | np.ndarray,
    mask: np.ndarray,
    amount: float = 1.0,
    radius: int = 8,
) -> QImage | np.ndarray:
    """Color Decontamination: eliminates background fringe color bleed by
    normalized convolution from interior pixels (mask > 0.75) into fringe
    pixels (0 < mask < 0.95) of the active layer (#417).
    `amount`: 0.0..1.0 decontamination strength.
    `radius`: convolution radius in pixels (default 8).
    """
    is_qimage = isinstance(image, QImage)
    if is_qimage:
        img_h, img_w = image.height(), image.width()
    else:
        img_h, img_w = image.shape[:2]
    if (img_h, img_w) != mask.shape[:2]:
        return QImage(image) if is_qimage else image.copy()

    if is_qimage:
        out_img = QImage(image)
        arr = view_u32(out_img)
        alpha = (arr >> np.uint32(24)) & 0xFF
        r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
        g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
        b = (arr & np.uint32(0xFF)).astype(np.float32)

        # Unpremultiply where alpha > 0
        nonzero = alpha > 0
        r[nonzero] = (r[nonzero] * 255.0) / alpha[nonzero]
        g[nonzero] = (g[nonzero] * 255.0) / alpha[nonzero]
        b[nonzero] = (b[nonzero] * 255.0) / alpha[nonzero]
        rgb = np.stack([r, g, b], axis=-1)
    else:
        rgb = image[..., :3].astype(np.float32)

    m = np.clip(mask.astype(np.float32), 0.0, 1.0)
    interior = (m > 0.75).astype(np.float32)
    if not interior.any():
        interior = (m > 0.5).astype(np.float32)
    if not interior.any():
        interior = (m > 0.0).astype(np.float32)
    if not interior.any():
        return out_img if is_qimage else image

    r_dec = max(1, int(radius))
    denom = _box_blur_float(interior, r_dec)

    fringe = (m > 0.01) & (m < 0.95)
    amt = np.clip(float(amount), 0.0, 1.0)

    out_rgb = rgb.copy()
    for c in range(3):
        num = _box_blur_float(rgb[..., c] * interior, r_dec)
        extrap = np.where(denom > 1e-4, num / np.maximum(denom, 1e-6), rgb[..., c])
        blend_factor = amt * (1.0 - m[fringe] * 0.5)
        out_rgb[fringe, c] = (1.0 - blend_factor) * rgb[fringe, c] + blend_factor * extrap[fringe]

    out_rgb = np.clip(out_rgb, 0.0, 255.0)

    if is_qimage:
        r_out = out_rgb[..., 0]
        g_out = out_rgb[..., 1]
        b_out = out_rgb[..., 2]
        pr = np.minimum((r_out * alpha / 255.0 + 0.5).astype(np.uint32), alpha)
        pg = np.minimum((g_out * alpha / 255.0 + 0.5).astype(np.uint32), alpha)
        pb = np.minimum((b_out * alpha / 255.0 + 0.5).astype(np.uint32), alpha)
        arr[:] = (alpha << np.uint32(24)) | (pr << np.uint32(16)) | (pg << np.uint32(8)) | pb
        return out_img
    else:
        if image.shape[-1] == 4:
            out = np.empty_like(image)
            out[..., :3] = out_rgb.astype(image.dtype)
            out[..., 3] = image[..., 3]
            return out
        return out_rgb.astype(image.dtype)


def refine_selection(
    mask: np.ndarray,
    image: QImage | np.ndarray | None = None,
    radius: int = 0,
    smart_radius: bool = False,
    smooth: int = 0,
    feather: int = 0,
    contrast: int = 0,
    shift: int = 0,
    decontaminate: bool = False,
    decontaminate_amount: float = 1.0,
) -> tuple[np.ndarray, np.ndarray, QImage | np.ndarray | None]:
    """Select and Mask refinement pipeline with DD-001 Memory Frugality.
    Restricts processing strictly to tiles/strips intersecting the selection
    boundary dilated by the search radius (+ margin for smooth/feather/shift).

    Returns:
    (refined_bool_mask, refined_alpha_weights, decontaminated_image_or_none)
    """
    if not mask.any():
        return mask.copy(), np.zeros_like(mask, dtype=np.float32), None

    h, w = mask.shape[:2]
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    ymin, ymax = np.where(rows)[0][[0, -1]]
    xmin, xmax = np.where(cols)[0][[0, -1]]

    margin = int(radius) + int(smooth) + int(feather) + max(10, abs(int(shift))) + 8
    y0 = max(0, ymin - margin)
    y1 = min(h, ymax + margin + 1)
    x0 = max(0, xmin - margin)
    x1 = min(w, xmax + margin + 1)

    sub_mask = mask[y0:y1, x0:x1]
    alpha = sub_mask.astype(np.float32)

    sub_guide = None
    if image is not None:
        img_h = image.height() if isinstance(image, QImage) else image.shape[0]
        img_w = image.width() if isinstance(image, QImage) else image.shape[1]
        if (img_h, img_w) == (h, w):
            if isinstance(image, QImage):
                arr = view_u32(image)[y0:y1, x0:x1]
                r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32) / 255.0
                g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32) / 255.0
                b = (arr & np.uint32(0xFF)).astype(np.float32) / 255.0
                sub_guide = np.stack([r, g, b], axis=-1)
            else:
                sub_guide = image[y0:y1, x0:x1]

    # 1. Edge Detection: Guided Image Filter
    if radius > 0 and sub_guide is not None:
        alpha = guided_filter(sub_guide, alpha, radius=radius, smart_radius=smart_radius)

    # 2. Global Refinements:
    # a. Smooth: morphological smoothing (close-then-open)
    if smooth > 0:
        s_steps = max(1, int(round(smooth / 2.0)))
        for _ in range(s_steps):
            alpha = _grey_dilate(alpha)
        for _ in range(s_steps * 2):
            alpha = _grey_erode(alpha)
        for _ in range(s_steps):
            alpha = _grey_dilate(alpha)

    # b. Feather: 3-pass box blur (Gaussian CLT approximation)
    if feather > 0:
        r_feather = max(1, int(feather) // 2 + 1)
        for _ in range(3):
            alpha = _box_blur_float(alpha, r_feather)

    # c. Contrast: steepens transition ramp around 50%
    if contrast > 0:
        c_val = min(100, max(0, int(contrast))) / 100.0
        slope = 1.0 / max(1.0 - 0.98 * c_val, 0.01)
        alpha = np.clip(0.5 + (alpha - 0.5) * slope, 0.0, 1.0)

    # d. Shift Edge: grey morphological dilation (+) / erosion (-)
    if shift != 0:
        steps = abs(int(shift))
        if shift > 0:
            for _ in range(steps):
                alpha = _grey_dilate(alpha)
        else:
            for _ in range(steps):
                alpha = _grey_erode(alpha)

    # Reconstruct full canvas alpha and boolean mask
    full_alpha = np.zeros((h, w), dtype=np.float32)
    full_alpha[y0:y1, x0:x1] = alpha
    full_bool = full_alpha >= 0.5

    # 3. Output / Color Decontamination
    decontam_out = None
    if decontaminate and image is not None:
        decontam_out = decontaminate_colors(
            image,
            full_alpha,
            amount=decontaminate_amount,
            radius=max(int(radius), 8),
        )

    return full_bool, full_alpha, decontam_out


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
                rects.append(QRect(span[0] + ox, y0 + oy, span[1] - span[0] + 1, last - y0 + 1))
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
