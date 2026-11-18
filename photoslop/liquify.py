# SPDX-License-Identifier: Apache-2.0
"""Filter: Liquify — mesh displacement deformation with forward warp, twirl,
pucker, bloat, and freeze masks (#419).

The deformation is stored as a 2D displacement field on a regular coarse grid
(d(p) offset map, e.g. 1 node per 8 or 16 px). Backward mapping samples each
output pixel p from p + d(p) via bilinear or Catmull-Rom cubic interpolation,
guaranteeing no unmapped pixel holes. Memory stays bounded (DD-001) by storing
only the coarse grid during interaction and evaluating full-resolution
interpolation in row bands during baking.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtGui import QImage, QPainter, QUndoCommand

from photoslop.npimage import BAND_ROWS, view_u32


class LiquifyTool(StrEnum):
    """Interactive deformation tools available in the Liquify filter."""

    FORWARD_WARP = "forward_warp"
    RECONSTRUCT = "reconstruct"
    SMOOTH = "smooth"
    TWIRL_CW = "twirl_cw"
    TWIRL_CCW = "twirl_ccw"
    PUCKER = "pucker"
    BLOAT = "bloat"
    PUSH_LEFT = "push_left"
    FREEZE_MASK = "freeze_mask"
    THAW_MASK = "thaw_mask"

    @classmethod
    def normalize(cls, name: str) -> LiquifyTool:
        """Resolve tool name or shorthand alias to a canonical enum member."""
        key = name.strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "warp": cls.FORWARD_WARP,
            "forward": cls.FORWARD_WARP,
            "twirl": cls.TWIRL_CW,
            "twirl_clockwise": cls.TWIRL_CW,
            "twirl_counterclockwise": cls.TWIRL_CCW,
            "twirl_counter_clockwise": cls.TWIRL_CCW,
            "push": cls.PUSH_LEFT,
            "freeze": cls.FREEZE_MASK,
            "thaw": cls.THAW_MASK,
            "mask": cls.FREEZE_MASK,
            "erase_mask": cls.THAW_MASK,
        }
        if key in aliases:
            return aliases[key]
        for member in cls:
            if member.value == key:
                return member
        raise ValueError(f"Unknown Liquify tool: {name!r}")


def catmull_rom_weights(t: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Catmull-Rom cubic spline weights for fraction t in [0, 1].

    Basis functions satisfy w0 + w1 + w2 + w3 == 1.0 with continuous C1 derivative.
    """
    t2 = t * t
    t3 = t2 * t
    w0 = -0.5 * t3 + t2 - 0.5 * t
    w1 = 1.5 * t3 - 2.5 * t2 + 1.0
    w2 = -1.5 * t3 + 2.0 * t2 + 0.5 * t
    w3 = 0.5 * t3 - 0.5 * t2
    return w0, w1, w2, w3


@dataclass
class LiquifyStroke:
    """A recorded stroke to apply to the displacement grid."""

    tool: LiquifyTool
    points: list[tuple[float, float]]
    size: float = 80.0
    pressure: float = 0.5
    density: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool.value,
            "points": [list(pt) for pt in self.points],
            "size": float(self.size),
            "pressure": float(self.pressure),
            "density": float(self.density),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiquifyStroke:
        tool = LiquifyTool.normalize(str(data.get("tool", "forward_warp")))
        raw_points = data.get("points")
        if raw_points is None:
            # Allow single point x, y or center
            if "center" in data:
                cx, cy = data["center"]
                points = [(float(cx), float(cy))]
            elif "x" in data and "y" in data:
                points = [(float(data["x"]), float(data["y"]))]
            else:
                raise ValueError("Stroke requires 'points' or ('x', 'y')")
        else:
            points = [(float(pt[0]), float(pt[1])) for pt in raw_points]
            if not points:
                raise ValueError("Stroke 'points' list cannot be empty")
        size = float(data.get("size", 80.0))
        pressure = float(data.get("pressure", 0.5))
        density = float(data.get("density", 0.5))
        return cls(tool=tool, points=points, size=size, pressure=pressure, density=density)


class LiquifyGrid:
    """Coarse 2D displacement field and freeze mask for layer deformation.

    Memory frugality (DD-001): Only stores dx, dy, and freeze arrays at coarse
    grid resolution (e.g. 1 node every 8 or 16 pixels). For a 2000x2000 layer,
    this requires less than 1 MB of memory.
    """

    def __init__(self, width: int, height: int, spacing: int = 8) -> None:
        if width <= 0 or height <= 0:
            raise ValueError(f"Dimensions must be positive (got {width}x{height})")
        self.width = int(width)
        self.height = int(height)
        self.spacing = max(2, int(spacing))

        self.cols = (self.width + self.spacing - 1) // self.spacing + 1
        self.rows = (self.height + self.spacing - 1) // self.spacing + 1

        # Displacement field offsets d(p) = (dx, dy) in pixels
        self.dx = np.zeros((self.rows, self.cols), dtype=np.float32)
        self.dy = np.zeros((self.rows, self.cols), dtype=np.float32)

        # Freeze protection mask [0.0 = completely editable, 1.0 = completely frozen]
        self.freeze = np.zeros((self.rows, self.cols), dtype=np.float32)

    def copy(self) -> LiquifyGrid:
        """Create a deep copy of the grid."""
        clone = LiquifyGrid(self.width, self.height, self.spacing)
        clone.dx[:] = self.dx
        clone.dy[:] = self.dy
        clone.freeze[:] = self.freeze
        return clone

    def reset(self) -> None:
        """Reset displacement offsets to zero (restoring identity mapping)."""
        self.dx.fill(0.0)
        self.dy.fill(0.0)

    def reconstruct_all(self) -> None:
        """Alias for reset."""
        self.reset()

    def clear_freeze(self) -> None:
        """Clear the freeze mask (unfreezing all nodes)."""
        self.freeze.fill(0.0)

    def invert_freeze(self) -> None:
        """Invert the freeze mask."""
        self.freeze[:] = 1.0 - self.freeze

    def apply_brush(
        self,
        tool: LiquifyTool | str,
        center: tuple[float, float],
        radius: float,
        pressure: float = 0.5,
        density: float = 0.5,
        delta: tuple[float, float] = (0.0, 0.0),
        step_rate: float = 1.0,
    ) -> tuple[int, int, int, int] | None:
        """Apply an interactive deformation brush at a single point.

        Returns dirty bounding box (min_x, min_y, max_x, max_y) in image pixel
        coordinates, or None if outside the canvas.
        """
        if isinstance(tool, str):
            tool = LiquifyTool.normalize(tool)

        cx, cy = float(center[0]), float(center[1])
        r = max(1.0, float(radius))
        p = np.clip(float(pressure), 0.0, 1.0)
        d = np.clip(float(density), 0.0, 1.0)
        s = max(0.01, float(self.spacing))

        # Node index bounding box
        c_min = max(0, int(math.floor((cx - r) / s)))
        c_max = min(self.cols - 1, int(math.ceil((cx + r) / s)))
        r_min = max(0, int(math.floor((cy - r) / s)))
        r_max = min(self.rows - 1, int(math.ceil((cy + r) / s)))

        if c_min > c_max or r_min > r_max:
            return None

        # Grid rest coordinates for the sub-window
        cols_idx = np.arange(c_min, c_max + 1, dtype=np.float32)
        rows_idx = np.arange(r_min, r_max + 1, dtype=np.float32)
        grid_x = cols_idx[None, :] * s
        grid_y = rows_idx[:, None] * s

        dist = np.hypot(grid_x - cx, grid_y - cy)
        in_brush = dist < r
        if not np.any(in_brush):
            return None

        t = dist / r
        if d > 0.0:
            t_eff = np.clip((t - d) / max(1e-5, 1.0 - d), 0.0, 1.0)
        else:
            t_eff = np.clip(t, 0.0, 1.0)

        # Smooth quartic falloff
        w = np.where(in_brush, (1.0 - t_eff * t_eff) ** 2 * (p * step_rate), 0.0).astype(np.float32)

        sub_freeze = self.freeze[r_min : r_max + 1, c_min : c_max + 1]
        w_eff = w * (1.0 - sub_freeze)

        sub_dx = self.dx[r_min : r_max + 1, c_min : c_max + 1]
        sub_dy = self.dy[r_min : r_max + 1, c_min : c_max + 1]

        if tool == LiquifyTool.FORWARD_WARP:
            vx, vy = float(delta[0]), float(delta[1])
            sub_dx -= vx * w_eff
            sub_dy -= vy * w_eff

        elif tool == LiquifyTool.RECONSTRUCT:
            rate = np.clip(w_eff * 0.4, 0.0, 1.0)
            sub_dx *= 1.0 - rate
            sub_dy *= 1.0 - rate

        elif tool == LiquifyTool.SMOOTH:
            # 4-neighbour local average of displacements
            dx_mean = np.zeros_like(sub_dx)
            dy_mean = np.zeros_like(sub_dy)
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                rr = np.clip(np.arange(r_min, r_max + 1) + dr, 0, self.rows - 1)
                cc = np.clip(np.arange(c_min, c_max + 1) + dc, 0, self.cols - 1)
                dx_mean += self.dx[rr[:, None], cc[None, :]]
                dy_mean += self.dy[rr[:, None], cc[None, :]]
            dx_mean *= 0.25
            dy_mean *= 0.25
            rate = np.clip(w_eff * 0.4, 0.0, 1.0)
            sub_dx += (dx_mean - sub_dx) * rate
            sub_dy += (dy_mean - sub_dy) * rate

        elif tool in (LiquifyTool.TWIRL_CW, LiquifyTool.TWIRL_CCW):
            # Rotates relative sampled location around brush center
            direction = -1.0 if tool == LiquifyTool.TWIRL_CW else 1.0
            angle = direction * (0.35 * w_eff)
            cos_a = np.cos(angle)
            sin_a = np.sin(angle)
            rx = grid_x + sub_dx - cx
            ry = grid_y + sub_dy - cy
            rx_new = rx * cos_a - ry * sin_a
            ry_new = rx * sin_a + ry * cos_a
            sub_dx[:] = (cx + rx_new) - grid_x
            sub_dy[:] = (cy + ry_new) - grid_y

        elif tool == LiquifyTool.PUCKER:
            # Squeezes pixels toward center -> source coordinates expand outward
            scale = 1.0 + (0.3 * w_eff)
            rx = grid_x + sub_dx - cx
            ry = grid_y + sub_dy - cy
            sub_dx[:] = (cx + rx * scale) - grid_x
            sub_dy[:] = (cy + ry * scale) - grid_y

        elif tool == LiquifyTool.BLOAT:
            # Expands pixels outward -> source coordinates contract inward
            scale = np.maximum(0.05, 1.0 - (0.3 * w_eff))
            rx = grid_x + sub_dx - cx
            ry = grid_y + sub_dy - cy
            sub_dx[:] = (cx + rx * scale) - grid_x
            sub_dy[:] = (cy + ry * scale) - grid_y

        elif tool == LiquifyTool.PUSH_LEFT:
            vx, vy = float(delta[0]), float(delta[1])
            length = math.hypot(vx, vy)
            if length > 1e-6:
                # Perpendicular vector to the left of the stroke direction
                ux = vy
                uy = -vx
                sub_dx -= ux * w_eff
                sub_dy -= uy * w_eff

        elif tool == LiquifyTool.FREEZE_MASK:
            rate = np.clip(w * 0.5, 0.0, 1.0)
            sub_freeze[:] = np.minimum(1.0, sub_freeze + rate)

        elif tool == LiquifyTool.THAW_MASK:
            rate = np.clip(w * 0.5, 0.0, 1.0)
            sub_freeze[:] = np.maximum(0.0, sub_freeze - rate)

        dirty_x0 = max(0, int(math.floor(cx - r - s)))
        dirty_y0 = max(0, int(math.floor(cy - r - s)))
        dirty_x1 = min(self.width, int(math.ceil(cx + r + s)))
        dirty_y1 = min(self.height, int(math.ceil(cy + r + s)))
        return (dirty_x0, dirty_y0, dirty_x1, dirty_y1)

    def apply_stroke(
        self,
        tool: LiquifyTool | str,
        points: list[tuple[float, float]],
        size: float = 80.0,
        pressure: float = 0.5,
        density: float = 0.5,
    ) -> tuple[int, int, int, int] | None:
        """Apply a stroke sequence with continuous sub-pixel interpolation."""
        if not points:
            return None
        radius = float(size) / 2.0
        dirty_box: tuple[int, int, int, int] | None = None

        def _union_box(
            b1: tuple[int, int, int, int] | None, b2: tuple[int, int, int, int] | None
        ) -> tuple[int, int, int, int] | None:
            if b1 is None:
                return b2
            if b2 is None:
                return b1
            return (
                min(b1[0], b2[0]),
                min(b1[1], b2[1]),
                max(b1[2], b2[2]),
                max(b1[3], b2[3]),
            )

        if len(points) == 1:
            box = self.apply_brush(tool, points[0], radius, pressure, density)
            return box

        step_dist = max(2.0, radius * 0.25)
        for i in range(len(points) - 1):
            p0 = points[i]
            p1 = points[i + 1]
            dx = p1[0] - p0[0]
            dy = p1[1] - p0[1]
            dist = math.hypot(dx, dy)
            steps = max(1, int(math.ceil(dist / step_dist)))
            delta_step = (dx / steps, dy / steps)

            for s in range(1, steps + 1):
                frac = s / steps
                cx = p0[0] + dx * frac
                cy = p0[1] + dy * frac
                box = self.apply_brush(
                    tool, (cx, cy), radius, pressure, density, delta=delta_step, step_rate=1.0
                )
                dirty_box = _union_box(dirty_box, box)

        return dirty_box

    def apply_strokes(self, strokes: list[LiquifyStroke | dict[str, Any]]) -> None:
        """Apply a list of LiquifyStroke instances or stroke dictionaries."""
        for s in strokes:
            stroke = LiquifyStroke.from_dict(s) if isinstance(s, dict) else s
            self.apply_stroke(
                stroke.tool,
                stroke.points,
                size=stroke.size,
                pressure=stroke.pressure,
                density=stroke.density,
            )

    def sample_displacement(
        self,
        xs: np.ndarray,
        ys: np.ndarray,
        method: str = "bilinear",
    ) -> tuple[np.ndarray, np.ndarray]:
        """Interpolate coarse grid (dx, dy) at continuous pixel coordinates (xs, ys).

        Supports 'bilinear' and 'catmull-rom' (C1 bicubic spline).
        """
        s = float(self.spacing)
        u = xs / s
        v = ys / s

        if method in ("catmull-rom", "bicubic", "catmull_rom"):
            # 4x4 Catmull-Rom cubic spline interpolation
            iu = np.floor(u).astype(np.int32)
            iv = np.floor(v).astype(np.int32)
            tu = u - iu
            tv = v - iv

            wu = catmull_rom_weights(tu)
            wv = catmull_rom_weights(tv)

            interp_dx = np.zeros_like(u, dtype=np.float32)
            interp_dy = np.zeros_like(v, dtype=np.float32)

            for j in range(4):
                rj = np.clip(iv + j - 1, 0, self.rows - 1)
                wv_j = wv[j]
                for i in range(4):
                    ci = np.clip(iu + i - 1, 0, self.cols - 1)
                    w_ij = (wv_j * wu[i]).astype(np.float32)
                    interp_dx += self.dx[rj, ci] * w_ij
                    interp_dy += self.dy[rj, ci] * w_ij

            return interp_dx, interp_dy

        # Default: bilinear interpolation
        c0 = np.floor(u).astype(np.int32)
        c1 = np.clip(c0 + 1, 0, self.cols - 1)
        c0 = np.clip(c0, 0, self.cols - 1)
        wu1 = (u - c0).astype(np.float32)
        wu0 = 1.0 - wu1

        r0 = np.floor(v).astype(np.int32)
        r1 = np.clip(r0 + 1, 0, self.rows - 1)
        r0 = np.clip(r0, 0, self.rows - 1)
        wv1 = (v - r0).astype(np.float32)
        wv0 = 1.0 - wv1

        interp_dx = (self.dx[r0, c0] * wu0 + self.dx[r0, c1] * wu1) * wv0 + (
            self.dx[r1, c0] * wu0 + self.dx[r1, c1] * wu1
        ) * wv1
        interp_dy = (self.dy[r0, c0] * wu0 + self.dy[r0, c1] * wu1) * wv0 + (
            self.dy[r1, c0] * wu0 + self.dy[r1, c1] * wu1
        ) * wv1
        return interp_dx, interp_dy

    def warp_image(
        self,
        image: QImage,
        interpolation: str = "bilinear",
        band_rows: int = BAND_ROWS,
        rect: tuple[int, int, int, int] | None = None,
        target_image: QImage | None = None,
    ) -> QImage:
        """Evaluate backward mapping p + d(p) into a QImage (Format_ARGB32_Premultiplied).

        If target_image is provided and rect is given, only warps the sub-rectangle
        in-place, keeping transient memory tiny (DD-001).
        """
        w, h = image.width(), image.height()
        if w != self.width or h != self.height:
            raise ValueError(
                f"Image dimensions ({w}x{h}) do not match grid ({self.width}x{self.height})"
            )

        if target_image is None:
            out_img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
            # If not a partial rect update, we process all rows
            min_x, min_y, max_x, max_y = (0, 0, w, h) if rect is None else rect
            if rect is not None:
                # Copy entire source first for unchanged pixels outside rect
                p = QPainter(out_img)
                p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
                p.drawImage(0, 0, image)
                p.end()
        else:
            out_img = target_image
            min_x, min_y, max_x, max_y = (0, 0, w, h) if rect is None else rect

        min_x = max(0, min_x)
        min_y = max(0, min_y)
        max_x = min(w, max_x)
        max_y = min(h, max_y)

        if min_x >= max_x or min_y >= max_y:
            return out_img

        src_arr = view_u32(image)
        dst_arr = view_u32(out_img)

        # Walk in row bands of band_rows to bound transient memory (DD-001)
        sub_w = max_x - min_x
        xs = np.arange(min_x, max_x, dtype=np.float32)[None, :]

        for y0 in range(min_y, max_y, band_rows):
            y1 = min(y0 + band_rows, max_y)
            bh = y1 - y0
            ys = np.arange(y0, y1, dtype=np.float32)[:, None]

            # Broadcast coordinates across the band
            xs_band = np.broadcast_to(xs, (bh, sub_w))
            ys_band = np.broadcast_to(ys, (bh, sub_w))

            interp_dx, interp_dy = self.sample_displacement(xs_band, ys_band, method=interpolation)

            # Inverse mapping: sample source coordinate p_src = p + d(p)
            sx = np.clip(xs_band + interp_dx, 0.0, float(w - 1))
            sy = np.clip(ys_band + interp_dy, 0.0, float(h - 1))

            sx0 = np.floor(sx).astype(np.int32)
            sx1 = np.clip(sx0 + 1, 0, w - 1)
            wx1 = sx - sx0
            wx0 = 1.0 - wx1

            sy0 = np.floor(sy).astype(np.int32)
            sy1 = np.clip(sy0 + 1, 0, h - 1)
            wy1 = sy - sy0
            wy0 = 1.0 - wy1

            # Sample 4 surrounding source pixels (premultiplied ARGB32)
            p00 = src_arr[sy0, sx0]
            p01 = src_arr[sy0, sx1]
            p10 = src_arr[sy1, sx0]
            p11 = src_arr[sy1, sx1]

            # Bilinear interpolation across each channel
            band_out = np.zeros((bh, sub_w), dtype=np.uint32)
            for shift in (24, 16, 8, 0):
                c00 = (p00 >> np.uint32(shift)) & 0xFF
                c01 = (p01 >> np.uint32(shift)) & 0xFF
                c10 = (p10 >> np.uint32(shift)) & 0xFF
                c11 = (p11 >> np.uint32(shift)) & 0xFF

                top = c00 * wx0 + c01 * wx1
                bot = c10 * wx0 + c11 * wx1
                interpolated = np.clip(top * wy0 + bot * wy1 + 0.5, 0.0, 255.0).astype(np.uint32)
                band_out |= interpolated << np.uint32(shift)

            dst_arr[y0:y1, min_x:max_x] = band_out

        return out_img

    def to_dict(self) -> dict[str, Any]:
        """Serialize grid metadata and coarse arrays."""
        return {
            "width": self.width,
            "height": self.height,
            "spacing": self.spacing,
            "dx": self.dx.tolist(),
            "dy": self.dy.tolist(),
            "freeze": self.freeze.tolist(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LiquifyGrid:
        """Construct LiquifyGrid from serialized dictionary."""
        grid = cls(
            width=int(data["width"]),
            height=int(data["height"]),
            spacing=int(data.get("spacing", 8)),
        )
        if "dx" in data and "dy" in data:
            grid.dx[:] = np.array(data["dx"], dtype=np.float32)
            grid.dy[:] = np.array(data["dy"], dtype=np.float32)
        if "freeze" in data:
            grid.freeze[:] = np.array(data["freeze"], dtype=np.float32)
        return grid


def load_strokes(source: str | Path | list[dict[str, Any]]) -> list[LiquifyStroke]:
    """Load stroke records from a JSON file path, inline JSON string, or list."""
    if isinstance(source, list):
        return [LiquifyStroke.from_dict(item) for item in source]

    text = str(source).strip()
    path = Path(text)
    if path.is_file():
        text = path.read_text(encoding="utf-8").strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON stroke specification: {exc}") from exc

    if isinstance(parsed, dict):
        if "strokes" in parsed and isinstance(parsed["strokes"], list):
            parsed = parsed["strokes"]
        else:
            parsed = [parsed]

    if not isinstance(parsed, list):
        raise ValueError("Liquify stroke specification must be a JSON array of strokes")

    return [LiquifyStroke.from_dict(item) for item in parsed]


class LiquifyCommand(QUndoCommand):
    """Undoable command applying a liquify mesh deformation to a layer."""

    def __init__(self, doc: Any, layer: Any, new_image: QImage):
        super().__init__("Liquify")
        self.doc = doc
        self.layer = layer
        self.old_image = QImage(layer.image)
        self.new_image = QImage(new_image)
        self._applied = True

    def _swap(self, image: QImage) -> None:
        dirty = self.layer.bounds()
        self.layer.image = QImage(image)
        self.doc.notify_pixels(dirty.united(self.layer.bounds()))
        self.doc.notify_structure()

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        self._swap(self.new_image)

    def undo(self) -> None:
        self._swap(self.old_image)
