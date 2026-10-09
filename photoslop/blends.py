# SPDX-License-Identifier: Apache-2.0
"""Vectorized NumPy evaluation for layer blend modes without extra layer buffers.

Implements all 27 standard blend modes:
- Normal: normal, dissolve
- Darken: darken, multiply, color-burn, linear-burn, darker-color
- Lighten: lighten, screen, color-dodge, linear-dodge (addition), lighter-color
- Contrast: overlay, soft-light, hard-light, vivid-light, linear-light, pin-light, hard-mix
- Inversion: difference, exclusion, subtract, divide
- Component (HSL): hue, saturation, color, luminosity
"""

from __future__ import annotations

import numpy as np

# Blend modes that are not natively supported by QPainter.CompositionMode
# and must be evaluated via vectorized NumPy during compositing.
CUSTOM_BLEND_MODES = frozenset(
    {
        "dissolve",
        "linear-burn",
        "darker-color",
        "lighter-color",
        "vivid-light",
        "linear-light",
        "pin-light",
        "hard-mix",
        "subtract",
        "divide",
        "hue",
        "saturation",
        "color",
        "luminosity",
    }
)


def lum(rgb: np.ndarray) -> np.ndarray:
    """Luminosity of an RGB array in [0, 1]. Returns shape (...) in [0, 1]."""
    return 0.3 * rgb[..., 0] + 0.59 * rgb[..., 1] + 0.11 * rgb[..., 2]


def sat(rgb: np.ndarray) -> np.ndarray:
    """Saturation of an RGB array in [0, 1]. Returns shape (...) in [0, 1]."""
    return np.max(rgb, axis=-1) - np.min(rgb, axis=-1)


def clip_color(rgb: np.ndarray) -> np.ndarray:
    """Clip out-of-gamut colors back into [0, 1] while preserving luminosity."""
    lum_val = lum(rgb)[..., None]
    n = np.min(rgb, axis=-1, keepdims=True)
    x = np.max(rgb, axis=-1, keepdims=True)

    denom_n = np.maximum(lum_val - n, 1e-7)
    rgb = np.where(n < 0.0, lum_val + (((rgb - lum_val) * lum_val) / denom_n), rgb)

    denom_x = np.maximum(x - lum_val, 1e-7)
    rgb = np.where(x > 1.0, lum_val + (((rgb - lum_val) * (1.0 - lum_val)) / denom_x), rgb)
    return np.clip(rgb, 0.0, 1.0)


def set_lum(rgb: np.ndarray, target_lum: np.ndarray) -> np.ndarray:
    """Adjust color components to match target luminosity."""
    d = target_lum[..., None] - lum(rgb)[..., None]
    return clip_color(rgb + d)


def set_sat(rgb: np.ndarray, s: np.ndarray) -> np.ndarray:
    """Adjust color components to match target saturation."""
    order = np.argsort(rgb, axis=-1)
    sorted_rgb = np.take_along_axis(rgb, order, axis=-1)
    c_min = sorted_rgb[..., 0:1]
    c_mid = sorted_rgb[..., 1:2]
    c_max = sorted_rgb[..., 2:3]
    range_val = c_max - c_min
    s_exp = s[..., None]
    new_mid = np.where(
        range_val > 0.0,
        ((c_mid - c_min) * s_exp) / np.maximum(range_val, 1e-7),
        0.0,
    )
    new_max = np.where(range_val > 0.0, s_exp, 0.0)
    new_min = np.zeros_like(new_max)
    sorted_res = np.concatenate([new_min, new_mid, new_max], axis=-1)
    inv_order = np.argsort(order, axis=-1)
    return np.take_along_axis(sorted_res, inv_order, axis=-1)


def dither_hash(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Deterministic spatial coordinate hash for Dissolve in [0, 1)."""
    hx = x.astype(np.uint32) * np.uint32(0x1F1F1F1F)
    hy = y.astype(np.uint32) * np.uint32(0x5D5D5D5D)
    h = hx ^ hy
    h = h ^ (h >> np.uint32(16))
    h = h * np.uint32(0x85EBCA6B)
    h = h ^ (h >> np.uint32(13))
    h = h * np.uint32(0xC2B2AE35)
    h = h ^ (h >> np.uint32(16))
    return (h & np.uint32(0xFFFF)).astype(np.float32) / 65536.0


def blend_rgb(b: np.ndarray, s: np.ndarray, mode: str) -> np.ndarray:
    """Evaluate pure color blend formula B(b, s) on normalized [0, 1] RGB arrays."""
    match mode:
        case "linear-burn":
            return np.maximum(0.0, b + s - 1.0)
        case "linear-dodge" | "addition":
            return np.minimum(1.0, b + s)
        case "vivid-light":
            burn = np.where(
                s > 0.0, np.maximum(0.0, 1.0 - (1.0 - b) / np.maximum(2.0 * s, 1e-7)), 0.0
            )
            dodge = np.where(s < 1.0, np.minimum(1.0, b / np.maximum(2.0 * (1.0 - s), 1e-7)), 1.0)
            return np.where(s <= 0.5, burn, dodge)
        case "linear-light":
            return np.clip(b + 2.0 * s - 1.0, 0.0, 1.0)
        case "pin-light":
            return np.where(s <= 0.5, np.minimum(b, 2.0 * s), np.maximum(b, 2.0 * s - 1.0))
        case "hard-mix":
            return np.where(b + s >= 1.0, 1.0, 0.0)
        case "darker-color":
            b_sum = b[..., 0] + b[..., 1] + b[..., 2]
            s_sum = s[..., 0] + s[..., 1] + s[..., 2]
            return np.where((b_sum <= s_sum)[..., None], b, s)
        case "lighter-color":
            b_sum = b[..., 0] + b[..., 1] + b[..., 2]
            s_sum = s[..., 0] + s[..., 1] + s[..., 2]
            return np.where((b_sum >= s_sum)[..., None], b, s)
        case "subtract":
            return np.maximum(0.0, b - s)
        case "divide":
            return np.where(s > 0.0, np.minimum(1.0, b / np.maximum(s, 1e-7)), 1.0)
        case "hue":
            return set_lum(set_sat(s, sat(b)), lum(b))
        case "saturation":
            return set_lum(set_sat(b, sat(s)), lum(b))
        case "color":
            return set_lum(s, lum(b))
        case "luminosity":
            return set_lum(b, lum(s))
        case "multiply":
            return b * s
        case "screen":
            return 1.0 - (1.0 - b) * (1.0 - s)
        case "overlay":
            return np.where(b <= 0.5, 2.0 * b * s, 1.0 - 2.0 * (1.0 - b) * (1.0 - s))
        case "darken":
            return np.minimum(b, s)
        case "lighten":
            return np.maximum(b, s)
        case "color-dodge":
            return np.where(s < 1.0, np.minimum(1.0, b / np.maximum(1.0 - s, 1e-7)), 1.0)
        case "color-burn":
            return np.where(s > 0.0, 1.0 - np.minimum(1.0, (1.0 - b) / np.maximum(s, 1e-7)), 0.0)
        case "hard-light":
            return np.where(s <= 0.5, 2.0 * b * s, 1.0 - 2.0 * (1.0 - b) * (1.0 - s))
        case "soft-light":
            d = np.where(b <= 0.25, ((16.0 * b - 12.0) * b + 4.0) * b, np.sqrt(b))
            return np.where(
                s <= 0.5,
                b - (1.0 - 2.0 * s) * b * (1.0 - b),
                b + (2.0 * s - 1.0) * (d - b),
            )
        case "difference":
            return np.abs(b - s)
        case "exclusion":
            return b + s - 2.0 * b * s
        case _:
            return s


def blend_u32_inplace(
    dst_arr: np.ndarray,
    src_arr: np.ndarray,
    mode: str,
    opacity: float = 1.0,
    origin_x: int = 0,
    origin_y: int = 0,
) -> None:
    """Blend src_arr into dst_arr in place.

    dst_arr and src_arr must both be 2D uint32 views of Format_ARGB32_Premultiplied
    with identical shape (H, W).
    """
    if opacity <= 0.0:
        return

    sa = (src_arr >> np.uint32(24)) & np.uint32(0xFF)
    if not np.any(sa):
        return

    h, w = dst_arr.shape
    sr = (src_arr >> np.uint32(16)) & np.uint32(0xFF)
    sg = (src_arr >> np.uint32(8)) & np.uint32(0xFF)
    sb = src_arr & np.uint32(0xFF)

    # Special stochastic handling for Dissolve
    if mode == "dissolve":
        xs = np.arange(origin_x, origin_x + w, dtype=np.int32)[None, :]
        ys = np.arange(origin_y, origin_y + h, dtype=np.int32)[:, None]
        h_vals = dither_hash(xs, ys)
        eff_sa = sa.astype(np.float32) / 255.0 * float(opacity)
        keep_src = h_vals < eff_sa
        if np.any(keep_src):
            # Unpremultiply source RGB for opaque rendering
            div = np.maximum(sa, 1)
            ur = np.clip(np.round(sr.astype(np.float32) * 255.0 / div), 0, 255).astype(np.uint32)
            ug = np.clip(np.round(sg.astype(np.float32) * 255.0 / div), 0, 255).astype(np.uint32)
            ub = np.clip(np.round(sb.astype(np.float32) * 255.0 / div), 0, 255).astype(np.uint32)
            opaque_src = (
                (np.uint32(0xFF) << np.uint32(24))
                | (ur << np.uint32(16))
                | (ug << np.uint32(8))
                | ub
            )
            dst_arr[:] = np.where(keep_src, opaque_src, dst_arr)
        return

    da = (dst_arr >> np.uint32(24)) & np.uint32(0xFF)
    dr = (dst_arr >> np.uint32(16)) & np.uint32(0xFF)
    dg = (dst_arr >> np.uint32(8)) & np.uint32(0xFF)
    db = dst_arr & np.uint32(0xFF)

    # Convert to float [0, 1]
    da_f = da.astype(np.float32) / 255.0
    dr_f = dr.astype(np.float32) / 255.0
    dg_f = dg.astype(np.float32) / 255.0
    db_f = db.astype(np.float32) / 255.0

    op_f = float(opacity)
    sa_f = sa.astype(np.float32) / 255.0 * op_f
    sr_f = sr.astype(np.float32) / 255.0 * op_f
    sg_f = sg.astype(np.float32) / 255.0 * op_f
    sb_f = sb.astype(np.float32) / 255.0 * op_f

    # Unpremultiplied color for blending formula
    s_r = np.clip(sr_f / np.maximum(sa_f, 1e-7), 0.0, 1.0)
    s_g = np.clip(sg_f / np.maximum(sa_f, 1e-7), 0.0, 1.0)
    s_b = np.clip(sb_f / np.maximum(sa_f, 1e-7), 0.0, 1.0)

    b_r = np.clip(dr_f / np.maximum(da_f, 1e-7), 0.0, 1.0)
    b_g = np.clip(dg_f / np.maximum(da_f, 1e-7), 0.0, 1.0)
    b_b = np.clip(db_f / np.maximum(da_f, 1e-7), 0.0, 1.0)

    b_rgb = np.stack([b_r, b_g, b_b], axis=-1)
    s_rgb = np.stack([s_r, s_g, s_b], axis=-1)

    c_blend = blend_rgb(b_rgb, s_rgb, mode)

    # Porter-Duff compositing with non-separable / separable blend function:
    # c_result = (1 - da) * c_source + (1 - sa) * c_backdrop + da * sa * B(b, s)
    res_a = sa_f + da_f * (1.0 - sa_f)
    res_r = (1.0 - da_f) * sr_f + (1.0 - sa_f) * dr_f + da_f * sa_f * c_blend[..., 0]
    res_g = (1.0 - da_f) * sg_f + (1.0 - sa_f) * dg_f + da_f * sa_f * c_blend[..., 1]
    res_b = (1.0 - da_f) * sb_f + (1.0 - sa_f) * db_f + da_f * sa_f * c_blend[..., 2]

    out_a = np.clip(np.round(res_a * 255.0), 0, 255).astype(np.uint32)
    out_r = np.clip(np.round(res_r * 255.0), 0, 255).astype(np.uint32)
    out_g = np.clip(np.round(res_g * 255.0), 0, 255).astype(np.uint32)
    out_b = np.clip(np.round(res_b * 255.0), 0, 255).astype(np.uint32)

    dst_arr[:] = (
        (out_a << np.uint32(24)) | (out_r << np.uint32(16)) | (out_g << np.uint32(8)) | out_b
    )
