# SPDX-License-Identifier: Apache-2.0
"""Safe SVG subset interchange for Photoslop's schema-v1 vector model."""

from __future__ import annotations

import json
import re
import uuid
import xml.etree.ElementTree as ET
from html import escape

from PySide6.QtCore import QByteArray, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

from photoslop import vector
from photoslop.document import Document
from photoslop.layer import Layer

_NUMBER = r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[Ee][-+]?\d+)?"
_TOKENS = re.compile(rf"[MLCZmlcz]|{_NUMBER}")
_SUPPORTED = {"svg", "g", "defs", "linearGradient", "radialGradient", "stop",
              "rect", "ellipse", "circle", "path", "text", "metadata", "title"}


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


def save_svg(doc: Document, path: str) -> None:
    definitions, gradient_ids, objects = [], {}, []
    for layer in doc.layers:
        if layer.vector_data is None:
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
                  f'transform="matrix({" ".join(map(str, transform))})" {style}')
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
    metadata = escape(json.dumps({"artboards": boards}))
    source = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{doc.size.width()}" '
              f'height="{doc.size.height()}" viewBox="0 0 {doc.size.width()} {doc.size.height()}">'
              f'<metadata id="photoslop">{metadata}</metadata><defs>{"".join(definitions)}</defs>'
              f'{"".join(objects)}</svg>')
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(source)
