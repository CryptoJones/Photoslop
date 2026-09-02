# SPDX-License-Identifier: Apache-2.0
"""Node Machine — generative circuit-trace artwork driven by a layer's
silhouette.

The layer's alpha (or luma, for flattened art) becomes a mask; nodes are
scattered inside it on a jittered grid, wired to their nearest neighbours,
and each edge is routed the way a PCB autorouter would — one axis-aligned
run plus one 45-degree diagonal — then stroked as a bundle of parallel
copies. Pads mark the nodes, the silhouette contour is stroked in the same
ink, and a two-stop gradient projected across the frame colours everything.

Six presets ship as sibling filters rather than a "preset" parameter:
``parse_params`` fills every unspecified key with its default, so ``apply``
cannot tell a deliberate value from a default and a preset selector would
silently fight the sliders. Subclasses get their own menu entry, their own
pre-filled dialog, and their own CLI name with every slider still live.

Buffers are premultiplied (DD-001). Every operation here preserves the
R,G,B <= A invariant: uniform 4-channel scaling for opacity, QPainter for
the ink, and clipped uniform gain for the glow.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, Qt

from photoslop import npimage
from photoslop.filters import Filter, ParamSpec

# Node count is capped so the O(n^2) neighbour search stays trivial
# (400 nodes -> a 160k-cell distance matrix).
_MAX_NODES = 400
# Below this many masked pixels there is no silhouette worth drawing.
_MIN_AREA = 64

_PARAMS: tuple[ParamSpec, ...] = (
    ParamSpec("components", "Components", "int", 4, _MAX_NODES, 60),
    ParamSpec("traces", "Traces per node", "int", 1, 8, 3),
    ParamSpec("bundle", "Bundle copies", "int", 1, 8, 4),
    ParamSpec("spacing", "Bundle spacing", "int", 1, 12, 3),
    ParamSpec("weight", "Line weight", "int", 1, 6, 1),
    ParamSpec("pads", "Pad radius (0=off)", "int", 0, 12, 3),
    ParamSpec("outline", "Silhouette outline (0=off, 1=on)", "int", 0, 1, 1),
    ParamSpec("style", "Routing", "choice", 0, 0, "pcb", ("pcb", "straight", "vertical")),
    ParamSpec("glow", "Glow", "int", 0, 100, 0),
    ParamSpec("hue-a", "Gradient A hue", "int", 0, 359, 84),
    ParamSpec("sat-a", "Gradient A saturation", "int", 0, 100, 90),
    ParamSpec("hue-b", "Gradient B hue", "int", 0, 359, 84),
    ParamSpec("sat-b", "Gradient B saturation", "int", 0, 100, 0),
    ParamSpec("angle", "Gradient angle", "int", 0, 359, 45),
    ParamSpec("keep", "Keep source art", "int", 0, 100, 0),
    ParamSpec("source", "Silhouette from", "choice", 0, 0, "auto", ("auto", "alpha", "luma")),
    ParamSpec("seed", "Seed", "int", 0, 9999, 7),
)


def _preset(overrides: dict[str, float]) -> tuple[ParamSpec, ...]:
    """Clone the shared specs with preset defaults (keys are kebab-case, so
    this takes a dict rather than keyword arguments)."""
    unknown = set(overrides) - {spec.key for spec in _PARAMS}
    if unknown:
        raise ValueError(f"unknown node-machine parameters: {sorted(unknown)}")
    return tuple(
        spec._replace(default=overrides[spec.key]) if spec.key in overrides else spec
        for spec in _PARAMS
    )


def _silhouette(arr: np.ndarray, source: str) -> np.ndarray:
    """Boolean mask of the subject. Alpha is the honest signal; a layer that
    is essentially opaque has no silhouette, so auto mode falls back to luma
    — which is the "subject on a black background" case."""
    alpha = (arr >> np.uint32(24)).astype(np.uint16)
    mask = alpha >= 8
    if source == "luma" or (source == "auto" and mask.mean() > 0.99):
        r = ((arr >> np.uint32(16)) & 0xFF).astype(np.float32)
        g = ((arr >> np.uint32(8)) & 0xFF).astype(np.float32)
        b = (arr & 0xFF).astype(np.float32)
        mask = (0.299 * r + 0.587 * g + 0.114 * b) >= 16.0
    return mask


def _scatter(mask: np.ndarray, count: int, rng: np.random.Generator) -> tuple[np.ndarray, float]:
    """Jittered-grid sampling inside the mask (poisson-ish, and vectorised —
    np.nonzero on a full-resolution mask would allocate tens of MB of
    coordinates on a camera-sized layer). Returns points and the cell size."""
    rows = np.flatnonzero(mask.any(axis=1))
    cols = np.flatnonzero(mask.any(axis=0))
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])
    cell = max(2.0, math.sqrt(int(mask.sum()) / max(1, count)))

    gx = np.arange(x0, x1 + 1.0, cell)
    gy = np.arange(y0, y1 + 1.0, cell)
    if gx.size == 0 or gy.size == 0:
        return np.empty((0, 2), dtype=np.float64), cell
    grid_x, grid_y = np.meshgrid(gx, gy)
    jitter_x = grid_x + rng.uniform(-0.4, 0.4, grid_x.shape) * cell
    jitter_y = grid_y + rng.uniform(-0.4, 0.4, grid_y.shape) * cell
    xi = np.clip(np.rint(jitter_x).astype(np.int64), 0, mask.shape[1] - 1)
    yi = np.clip(np.rint(jitter_y).astype(np.int64), 0, mask.shape[0] - 1)

    inside = mask[yi, xi]
    pts = np.stack([xi[inside], yi[inside]], axis=1).astype(np.float64)
    if len(pts) > count:  # honour the slider when the shape is a solid block
        pts = pts[rng.permutation(len(pts))[:count]]
    return pts, cell


def _edges(pts: np.ndarray, neighbours: int, max_len: float) -> list[tuple[int, int]]:
    """Wire every node to its k nearest neighbours. Edges longer than
    max_len are dropped — without the cap, traces leap the empty gaps in a
    figure (statue to bow) and the silhouette stops reading."""
    n = len(pts)
    k = min(neighbours, n - 1)
    dist = np.hypot(
        pts[:, 0, None] - pts[None, :, 0],
        pts[:, 1, None] - pts[None, :, 1],
    )
    np.fill_diagonal(dist, np.inf)
    nearest = np.argpartition(dist, k - 1, axis=1)[:, :k]
    out: set[tuple[int, int]] = set()
    for i in range(n):
        for j in nearest[i].tolist():
            if dist[i, j] <= max_len:
                out.add((min(i, j), max(i, j)))
    return sorted(out)


def _route(ax: float, ay: float, bx: float, by: float, style: str, flip: bool) -> QPainterPath:
    """A -> B as a PCB trace: one axis-aligned run, one 45-degree diagonal."""
    path = QPainterPath(QPointF(ax, ay))
    if style != "pcb":
        path.lineTo(bx, by)
        return path
    dx, dy = bx - ax, by - ay
    if abs(dx) >= abs(dy):
        run = abs(dx) - abs(dy)
        elbow = (bx - math.copysign(run, dx), by) if flip else (ax + math.copysign(run, dx), ay)
    else:
        run = abs(dy) - abs(dx)
        elbow = (bx, by - math.copysign(run, dy)) if flip else (ax, ay + math.copysign(run, dy))
    path.lineTo(*elbow)
    path.lineTo(bx, by)
    return path


class _Gradient:
    """Two-stop gradient projected along an axis across the mask bbox."""

    def __init__(self, mask: np.ndarray, params: dict) -> None:
        angle = math.radians(float(params.get("angle", 45)))
        self._dx, self._dy = math.cos(angle), math.sin(angle)
        self._hue_a = float(params.get("hue-a", 84))
        self._sat_a = float(params.get("sat-a", 90))
        self._hue_b = float(params.get("hue-b", 84))
        self._sat_b = float(params.get("sat-b", 0))
        rows = np.flatnonzero(mask.any(axis=1))
        cols = np.flatnonzero(mask.any(axis=0))
        corners = [
            (float(cols[0]), float(rows[0])),
            (float(cols[-1]), float(rows[0])),
            (float(cols[0]), float(rows[-1])),
            (float(cols[-1]), float(rows[-1])),
        ]
        projections = [x * self._dx + y * self._dy for x, y in corners]
        self._lo = min(projections)
        self._span = max(1e-6, max(projections) - self._lo)
        # Shortest arc, so 350 -> 10 crosses zero rather than sweeping back.
        self._delta = ((self._hue_b - self._hue_a + 180.0) % 360.0) - 180.0
        if abs(self._delta + 180.0) < 1e-9:
            # Exact opposites have no shorter arc; the modulo picks the
            # descending one, which turns yellow -> blue into a red sweep.
            self._delta = 180.0

    def at(self, x: float, y: float) -> QColor:
        t = (x * self._dx + y * self._dy - self._lo) / self._span
        t = min(1.0, max(0.0, t))
        hue = (self._hue_a + self._delta * t) % 360.0
        sat = self._sat_a + (self._sat_b - self._sat_a) * t
        color = QColor()
        color.setHsvF(hue / 360.0, min(1.0, max(0.0, sat / 100.0)), 1.0)
        return color


def _draw_pad(painter: QPainter, x: float, y: float, radius: float, kind: int) -> None:
    if kind == 0:
        painter.setBrush(painter.pen().color())
        painter.drawEllipse(QPointF(x, y), radius, radius)
        painter.setBrush(Qt.BrushStyle.NoBrush)
    elif kind == 1:
        painter.drawEllipse(QPointF(x, y), radius, radius)
    else:
        painter.setBrush(painter.pen().color())
        painter.drawRect(QRectF(x - radius, y - radius, radius * 2, radius * 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)


def _paint_traces(
    painter: QPainter,
    pts: np.ndarray,
    cell: float,
    gradient: _Gradient,
    params: dict,
    rng: np.random.Generator,
) -> None:
    style = str(params.get("style", "pcb"))
    bundle = max(1, int(params.get("bundle", 4)))
    spacing = max(1, int(params.get("spacing", 3)))
    weight = max(1, int(params.get("weight", 1)))

    if style == "vertical":  # vertical flow: drop lines, not a graph
        for x, y in pts.tolist():
            length = rng.uniform(0.5, 6.0) * cell
            end = y + (length if rng.random() < 0.5 else -length)
            pen = QPen(gradient.at(x, (y + end) / 2.0), weight)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(x, y), QPointF(x, end))
            if rng.random() < 0.15:
                side = cell * 0.4
                painter.drawRect(QRectF(x - side / 2, min(y, end) - side, side, side))
        return

    edges = _edges(pts, max(1, int(params.get("traces", 3))), 3.0 * cell)
    for i, j in edges:
        ax, ay = pts[i]
        bx, by = pts[j]
        path = _route(ax, ay, bx, by, style, rng.random() < 0.5)
        pen = QPen(gradient.at((ax + bx) / 2.0, (ay + by) / 2.0), weight)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.MiterJoin)
        painter.setPen(pen)
        # Offset perpendicular to the chord and translate the whole path, so
        # the copies stay parallel through the elbow.
        length = max(1e-6, math.hypot(bx - ax, by - ay))
        px, py = -(by - ay) / length, (bx - ax) / length
        for copy in range(bundle):
            offset = (copy - (bundle - 1) / 2.0) * spacing
            painter.save()
            painter.translate(px * offset, py * offset)
            painter.drawPath(path)
            painter.restore()


def _paint_outline(painter: QPainter, mask: np.ndarray, gradient: _Gradient, weight: int) -> None:
    """Stroke the silhouette contour. mask_to_path returns a simplified
    rect-union path — deliberately blocky, which suits the aesthetic."""
    polygons = npimage.mask_to_path(mask).toSubpathPolygons()
    for polygon in polygons:
        points = [polygon.at(i) for i in range(polygon.count())]
        if len(points) < 2:
            continue
        # colour per chunk so the gradient runs along the contour
        for start in range(0, len(points) - 1, 24):
            chunk = points[start : start + 25]
            if len(chunk) < 2:
                continue
            mid = chunk[len(chunk) // 2]
            pen = QPen(gradient.at(mid.x(), mid.y()), weight)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawPolyline(chunk)


def _paint_pads(
    painter: QPainter,
    pts: np.ndarray,
    gradient: _Gradient,
    radius: int,
    rng: np.random.Generator,
) -> None:
    for x, y in pts.tolist():
        pen = QPen(gradient.at(x, y), 1)
        painter.setPen(pen)
        _draw_pad(painter, x, y, float(radius), int(rng.integers(0, 3)))


def _glow_radius(overlay: QImage, glow: int) -> int:
    """Blur radius for the halo, clamped to what the buffer can carry.

    npimage.gaussian_blur halves the radius into ``r = radius // 2 + 1``, and
    _box_blur_plane's cumsum trick only balances its stacked operands while
    ``r < dimension`` — past that numpy raises on the broadcast. A narrow layer
    (a pasted strip, a slim text layer) therefore has to cap the radius however
    high the glow slider goes. Returns 0 when the buffer is too thin to blur."""
    limit = 2 * min(overlay.width(), overlay.height()) - 3
    if limit < 1:
        return 0
    return min(glow // 3 + 2, limit)


def _apply_glow(overlay: QImage, glow: int, radius: int) -> QImage:
    """Gain then blur a copy of the ink. The gain is uniform across all four
    premultiplied channels, so clipping cannot push R,G,B above A."""
    halo = overlay.copy()
    arr = npimage.view_u32(halo)
    gain = 1.0 + glow / 50.0
    planes = [((arr >> np.uint32(k)) & 0xFF).astype(np.float32) * gain for k in (24, 16, 8, 0)]
    a, r, g, b = (np.clip(c, 0, 255).astype(np.uint32) for c in planes)
    arr[...] = (a << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    del arr
    npimage.gaussian_blur(halo, radius)
    return halo


def _render(image: QImage, params: dict) -> None:
    arr = npimage.view_u32(image)
    mask = _silhouette(arr, str(params.get("source", "auto")))
    if int(mask.sum()) < _MIN_AREA:
        return  # nothing to trace; a no-op beats a crash

    rng = np.random.default_rng(int(params.get("seed", 7)))
    count = min(_MAX_NODES, max(4, int(params.get("components", 60))))
    pts, cell = _scatter(mask, count, rng)
    if len(pts) < 3:
        return

    gradient = _Gradient(mask, params)
    weight = max(1, int(params.get("weight", 1)))
    overlay = QImage(image.size(), QImage.Format.Format_ARGB32_Premultiplied)
    overlay.fill(0)
    painter = QPainter(overlay)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if int(params.get("outline", 1)):
        _paint_outline(painter, mask, gradient, weight)
    _paint_traces(painter, pts, cell, gradient, params, rng)
    pads = int(params.get("pads", 3))
    if pads > 0:
        _paint_pads(painter, pts, gradient, pads, rng)
    painter.end()

    glow = int(params.get("glow", 0))
    radius = _glow_radius(overlay, glow) if glow > 0 else 0
    halo = _apply_glow(overlay, glow, radius) if radius > 0 else None

    keep = min(100, max(0, int(params.get("keep", 0))))
    if keep < 100:  # premultiplied: a uniform 4-channel scale is an opacity
        scale = keep / 100.0
        planes = [((arr >> np.uint32(k)) & 0xFF).astype(np.float32) * scale for k in (24, 16, 8, 0)]
        a, r, g, b = (np.clip(c, 0, 255).astype(np.uint32) for c in planes)
        arr[...] = (a << np.uint32(24)) | (r << np.uint32(16)) | (g << np.uint32(8)) | b
    del arr  # release the buffer view before handing the image to QPainter

    out = QPainter(image)
    if halo is not None:
        out.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
        out.drawImage(0, 0, halo)
        out.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    out.drawImage(0, 0, overlay)
    out.end()


class NodeMachineFilter(Filter):
    """Circuit traces grown from the layer's silhouette.

    Safe to run on a worker thread: QPainter on a QImage is a raster paint
    device with a single painter, which is why the >=1MP async filter path
    can take this without special handling.
    """

    name = "node-machine"
    label = "Node Machine"
    params = _PARAMS

    def apply(self, image: QImage, params: dict) -> None:
        _render(image, params)


class NodeMachineCircuitFilter(NodeMachineFilter):
    name = "node-machine-circuit"
    label = "Node Machine (Circu1t)"
    params = _preset(
        {
            "keep": 100,
            "bundle": 1,
            "components": 50,
            "traces": 2,
            "pads": 3,
            "hue-a": 185,
            "sat-a": 70,
            "hue-b": 185,
            "sat-b": 70,
        }
    )


class NodeMachineWebFilter(NodeMachineFilter):
    name = "node-machine-web"
    label = "Node Machine (Web)"
    params = _preset(
        {
            "components": 45,
            "traces": 2,
            "bundle": 1,
            "pads": 4,
            "hue-a": 185,
            "sat-a": 55,
            "hue-b": 185,
            "sat-b": 55,
        }
    )


class NodeMachineNodesFilter(NodeMachineFilter):
    name = "node-machine-nodes"
    label = "Node Machine (Nodes)"
    params = _preset(
        {
            "style": "straight",
            "components": 140,
            "traces": 4,
            "bundle": 1,
            "pads": 2,
            "glow": 60,
            "outline": 0,
            "hue-a": 55,
            "sat-a": 95,
            "hue-b": 235,
            "sat-b": 90,
        }
    )


class NodeMachineLightningFilter(NodeMachineFilter):
    name = "node-machine-lightning"
    label = "Node Machine (Lightning)"
    params = _preset(
        {
            "bundle": 6,
            "spacing": 2,
            "glow": 35,
            "hue-a": 300,
            "sat-a": 85,
            "hue-b": 170,
            "sat-b": 45,
        }
    )


class NodeMachineVerticalFilter(NodeMachineFilter):
    name = "node-machine-vertical"
    label = "Node Machine (Vertical Flow)"
    params = _preset(
        {
            "style": "vertical",
            "components": 120,
            "pads": 3,
            "outline": 0,
            "hue-a": 110,
            "sat-a": 85,
            "hue-b": 110,
            "sat-b": 85,
        }
    )


NODE_MACHINE_FILTERS: tuple[type[Filter], ...] = (
    NodeMachineFilter,
    NodeMachineCircuitFilter,
    NodeMachineWebFilter,
    NodeMachineNodesFilter,
    NodeMachineLightningFilter,
    NodeMachineVerticalFilter,
)
