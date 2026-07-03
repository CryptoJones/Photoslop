# SPDX-License-Identifier: Apache-2.0
"""Headless command-line interface: the editor's engine without the GUI.

Operations are applied in command-line order — every option below is a
pipeline step, so combinations compose left to right:

    photoslop-cli in.cr2 --resize 1600x1067 --levels 10,240,1.2 \
                  --gaussian-blur 2 --drop-shadow 4,4,6,160 --output out.png

Exit codes: 0 success · 2 usage/value errors · 1 runtime failures.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field


def _die(message: str) -> int:
    print(f"photoslop-cli: {message}", file=sys.stderr)
    return 1


class _ValueError(ValueError):
    """A user-facing option-value problem (exit code 2)."""


# ----- value parsers ---------------------------------------------------------


def _ints(text: str, n: int, name: str) -> list[int]:
    parts = text.split(",")
    if len(parts) != n:
        raise _ValueError(f"{name} expects {n} comma-separated values")
    try:
        return [int(p) for p in parts]
    except ValueError as exc:
        raise _ValueError(f"{name}: {exc}") from exc


def _size(text: str, name: str) -> tuple[int, int]:
    parts = text.lower().split("x")
    if len(parts) != 2:
        raise _ValueError(f"{name} expects WxH (e.g. 800x600)")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError as exc:
        raise _ValueError(f"{name}: {exc}") from exc
    if w < 1 or h < 1:
        raise _ValueError(f"{name}: dimensions must be positive")
    return w, h


def _curve_points(text: str) -> list[tuple[float, float]]:
    points = []
    for chunk in text.split(","):
        xy = chunk.split(":")
        if len(xy) != 2:
            raise _ValueError("--curves expects x:y,x:y,... (0..255 pairs)")
        try:
            points.append((float(xy[0]), float(xy[1])))
        except ValueError as exc:
            raise _ValueError(f"--curves: {exc}") from exc
    if len(points) < 2:
        raise _ValueError("--curves needs at least two points")
    return points


# ----- pipeline context ------------------------------------------------------


@dataclass
class Context:
    doc: object
    all_layers: bool = False
    model_url: str = ""
    exports: list = field(default_factory=list)  # written artboard paths


def _target_layers(ctx: Context) -> list:
    doc = ctx.doc
    if ctx.all_layers:
        return [layer for layer in doc.layers
                if layer.visible and layer.adjustment is None]
    return [doc.active_layer]


def _filter_region(ctx: Context, layer, apply) -> None:
    """Selection-aware in-place filter on one layer (mirrors _run_filter)."""
    from photoslop import npimage

    mask = None
    weights = None
    doc = ctx.doc
    if doc.selection is not None:
        if doc.selection_feather > 0:
            weights = npimage.feathered_weights(
                doc.selection, layer.image.size(), layer.offset,
                doc.selection_feather)
        else:
            mask = npimage.selection_mask(doc.selection, layer.image.size(),
                                          layer.offset)
            if not mask.any():
                mask = None
    from PySide6.QtGui import QImage

    before = QImage(layer.image)
    layer.image = QImage(before)
    apply(layer.image, mask)
    if weights is not None:
        npimage.blend_by_weights(layer.image, before, weights)
    elif mask is not None:
        # confine even appliers that ignore the mask argument (LUT ops)
        dst = npimage.view_u32(layer.image)
        src = npimage.view_u32(before)
        dst[~mask] = src[~mask]


# ----- operation appliers ----------------------------------------------------


def _op_resize(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QSize

    from photoslop.commands import ResizeImageCommand

    w, h = _size(value, "--resize")
    ResizeImageCommand(ctx.doc, QSize(w, h)).redo()


def _op_canvas_size(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QPoint, QSize

    from photoslop.commands import ResizeCanvasCommand

    w, h = _size(value, "--canvas-size")
    delta = QPoint((w - ctx.doc.size.width()) // 2,
                   (h - ctx.doc.size.height()) // 2)
    ResizeCanvasCommand(ctx.doc, QSize(w, h), delta).redo()


def _op_crop_real(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QPoint, QSize

    from photoslop.commands import ResizeCanvasCommand

    x, y, w, h = _ints(value, 4, "--crop")
    if w < 1 or h < 1:
        raise _ValueError("--crop: width and height must be positive")
    ResizeCanvasCommand(ctx.doc, QSize(w, h), QPoint(-x, -y), "Crop").redo()


def _op_rotate(ctx: Context, value: str) -> None:
    from photoslop.commands import ArbitraryRotateCommand

    try:
        angle = float(value)
    except ValueError as exc:
        raise _ValueError(f"--rotate: {exc}") from exc
    ArbitraryRotateCommand(ctx.doc, angle).redo()


def _op_cas(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QPoint, QSize

    from photoslop import npimage
    from photoslop.commands import ResizeCanvasCommand

    w, h = _size(value, "--content-aware-scale")
    # each layer carves by the canvas ratio, so multi-layer docs stay coherent
    rx = w / ctx.doc.size.width()
    ry = h / ctx.doc.size.height()
    for layer in _target_layers(ctx):
        lw = max(2, round(layer.image.width() * rx))
        lh = max(2, round(layer.image.height() * ry))
        layer.image = npimage.seam_carve(layer.image, lw, lh)
        layer.offset = QPoint(round(layer.offset.x() * rx),
                              round(layer.offset.y() * ry))
        layer.fx_cache = None
    ResizeCanvasCommand(ctx.doc, QSize(w, h), QPoint(0, 0),
                        "Content-Aware Scale").redo()


def _op_levels(ctx: Context, value: str) -> None:
    from photoslop import adjust

    parts = value.split(",")
    if len(parts) != 3:
        raise _ValueError("--levels expects black,white,gamma")
    try:
        black, white, gamma = int(parts[0]), int(parts[1]), float(parts[2])
    except ValueError as exc:
        raise _ValueError(f"--levels: {exc}") from exc
    import numpy as np

    lut = adjust.levels_lut(black, white, gamma, 0, 255)
    luts = np.repeat(lut[None, :], 3, axis=0)
    for layer in _target_layers(ctx):
        _filter_region(ctx, layer,
                       lambda img, m, luts=luts: adjust.apply_luts(img, luts))


def _op_auto_levels(ctx: Context, value: str) -> None:
    import numpy as np

    from photoslop import adjust, npimage

    for layer in _target_layers(ctx):
        arr = npimage.view_u32(layer.image)
        r = (arr >> np.uint32(16)) & 0xFF
        g = (arr >> np.uint32(8)) & 0xFF
        b = arr & 0xFF
        luma = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8).ravel()
        lo, hi = np.percentile(luma, [0.1, 99.9])
        lut = adjust.levels_lut(int(min(lo, 253)), int(max(hi, lo + 2)),
                                1.0, 0, 255)
        luts = np.repeat(lut[None, :], 3, axis=0)
        _filter_region(ctx, layer,
                       lambda img, m, luts=luts: adjust.apply_luts(img, luts))


def _op_hue_sat(ctx: Context, value: str) -> None:
    from photoslop import adjust

    h, s, li = _ints(value, 3, "--hue-sat")
    for layer in _target_layers(ctx):
        _filter_region(ctx, layer,
                       lambda img, m: adjust.apply_hsl(img, h, s, li))


def _op_color_balance(ctx: Context, value: str) -> None:
    from photoslop import adjust

    v = _ints(value, 9, "--color-balance")
    values = {"shadows": tuple(v[0:3]), "midtones": tuple(v[3:6]),
              "highlights": tuple(v[6:9])}
    luts = adjust.color_balance_luts(values)
    for layer in _target_layers(ctx):
        _filter_region(ctx, layer,
                       lambda img, m, luts=luts: adjust.apply_luts(img, luts))


def _op_curves(ctx: Context, value: str) -> None:
    from photoslop import adjust

    points = _curve_points(value)
    luts = adjust.curves_luts({"rgb": points})
    for layer in _target_layers(ctx):
        _filter_region(ctx, layer,
                       lambda img, m, luts=luts: adjust.apply_luts(img, luts))


def _op_gaussian_blur(ctx: Context, value: str) -> None:
    from photoslop import npimage

    try:
        radius = int(value)
    except ValueError as exc:
        raise _ValueError(f"--gaussian-blur: {exc}") from exc
    if radius < 1:
        raise _ValueError("--gaussian-blur: radius must be >= 1")
    for layer in _target_layers(ctx):
        _filter_region(ctx, layer,
                       lambda img, m: npimage.gaussian_blur(img, radius, m))


def _op_unsharp(ctx: Context, value: str) -> None:
    from photoslop import npimage

    try:
        amount = int(value)
    except ValueError as exc:
        raise _ValueError(f"--unsharp: {exc}") from exc
    for layer in _target_layers(ctx):
        _filter_region(
            ctx, layer,
            lambda img, m: npimage.unsharp_mask(img, 4, amount / 100.0, m))


def _op_tilt_shift(ctx: Context, value: str) -> None:
    import numpy as np
    from PySide6.QtGui import QImage

    from photoslop import npimage

    centre, band, transition, radius = _ints(value, 4, "--tilt-shift")
    for layer in _target_layers(ctx):
        # weight plane: 1 (sharp) inside the band, ramping to 0 outside
        ys = np.arange(layer.image.height(), dtype=np.float32)
        dist = np.maximum(0.0, np.abs(ys - centre) - band / 2.0)
        blur_w = np.clip(dist / max(1.0, float(transition)), 0.0, 1.0)
        weights = np.repeat(blur_w[:, None].astype(np.float32),
                            layer.image.width(), axis=1)
        before = QImage(layer.image)
        blurred = QImage(before)
        npimage.gaussian_blur(blurred, max(1, radius), None)
        layer.image = blurred
        npimage.blend_by_weights(layer.image, before, weights)


def _op_drop_shadow(ctx: Context, value: str) -> None:
    dx, dy, blur, alpha = _ints(value, 4, "--drop-shadow")
    for layer in _target_layers(ctx):
        layer.effects = [*layer.effects,
                         ("drop-shadow", dx, dy, blur, [0, 0, 0, alpha])]
        layer.fx_cache = None


def _op_glow(ctx: Context, value: str) -> None:
    try:
        size = int(value)
    except ValueError as exc:
        raise _ValueError(f"--glow: {exc}") from exc
    for layer in _target_layers(ctx):
        layer.effects = [*layer.effects,
                         ("glow", size, [255, 220, 120, 200])]
        layer.fx_cache = None


def _op_stroke(ctx: Context, value: str) -> None:
    w, r, g, b = _ints(value, 4, "--stroke")
    for layer in _target_layers(ctx):
        layer.effects = [*layer.effects, ("stroke", w, [r, g, b, 255])]
        layer.fx_cache = None


def _op_fill_opacity(ctx: Context, value: str) -> None:
    try:
        pct = int(value)
    except ValueError as exc:
        raise _ValueError(f"--fill-opacity: {exc}") from exc
    if not 0 <= pct <= 100:
        raise _ValueError("--fill-opacity: expects 0..100")
    for layer in _target_layers(ctx):
        layer.fill_opacity = pct / 100.0
        layer.fx_cache = None


def _op_layer(ctx: Context, value: str) -> None:
    try:
        index = int(value)
    except ValueError as exc:
        raise _ValueError(f"--layer: {exc}") from exc
    if not 0 <= index < len(ctx.doc.layers):
        raise _ValueError(
            f"--layer: index {index} out of range (0..{len(ctx.doc.layers) - 1})")
    ctx.doc.active_index = index
    ctx.all_layers = False


def _op_all_layers(ctx: Context, value: str) -> None:
    ctx.all_layers = True


def _op_select(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainterPath

    x, y, w, h = _ints(value, 4, "--select")
    path = QPainterPath()
    path.addRect(QRectF(x, y, w, h))
    ctx.doc.set_selection(path)


def _op_select_poly(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath, QPolygonF

    points = []
    for chunk in value.replace(";", " ").split():
        x, y = _ints(chunk, 2, "--select-poly point")
        points.append(QPointF(x, y))
    if len(points) < 3:
        raise _ValueError("--select-poly needs at least three X,Y points")
    path = QPainterPath()
    path.addPolygon(QPolygonF(points))
    path.closeSubpath()
    ctx.doc.set_selection(path)


def _op_clear(ctx: Context, value: str) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPainter

    doc = ctx.doc
    if doc.selection is None:
        raise _ValueError("--clear needs a selection earlier in the pipeline")
    for layer in _target_layers(ctx):
        p = QPainter(layer.image)
        p.setClipPath(doc.selection.translated(-layer.offset.x(),
                                               -layer.offset.y()))
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(layer.image.rect(), Qt.GlobalColor.black)
        p.end()
        layer.fx_cache = None


def _op_adjust(ctx: Context, value: str) -> None:
    from photoslop.adjust import AdjustSettings, apply_settings

    values = {}
    for chunk in value.split(","):
        key, sep, num = chunk.partition("=")
        key = key.strip()
        if not sep or key not in AdjustSettings.FIELDS:
            raise _ValueError("--adjust expects KEY=VALUE pairs from: "
                              + ", ".join(AdjustSettings.FIELDS))
        try:
            values[key] = float(num)
        except ValueError as exc:
            raise _ValueError(f"--adjust {key}: {exc}") from exc
    settings = AdjustSettings(**values)
    for layer in _target_layers(ctx):
        _filter_region(ctx, layer,
                       lambda img, m: apply_settings(img, settings))


def _op_select_ellipse(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainterPath

    x, y, w, h = _ints(value, 4, "--select-ellipse")
    if w < 1 or h < 1:
        raise _ValueError("--select-ellipse: width/height must be positive")
    path = QPainterPath()
    path.addEllipse(QRectF(x, y, w, h))
    ctx.doc.set_selection(path)


def _op_deselect(ctx: Context, value: str) -> None:
    ctx.doc.set_selection(None)


def _op_model_url(ctx: Context, value: str) -> None:
    if not value.strip():
        raise _ValueError("--model-url: expects a URL")
    ctx.model_url = value.strip()


def _adapter(ctx: Context):
    from photoslop.modeladapter import HttpModelAdapter

    if not ctx.model_url:
        raise _ValueError("model operations need --model-url first")
    return HttpModelAdapter(ctx.model_url)


def _op_select_subject(ctx: Context, value: str) -> None:
    import numpy as np
    from PySide6.QtGui import QImage

    from photoslop import npimage

    mask_img = _adapter(ctx).select_subject(ctx.doc.flatten())
    gray = mask_img.convertToFormat(QImage.Format.Format_Grayscale8)
    h, w = gray.height(), gray.width()
    buf = np.frombuffer(gray.constBits(), np.uint8,
                        count=h * gray.bytesPerLine())
    mask = buf.reshape(h, gray.bytesPerLine())[:, :w] > 127
    if not mask.any():
        raise RuntimeError("backend found no subject")
    ctx.doc.set_selection(npimage.mask_to_path(mask))


def _op_generative_fill(ctx: Context, value: str) -> None:
    import numpy as np
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QImage, QPainter

    from photoslop import npimage

    doc = ctx.doc
    if doc.selection is None:
        raise _ValueError("--generative-fill needs a selection "
                          "(--select or --select-subject first)")
    sel = npimage.selection_mask(doc.selection, doc.size, QPoint(0, 0))
    mask_img = QImage(doc.size, QImage.Format.Format_Grayscale8)
    mask_img.fill(0)
    buf = np.frombuffer(mask_img.bits(), np.uint8,
                        count=doc.size.height() * mask_img.bytesPerLine())
    view = buf.reshape(doc.size.height(), mask_img.bytesPerLine())
    view[:, : doc.size.width()][sel] = 255
    result = _adapter(ctx).generative_fill(doc.flatten(), mask_img, value)
    if result.size() != doc.size:
        raise RuntimeError("backend returned an image of the wrong size")
    result = result.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    layer = doc.active_layer

    def paste(img: QImage, mask) -> None:
        aligned = QImage(img.size(), QImage.Format.Format_ARGB32_Premultiplied)
        aligned.fill(0)
        p = QPainter(aligned)
        p.drawImage(-QPoint(layer.offset), result)
        p.end()
        src = npimage.view_u32(aligned)
        dst = npimage.view_u32(img)
        if mask is None:
            dst[:] = src
        else:
            dst[mask] = src[mask]

    _filter_region(ctx, layer, paste)


def _op_flip(ctx: Context, value: str) -> None:
    if value not in ("h", "v"):
        raise _ValueError("--flip expects h or v")
    for layer in _target_layers(ctx):
        layer.image = layer.image.mirrored(value == "h", value == "v")
        layer.fx_cache = None


def _op_fill(ctx: Context, value: str) -> None:
    from PySide6.QtGui import QColor, QImage

    r, g, b = _ints(value, 3, "--fill")
    for layer in _target_layers(ctx):
        filled = QImage(layer.image.size(),
                        QImage.Format.Format_ARGB32_Premultiplied)
        filled.fill(QColor(r, g, b))
        layer.image = filled
        layer.fx_cache = None


def _op_text(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QColor, QFont

    from photoslop.textdialog import render_text_layer

    head, sep, body = value.partition(":")
    if not sep or not body.strip():
        raise _ValueError('--text expects "x,y,size[,r,g,b]:the text"')
    if len(head.split(",")) == 6:
        x, y, size, r, g, b = _ints(head, 6, "--text position/colour")
        color = QColor(r, g, b)
    else:
        x, y, size = _ints(head, 3, "--text position")
        color = QColor(0, 0, 0)
    font = QFont()
    font.setPointSize(max(1, size))
    layer = render_text_layer(body, font, color, QPoint(x, y))
    if layer is None:
        raise _ValueError("--text: nothing to render")
    ctx.doc.layers.append(layer)
    ctx.doc.active_index = len(ctx.doc.layers) - 1


def _op_shape(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QPoint, QRectF, QSize
    from PySide6.QtGui import QColor, QPainter

    from photoslop.layer import Layer

    parts = value.split(",")
    if len(parts) != 8:
        raise _ValueError("--shape expects KIND,X,Y,W,H,R,G,B")
    kind = parts[0]
    if kind not in ("rect", "ellipse", "line"):
        raise _ValueError("--shape kind must be rect, ellipse, or line")
    x, y, w, h, r, g, b = _ints(",".join(parts[1:]), 7, "--shape")
    layer = Layer.blank(f"Shape {len(ctx.doc.layers)}", QSize(max(2, w), max(2, h)),
                        QPoint(x, y))
    p = QPainter(layer.image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(r, g, b)
    if kind == "line":
        from PySide6.QtGui import QPen

        p.setPen(QPen(color, 2))
        p.drawLine(0, 0, w - 1, h - 1)
    else:
        p.setPen(QColor(0, 0, 0, 0))
        p.setBrush(color)
        rect = QRectF(0, 0, w, h)
        p.drawEllipse(rect) if kind == "ellipse" else p.drawRect(rect)
    p.end()
    ctx.doc.layers.append(layer)
    ctx.doc.active_index = len(ctx.doc.layers) - 1


def _op_blend_mode(ctx: Context, value: str) -> None:
    from photoslop.layer import BLEND_MODES

    if value not in BLEND_MODES:
        raise _ValueError(
            f"--blend-mode: unknown mode (choose from {sorted(BLEND_MODES)})")
    for layer in _target_layers(ctx):
        layer.blend_mode = value


def _op_layer_opacity(ctx: Context, value: str) -> None:
    try:
        pct = int(value)
    except ValueError as exc:
        raise _ValueError(f"--layer-opacity: {exc}") from exc
    if not 0 <= pct <= 100:
        raise _ValueError("--layer-opacity: expects 0..100")
    for layer in _target_layers(ctx):
        layer.opacity = pct / 100.0


def _op_content_aware_fill(ctx: Context, value: str) -> None:
    from photoslop import npimage

    doc = ctx.doc
    if doc.selection is None:
        raise _ValueError("--content-aware-fill needs a selection first")
    for layer in _target_layers(ctx):
        mask = npimage.selection_mask(doc.selection, layer.image.size(),
                                      layer.offset)
        if not mask.any():
            continue
        from PySide6.QtGui import QImage

        layer.image = QImage(layer.image)
        npimage.inpaint_diffuse(layer.image, mask)


def _op_feather(ctx: Context, value: str) -> None:
    try:
        radius = float(value)
    except ValueError as exc:
        raise _ValueError(f"--feather: {exc}") from exc
    if ctx.doc.selection is None:
        raise _ValueError("--feather needs a selection first")
    if radius < 0:
        raise _ValueError("--feather: radius must be >= 0")
    ctx.doc.selection_feather = radius


def _op_duplicate_layer(ctx: Context, value: str) -> None:
    doc = ctx.doc
    clone = doc.active_layer.clone()
    clone.name = f"{doc.active_layer.name} copy"
    doc.layers.insert(doc.active_index + 1, clone)
    doc.active_index += 1


def _op_flatten(ctx: Context, value: str) -> None:
    from photoslop.document import Document
    from photoslop.layer import Layer

    doc = ctx.doc
    flat = doc.flatten()
    doc.layers[:] = [Layer("Background", flat)]
    doc.active_index = 0
    assert isinstance(doc, Document)


def _op_convert_smart(ctx: Context, value: str) -> None:
    from PySide6.QtGui import QImage

    for layer in _target_layers(ctx):
        layer.source = QImage(layer.image)


def _op_restore_smart(ctx: Context, value: str) -> None:
    from PySide6.QtGui import QImage

    for layer in _target_layers(ctx):
        if layer.source is None:
            raise _ValueError("--restore-smart: layer is not a smart object")
        layer.image = QImage(layer.source)
        layer.fx_cache = None


def _op_add_artboard(ctx: Context, value: str) -> None:
    from PySide6.QtCore import QRect

    parts = value.split(",")
    if len(parts) != 5:
        raise _ValueError("--add-artboard expects NAME,X,Y,W,H")
    x, y, w, h = _ints(",".join(parts[1:]), 4, "--add-artboard")
    name = parts[0].strip() or f"Artboard {len(ctx.doc.artboards) + 1}"
    ctx.doc.artboards.append((name, QRect(x, y, w, h)))


# name -> (metavar, help, apply_fn). Drives argparse AND the test catalog.
OPS: dict = {
    "resize": ("WxH", "rescale the whole image", _op_resize),
    "canvas-size": ("WxH", "grow/shrink the canvas (content centred)",
                    _op_canvas_size),
    "crop": ("X,Y,W,H", "crop the canvas to a rectangle", _op_crop_real),
    "rotate": ("DEG", "rotate the whole image by any angle", _op_rotate),
    "content-aware-scale": ("WxH", "seam-carve the target layer(s)", _op_cas),
    "levels": ("B,W,GAMMA", "levels adjustment", _op_levels),
    "auto-levels": (None, "0.1%-percentile auto levels", _op_auto_levels),
    "hue-sat": ("H,S,L", "hue/saturation/lightness (-180..180,-100..100)",
                _op_hue_sat),
    "color-balance": ("9 INTS", "shadows,midtones,highlights r,g,b each",
                      _op_color_balance),
    "curves": ("X:Y,...", "master curve points in 0..255", _op_curves),
    "adjust": ('"KEY=VAL,..."',
               "Lightroom Basic sliders (temperature, tint, exposure, "
               "contrast, highlights, shadows, whites, blacks, vibrance, "
               "saturation)", _op_adjust),
    "gaussian-blur": ("RADIUS", "gaussian blur (selection-aware)",
                      _op_gaussian_blur),
    "unsharp": ("AMOUNT", "unsharp mask, percent", _op_unsharp),
    "tilt-shift": ("C,B,T,R", "tilt-shift blur: centre,band,transition,radius",
                   _op_tilt_shift),
    "drop-shadow": ("DX,DY,BLUR,ALPHA", "live drop-shadow effect",
                    _op_drop_shadow),
    "glow": ("SIZE", "live outer-glow effect", _op_glow),
    "stroke": ("W,R,G,B", "live stroke effect", _op_stroke),
    "fill-opacity": ("PCT", "fill opacity (effects keep full strength)",
                     _op_fill_opacity),
    "layer": ("N", "target layer index for following ops", _op_layer),
    "all-layers": (None, "apply following ops to every visible layer",
                   _op_all_layers),
    "select": ("X,Y,W,H", "rectangular selection for region-aware ops",
               _op_select),
    "select-ellipse": ("X,Y,W,H", "elliptical selection inscribed in the box",
                       _op_select_ellipse),
    "select-poly": ('"X,Y X,Y X,Y..."',
                    "polygon selection from three or more points",
                    _op_select_poly),
    "deselect": (None, "clear the selection", _op_deselect),
    "clear": (None, "erase the selection to transparency (headless Cut)",
              _op_clear),
    "flip": ("h|v", "mirror the target layer(s)", _op_flip),
    "fill": ("R,G,B", "fill the whole target layer with a colour", _op_fill),
    "text": ('"X,Y,SIZE[,R,G,B]:TEXT"',
             "rasterise text onto a new layer (default colour black)", _op_text),
    "shape": ("KIND,X,Y,W,H,R,G,B", "rect/ellipse/line onto a new layer",
              _op_shape),
    "blend-mode": ("NAME", "set the target layer's blend mode",
                   _op_blend_mode),
    "layer-opacity": ("PCT", "set the target layer's opacity", _op_layer_opacity),
    "content-aware-fill": (None, "diffusion-fill the selection",
                           _op_content_aware_fill),
    "feather": ("RADIUS", "feather the current selection's edge", _op_feather),
    "duplicate-layer": (None, "duplicate the active layer",
                        _op_duplicate_layer),
    "flatten": (None, "collapse all layers into one", _op_flatten),
    "convert-smart": (None, "snapshot target layer(s) as smart objects",
                      _op_convert_smart),
    "restore-smart": (None, "restore smart-object pristine pixels",
                      _op_restore_smart),
    "add-artboard": ("NAME,X,Y,W,H", "register a named export region",
                     _op_add_artboard),
    "model-url": ("URL", "backend for model ops (generic HTTP adapter)",
                  _op_model_url),
    "select-subject": (None, "ask the model backend for a subject selection",
                       _op_select_subject),
    "generative-fill": ("PROMPT", "model-paint the selection from a prompt",
                        _op_generative_fill),
}


class _PipelineAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if not hasattr(namespace, "pipeline") or namespace.pipeline is None:
            namespace.pipeline = []
        namespace.pipeline.append((self.dest.replace("_", "-"),
                                   values if values is not None else ""))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="photoslop-cli",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?",
                        help="input image (PNG/JPG/ORA/camera-raw); "
                             "omit when starting from --new")
    parser.add_argument("--new", metavar="WxH|PRESET",
                        help="start from a blank white document instead of an "
                             "input file: pixel size (800x600) or a paper "
                             "preset (A5, A4, A3, Letter, Legal) at --dpi")
    parser.add_argument("--dpi", type=int, default=72, metavar="N",
                        help="resolution for --new documents and paper "
                             "presets (default 72)")
    parser.add_argument("--output", "-o", metavar="PATH",
                        help=".ora keeps layers; raster extensions flatten")
    parser.add_argument("--export-artboards", metavar="DIR",
                        help="write each artboard as <name>.png into DIR")
    parser.add_argument("--info", action="store_true",
                        help="print document info as JSON")
    from photoslop import __version__

    parser.add_argument("--version", action="version",
                        version=f"photoslop-cli {__version__}")
    for name, (metavar, help_text, _fn) in OPS.items():
        kwargs: dict = {"action": _PipelineAction, "help": help_text}
        if metavar is None:
            kwargs["nargs"] = 0
        else:
            kwargs["metavar"] = metavar
        parser.add_argument(f"--{name}", **kwargs)
    return parser


def _load_document(path: str):
    from photoslop.document import Document
    from photoslop.io_ora import load_ora
    from photoslop.io_raw import is_raw_path, load_raw

    if not os.path.exists(path):
        raise _ValueError(f"input not found: {path}")
    if path.lower().endswith(".ora"):
        return load_ora(path)
    if is_raw_path(path):
        return Document.from_image(load_raw(path),
                                   os.path.basename(path), 72.0)
    from PySide6.QtGui import QImage

    img = QImage(path)
    if img.isNull():
        raise _ValueError(f"could not decode: {path}")
    return Document.from_image(img, os.path.basename(path), 72.0)


def _new_document(spec: str, dpi: int):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor

    from photoslop.document import Document
    from photoslop.units import PAPER_SIZES

    for name, wmm, hmm, _metric, _inches in PAPER_SIZES:
        if spec.lower() == name.lower():
            w = max(1, round(wmm / 25.4 * dpi))
            h = max(1, round(hmm / 25.4 * dpi))
            break
    else:
        try:
            w, h = _size(spec, "--new")
        except _ValueError:
            names = ", ".join(n for n, *_ in PAPER_SIZES)
            raise _ValueError(
                f"--new expects WxH or a preset ({names})") from None
    return Document.new(QSize(w, h), float(dpi), "Untitled",
                        QColor(255, 255, 255))


RASTER_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")


def _write_output(doc, path: str) -> None:
    from photoslop.io_ora import save_ora

    lower = path.lower()
    if lower.endswith(".ora"):
        save_ora(doc, path)
        return
    if not lower.endswith(RASTER_EXTS):
        raise _ValueError(f"unsupported output extension: {path}")
    if not doc.flatten().save(path):
        raise RuntimeError(f"could not write {path}")


def _export_artboards(doc, directory: str) -> list[str]:
    os.makedirs(directory, exist_ok=True)
    flat = doc.flatten()
    written = []
    for name, rect in doc.artboards:
        region = rect.intersected(doc.canvas_rect())
        if region.isEmpty():
            continue
        safe = "".join(c if c.isalnum() or c in "-_ " else "_"
                       for c in name).strip() or "artboard"
        out = os.path.join(directory, f"{safe}.png")
        flat.copy(region).save(out, "PNG")
        written.append(out)
    return written


def _doc_info(doc) -> dict:
    return {
        "size": [doc.size.width(), doc.size.height()],
        "dpi": doc.dpi,
        "layers": [
            {"name": layer.name, "visible": layer.visible,
             "opacity": layer.opacity, "fill_opacity": layer.fill_opacity,
             "blend_mode": layer.blend_mode,
             "offset": [layer.offset.x(), layer.offset.y()],
             "size": [layer.image.width(), layer.image.height()],
             "effects": [list(f) for f in layer.effects],
             "smart_object": layer.source is not None}
            for layer in doc.layers
        ],
        "artboards": [[n, r.x(), r.y(), r.width(), r.height()]
                      for n, r in doc.artboards],
    }


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication

    if QGuiApplication.instance() is None:
        _app = QGuiApplication([])  # noqa: F841 — keeps QImage/QPainter alive

    parser = build_parser()
    args = parser.parse_args(argv)
    pipeline = getattr(args, "pipeline", None) or []
    if args.input and args.new:
        parser.error("give an input file or --new, not both")
    if not args.input and not args.new:
        parser.error("give an input file, or start blank with --new")
    try:
        doc = (_load_document(args.input) if args.input
               else _new_document(args.new, args.dpi))
        ctx = Context(doc=doc)
        for op, value in pipeline:
            OPS[op][2](ctx, value)
        if args.info:
            print(json.dumps(_doc_info(doc), indent=2))
        if args.export_artboards:
            written = _export_artboards(doc, args.export_artboards)
            for path in written:
                print(path)
        if args.output:
            _write_output(doc, args.output)
        if not (args.info or args.export_artboards or args.output):
            parser.error("nothing to do: give --output, --info, "
                         "or --export-artboards")
    except _ValueError as exc:
        parser.exit(2, f"photoslop-cli: error: {exc}\n")
    except Exception as exc:  # engine/backend/IO failures
        return _die(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
