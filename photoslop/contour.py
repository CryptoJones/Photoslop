# SPDX-License-Identifier: Apache-2.0
"""Contour extraction and Bézier curve fitting for selection masks (#424).

Implements Potrace-style contour decomposition:
1. Extract 8-connected polygon boundary contours from a binary selection mask.
2. Simplify polygons using sub-pixel vertex decimation (Ramer-Douglas-Peucker).
3. Fit cubic Bézier curve segments (`C` commands with smooth control points) subject
   to user-selectable tolerance (0.5–10.0 px, default 2.0 px).
4. Output structured vector path commands matching the schema in `photoslop/vector.py`.
"""

from __future__ import annotations

import math
import uuid

import numpy as np

DX = [0, 1, 0, -1]  # 0: N, 1: E, 2: S, 3: W
DY = [-1, 0, 1, 0]


def _next_dir(nx: int, ny: int, in_dir: int, padded: np.ndarray) -> int | None:
    """Disambiguate the outgoing direction at lattice vertex (nx, ny) using 8-connectivity."""
    tl = bool(padded[ny - 1, nx - 1])
    tr = bool(padded[ny - 1, nx])
    bl = bool(padded[ny, nx - 1])
    br = bool(padded[ny, nx])

    # Saddle point 1: TL and BR foreground, TR and BL background
    # 8-connectivity connects TL and BR diagonally; boundary must not separate them.
    if tl and br and not tr and not bl:
        if in_dir == 2:  # incoming Southbound
            return 3  # turn West
        if in_dir == 0:  # incoming Northbound
            return 1  # turn East

    # Saddle point 2: TR and BL foreground, TL and BR background
    if tr and bl and not tl and not br:
        if in_dir == 1:  # incoming Eastbound
            return 2  # turn South
        if in_dir == 3:  # incoming Westbound
            return 0  # turn North

    # Standard non-saddle vertices: find valid outgoing edge that does not reverse
    if not tl and tr and in_dir != 2:
        return 0  # outgoing North
    if not tr and br and in_dir != 3:
        return 1  # outgoing East
    if bl and not br and in_dir != 0:
        return 2  # outgoing South
    if tl and not bl and in_dir != 1:
        return 3  # outgoing West

    # Fallback search all four directions if exact match not hit
    for out_d in (0, 1, 2, 3):
        if out_d == 0 and not tl and tr:
            return 0
        if out_d == 1 and not tr and br:
            return 1
        if out_d == 2 and bl and not br:
            return 2
        if out_d == 3 and tl and not bl:
            return 3

    return None


def _compress_collinear(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Remove redundant collinear points along straight runs."""
    n = len(pts)
    if n <= 2:
        return pts
    out: list[tuple[float, float]] = []
    for i in range(n):
        p0 = pts[(i - 1) % n]
        p1 = pts[i]
        p2 = pts[(i + 1) % n]
        dx1, dy1 = p1[0] - p0[0], p1[1] - p0[1]
        dx2, dy2 = p2[0] - p1[0], p2[1] - p1[1]
        # Cross product != 0 or opposite direction means a corner
        if dx1 * dy2 != dy1 * dx2 or (dx1 * dx2 + dy1 * dy2 <= 0):
            out.append(p1)
    return out if len(out) >= 3 else pts


def trace_contours(
    mask: np.ndarray, offset: tuple[float, float] = (0.0, 0.0)
) -> list[list[tuple[float, float]]]:
    """Extract 8-connected closed polygon contours from a boolean mask."""
    if not mask.any():
        return []

    h, w = mask.shape
    padded = np.pad(mask, 1, mode="constant", constant_values=False)

    all_edges: set[tuple[int, int, int]] = set()
    for y in range(1, h + 2):
        for x in range(1, w + 2):
            tl = bool(padded[y - 1, x - 1])
            tr = bool(padded[y - 1, x])
            bl = bool(padded[y, x - 1])
            br = bool(padded[y, x])
            if not tl and tr:
                all_edges.add((x, y, 0))  # North
            if not tr and br:
                all_edges.add((x, y, 1))  # East
            if bl and not br:
                all_edges.add((x, y, 2))  # South
            if tl and not bl:
                all_edges.add((x, y, 3))  # West

    ox, oy = offset
    loops: list[list[tuple[float, float]]] = []
    visited: set[tuple[int, int, int]] = set()

    for edge in list(all_edges):
        if edge in visited:
            continue
        curr = edge
        loop: list[tuple[float, float]] = []
        while curr not in visited:
            visited.add(curr)
            x, y, d = curr
            loop.append((float(x - 1) + ox, float(y - 1) + oy))
            nx, ny = x + DX[d], y + DY[d]
            nd = _next_dir(nx, ny, d, padded)
            if nd is None:
                break
            curr = (nx, ny, nd)
        if len(loop) >= 3:
            compressed = _compress_collinear(loop)
            if len(compressed) >= 3:
                loops.append(compressed)

    return loops


def _point_line_dist(
    pt: tuple[float, float], a: tuple[float, float], b: tuple[float, float]
) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    seg_sq = dx * dx + dy * dy
    if seg_sq == 0:
        return math.hypot(pt[0] - a[0], pt[1] - a[1])
    return abs(dy * pt[0] - dx * pt[1] + b[0] * a[1] - b[1] * a[0]) / math.sqrt(seg_sq)


def _rdp_open(pts: list[tuple[float, float]], epsilon: float) -> list[tuple[float, float]]:
    if len(pts) <= 2:
        return pts
    a, b = pts[0], pts[-1]
    max_d = -1.0
    idx = -1
    for i in range(1, len(pts) - 1):
        d = _point_line_dist(pts[i], a, b)
        if d > max_d:
            max_d = d
            idx = i
    if max_d > epsilon:
        left = _rdp_open(pts[: idx + 1], epsilon)
        right = _rdp_open(pts[idx:], epsilon)
        return left[:-1] + right
    return [a, b]


def simplify_polygon(pts: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Simplify a closed polygon using sub-pixel Ramer-Douglas-Peucker decimation."""
    if len(pts) <= 3:
        return pts
    epsilon = max(0.2, tolerance * 0.5)
    p0 = pts[0]
    max_d_sq = -1.0
    split = len(pts) // 2
    for i in range(1, len(pts)):
        d_sq = (pts[i][0] - p0[0]) ** 2 + (pts[i][1] - p0[1]) ** 2
        if d_sq > max_d_sq:
            max_d_sq = d_sq
            split = i
    part1 = _rdp_open(pts[: split + 1], epsilon)
    part2 = _rdp_open(pts[split:] + [pts[0]], epsilon)
    res = part1[:-1] + part2[:-1]
    return res if len(res) >= 3 else pts


def fit_cubic_beziers(
    pts: list[tuple[float, float]], corner_angle_thresh: float = 75.0
) -> list[dict]:
    """Fit cubic Bézier curve segments to a closed polygon chain."""
    n = len(pts)
    if n < 3:
        commands: list[dict] = [{"op": "M", "p": [pts[0][0], pts[0][1]], "node": "corner"}]
        for p in pts[1:]:
            commands.append({"op": "L", "p": [p[0], p[1]], "node": "corner"})
        commands.append({"op": "Z"})
        return commands

    cos_thresh = math.cos(math.radians(corner_angle_thresh))
    is_corner = [False] * n

    for i in range(n):
        p_prev = np.array(pts[(i - 1) % n], dtype=np.float64)
        p_curr = np.array(pts[i], dtype=np.float64)
        p_next = np.array(pts[(i + 1) % n], dtype=np.float64)
        v1 = p_curr - p_prev
        v2 = p_next - p_curr
        l1 = float(np.hypot(v1[0], v1[1]))
        l2 = float(np.hypot(v2[0], v2[1]))
        if l1 < 1e-6 or l2 < 1e-6:
            is_corner[i] = True
            continue
        cos_ang = float(np.dot(v1, v2) / (l1 * l2))
        if cos_ang < cos_thresh:
            is_corner[i] = True

    first_node = "corner" if is_corner[0] else "smooth"
    commands = [{"op": "M", "p": [pts[0][0], pts[0][1]], "node": first_node}]

    for i in range(n):
        p0 = np.array(pts[(i - 1) % n], dtype=np.float64)
        p1 = np.array(pts[i], dtype=np.float64)
        p2 = np.array(pts[(i + 1) % n], dtype=np.float64)
        p3 = np.array(pts[(i + 2) % n], dtype=np.float64)

        c1_corner = is_corner[i]
        c2_corner = is_corner[(i + 1) % n]

        chord_v = p2 - p1
        chord = float(np.hypot(chord_v[0], chord_v[1]))
        if chord < 1e-6:
            continue

        if c1_corner:
            t1 = chord_v / chord
        else:
            v_prev = p1 - p0
            v_next = p2 - p1
            l_prev = float(np.hypot(v_prev[0], v_prev[1]))
            l_next = float(np.hypot(v_next[0], v_next[1]))
            s_prev = v_prev / (l_prev if l_prev > 1e-6 else 1.0)
            s_next = v_next / (l_next if l_next > 1e-6 else 1.0)
            t1 = s_prev + s_next
            t1_len = float(np.hypot(t1[0], t1[1]))
            t1 = t1 / (t1_len if t1_len > 1e-6 else 1.0)

        if c2_corner:
            t2 = chord_v / chord
        else:
            v_curr = p2 - p1
            v_after = p3 - p2
            l_curr = float(np.hypot(v_curr[0], v_curr[1]))
            l_after = float(np.hypot(v_after[0], v_after[1]))
            s_curr = v_curr / (l_curr if l_curr > 1e-6 else 1.0)
            s_after = v_after / (l_after if l_after > 1e-6 else 1.0)
            t2 = s_curr + s_after
            t2_len = float(np.hypot(t2[0], t2[1]))
            t2 = t2 / (t2_len if t2_len > 1e-6 else 1.0)

        c1 = p1 + t1 * (chord / 3.0)
        c2 = p2 - t2 * (chord / 3.0)

        node_type = "corner" if c2_corner else "smooth"
        commands.append(
            {
                "op": "C",
                "c1": [round(float(c1[0]), 3), round(float(c1[1]), 3)],
                "c2": [round(float(c2[0]), 3), round(float(c2[1]), 3)],
                "p": [round(float(p2[0]), 3), round(float(p2[1]), 3)],
                "node": node_type,
            }
        )

    commands.append({"op": "Z"})
    return commands


def contour_to_commands(
    loops: list[list[tuple[float, float]]], tolerance: float = 2.0
) -> list[dict]:
    """Simplify polygon loops and fit cubic Bézier curve segments."""
    commands: list[dict] = []
    for loop in loops:
        simplified = simplify_polygon(loop, tolerance)
        cmds = fit_cubic_beziers(simplified)
        commands.extend(cmds)
    return commands


def commands_to_svg_path(commands: list[dict]) -> str:
    """Convert structured vector commands to SVG path data string."""
    parts: list[str] = []
    for cmd in commands:
        op = cmd.get("op")
        if op == "M":
            p = cmd["p"]
            parts.append(f"M {p[0]} {p[1]}")
        elif op == "L":
            p = cmd["p"]
            parts.append(f"L {p[0]} {p[1]}")
        elif op == "C":
            c1, c2, p = cmd["c1"], cmd["c2"], cmd["p"]
            parts.append(f"C {c1[0]} {c1[1]} {c2[0]} {c2[1]} {p[0]} {p[1]}")
        elif op == "Z":
            parts.append("Z")
    return " ".join(parts)


def selection_to_vector_data(
    mask: np.ndarray,
    tolerance: float = 2.0,
    name: str = "Work Path",
    offset: tuple[float, float] = (0.0, 0.0),
) -> dict:
    """Generate a schema-v1 vector layer dictionary from a binary mask."""
    tolerance = max(0.5, min(10.0, float(tolerance)))
    loops = trace_contours(mask, offset=offset)
    commands = contour_to_commands(loops, tolerance=tolerance)
    svg_d = commands_to_svg_path(commands)

    points = [[cmd["p"][0], cmd["p"][1]] for cmd in commands if "p" in cmd]
    return {
        "schema_version": 1,
        "id": uuid.uuid4().hex,
        "name": name,
        "type": "path",
        "parent_id": None,
        "geometry": {"kind": "path", "commands": commands},
        "transform": [1, 0, 0, 1, 0, 0],
        "appearance": {
            "fill": None,
            "fill_rule": "evenodd",
            "stroke": {"type": "solid", "color": [0, 0, 0, 255]},
            "stroke_width": 1.0,
            "cap": "round",
            "join": "round",
            "miter_limit": 4.0,
            "dash": [],
            "dash_offset": 0.0,
            "scale_stroke": True,
        },
        "opacity": 1.0,
        "blend_mode": "normal",
        "text": None,
        "extensions": {"svg_path": svg_d, "tolerance": tolerance},
        # Legacy projection fields
        "kind": "path",
        "points": points,
        "close": True,
        "fill": False,
        "color": [0, 0, 0, 255],
        "width": 1.0,
    }
