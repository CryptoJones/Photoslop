# SPDX-License-Identifier: Apache-2.0
"""Parametric vector layers (#110) — the text_data pattern applied to
Shape and Pen. A vector layer keeps `vector_data`: JSON-able geometry in
DOCUMENT coordinates plus style, and the raster content is always
reproducible from it. Re-editing, document transforms, and ORA round-trips
all work from the parameters; the resident cost is a few dozen floats.

Kinds:
  {"kind": "rect"|"ellipse", "x1","y1","x2","y2", "color": [r,g,b,a]}
  {"kind": "line", "x1","y1","x2","y2", "width": w, "color": [r,g,b,a]}
  {"kind": "path", "points": [[x,y],...], "close": bool, "fill": bool,
   "width": w, "color": [r,g,b,a]}"""

from __future__ import annotations

import copy
import uuid

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QTransform,
)

from photoslop.layer import Layer

HANDLE_RADIUS = 10.0  # doc-space pixels for grabbing a handle
SCHEMA_VERSION = 1

_LEGACY_KEYS = {
    "kind", "x1", "y1", "x2", "y2", "points", "close", "fill", "width", "color"
}


def _path_commands(pts: list[QPointF], close: bool) -> list[dict]:
    commands = [{"op": "M", "p": [pts[0].x(), pts[0].y()], "node": "smooth"}]
    if len(pts) < 2:
        return commands
    if len(pts) == 2:
        commands.append({"op": "L", "p": [pts[1].x(), pts[1].y()], "node": "corner"})
    else:
        ring = ([pts[-1], *pts, pts[0], pts[1]] if close
                else [pts[0], *pts, pts[-1]])
        for i in range(1, len(ring) - 2):
            p0, p1, p2, p3 = ring[i - 1], ring[i], ring[i + 1], ring[i + 2]
            c1 = [p1.x() + (p2.x() - p0.x()) / 6,
                  p1.y() + (p2.y() - p0.y()) / 6]
            c2 = [p2.x() - (p3.x() - p1.x()) / 6,
                  p2.y() - (p3.y() - p1.y()) / 6]
            commands.append({"op": "C", "c1": c1, "c2": c2,
                             "p": [p2.x(), p2.y()], "node": "smooth"})
    if close:
        commands.append({"op": "Z"})
    return commands


def migrate_vector(data: dict) -> dict:
    """Return schema-v1 data; legacy fields stay as a compatibility projection."""
    source = copy.deepcopy(data)
    if "kind" not in source and source.get("schema_version") == SCHEMA_VERSION:
        return source
    kind = source.get("kind", "path")
    rgba = [int(value) for value in source.get("color", [0, 0, 0, 255])]
    width = max(1.0, float(source.get("width", 3)))
    fill_enabled = kind in {"rect", "ellipse"} or bool(source.get("fill", False))
    stroke_enabled = kind == "line" or (kind == "path" and not fill_enabled)
    if kind == "path":
        pts = [QPointF(float(x), float(y)) for x, y in source.get("points", [])]
        geometry = {"kind": "path", "commands": _path_commands(
            pts, bool(source.get("close", fill_enabled)))} if pts else {
                "kind": "path", "commands": []}
    elif kind in {"rect", "ellipse"}:
        geometry = {"kind": kind, "rect": [float(source["x1"]), float(source["y1"]),
                                               float(source["x2"]), float(source["y2"])]}
    else:
        geometry = {"kind": "path", "commands": [
            {"op": "M", "p": [float(source["x1"]), float(source["y1"])],
             "node": "corner"},
            {"op": "L", "p": [float(source["x2"]), float(source["y2"])],
             "node": "corner"},
        ]}
    known_schema = {"schema_version", "id", "name", "type", "parent_id", "geometry",
                    "transform", "appearance", "opacity", "blend_mode", "text",
                    "extensions"}
    unknown = {key: copy.deepcopy(value) for key, value in source.items()
               if key not in _LEGACY_KEYS and key not in known_schema}
    extensions = copy.deepcopy(source.get("extensions", {}))
    extensions.update(unknown)
    migrated = {
        **{key: copy.deepcopy(value) for key, value in source.items() if key in _LEGACY_KEYS},
        "schema_version": SCHEMA_VERSION,
        "id": source.get("id", uuid.uuid4().hex),
        "name": source.get("name", kind.title()),
        "type": source.get("type", "path" if kind in {"line", "path"} else "shape"),
        "parent_id": source.get("parent_id"),
        "geometry": geometry,
        "transform": copy.deepcopy(source.get("transform", [1, 0, 0, 1, 0, 0])),
        "appearance": {
            "fill": copy.deepcopy(source.get("appearance", {}).get(
                "fill", {"type": "solid", "color": rgba} if fill_enabled else None)),
            "fill_rule": source.get("appearance", {}).get("fill_rule", "winding"),
            "stroke": copy.deepcopy(source.get("appearance", {}).get(
                "stroke", {"type": "solid", "color": rgba} if stroke_enabled else None)),
            "stroke_width": source.get("appearance", {}).get("stroke_width", width),
            "cap": source.get("appearance", {}).get("cap", "round"),
            "join": source.get("appearance", {}).get("join", "round"),
            "miter_limit": source.get("appearance", {}).get("miter_limit", 4.0),
            "dash": copy.deepcopy(source.get("appearance", {}).get("dash", [])),
            "dash_offset": source.get("appearance", {}).get("dash_offset", 0.0),
            "scale_stroke": source.get("appearance", {}).get("scale_stroke", True),
        },
        "opacity": float(source.get("opacity", 1.0)),
        "blend_mode": source.get("blend_mode", "normal"),
        "text": copy.deepcopy(source.get("text")),
        "extensions": extensions,
    }
    return migrated


def path_from_commands(commands: list[dict]) -> QPainterPath:
    path = QPainterPath()
    for command in commands:
        op = command.get("op")
        if op == "M":
            path.moveTo(*command["p"])
        elif op == "L":
            path.lineTo(*command["p"])
        elif op == "C":
            path.cubicTo(*command["c1"], *command["c2"], *command["p"])
        elif op == "Z":
            path.closeSubpath()
    return path


def native_path(data: dict) -> QPainterPath:
    data = migrate_vector(data)
    geometry = data["geometry"]
    if geometry["kind"] == "path":
        path = path_from_commands(geometry.get("commands", []))
    else:
        x1, y1, x2, y2 = geometry["rect"]
        rect = QRectF(QPointF(x1, y1), QPointF(x2, y2)).normalized()
        path = QPainterPath()
        (path.addEllipse if geometry["kind"] == "ellipse" else path.addRect)(rect)
    a, b, c, d, tx, ty = data.get("transform", [1, 0, 0, 1, 0, 0])
    return QTransform(a, b, c, d, tx, ty).map(path)


def draw_native(painter: QPainter, data: dict) -> None:
    data = migrate_vector(data)
    appearance = data["appearance"]
    path = native_path(data)
    painter.save()
    painter.setOpacity(painter.opacity() * data.get("opacity", 1.0))
    fill = appearance.get("fill")
    painter.setBrush(_paint_brush(fill, path.boundingRect()))
    stroke = appearance.get("stroke")
    if stroke:
        pen = QPen(_paint_brush(stroke, path.boundingRect()),
                   float(appearance.get("stroke_width", 1)))
        pen.setCapStyle({"flat": Qt.PenCapStyle.FlatCap,
                         "square": Qt.PenCapStyle.SquareCap}.get(
                             appearance.get("cap"), Qt.PenCapStyle.RoundCap))
        pen.setJoinStyle({"miter": Qt.PenJoinStyle.MiterJoin,
                          "bevel": Qt.PenJoinStyle.BevelJoin}.get(
                              appearance.get("join"), Qt.PenJoinStyle.RoundJoin))
        pen.setMiterLimit(float(appearance.get("miter_limit", 4)))
        if appearance.get("dash"):
            pen.setDashPattern([float(value) for value in appearance["dash"]])
            pen.setDashOffset(float(appearance.get("dash_offset", 0)))
        painter.setPen(pen)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
    path.setFillRule(Qt.FillRule.OddEvenFill if appearance.get("fill_rule") == "evenodd"
                     else Qt.FillRule.WindingFill)
    if data.get("type") == "text" and data.get("text"):
        painter.drawText(path.boundingRect(), int(Qt.AlignmentFlag.AlignLeft |
                         Qt.AlignmentFlag.AlignTop), str(data["text"].get("content", "")))
    else:
        painter.drawPath(path)
    painter.restore()


def _paint_brush(paint: dict | None, bounds: QRectF) -> QBrush:
    if not paint:
        return QBrush(Qt.BrushStyle.NoBrush)
    if paint.get("type") == "solid":
        return QBrush(QColor(*paint["color"]))
    if paint.get("type") == "linear-gradient":
        start = paint.get("start", [bounds.left(), bounds.top()])
        end = paint.get("end", [bounds.right(), bounds.top()])
        gradient = QLinearGradient(*start, *end)
    elif paint.get("type") == "radial-gradient":
        center = paint.get("center", [bounds.center().x(), bounds.center().y()])
        gradient = QRadialGradient(*center, float(paint.get("radius", bounds.width() / 2)))
    else:
        return QBrush(Qt.BrushStyle.NoBrush)
    for offset, color in paint.get("stops", []):
        gradient.setColorAt(float(offset), QColor(*color))
    return QBrush(gradient)


def smooth_path(pts: list[QPointF], close: bool) -> QPainterPath:
    """Catmull-Rom through the anchors, converted to cubic Beziers.
    (Single source of truth — PenTool delegates here.)"""
    path = QPainterPath(pts[0])
    if len(pts) == 2:
        path.lineTo(pts[1])
        return path
    ring = ([pts[-1], *pts, pts[0], pts[1]] if close
            else [pts[0], *pts, pts[-1]])
    for i in range(1, len(ring) - 2):
        p0, p1, p2, p3 = ring[i - 1], ring[i], ring[i + 1], ring[i + 2]
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                     p1.y() + (p2.y() - p0.y()) / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                     p2.y() - (p3.y() - p1.y()) / 6.0)
        path.cubicTo(c1, c2, p2)
    if close:
        path.closeSubpath()
    return path


def _color(data: dict) -> QColor:
    r, g, b, *a = data.get("color", [0, 0, 0, 255])
    return QColor(int(r), int(g), int(b), int(a[0]) if a else 255)


def render_vector(data: dict, name: str, canvas_rect: QRect) -> Layer | None:
    """Rasterize vector_data into a bounded Layer (None if degenerate)."""
    data = migrate_vector(data)
    path = native_path(data)
    if path.isEmpty():
        return None
    raw = path.boundingRect()
    appearance = data["appearance"]
    width = max(1, int(float(appearance.get("stroke_width", 1))))
    margin = max(2, width) if appearance.get("stroke") else 2
    bounds = (raw.toAlignedRect()
              .adjusted(-margin, -margin, margin, margin)
              .intersected(canvas_rect.adjusted(-margin, -margin,
                                                margin, margin)))
    if bounds.width() < 2 or bounds.height() < 2:
        return None
    layer = Layer.blank(name, bounds.size(), bounds.topLeft())
    p = QPainter(layer.image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.translate(-bounds.topLeft())
    draw_native(p, data)
    p.end()
    layer.vector_data = copy.deepcopy(data)
    return layer


def rerender_into(layer, data: dict, canvas_rect: QRect) -> bool:
    """Replace a layer's raster content from (possibly new) vector_data."""
    fresh = render_vector(data, layer.name, canvas_rect)
    if fresh is None:
        return False
    layer.image = fresh.image
    layer.offset = fresh.offset
    layer.vector_data = copy.deepcopy(migrate_vector(data))
    layer.fx_cache = None
    return True


def _map_points(data: dict, fn) -> dict:
    out = dict(data)
    if data.get("kind") == "path":
        out["points"] = [list(fn(float(x), float(y)))
                         for x, y in data["points"]]
    else:
        x1, y1 = fn(float(data["x1"]), float(data["y1"]))
        x2, y2 = fn(float(data["x2"]), float(data["y2"]))
        out.update(x1=x1, y1=y1, x2=x2, y2=y2)
    return out


def scale_vector(data: dict, sx: float, sy: float) -> dict:
    out = _map_points(data, lambda x, y: (x * sx, y * sy))
    if "width" in out:
        out["width"] = max(1, round(out["width"] * (sx + sy) / 2.0))
    return out


def rotate_vector(data: dict, deg: int, old_w: int, old_h: int) -> dict:
    deg %= 360
    if deg == 90:
        return _map_points(data, lambda x, y: (old_h - y, x))
    if deg == 180:
        return _map_points(data, lambda x, y: (old_w - x, old_h - y))
    if deg == 270:
        return _map_points(data, lambda x, y: (y, old_w - x))
    return dict(data)


def flip_vector(data: dict, horizontal: bool, w: int, h: int) -> dict:
    if horizontal:
        return _map_points(data, lambda x, y: (w - x, y))
    return _map_points(data, lambda x, y: (x, h - y))


def handles(data: dict) -> list[tuple[str, float, float]]:
    """Named drag handles in doc coords."""
    if data.get("kind") == "path":
        return [(str(i), float(x), float(y))
                for i, (x, y) in enumerate(data.get("points", []))]
    x1, y1 = float(data["x1"]), float(data["y1"])
    x2, y2 = float(data["x2"]), float(data["y2"])
    if data.get("kind") == "line":
        return [("p1", x1, y1), ("p2", x2, y2)]
    return [("c11", x1, y1), ("c22", x2, y2), ("c12", x1, y2), ("c21", x2, y1)]


def grab(data: dict, x: float, y: float) -> str | None:
    """Handle name at (x, y), or "move" inside the geometry, or None."""
    for name, hx, hy in handles(data):
        if abs(hx - x) <= HANDLE_RADIUS and abs(hy - y) <= HANDLE_RADIUS:
            return name
    if data.get("kind") == "path":
        xs = [p[0] for p in data["points"]]
        ys = [p[1] for p in data["points"]]
        box = QRectF(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
    else:
        box = QRectF(QPointF(float(data["x1"]), float(data["y1"])),
                     QPointF(float(data["x2"]), float(data["y2"]))).normalized()
    return "move" if box.adjusted(-4, -4, 4, 4).contains(x, y) else None


def drag(data: dict, name: str, x: float, y: float,
         dx: float, dy: float) -> dict:
    """New vector_data after dragging handle `name` to (x, y), or the whole
    geometry by (dx, dy) when name == "move"."""
    out = dict(data)
    if name == "move":
        return _map_points(data, lambda px, py: (px + dx, py + dy))
    if data.get("kind") == "path":
        pts = [list(p) for p in data["points"]]
        pts[int(name)] = [x, y]
        out["points"] = pts
        return out
    if name in ("p1", "c11"):
        out.update(x1=x, y1=y)
    elif name in ("p2", "c22"):
        out.update(x2=x, y2=y)
    elif name == "c12":
        out.update(x1=x, y2=y)
    elif name == "c21":
        out.update(x2=x, y1=y)
    return out


def flip_vector_local(data: dict, horizontal: bool) -> dict:
    """Mirror geometry about its own bounding box (self-inverse — matches
    FlipLayerCommand's undo == redo)."""
    if data.get("kind") == "path":
        xs = [float(p[0]) for p in data["points"]]
        ys = [float(p[1]) for p in data["points"]]
    else:
        xs = [float(data["x1"]), float(data["x2"])]
        ys = [float(data["y1"]), float(data["y2"])]
    sx, ex, sy, ey = min(xs), max(xs), min(ys), max(ys)
    if horizontal:
        return _map_points(data, lambda x, y: (sx + ex - x, y))
    return _map_points(data, lambda x, y: (x, sy + ey - y))
