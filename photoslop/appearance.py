# SPDX-License-Identifier: Apache-2.0
"""Versioned, non-destructive appearance effects shared by every layer type."""

from __future__ import annotations

import copy
import json
import math
import uuid
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage

from photoslop import npimage
from photoslop.layer import BLEND_MODES, FORMAT

SCHEMA_VERSION = 1

EFFECT_DEFAULTS: dict[str, dict] = {
    "drop-shadow": {"offset_x": 6, "offset_y": 6, "blur": 8, "spread": 0,
                    "color": [0, 0, 0, 153]},
    "inner-shadow": {"offset_x": 3, "offset_y": 3, "blur": 5, "spread": 0,
                     "color": [0, 0, 0, 140]},
    "outer-glow": {"size": 10, "spread": 0, "color": [255, 220, 120, 200]},
    "inner-glow": {"size": 8, "choke": 0, "source": "edge",
                   "color": [255, 255, 255, 180]},
    "outline": {"width": 3, "position": "outside", "color": [0, 0, 0, 255]},
    "color-overlay": {"color": [255, 255, 255, 255]},
    "gradient-overlay": {"color1": [255, 255, 255, 255],
                         "color2": [0, 0, 0, 255], "angle": 90,
                         "scale": 100, "offset_x": 0, "offset_y": 0,
                         "reverse": False},
    "bevel-emboss": {"style": "inner-bevel", "depth": 100, "size": 5,
                     "soften": 1, "angle": 120, "altitude": 30,
                     "highlight_color": [255, 255, 255, 190],
                     "shadow_color": [0, 0, 0, 160]},
    "gaussian-blur": {"radius": 5},
    "feather": {"radius": 5},
}

EFFECT_LABELS = {
    "drop-shadow": "Drop Shadow", "inner-shadow": "Inner Shadow",
    "outer-glow": "Outer Glow", "inner-glow": "Inner Glow",
    "outline": "Outline", "color-overlay": "Color Overlay",
    "gradient-overlay": "Gradient Overlay", "bevel-emboss": "Bevel / Emboss",
    "gaussian-blur": "Gaussian Blur", "feather": "Feather",
}


def new_effect(kind: str, **parameters) -> dict:
    if kind not in EFFECT_DEFAULTS:
        raise ValueError(f"Unknown appearance effect: {kind}")
    effect = {
        "schema_version": SCHEMA_VERSION,
        "id": uuid.uuid4().hex,
        "type": kind,
        "enabled": True,
        "blend_mode": "normal",
        "opacity": 1.0,
        "parameters": copy.deepcopy(EFFECT_DEFAULTS[kind]),
    }
    effect["parameters"].update(copy.deepcopy(parameters))
    return normalize_effect(effect)


def _legacy_effect(value) -> dict:
    kind = value[0]
    if kind == "drop-shadow":
        _, dx, dy, blur, color = value
        effect = new_effect(kind, offset_x=dx, offset_y=dy, blur=blur, color=color)
    elif kind == "glow":
        _, size, color = value
        effect = new_effect("outer-glow", size=size, color=color)
    elif kind == "stroke":
        _, width, color = value
        effect = new_effect("outline", width=width, color=color)
    else:
        raise ValueError(f"Unknown legacy appearance effect: {kind}")
    # Legacy tuples have no ID; a content-derived ID keeps cache keys stable.
    effect["id"] = uuid.uuid5(uuid.NAMESPACE_URL,
                              "photoslop-effect:" + repr(tuple(value))).hex
    return effect


def _number(value, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _rgba(value, default) -> list[int]:
    if not isinstance(value, (list, tuple)) or len(value) not in {3, 4}:
        value = default
    values = [int(_number(item, 0, 255, 0)) for item in value]
    return [*values[:3], values[3] if len(values) > 3 else 255]


def normalize_effect(value) -> dict:
    """Validate one effect and migrate the historical tuple representation."""
    if isinstance(value, (tuple, list)):
        return _legacy_effect(value)
    if not isinstance(value, dict):
        raise ValueError("Appearance effects must be objects")
    kind = str(value.get("type", ""))
    if kind not in EFFECT_DEFAULTS:
        raise ValueError(f"Unknown appearance effect: {kind}")
    defaults = EFFECT_DEFAULTS[kind]
    params = copy.deepcopy(defaults)
    incoming = value.get("parameters", {})
    if isinstance(incoming, dict):
        params.update(copy.deepcopy(incoming))
    for key in tuple(params):
        if key not in defaults:
            continue  # preserve future parameters without interpreting them
        if key.endswith("color") or key in {"color", "color1", "color2"}:
            params[key] = _rgba(params[key], defaults[key])
        elif key in {"reverse"}:
            params[key] = bool(params[key])
        elif key in {"source", "position", "style"}:
            params[key] = str(params[key])
        elif key.startswith("offset_"):
            params[key] = _number(params[key], -10000, 10000, defaults[key])
        elif key in {"angle"}:
            params[key] = _number(params[key], 0, 360, defaults[key])
        elif key in {"scale", "depth"}:
            params[key] = _number(params[key], 1, 1000, defaults[key])
        else:
            params[key] = _number(params[key], 0, 1000, defaults[key])
    blend = str(value.get("blend_mode", "normal"))
    known = {"schema_version", "id", "type", "enabled", "blend_mode", "opacity",
             "parameters", "extensions"}
    extensions = copy.deepcopy(value.get("extensions", {}))
    if not isinstance(extensions, dict):
        extensions = {}
    extensions.update({key: copy.deepcopy(item) for key, item in value.items()
                       if key not in known})
    return {
        "schema_version": SCHEMA_VERSION,
        "id": str(value.get("id") or uuid.uuid4().hex),
        "type": kind,
        "enabled": bool(value.get("enabled", True)),
        "blend_mode": blend if blend in BLEND_MODES else "normal",
        "opacity": _number(value.get("opacity", 1.0), 0, 1, 1),
        "parameters": params,
        **({"extensions": extensions} if extensions else {}),
    }


def normalize_effects(values) -> list[dict]:
    result = []
    for value in values or []:
        try:
            result.append(normalize_effect(value))
        except (TypeError, ValueError, IndexError):
            continue
    return result


def effect_margin(effects) -> int:
    margin = 0
    for effect in normalize_effects(effects):
        if not effect["enabled"]:
            continue
        kind, p = effect["type"], effect["parameters"]
        if kind == "drop-shadow":
            margin = max(margin, round(p["blur"] + p["spread"]
                         + max(abs(p["offset_x"]), abs(p["offset_y"]))))
        elif kind in {"outer-glow", "outline"}:
            margin = max(margin, round(p.get("size", p.get("width", 0))
                                       + p.get("spread", 0)))
        elif kind in {"gaussian-blur", "feather"}:
            margin = max(margin, round(p["radius"] * 2))
    return margin


def stack_key(effects) -> str:
    return json.dumps(normalize_effects(effects), sort_keys=True, separators=(",", ":"))


def _alpha(img: QImage) -> np.ndarray:
    return ((npimage.view_u32(img) >> np.uint32(24)) & 0xFF).astype(np.float32)


def _blur_plane(plane: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return plane.copy()
    result = plane
    r = max(1, int(radius) // 2 + 1)
    for _ in range(3):
        result = npimage._box_blur_plane(result, r)
    return result


def _morph(mask: np.ndarray, amount: int, grow: bool) -> np.ndarray:
    result = mask > 1
    for _ in range(max(0, int(amount))):
        if grow:
            result = npimage._dilate(result)
        else:
            padded = np.pad(result, 1, constant_values=False)
            result = (padded[:-2, :-2] & padded[:-2, 1:-1] & padded[:-2, 2:]
                      & padded[1:-1, :-2] & padded[1:-1, 1:-1]
                      & padded[1:-1, 2:] & padded[2:, :-2]
                      & padded[2:, 1:-1] & padded[2:, 2:])
    return result.astype(np.float32) * 255


def _color_image(alpha: np.ndarray, color) -> QImage:
    rgba = _rgba(color, [0, 0, 0, 255])
    a = np.clip(alpha * rgba[3] / 255.0, 0, 255).astype(np.uint32)
    scale = a / 255.0
    out = QImage(alpha.shape[1], alpha.shape[0], FORMAT)
    npimage.view_u32(out)[:] = ((a << np.uint32(24))
        | ((rgba[0] * scale).astype(np.uint32) << np.uint32(16))
        | ((rgba[1] * scale).astype(np.uint32) << np.uint32(8))
        | (rgba[2] * scale).astype(np.uint32))
    return out


def _padded_alpha(img: QImage, pad: int) -> np.ndarray:
    source = _alpha(img)
    result = np.zeros((img.height() + pad * 2, img.width() + pad * 2), np.float32)
    result[pad:pad + img.height(), pad:pad + img.width()] = source
    return result


def _shift(plane: np.ndarray, dx: int, dy: int) -> np.ndarray:
    result = np.zeros_like(plane)
    x0, x1 = max(0, dx), min(plane.shape[1], plane.shape[1] + dx)
    y0, y1 = max(0, dy), min(plane.shape[0], plane.shape[0] + dy)
    sx0, sy0 = max(0, -dx), max(0, -dy)
    if x1 > x0 and y1 > y0:
        result[y0:y1, x0:x1] = plane[sy0:sy0 + y1 - y0, sx0:sx0 + x1 - x0]
    return result


def _gradient_image(img: QImage, p: dict) -> QImage:
    h, w = img.height(), img.width()
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    angle = math.radians(float(p["angle"]) - 90)
    span = max(1.0, math.hypot(w, h) * float(p["scale"]) / 100.0)
    cx = w / 2 + float(p["offset_x"])
    cy = h / 2 + float(p["offset_y"])
    t = np.clip(((xx - cx) * math.cos(angle) + (yy - cy) * math.sin(angle))
                / span + 0.5, 0, 1)
    if p["reverse"]:
        t = 1 - t
    c1, c2 = np.array(p["color1"], np.float32), np.array(p["color2"], np.float32)
    rgba = c1[None, None, :] * (1 - t[..., None]) + c2[None, None, :] * t[..., None]
    source_alpha = _alpha(img) / 255.0
    a = np.clip(rgba[..., 3] * source_alpha, 0, 255).astype(np.uint32)
    scale = a.astype(np.float32) / 255.0
    out = QImage(w, h, FORMAT)
    npimage.view_u32(out)[:] = ((a << np.uint32(24))
        | ((rgba[..., 0] * scale).astype(np.uint32) << np.uint32(16))
        | ((rgba[..., 1] * scale).astype(np.uint32) << np.uint32(8))
        | (rgba[..., 2] * scale).astype(np.uint32))
    return out


@dataclass
class Plane:
    image: QImage
    offset: QPoint
    under: bool
    blend_mode: str = "normal"
    opacity: float = 1.0


@dataclass
class RenderedAppearance:
    planes: list[Plane]
    fill_image: QImage | None = None
    fill_offset: QPoint | None = None


def render(layer) -> RenderedAppearance:
    """Render a bounded, layer-local appearance from the effective alpha."""
    effects = normalize_effects(layer.effects)
    source = (layer.paint_image(layer.image.rect()) if layer.mask is not None
              else QImage(layer.image))
    # Keep cached geometry independent of canvas placement.  The compositor
    # adds layer.offset when drawing, so moving a layer never rebuilds effects.
    source_offset = QPoint()
    fill_override = None
    planes: list[Plane] = []
    for effect in effects:
        if not effect["enabled"]:
            continue
        kind, p = effect["type"], effect["parameters"]
        blend, opacity = effect["blend_mode"], float(effect["opacity"])
        alpha = _alpha(source)
        if kind == "drop-shadow":
            spread, blur = round(p["spread"]), round(p["blur"])
            pad = spread + blur
            plane = _padded_alpha(source, pad)
            if spread:
                plane = _morph(plane, spread, True)
            plane = _blur_plane(plane, blur)
            image = _color_image(plane, p["color"])
            off = source_offset + QPoint(round(p["offset_x"]) - pad,
                                         round(p["offset_y"]) - pad)
            planes.append(Plane(image, off, True, blend, opacity))
        elif kind == "outer-glow":
            spread, size = round(p["spread"]), round(p["size"])
            pad = spread + size
            plane = _padded_alpha(source, pad)
            if spread:
                plane = _morph(plane, spread, True)
            original = _padded_alpha(source, pad)
            plane = np.clip(_blur_plane(plane, size) - original, 0, 255)
            planes.append(Plane(_color_image(plane, p["color"]),
                                source_offset - QPoint(pad, pad), True, blend, opacity))
        elif kind == "outline":
            width = max(1, round(p["width"]))
            position = p["position"]
            if position == "inside":
                plane = np.clip(alpha - _morph(alpha, width, False), 0, 255)
                image, off = _color_image(plane, p["color"]), source_offset
            else:
                outside = width if position == "outside" else max(1, width // 2)
                padded = _padded_alpha(source, outside)
                plane = np.clip(_morph(padded, outside, True) - padded, 0, 255)
                if position == "center":
                    inside = np.clip(alpha - _morph(alpha, width - outside, False), 0, 255)
                    plane[outside:outside + source.height(),
                          outside:outside + source.width()] += inside
                image = _color_image(plane, p["color"])
                off = source_offset - QPoint(outside, outside)
            planes.append(Plane(image, off, position == "outside", blend, opacity))
        elif kind == "inner-shadow":
            shifted = _shift(alpha, -round(p["offset_x"]), -round(p["offset_y"]))
            shifted = _blur_plane(shifted, round(p["blur"]))
            plane = alpha * (1 - shifted / 255.0)
            if p["spread"]:
                plane = np.maximum(plane, alpha - _morph(alpha, round(p["spread"]), False))
            planes.append(Plane(_color_image(plane, p["color"]), source_offset,
                                False, blend, opacity))
        elif kind == "inner-glow":
            size = round(p["size"])
            if p["source"] == "center":
                plane = _blur_plane(_morph(alpha, round(p["choke"]), False), size)
            else:
                edge = np.clip(alpha - _morph(alpha, max(1, size + round(p["choke"])), False),
                               0, 255)
                plane = _blur_plane(edge, max(1, size // 2)) * (alpha / 255.0)
            planes.append(Plane(_color_image(plane, p["color"]), source_offset,
                                False, blend, opacity))
        elif kind == "color-overlay":
            planes.append(Plane(_color_image(alpha, p["color"]), source_offset,
                                False, blend, opacity))
        elif kind == "gradient-overlay":
            planes.append(Plane(_gradient_image(source, p), source_offset,
                                False, blend, opacity))
        elif kind == "bevel-emboss":
            height = _blur_plane(alpha, round(p["soften"])) / 255.0
            gy, gx = np.gradient(height)
            azimuth = math.radians(float(p["angle"]))
            altitude = math.radians(float(p["altitude"]))
            light = (-gx * math.cos(azimuth) - gy * math.sin(azimuth))
            light *= math.cos(altitude) * float(p["depth"]) / 100.0
            light += math.sin(altitude) * 0.05
            edge = alpha / 255.0
            highlight = np.clip(light, 0, 1) * 255 * edge
            shadow = np.clip(-light, 0, 1) * 255 * edge
            planes.append(Plane(_color_image(highlight, p["highlight_color"]), source_offset,
                                False, "screen", opacity))
            planes.append(Plane(_color_image(shadow, p["shadow_color"]), source_offset,
                                False, "multiply", opacity))
        elif kind in {"gaussian-blur", "feather"}:
            radius = round(p["radius"])
            if radius <= 0:
                continue
            pad = max(0, radius * 2)
            canvas = QImage(source.width() + pad * 2, source.height() + pad * 2, FORMAT)
            canvas.fill(QColor(0, 0, 0, 0))
            from PySide6.QtGui import QPainter
            painter = QPainter(canvas)
            painter.drawImage(pad, pad, source)
            painter.end()
            npimage.gaussian_blur(canvas, max(1, radius))
            if kind == "feather":
                blurred_alpha = _alpha(canvas)
                original = _padded_alpha(source, pad)
                # Feather only removes edge opacity; it never grows the silhouette.
                target_alpha = np.minimum(blurred_alpha, original).astype(np.uint32)
                packed = npimage.view_u32(canvas)
                old_alpha = ((packed >> np.uint32(24)) & 0xFF).astype(np.float32)
                scale = target_alpha / np.maximum(old_alpha, 1)
                red = (((packed >> np.uint32(16)) & 0xFF) * scale).astype(np.uint32)
                green = (((packed >> np.uint32(8)) & 0xFF) * scale).astype(np.uint32)
                blue = ((packed & 0xFF) * scale).astype(np.uint32)
                packed[:] = ((target_alpha << np.uint32(24))
                              | (red << np.uint32(16))
                              | (green << np.uint32(8)) | blue)
            source, source_offset = canvas, source_offset - QPoint(pad, pad)
            fill_override = QImage(source)
    return RenderedAppearance(planes, fill_override,
                              QPoint(source_offset) if fill_override is not None else None)


BUILTIN_PRESETS: dict[str, list[dict]] = {
    "Lifted": [new_effect("drop-shadow", offset_x=5, offset_y=7, blur=10)],
    "Sticker": [new_effect("drop-shadow", offset_x=4, offset_y=5, blur=5),
                new_effect("outline", width=6, color=[255, 255, 255, 255])],
    "Neon": [new_effect("outer-glow", size=16, spread=2,
                         color=[0, 220, 255, 230]),
             new_effect("inner-glow", size=5, color=[255, 255, 255, 210])],
    "Letterpress": [new_effect("inner-shadow", offset_x=2, offset_y=2, blur=3),
                    new_effect("bevel-emboss", depth=60, size=2)],
    "Chrome": [new_effect("gradient-overlay", color1=[245, 250, 255, 255],
                           color2=[45, 65, 90, 255]),
               new_effect("bevel-emboss", depth=180, size=5)],
    "Soft Focus": [new_effect("gaussian-blur", radius=2),
                   new_effect("outer-glow", size=8,
                              color=[255, 255, 255, 130])],
}
