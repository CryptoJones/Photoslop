# SPDX-License-Identifier: Apache-2.0
"""Undoable native-vector selection, construction, appearance, and geometry ops."""

from __future__ import annotations

import copy
import math
import uuid
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QTransform, QUndoCommand

from photoslop import vector


def vector_layers(doc):
    return [layer for layer in doc.layers if layer.vector_data is not None]


def by_id(doc, object_id: str):
    return next(
        (
            layer
            for layer in vector_layers(doc)
            if vector.migrate_vector(layer.vector_data)["id"] == object_id
        ),
        None,
    )


def selected(doc):
    ids = set(doc.vector_selection)
    return [
        layer
        for layer in vector_layers(doc)
        if vector.migrate_vector(layer.vector_data)["id"] in ids
    ]


def select(doc, ids: list[str], mode: str = "replace") -> list[str]:
    available = {vector.migrate_vector(layer.vector_data)["id"] for layer in vector_layers(doc)}
    incoming = [item for item in ids if item in available]
    current = list(doc.vector_selection)
    if mode == "replace":
        result = incoming
    elif mode == "add":
        result = list(dict.fromkeys([*current, *incoming]))
    elif mode == "subtract":
        result = [item for item in current if item not in incoming]
    elif mode == "intersect":
        result = [item for item in current if item in incoming]
    else:
        raise ValueError(f"Unknown selection mode: {mode}")
    doc.vector_selection = result
    doc.notify_structure()
    return result


class SetVectorDataCommand(QUndoCommand):
    def __init__(self, doc, changes: list[tuple[object, dict]], text: str) -> None:
        super().__init__(text)
        self.doc = doc
        self.layers = [layer for layer, _data in changes]
        self.old = [copy.deepcopy(layer.vector_data) for layer in self.layers]
        self.new = [copy.deepcopy(data) for _layer, data in changes]
        self._applied = False

    def _set(self, values: list[dict]) -> None:
        dirty = None
        for layer, data in zip(self.layers, values, strict=True):
            before = layer.bounds()
            vector.rerender_into(layer, data, self.doc.canvas_rect())
            area = before.united(layer.bounds())
            dirty = area if dirty is None else dirty.united(area)
        if dirty is not None:
            self.doc.notify_pixels(dirty)
        self.doc.notify_structure()

    def redo(self) -> None:
        self._set(self.new)

    def undo(self) -> None:
        self._set(self.old)


def _transform_data(data: dict, transform: QTransform) -> dict:
    migrated = vector.migrate_vector(data)
    a, b, c, d, tx, ty = migrated.get("transform", [1, 0, 0, 1, 0, 0])
    current = QTransform(a, b, c, d, tx, ty)
    result = transform * current
    migrated["transform"] = [
        result.m11(),
        result.m12(),
        result.m21(),
        result.m22(),
        result.dx(),
        result.dy(),
    ]
    return migrated


def transform(
    doc,
    ids: list[str],
    *,
    dx=0.0,
    dy=0.0,
    rotate=0.0,
    sx=1.0,
    sy=1.0,
    origin: tuple[float, float] | None = None,
) -> None:
    layers = [by_id(doc, item) for item in ids]
    layers = [layer for layer in layers if layer is not None]
    if not layers:
        return
    bounds = [vector.native_path(layer.vector_data).boundingRect() for layer in layers]
    union = bounds[0]
    for rect in bounds[1:]:
        union = union.united(rect)
    ox, oy = origin or (union.center().x(), union.center().y())
    matrix = QTransform()
    matrix.translate(dx, dy)
    matrix.translate(ox, oy)
    matrix.rotate(rotate)
    matrix.scale(sx, sy)
    matrix.translate(-ox, -oy)
    doc.undo_stack.push(
        SetVectorDataCommand(
            doc,
            [(layer, _transform_data(layer.vector_data, matrix)) for layer in layers],
            "Transform Vector Objects",
        )
    )


def set_appearance(doc, ids: list[str], **values) -> None:
    changes = []
    for object_id in ids:
        layer = by_id(doc, object_id)
        if layer is None:
            continue
        data = vector.migrate_vector(layer.vector_data)
        data["appearance"].update(copy.deepcopy(values))
        changes.append((layer, data))
    if changes:
        doc.undo_stack.push(SetVectorDataCommand(doc, changes, "Vector Appearance"))


def group(doc, ids: list[str], parent_id: str | None) -> None:
    changes = []
    for object_id in ids:
        layer = by_id(doc, object_id)
        if layer is not None:
            data = vector.migrate_vector(layer.vector_data)
            data["parent_id"] = parent_id
            changes.append((layer, data))
    if changes:
        doc.undo_stack.push(SetVectorDataCommand(doc, changes, "Group Vector Objects"))


def align(doc, ids: list[str], axis: str, target: str = "selection") -> None:
    layers = [by_id(doc, item) for item in ids]
    layers = [layer for layer in layers if layer is not None]
    if len(layers) < 2:
        return
    rects = [vector.native_path(layer.vector_data).boundingRect() for layer in layers]
    union = rects[0]
    for rect in rects[1:]:
        union = union.united(rect)
    if target == "canvas":
        union = QRectF(doc.canvas_rect())
    changes = []
    for layer, rect in zip(layers, rects, strict=True):
        if axis == "left":
            dx, dy = union.left() - rect.left(), 0
        elif axis == "right":
            dx, dy = union.right() - rect.right(), 0
        elif axis == "top":
            dx, dy = 0, union.top() - rect.top()
        elif axis == "bottom":
            dx, dy = 0, union.bottom() - rect.bottom()
        elif axis == "hcenter":
            dx, dy = union.center().x() - rect.center().x(), 0
        elif axis == "vcenter":
            dx, dy = 0, union.center().y() - rect.center().y()
        else:
            raise ValueError(f"Unknown alignment: {axis}")
        changes.append(
            (layer, _transform_data(layer.vector_data, QTransform.fromTranslate(dx, dy)))
        )
    doc.undo_stack.push(SetVectorDataCommand(doc, changes, "Align Vector Objects"))


def distribute(doc, ids: list[str], axis: str) -> None:
    layers = [by_id(doc, item) for item in ids]
    layers = [layer for layer in layers if layer is not None]
    if len(layers) < 3:
        return

    def key(layer):
        center = vector.native_path(layer.vector_data).boundingRect().center()
        return center.x() if axis == "horizontal" else center.y()

    layers.sort(key=key)
    first, last = key(layers[0]), key(layers[-1])
    step = (last - first) / (len(layers) - 1)
    changes = []
    for index, layer in enumerate(layers):
        delta = first + step * index - key(layer)
        matrix = QTransform.fromTranslate(
            delta if axis == "horizontal" else 0, delta if axis == "vertical" else 0
        )
        changes.append((layer, _transform_data(layer.vector_data, matrix)))
    doc.undo_stack.push(SetVectorDataCommand(doc, changes, "Distribute Vector Objects"))


def edit_node(
    doc,
    object_id: str,
    index: int,
    action: str,
    point: tuple[float, float] | None = None,
    node_type: str | None = None,
) -> None:
    layer = by_id(doc, object_id)
    if layer is None:
        return
    data = vector.migrate_vector(layer.vector_data)
    commands = data["geometry"].get("commands", [])
    nodes = [
        position
        for position, command in enumerate(commands)
        if command.get("op") in {"M", "L", "C"}
    ]
    if action == "delete":
        commands.pop(nodes[index])
    elif action == "add":
        if point is None:
            raise ValueError("add node requires point")
        commands.insert(
            nodes[index] + 1, {"op": "L", "p": list(point), "node": node_type or "corner"}
        )
    elif action == "convert":
        commands[nodes[index]]["node"] = node_type or "corner"
    else:
        raise ValueError(f"Unknown node action: {action}")
    doc.undo_stack.push(SetVectorDataCommand(doc, [(layer, data)], "Edit Vector Node"))


def _path_data(path: QPainterPath, template: dict, name: str) -> dict:
    polygons = path.toFillPolygons()
    commands = []
    for raw_polygon in polygons:
        polygon = list(raw_polygon)
        if not polygon:
            continue
        commands.append({"op": "M", "p": [polygon[0].x(), polygon[0].y()], "node": "corner"})
        commands.extend(
            {"op": "L", "p": [point.x(), point.y()], "node": "corner"} for point in polygon[1:]
        )
        commands.append({"op": "Z"})
    data = vector.migrate_vector(template)
    for key in ("kind", "x1", "y1", "x2", "y2", "points", "close", "fill", "width", "color"):
        data.pop(key, None)
    data["id"] = uuid.uuid4().hex
    data["name"] = name
    data["type"] = "path"
    data["geometry"] = {"kind": "path", "commands": commands}
    data["transform"] = [1, 0, 0, 1, 0, 0]
    return data


def boolean_path(doc, ids: list[str], operation: str) -> dict | None:
    layers = [by_id(doc, item) for item in ids]
    layers = [layer for layer in layers if layer is not None]
    if len(layers) < 2:
        return None
    result = vector.native_path(layers[0].vector_data)
    for layer in layers[1:]:
        other = vector.native_path(layer.vector_data)
        if operation == "union":
            result = result.united(other)
        elif operation == "difference":
            result = result.subtracted(other)
        elif operation == "intersect":
            result = result.intersected(other)
        elif operation == "exclude":
            result = result.united(other).subtracted(result.intersected(other))
        else:
            raise ValueError(f"Unknown Boolean operation: {operation}")
    data = _path_data(result.simplified(), layers[0].vector_data, f"{operation.title()} Result")
    doc.undo_stack.push(
        SetVectorDataCommand(doc, [(layers[0], data)], f"Vector {operation.title()}")
    )
    return data


@dataclass(frozen=True)
class SnapResult:
    point: QPointF
    target: str | None
    distance: float


def snap(doc, point: QPointF, tolerance: float = 8.0) -> SnapResult:
    candidates: list[tuple[QPointF, str]] = []
    candidates.extend((QPointF(x, point.y()), "vertical guide") for x in doc.guides_v)
    candidates.extend((QPointF(point.x(), y), "horizontal guide") for y in doc.guides_h)
    for layer in vector_layers(doc):
        rect = vector.native_path(layer.vector_data).boundingRect()
        candidates.extend(
            (candidate, name)
            for candidate, name in (
                (rect.topLeft(), "object corner"),
                (rect.bottomRight(), "object corner"),
                (rect.center(), "object center"),
            )
        )
    if not candidates:
        return SnapResult(QPointF(point), None, math.inf)
    candidate, name = min(
        candidates, key=lambda item: math.hypot(item[0].x() - point.x(), item[0].y() - point.y())
    )
    distance = math.hypot(candidate.x() - point.x(), candidate.y() - point.y())
    return (
        SnapResult(candidate, name, distance)
        if distance <= tolerance
        else SnapResult(QPointF(point), None, distance)
    )
