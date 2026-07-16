# SPDX-License-Identifier: Apache-2.0
"""Safe SVG subset interchange for Photoslop's schema-v1 vector model."""

from __future__ import annotations

import base64
import json
import math
import re
import uuid
import xml.etree.ElementTree as ET
from html import escape

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QTextDocument
from PySide6.QtSvg import QSvgRenderer

from photoslop import vector
from photoslop.document import Document
from photoslop.layer import Layer

_NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[Ee][-+]?\d+)?"
_TOKENS = re.compile(rf"[MLCZmlcz]|{_NUMBER}")
_SUPPORTED = {"svg", "g", "defs", "linearGradient", "radialGradient", "stop",
              "rect", "ellipse", "circle", "path", "text", "tspan", "image",
              "filter", "feGaussianBlur", "feOffset", "feFlood", "feComposite",
              "feMorphology", "feBlend", "feMerge", "feMergeNode", "feImage",
              "metadata", "title"}


def _tag(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _color(value: str | None, opacity: str | None = None):
    if not value or value == "none":
        return None
    color = QColor(value)
    if not color.isValid():
        return None
    color.setAlphaF(float(opacity or 1))
    return [color.red(), color.green(), color.blue(), color.alpha()]


def _commands(source: str) -> list[dict]:
    tokens = _TOKENS.findall(source.replace(",", " "))
    commands, index, op = [], 0, None
    cursor = [0.0, 0.0]
    sizes = {"M": 2, "L": 2, "C": 6, "Z": 0}
    while index < len(tokens):
        if tokens[index].isalpha():
            op = tokens[index]
            index += 1
        if op is None or op.upper() not in sizes:
            raise ValueError("unsupported SVG path command")
        upper, relative = op.upper(), op.islower()
        if upper == "Z":
            commands.append({"op": "Z"})
            op = None
            continue
        count = sizes[upper]
        values = [float(value) for value in tokens[index:index + count]]
        if len(values) != count:
            raise ValueError("incomplete SVG path command")
        index += count
        points = [values[i:i + 2] for i in range(0, count, 2)]
        if relative:
            points = [[x + cursor[0], y + cursor[1]] for x, y in points]
        cursor = points[-1]
        if upper in {"M", "L"}:
            commands.append({"op": upper, "p": cursor, "node": "corner"})
            if upper == "M":
                op = "l" if relative else "L"
        else:
            commands.append({"op": "C", "c1": points[0], "c2": points[1],
                             "p": points[2], "node": "smooth"})
    return commands


def _style(element, gradients: dict) -> dict:
    values = dict(item.split(":", 1) for item in element.get("style", "").split(";")
                  if ":" in item)
    values.update(element.attrib)

    def paint(name):
        raw = values.get(name)
        match = re.fullmatch(r"url\(#(.+)\)", raw or "")
        if match:
            return gradients.get(match.group(1))
        color = _color(raw, values.get(f"{name}-opacity"))
        return {"type": "solid", "color": color} if color else None

    return {"fill": paint("fill"), "stroke": paint("stroke"),
            "stroke_width": float(values.get("stroke-width", 1)),
            "cap": values.get("stroke-linecap", "round"),
            "join": values.get("stroke-linejoin", "round"),
            "miter_limit": float(values.get("stroke-miterlimit", 4)),
            "dash": [float(value) for value in
                     re.findall(_NUMBER, values.get("stroke-dasharray", ""))],
            "dash_offset": float(values.get("stroke-dashoffset", 0)),
            "fill_rule": values.get("fill-rule", "winding")}


def _gradient(element) -> dict:
    kind = _tag(element)
    paint = {"type": "linear-gradient" if kind == "linearGradient"
             else "radial-gradient", "stops": []}
    if kind == "linearGradient":
        paint.update(start=[float(element.get("x1", 0)), float(element.get("y1", 0))],
                     end=[float(element.get("x2", 1)), float(element.get("y2", 0))])
    else:
        paint.update(center=[float(element.get("cx", 0.5)), float(element.get("cy", 0.5))],
                     radius=float(element.get("r", 0.5)))
    for stop in element:
        if _tag(stop) != "stop":
            continue
        style = dict(item.split(":", 1) for item in stop.get("style", "").split(";")
                     if ":" in item)
        color = _color(stop.get("stop-color", style.get("stop-color", "black")),
                       stop.get("stop-opacity", style.get("stop-opacity")))
        offset = stop.get("offset", "0").rstrip("%")
        value = float(offset) / (100 if "%" in stop.get("offset", "") else 1)
        paint["stops"].append([value, color])
    return paint


def _transform(value: str | None) -> list[float]:
    if not value:
        return [1, 0, 0, 1, 0, 0]
    match = re.fullmatch(r"\s*matrix\(([^)]+)\)\s*", value)
    numbers = [float(item) for item in re.findall(_NUMBER, match.group(1))] if match else []
    return numbers if len(numbers) == 6 else [1, 0, 0, 1, 0, 0]


def load_svg(path: str) -> Document:
    with open(path, "rb") as handle:
        source = handle.read()
    root = ET.fromstring(source)
    view = [float(value) for value in root.get("viewBox", "").split()]
    width = int(round(view[2] if len(view) == 4 else float(root.get("width", 800))))
    height = int(round(view[3] if len(view) == 4 else float(root.get("height", 600))))
    doc = Document(QSize(max(1, width), max(1, height)), 72, path)
    gradients = {element.get("id"): _gradient(element) for element in root.iter()
                 if _tag(element) in {"linearGradient", "radialGradient"}
                 and element.get("id")}
    unsupported = sorted({_tag(element) for element in root.iter()
                          if _tag(element) not in _SUPPORTED})
    for element in root.iter():
        tag = _tag(element)
        geometry = None
        if tag == "image":
            href = (element.get("href")
                    or element.get("{http://www.w3.org/1999/xlink}href", ""))
            prefix = "data:image/png;base64,"
            if href.startswith(prefix):
                image = QImage.fromData(base64.b64decode(href[len(prefix):]))
                if not image.isNull():
                    layer = Layer(
                        element.get("id", "SVG image"), image,
                        QPoint(round(float(element.get("x", 0))),
                               round(float(element.get("y", 0)))))
                    layer.visible = "display:none" not in element.get("style", "")
                    doc.layers.append(layer)
                    continue
            unsupported.append("image")
            continue
        if tag == "rect":
            x, y = float(element.get("x", 0)), float(element.get("y", 0))
            geometry = {"kind": "rect", "rect": [x, y, x + float(element.get("width", 0)),
                                                     y + float(element.get("height", 0))]}
        elif tag in {"ellipse", "circle"}:
            cx, cy = float(element.get("cx", 0)), float(element.get("cy", 0))
            rx = float(element.get("rx", element.get("r", 0)))
            ry = float(element.get("ry", element.get("r", 0)))
            geometry = {"kind": "ellipse", "rect": [cx - rx, cy - ry, cx + rx, cy + ry]}
        elif tag == "path":
            try:
                geometry = {"kind": "path", "commands": _commands(element.get("d", ""))}
            except ValueError:
                unsupported.append("path-command")
        elif tag == "text":
            x, y = float(element.get("x", 0)), float(element.get("y", 0))
            geometry = {"kind": "rect", "rect": [x, y, x + max(1, width - x), y + 40]}
        if geometry is None:
            continue
        data = vector.migrate_vector({"schema_version": 1,
                                      "id": element.get("id") or uuid.uuid4().hex,
                                      "name": element.get("data-name", element.get("id", tag)),
                                      "type": "text" if tag == "text" else "shape",
                                      "geometry": geometry,
                                      "transform": _transform(element.get("transform")),
                                      "appearance": _style(element, gradients),
                                      "opacity": float(element.get("opacity", 1)),
                                      "blend_mode": "normal", "parent_id": None,
                                      "extensions": {},
                                      "text": ({"content": "".join(element.itertext())}
                                               if tag == "text" else None)})
        layer = vector.render_vector(data, data["name"], doc.canvas_rect())
        if layer is not None:
            doc.layers.append(layer)
    metadata = next((element for element in root.iter()
                     if _tag(element) == "metadata" and element.get("id") == "photoslop"), None)
    if metadata is not None and metadata.text:
        payload = json.loads(metadata.text)
        doc.artboards = [(name, QRect(x, y, w, h))
                         for name, x, y, w, h in payload.get("artboards", [])]
        appearances = payload.get("appearances", {})
        text_layers = payload.get("text_layers", {})
        from photoslop.appearance import normalize_effects

        for layer in doc.layers:
            object_id = (layer.vector_data or {}).get("id") or layer.name
            if object_id in appearances:
                layer.effects = normalize_effects(appearances[object_id])
            if object_id in text_layers:
                stored = text_layers[object_id]
                data = stored.get("data", stored)
                offset = stored.get("offset", [layer.offset.x(), layer.offset.y()])
                document = QTextDocument()
                if data.get("html"):
                    document.setHtml(data["html"])
                else:
                    document.setPlainText(str(data.get("text", "")))
                from photoslop.textdialog import render_text_document

                rendered = render_text_document(document, QPoint(*offset))
                if rendered is not None:
                    layer.image = rendered.image
                    layer.offset = rendered.offset
                    layer.text_data = data
                    layer.vector_data = None
    doc.import_warnings = sorted(set(unsupported))
    if unsupported:
        fallback = QImage(doc.size, QImage.Format.Format_ARGB32_Premultiplied)
        fallback.fill(QColor(0, 0, 0, 0))
        renderer = QSvgRenderer(QByteArray(source))
        painter = QPainter(fallback)
        renderer.render(painter)
        painter.end()
        layer = Layer("SVG raster fallback (unsupported content)", fallback)
        layer.visible = False
        doc.layers.insert(0, layer)
    doc.active_index = max(0, len(doc.layers) - 1)
    return doc


def _paint(paint: dict | None, ids: dict, definitions: list[str]) -> str:
    if not paint:
        return "none"
    if paint.get("type") == "solid":
        return QColor(*paint["color"]).name(QColor.NameFormat.HexArgb)
    key = json.dumps(paint, sort_keys=True)
    if key not in ids:
        gradient_id = f"gradient-{len(ids) + 1}"
        ids[key] = gradient_id
        radial = paint["type"] == "radial-gradient"
        attrs = (f'cx="{paint["center"][0]}" cy="{paint["center"][1]}" r="{paint["radius"]}"'
                 if radial else f'x1="{paint["start"][0]}" y1="{paint["start"][1]}" '
                 f'x2="{paint["end"][0]}" y2="{paint["end"][1]}"')
        stops = "".join(
            f'<stop offset="{offset}" '
            f'stop-color="{QColor(*color).name(QColor.NameFormat.HexArgb)}"/>'
            for offset, color in paint.get("stops", []))
        tag = "radialGradient" if radial else "linearGradient"
        definitions.append(f'<{tag} id="{gradient_id}" {attrs}>{stops}</{tag}>')
    return f'url(#{ids[key]})'


def _svg_color(value) -> tuple[str, float]:
    color = QColor(*value)
    return color.name(), color.alphaF()


def _filter_definition(filter_id: str, effects: list[dict], margin: int,
                       bounds: QRect) -> str:
    """Translate the native effect stack to a portable SVG filter chain."""
    from photoslop.appearance import normalize_effects

    primitives = []
    current = "SourceGraphic"
    counter = 0

    def name(prefix: str) -> str:
        nonlocal counter
        counter += 1
        return f"{prefix}{counter}"

    for effect in normalize_effects(effects):
        if not effect["enabled"]:
            continue
        kind, p = effect["type"], effect["parameters"]
        opacity = float(effect["opacity"])
        result = name("effect")
        if kind == "drop-shadow":
            color, alpha = _svg_color(p["color"])
            primitives.append(
                f'<feGaussianBlur in="SourceAlpha" stdDeviation="{p["blur"] / 2}" '
                f'result="blur{counter}"/><feOffset in="blur{counter}" '
                f'dx="{p["offset_x"]}" dy="{p["offset_y"]}" result="off{counter}"/>'
                f'<feFlood flood-color="{color}" flood-opacity="{alpha * opacity}" '
                f'result="color{counter}"/><feComposite in="color{counter}" '
                f'in2="off{counter}" operator="in" result="shadow{counter}"/>'
                f'<feMerge result="{result}"><feMergeNode in="shadow{counter}"/>'
                f'<feMergeNode in="{current}"/></feMerge>')
        elif kind == "outer-glow":
            color, alpha = _svg_color(p["color"])
            primitives.append(
                f'<feMorphology in="SourceAlpha" operator="dilate" radius="{p["spread"]}" '
                f'result="grown{counter}"/><feGaussianBlur in="grown{counter}" '
                f'stdDeviation="{p["size"] / 2}" result="blur{counter}"/>'
                f'<feFlood flood-color="{color}" flood-opacity="{alpha * opacity}" '
                f'result="color{counter}"/><feComposite in="color{counter}" '
                f'in2="blur{counter}" operator="in" result="glow{counter}"/>'
                f'<feMerge result="{result}"><feMergeNode in="glow{counter}"/>'
                f'<feMergeNode in="{current}"/></feMerge>')
        elif kind == "outline":
            color, alpha = _svg_color(p["color"])
            position = p["position"]
            radius = p["width"] / 2 if position == "center" else p["width"]
            if position == "inside":
                morphology = (f'<feMorphology in="SourceAlpha" operator="erode" '
                              f'radius="{radius}" result="morph{counter}"/>'
                              f'<feComposite in="SourceAlpha" in2="morph{counter}" '
                              f'operator="out" result="edge{counter}"/>')
            elif position == "center":
                morphology = (f'<feMorphology in="SourceAlpha" operator="dilate" '
                              f'radius="{radius}" result="outer{counter}"/>'
                              f'<feMorphology in="SourceAlpha" operator="erode" '
                              f'radius="{radius}" result="inner{counter}"/>'
                              f'<feComposite in="outer{counter}" in2="inner{counter}" '
                              f'operator="out" result="edge{counter}"/>')
            else:
                morphology = (f'<feMorphology in="SourceAlpha" operator="dilate" '
                              f'radius="{radius}" result="morph{counter}"/>'
                              f'<feComposite in="morph{counter}" in2="SourceAlpha" '
                              f'operator="out" result="edge{counter}"/>')
            primitives.append(
                f'{morphology}<feFlood flood-color="{color}" '
                f'flood-opacity="{alpha * opacity}" result="color{counter}"/>'
                f'<feComposite in="color{counter}" in2="edge{counter}" operator="in" '
                f'result="line{counter}"/><feMerge result="{result}">'
                f'<feMergeNode in="line{counter}"/><feMergeNode in="{current}"/></feMerge>')
        elif kind in {"color-overlay", "gradient-overlay"}:
            if kind == "color-overlay":
                color, alpha = _svg_color(p["color"])
                paint = (f'<feFlood flood-color="{color}" '
                         f'flood-opacity="{alpha * opacity}" result="color{counter}"/>')
                paint_input = f"color{counter}"
            else:
                color1, alpha1 = _svg_color(p["color1"])
                color2, alpha2 = _svg_color(p["color2"])
                angle = math.radians(float(p["angle"]) - 90)
                x1, y1 = 50 - 50 * math.cos(angle), 50 - 50 * math.sin(angle)
                x2, y2 = 50 + 50 * math.cos(angle), 50 + 50 * math.sin(angle)
                gradient_svg = (
                    f'<svg xmlns="http://www.w3.org/2000/svg" width="{bounds.width()}" '
                    f'height="{bounds.height()}"><defs><linearGradient id="g" '
                    f'x1="{x1}%" y1="{y1}%" x2="{x2}%" y2="{y2}%">'
                    f'<stop offset="0" stop-color="{color1}" stop-opacity="{alpha1}"/>'
                    f'<stop offset="1" stop-color="{color2}" stop-opacity="{alpha2}"/>'
                    f'</linearGradient></defs><rect width="100%" height="100%" '
                    f'fill="url(#g)"/></svg>')
                encoded = base64.b64encode(gradient_svg.encode()).decode("ascii")
                paint = (f'<feImage href="data:image/svg+xml;base64,{encoded}" '
                         f'x="{bounds.x()}" y="{bounds.y()}" width="{bounds.width()}" '
                         f'height="{bounds.height()}" preserveAspectRatio="none" '
                         f'result="gradient{counter}"/>')
                paint_input = f"gradient{counter}"
            primitives.append(
                f'{paint}<feComposite in="{paint_input}" in2="SourceAlpha" operator="in" '
                f'result="paint{counter}"/><feBlend in="{current}" in2="paint{counter}" '
                f'mode="{effect["blend_mode"]}" result="{result}"/>')
        elif kind in {"gaussian-blur", "feather"}:
            primitives.append(
                f'<feGaussianBlur in="{current}" stdDeviation="{p["radius"] / 2}" '
                f'result="{result}"/>')
        elif kind in {"inner-shadow", "inner-glow", "bevel-emboss"}:
            value = p.get("color", p.get("shadow_color", [0, 0, 0, 160]))
            color, alpha = _svg_color(value)
            radius = p.get("blur", p.get("size", p.get("soften", 2)))
            primitives.append(
                f'<feGaussianBlur in="SourceAlpha" stdDeviation="{float(radius) / 2}" '
                f'result="inner{counter}"/><feFlood flood-color="{color}" '
                f'flood-opacity="{alpha * opacity}" result="color{counter}"/>'
                f'<feComposite in="color{counter}" in2="inner{counter}" operator="in" '
                f'result="shade{counter}"/><feBlend in="{current}" in2="shade{counter}" '
                f'mode="multiply" result="{result}"/>')
        else:
            continue
        current = result
    size = max(1, margin)
    return (f'<filter id="{filter_id}" x="{bounds.x() - size}" '
            f'y="{bounds.y() - size}" width="{bounds.width() + size * 2}" '
            f'height="{bounds.height() + size * 2}" '
            f'filterUnits="userSpaceOnUse">{"".join(primitives)}</filter>')


def _png_data(img: QImage) -> str:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buffer, "PNG")
    buffer.close()
    return base64.b64encode(bytes(buffer.data())).decode("ascii")


def _text_spans(layer, object_id: str) -> str:
    data = layer.text_data or {}
    document = QTextDocument()
    if data.get("html"):
        document.setHtml(data["html"])
    else:
        document.setPlainText(str(data.get("text", "")))
        font = document.defaultFont()
        font.setFamily(str(data.get("family", font.family())))
        font.setPointSizeF(float(data.get("size", 12)))
        document.setDefaultFont(font)
    x = layer.offset.x() + 2
    y = layer.offset.y() + max(1, float(data.get("size", document.defaultFont().pointSizeF())))
    pieces = []
    line = 0
    block = document.begin()
    while block.isValid():
        iterator = block.begin()
        first = True
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid():
                fmt, font = fragment.charFormat(), fragment.charFormat().font()
                color = fmt.foreground().color()
                attrs = [f'font-family="{escape(font.family())}"',
                         f'font-size="{font.pointSizeF() or data.get("size", 12)}pt"']
                if font.bold():
                    attrs.append('font-weight="bold"')
                if font.italic():
                    attrs.append('font-style="italic"')
                if color.isValid():
                    attrs.append(f'fill="{color.name(QColor.NameFormat.HexArgb)}"')
                position = (f'x="{x}" dy="{0 if line == 0 else font.pointSizeF() * 1.2}"'
                            if first else "")
                pieces.append(f'<tspan {position} {" ".join(attrs)}>'
                              f'{escape(fragment.text())}</tspan>')
                first = False
            iterator += 1
        line += 1
        block = block.next()
    return f'<text id="{object_id}" x="{x}" y="{y}">{"".join(pieces)}</text>'


def save_svg(doc: Document, path: str) -> None:
    from photoslop.appearance import effect_margin, normalize_effects

    definitions, gradient_ids, objects = [], {}, []
    appearances, text_layers = {}, {}
    for index, layer in enumerate(doc.layers):
        object_id = ((layer.vector_data or {}).get("id") or f"layer-{index + 1}")
        effects = normalize_effects(layer.effects)
        filter_attr = ""
        if effects:
            filter_id = f"appearance-{index + 1}"
            definitions.append(_filter_definition(
                filter_id, effects, effect_margin(effects), layer.bounds()))
            filter_attr = f' filter="url(#{filter_id})"'
            appearances[object_id] = effects
        visibility = "" if layer.visible else ' style="display:none"'
        if layer.text_data is not None:
            text = _text_spans(layer, object_id)
            text = text.replace(">", f'{filter_attr}{visibility}>', 1)
            objects.append(text)
            text_layers[object_id] = {
                "data": layer.text_data,
                "offset": [layer.offset.x(), layer.offset.y()],
            }
            continue
        if layer.vector_data is None:
            objects.append(
                f'<image id="{object_id}" x="{layer.offset.x()}" y="{layer.offset.y()}" '
                f'width="{layer.image.width()}" height="{layer.image.height()}" '
                f'href="data:image/png;base64,{_png_data(layer.image)}"'
                f'{filter_attr}{visibility}/>')
            continue
        data = vector.migrate_vector(layer.vector_data)
        geometry, appearance = data["geometry"], data["appearance"]
        style = (f'fill="{_paint(appearance.get("fill"), gradient_ids, definitions)}" '
                 f'stroke="{_paint(appearance.get("stroke"), gradient_ids, definitions)}" '
                 f'stroke-width="{appearance.get("stroke_width", 1)}" '
                 f'stroke-linecap="{appearance.get("cap", "round")}" '
                 f'stroke-linejoin="{appearance.get("join", "round")}"')
        transform = data.get("transform", [1, 0, 0, 1, 0, 0])
        common = (f'id="{escape(data["id"])}" data-name="{escape(data["name"])}" '
                  f'transform="matrix({" ".join(map(str, transform))})" {style}'
                  f'{filter_attr}{visibility}')
        if data.get("type") == "text" and data.get("text"):
            rect = geometry["rect"]
            content = escape(str(data["text"].get("content", "")))
            obj = f'<text x="{rect[0]}" y="{rect[1]}" {common}>{content}</text>'
        elif geometry["kind"] == "rect":
            x1, y1, x2, y2 = geometry["rect"]
            obj = f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" {common}/>'
        elif geometry["kind"] == "ellipse":
            x1, y1, x2, y2 = geometry["rect"]
            obj = (f'<ellipse cx="{(x1+x2)/2}" cy="{(y1+y2)/2}" '
                   f'rx="{(x2-x1)/2}" ry="{(y2-y1)/2}" {common}/>')
        else:
            parts = []
            for command in geometry.get("commands", []):
                op = command["op"]
                if op in {"M", "L"}:
                    parts.append(f'{op} {command["p"][0]} {command["p"][1]}')
                elif op == "C":
                    parts.append(
                        f'C {command["c1"][0]} {command["c1"][1]} '
                        f'{command["c2"][0]} {command["c2"][1]} '
                        f'{command["p"][0]} {command["p"][1]}')
                else:
                    parts.append("Z")
            obj = f'<path d="{" ".join(parts)}" {common}/>'
        objects.append(obj)
    boards = [[name, rect.x(), rect.y(), rect.width(), rect.height()]
              for name, rect in doc.artboards]
    metadata = escape(json.dumps({"artboards": boards, "appearances": appearances,
                                  "text_layers": text_layers}, separators=(",", ":")))
    source = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{doc.size.width()}" '
              f'height="{doc.size.height()}" viewBox="0 0 {doc.size.width()} {doc.size.height()}">'
              f'<metadata id="photoslop">{metadata}</metadata><defs>{"".join(definitions)}</defs>'
              f'{"".join(objects)}</svg>')
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
