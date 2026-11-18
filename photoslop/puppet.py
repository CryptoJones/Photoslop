# SPDX-License-Identifier: Apache-2.0
"""Puppet Warp: 2D triangle mesh deformation via As-Rigid-As-Possible (ARAP) solver.

References:
- Sorkine & Alexa (2007): "As-Rigid-As-Possible Surface Modeling"
- Igarashi et al. (2005): "As-Rigid-As-Possible Shape Manipulation"
- Liu et al. (2008): "A Local/Global Approach to Mesh Parameterization"

The solver alternates between local rotation estimation (closed-form 2D polar
decomposition / SVD) and a global linear solve satisfying pin position
constraints. Transient memory stays bounded by rasterizing triangles directly
into a tightly-bounded layer buffer (DD-001).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QTransform,
    QUndoCommand,
)

from photoslop.cursors import CursorIntent
from photoslop.tools import Tool, ToolOptions


@dataclass
class PuppetPin:
    """A control pin placed on the layer for mesh deformation."""

    rest_pos: np.ndarray  # [x, y] in rest coordinates
    target_pos: np.ndarray  # [x, y] in current/target coordinates
    depth: int = 0  # overlap priority (higher = rendered in front)
    rotation: float = 0.0  # degrees (pin rotation around rest_pos)
    vertex_idx: int = -1  # mapped vertex in the mesh


@dataclass
class PuppetMesh:
    """2D triangle mesh covering the active region of a layer."""

    vertices: np.ndarray  # (N, 2) rest positions [x, y]
    deformed_vertices: np.ndarray  # (N, 2) deformed positions [x, y]
    triangles: np.ndarray  # (M, 3) vertex indices
    adj: list[list[int]]  # adjacency list per vertex
    components: list[list[int]]  # connected component vertex index lists
    spacing: int  # grid spacing in pixels


def generate_mesh(
    image: QImage,
    spacing: int = 20,
    mask: QImage | None = None,
) -> PuppetMesh:
    """Generate a uniform 2D triangle mesh covering the non-transparent alpha region.

    If the image has non-zero alpha, only cells containing non-transparent pixels
    (plus 1-cell border margin) receive triangles. If the entire image is opaque or
    alpha is uniform, the full bounds are triangulated.
    """
    w, h = image.width(), image.height()
    if w < 2 or h < 2:
        # Trivial fallback
        v = np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]], dtype=np.float64)
        t = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
        adj = [[1, 2, 3], [0, 2], [0, 1, 3], [0, 2]]
        return PuppetMesh(v, v.copy(), t, adj, [[0, 1, 2, 3]], spacing)

    # Extract alpha channel
    from photoslop.npimage import view_u32

    # Ensure format with alpha
    if image.format() not in (
        QImage.Format.Format_ARGB32,
        QImage.Format.Format_ARGB32_Premultiplied,
    ):
        img_argb = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    else:
        img_argb = image

    arr = view_u32(img_argb)
    alpha = (arr >> np.uint32(24)).astype(np.uint8)
    if mask is not None:
        mask_w, mask_h = mask.width(), mask.height()
        if mask_w == w and mask_h == h:
            mask_bpl = mask.bytesPerLine()
            mask_buf = np.frombuffer(mask.bits(), dtype=np.uint8, count=mask_h * mask_bpl).reshape(
                mask_h, mask_bpl
            )[:, :mask_w]
            alpha = ((alpha.astype(np.uint16) * mask_buf) // 255).astype(np.uint8)

    has_transparency = np.any(alpha < 255)
    any_opaque = np.any(alpha > 0)

    if not any_opaque:
        # All transparent fallback: single quad
        v = np.array([[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]], dtype=np.float64)
        t = np.array([[0, 1, 2], [0, 2, 3]], dtype=np.int32)
        adj = [[1, 2, 3], [0, 2], [0, 1, 3], [0, 2]]
        return PuppetMesh(v, v.copy(), t, adj, [[0, 1, 2, 3]], spacing)

    spacing = max(6, int(spacing))

    # Grid coordinates
    xs = list(range(0, w, spacing))
    if xs[-1] < w:
        xs.append(w)
    ys = list(range(0, h, spacing))
    if ys[-1] < h:
        ys.append(h)

    num_x = len(xs)
    num_y = len(ys)

    # Active grid cells
    active_cells = np.zeros((num_y - 1, num_x - 1), dtype=bool)

    if not has_transparency:
        active_cells[:, :] = True
    else:
        # Determine which cells contain non-zero alpha
        for r in range(num_y - 1):
            y0, y1 = ys[r], ys[r + 1]
            for c in range(num_x - 1):
                x0, x1 = xs[c], xs[c + 1]
                if np.any(alpha[y0:y1, x0:x1] > 0):
                    active_cells[r, c] = True

        # Dilate active cells by 1 neighbor to avoid clipping antialiased boundaries
        dilated = active_cells.copy()
        for r in range(num_y - 1):
            for c in range(num_x - 1):
                if active_cells[r, c]:
                    r_min, r_max = max(0, r - 1), min(num_y - 1, r + 2)
                    c_min, c_max = max(0, c - 1), min(num_x - 1, c + 2)
                    dilated[r_min:r_max, c_min:c_max] = True
        active_cells = dilated

    # If no cell survived (extremely rare edge case), mark all
    if not np.any(active_cells):
        active_cells[:, :] = True

    # Build vertex mapping
    grid_to_vidx: dict[tuple[int, int], int] = {}
    vertices_list: list[list[float]] = []

    def get_vidx(r: int, c: int) -> int:
        key = (r, c)
        if key not in grid_to_vidx:
            grid_to_vidx[key] = len(vertices_list)
            vertices_list.append([float(xs[c]), float(ys[r])])
        return grid_to_vidx[key]

    triangles_list: list[list[int]] = []
    for r in range(num_y - 1):
        for c in range(num_x - 1):
            if active_cells[r, c]:
                v00 = get_vidx(r, c)
                v10 = get_vidx(r + 1, c)
                v01 = get_vidx(r, c + 1)
                v11 = get_vidx(r + 1, c + 1)
                # Two triangles per quad
                triangles_list.append([v00, v10, v11])
                triangles_list.append([v00, v11, v01])

    v_coords = np.array(vertices_list, dtype=np.float64)
    triangles = np.array(triangles_list, dtype=np.int32)
    n_verts = len(v_coords)

    # Build adjacency
    adj_set: list[set[int]] = [set() for _ in range(n_verts)]
    for tri in triangles:
        a, b, c = tri
        adj_set[a].add(b)
        adj_set[a].add(c)
        adj_set[b].add(a)
        adj_set[b].add(c)
        adj_set[c].add(a)
        adj_set[c].add(b)
    adj = [sorted(s) for s in adj_set]

    # Find connected components
    visited = [False] * n_verts
    components: list[list[int]] = []
    for i in range(n_verts):
        if not visited[i]:
            comp: list[int] = []
            queue = [i]
            visited[i] = True
            while queue:
                curr = queue.pop()
                comp.append(curr)
                for nbr in adj[curr]:
                    if not visited[nbr]:
                        visited[nbr] = True
                        queue.append(nbr)
            components.append(comp)

    return PuppetMesh(
        vertices=v_coords,
        deformed_vertices=v_coords.copy(),
        triangles=triangles,
        adj=adj,
        components=components,
        spacing=spacing,
    )


def solve_arap(
    mesh: PuppetMesh,
    pins: list[PuppetPin],
    mode: str = "normal",
    iterations: int = 10,
) -> np.ndarray:
    """Run the As-Rigid-As-Possible (ARAP) iterative deformation solver.

    Modes:
    - 'rigid': stiff rotation penalty (isometric, scale constrained to 1.0)
    - 'normal': balanced rotation and moderate stretch
    - 'distort': allows similarity / affine stretching to satisfy constraints

    Returns the deformed vertex coordinates array of shape (N, 2).
    """
    v_rest = mesh.vertices
    n_verts = len(v_rest)
    if n_verts == 0:
        return np.zeros((0, 2), dtype=np.float64)

    if not pins:
        mesh.deformed_vertices = v_rest.copy()
        return mesh.deformed_vertices

    # Update pin vertex mappings
    for pin in pins:
        if pin.vertex_idx < 0 or pin.vertex_idx >= n_verts:
            dists = np.hypot(v_rest[:, 0] - pin.rest_pos[0], v_rest[:, 1] - pin.rest_pos[1])
            pin.vertex_idx = int(np.argmin(dists))

    # Single pin case: pure translation
    if len(pins) == 1:
        pin = pins[0]
        delta = pin.target_pos - pin.rest_pos
        if abs(pin.rotation) > 1e-3:
            # Single pin with rotation: rotate around the pin
            theta = np.radians(pin.rotation)
            c, s = np.cos(theta), np.sin(theta)
            r_mat = np.array([[c, -s], [s, c]])
            diff = v_rest - pin.rest_pos
            mesh.deformed_vertices = (diff @ r_mat.T) + pin.target_pos
        else:
            mesh.deformed_vertices = v_rest + delta
        return mesh.deformed_vertices

    v_cur = mesh.deformed_vertices.copy()

    # Pre-build rotation overrides for rotated pins
    pin_rotations: dict[int, np.ndarray] = {}
    for pin in pins:
        if abs(pin.rotation) > 1e-3:
            theta = np.radians(pin.rotation)
            c, s = np.cos(theta), np.sin(theta)
            pin_rotations[pin.vertex_idx] = np.array([[c, -s], [s, c]])

    # Solve component by component
    for comp in mesh.components:
        comp_set = set(comp)
        comp_pins = [p for p in pins if p.vertex_idx in comp_set]

        if not comp_pins:
            # No pins in this component: keep it at rest
            v_cur[comp] = v_rest[comp]
            continue

        if len(comp_pins) == 1:
            # One pin in component: translation (+ optional rotation)
            p = comp_pins[0]
            delta = p.target_pos - p.rest_pos
            if abs(p.rotation) > 1e-3:
                theta = np.radians(p.rotation)
                c, s = np.cos(theta), np.sin(theta)
                r_mat = np.array([[c, -s], [s, c]])
                diff = v_rest[comp] - p.rest_pos
                v_cur[comp] = (diff @ r_mat.T) + p.target_pos
            else:
                v_cur[comp] = v_rest[comp] + delta
            continue

        # Multiple pins in this component: ARAP solve
        comp_n = len(comp)
        global_to_local = {g: loc for loc, g in enumerate(comp)}

        # Local Laplacian matrix
        laplacian = np.zeros((comp_n, comp_n), dtype=np.float64)
        for loc, g in enumerate(comp):
            for nbr in mesh.adj[g]:
                if nbr in global_to_local:
                    nbr_loc = global_to_local[nbr]
                    laplacian[loc, loc] += 1.0
                    laplacian[loc, nbr_loc] = -1.0

        # Pin weights
        w_pin = 10000.0
        a_mat = laplacian.copy()
        for p in comp_pins:
            p_loc = global_to_local[p.vertex_idx]
            a_mat[p_loc, p_loc] += w_pin

        # Pre-factorize if possible, or solve with np.linalg.solve
        comp_v = v_rest[comp]
        comp_v_cur = v_cur[comp].copy()

        # Mode configuration
        is_rigid = mode == "rigid"
        is_distort = mode == "distort"

        for _ in range(iterations):
            # --- Local Step: compute optimal T_i for each vertex ---
            t_matrices = [None] * comp_n
            for loc, g in enumerate(comp):
                if g in pin_rotations:
                    t_matrices[loc] = pin_rotations[g]
                    continue

                nbrs = [nbr for nbr in mesh.adj[g] if nbr in global_to_local]
                if not nbrs:
                    t_matrices[loc] = np.eye(2)
                    continue

                nbr_locs = [global_to_local[n] for n in nbrs]
                e = comp_v[loc] - comp_v[nbr_locs]  # shape (K, 2)
                e_prime = comp_v_cur[loc] - comp_v_cur[nbr_locs]  # shape (K, 2)

                # Covariance matrix S = e_prime.T @ e
                cov = e_prime.T @ e
                a = cov[0, 0] + cov[1, 1]
                b = cov[1, 0] - cov[0, 1]
                r = math.hypot(a, b)

                if r > 1e-9:
                    c, s = a / r, b / r
                    r_mat = np.array([[c, -s], [s, c]])
                else:
                    r_mat = np.eye(2)

                if is_rigid:
                    t_matrices[loc] = r_mat
                else:
                    # Estimate scale factor
                    rest_sq_sum = np.sum(e**2)
                    if rest_sq_sum > 1e-9:
                        raw_scale = r / rest_sq_sum
                        if is_distort:
                            scale = max(0.1, min(raw_scale, 3.0))
                        else:  # normal mode
                            scale = 1.0 + 0.5 * (raw_scale - 1.0)
                            scale = max(0.65, min(scale, 1.5))
                        t_matrices[loc] = scale * r_mat
                    else:
                        t_matrices[loc] = r_mat

            # --- Global Step: build RHS B and solve ---
            b_mat = np.zeros((comp_n, 2), dtype=np.float64)
            for loc, g in enumerate(comp):
                t_i = t_matrices[loc]
                for nbr in mesh.adj[g]:
                    if nbr in global_to_local:
                        nbr_loc = global_to_local[nbr]
                        t_j = t_matrices[nbr_loc]
                        t_avg = 0.5 * (t_i + t_j)
                        e_ij = comp_v[loc] - comp_v[nbr_loc]
                        b_mat[loc] += t_avg @ e_ij

            for p in comp_pins:
                p_loc = global_to_local[p.vertex_idx]
                b_mat[p_loc] += w_pin * p.target_pos

            comp_v_cur = np.linalg.solve(a_mat, b_mat)

        # Enforce exact pin positions
        for p in comp_pins:
            p_loc = global_to_local[p.vertex_idx]
            comp_v_cur[p_loc] = p.target_pos

        v_cur[comp] = comp_v_cur

    mesh.deformed_vertices = v_cur
    return mesh.deformed_vertices


def compute_triangle_depths(
    mesh: PuppetMesh,
    pins: list[PuppetPin],
) -> np.ndarray:
    """Compute per-triangle depth for depth-ordered rasterization.

    Each triangle inherits the depth of its nearest pin (based on centroid distance).
    """
    triangles = mesh.triangles
    num_triangles = len(triangles)
    if num_triangles == 0 or not pins:
        return np.zeros(num_triangles, dtype=np.int32)

    v_coords = mesh.vertices
    centroids = np.mean(v_coords[triangles], axis=1)  # shape (M, 2)
    pin_positions = np.array([p.rest_pos for p in pins], dtype=np.float64)  # (K, 2)
    pin_depths = np.array([p.depth for p in pins], dtype=np.int32)  # (K,)

    # Pairwise distances from each centroid to each pin
    # (M, 1, 2) - (1, K, 2) -> (M, K, 2)
    diff = centroids[:, np.newaxis, :] - pin_positions[np.newaxis, :, :]
    dists_sq = np.sum(diff**2, axis=-1)  # (M, K)
    nearest_pins = np.argmin(dists_sq, axis=-1)  # (M,)

    return pin_depths[nearest_pins]


def rasterize_mesh(
    image: QImage,
    mesh: PuppetMesh,
    pins: list[PuppetPin] | None = None,
    mask: QImage | None = None,
) -> tuple[QImage, QPoint, QImage | None]:
    """Rasterize deformed triangles directly into a tightly-bounded layer buffer (DD-001).

    Performs affine texture warping per triangle with depth ordering.
    Returns (warped_image, new_offset_relative_to_original, warped_mask).
    """
    v_def = mesh.deformed_vertices
    triangles = mesh.triangles
    if len(v_def) == 0 or len(triangles) == 0:
        return QImage(image), QPoint(0, 0), (QImage(mask) if mask else None)

    min_x = np.min(v_def[:, 0])
    max_x = np.max(v_def[:, 0])
    min_y = np.min(v_def[:, 1])
    max_y = np.max(v_def[:, 1])

    out_x0 = int(math.floor(min_x)) - 1
    out_y0 = int(math.floor(min_y)) - 1
    out_w = max(1, int(math.ceil(max_x)) - out_x0 + 2)
    out_h = max(1, int(math.ceil(max_y)) - out_y0 + 2)

    # Tight target buffer (DD-001)
    warped = QImage(out_w, out_h, QImage.Format.Format_ARGB32_Premultiplied)
    warped.fill(0)

    warped_mask = None
    if mask is not None:
        warped_mask = QImage(out_w, out_h, QImage.Format.Format_Grayscale8)
        warped_mask.fill(0)

    # Order triangles by depth
    if pins:
        triangle_depths = compute_triangle_depths(mesh, pins)
        sorted_indices = sorted(range(len(triangles)), key=lambda idx: (triangle_depths[idx], idx))
    else:
        sorted_indices = list(range(len(triangles)))

    v_rest = mesh.vertices

    p = QPainter(warped)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    p.translate(-out_x0, -out_y0)

    mp = None
    if warped_mask is not None:
        mp = QPainter(warped_mask)
        mp.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        mp.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        mp.translate(-out_x0, -out_y0)

    for idx in sorted_indices:
        i0, i1, i2 = triangles[idx]
        u0, u1, u2 = v_rest[i0], v_rest[i1], v_rest[i2]
        v0, v1, v2 = v_def[i0], v_def[i1], v_def[i2]

        u_mat = np.array([[u0[0], u0[1], 1.0], [u1[0], u1[1], 1.0], [u2[0], u2[1], 1.0]])
        # Area check to avoid singular rest triangles
        det = np.linalg.det(u_mat)
        if abs(det) < 1e-6:
            continue

        v_mat = np.array([v0, v1, v2])
        m_aff = np.linalg.solve(u_mat, v_mat)
        transform = QTransform(
            m_aff[0, 0], m_aff[0, 1], m_aff[1, 0], m_aff[1, 1], m_aff[2, 0], m_aff[2, 1]
        )

        poly = QPolygonF([QPointF(v0[0], v0[1]), QPointF(v1[0], v1[1]), QPointF(v2[0], v2[1])])
        clip_path = QPainterPath()
        clip_path.addPolygon(poly)

        p.save()
        p.setClipPath(clip_path)
        p.setTransform(transform, True)
        p.drawImage(QPointF(0, 0), image)
        p.restore()

        if mp is not None:
            mp.save()
            mp.setClipPath(clip_path)
            mp.setTransform(transform, True)
            mp.drawImage(QPointF(0, 0), mask)
            mp.restore()

    p.end()
    if mp is not None:
        mp.end()

    return warped, QPoint(out_x0, out_y0), warped_mask


class PuppetWarpCommand(QUndoCommand):
    """Undoable command committing a puppet warp deformation to a layer."""

    def __init__(
        self,
        doc,
        layer,
        old_image: QImage,
        old_offset: QPoint,
        new_image: QImage,
        new_offset: QPoint,
        old_mask: QImage | None = None,
        new_mask: QImage | None = None,
    ):
        super().__init__("Puppet Warp")
        self.doc = doc
        self.layer = layer
        self.old_image = old_image
        self.old_offset = QPoint(old_offset)
        self.new_image = new_image
        self.new_offset = QPoint(new_offset)
        self.old_mask = old_mask
        self.new_mask = new_mask
        self._applied = True

    def _swap(self, image: QImage, offset: QPoint, mask: QImage | None) -> None:
        dirty = self.layer.bounds()
        self.layer.image = QImage(image)
        self.layer.offset = QPoint(offset)
        self.layer.mask = QImage(mask) if mask is not None else None
        self.doc.notify_pixels(dirty.united(self.layer.bounds()))
        self.doc.notify_structure()

    def redo(self) -> None:
        if self._applied:
            self._applied = False
            return
        self._swap(self.new_image, self.new_offset, self.new_mask)

    def undo(self) -> None:
        self._swap(self.old_image, self.old_offset, self.old_mask)


class PuppetSession:
    """Active interactive Puppet Warp session on a layer."""

    def __init__(self, doc, layer) -> None:
        self.doc = doc
        self.layer = layer
        self.base_image = QImage(layer.image)
        self.base_offset = QPoint(layer.offset)
        self.base_mask = QImage(layer.mask) if layer.mask is not None else None

        self.density: str = "normal"  # "low", "normal", "high"
        self.mode: str = "normal"  # "rigid", "normal", "distort"
        self.mesh_visible: bool = True
        self.pins: list[PuppetPin] = []
        self.selected_pin_idx: int | None = None

        self._init_mesh()

    def _spacing_for_density(self) -> int:
        if self.density == "low":
            return 35
        elif self.density == "high":
            return 12
        return 20  # normal

    def _init_mesh(self) -> None:
        spacing = self._spacing_for_density()
        self.mesh = generate_mesh(self.base_image, spacing=spacing, mask=self.base_mask)
        # Re-map existing pins if any
        for pin in self.pins:
            pin.vertex_idx = -1
        if self.pins:
            solve_arap(self.mesh, self.pins, mode=self.mode)

    def set_density(self, density: str) -> None:
        if density in ("low", "normal", "high") and density != self.density:
            self.density = density
            self._init_mesh()
            self.doc.notify_structure()

    def set_mode(self, mode: str) -> None:
        if mode in ("rigid", "normal", "distort") and mode != self.mode:
            self.mode = mode
            if self.pins:
                solve_arap(self.mesh, self.pins, mode=self.mode)
            self.doc.notify_structure()

    def add_pin(self, canvas_pos: QPointF) -> int:
        """Add a pin at canvas coordinates. Returns its index."""
        local = canvas_pos - QPointF(self.base_offset)
        pos_np = np.array([local.x(), local.y()], dtype=np.float64)
        pin = PuppetPin(rest_pos=pos_np.copy(), target_pos=pos_np.copy())
        self.pins.append(pin)
        self.selected_pin_idx = len(self.pins) - 1
        solve_arap(self.mesh, self.pins, mode=self.mode)
        self._update_live_image()
        return self.selected_pin_idx

    def remove_pin(self, index: int) -> None:
        if 0 <= index < len(self.pins):
            self.pins.pop(index)
            if self.selected_pin_idx == index:
                self.selected_pin_idx = None
            elif self.selected_pin_idx is not None and self.selected_pin_idx > index:
                self.selected_pin_idx -= 1
            solve_arap(self.mesh, self.pins, mode=self.mode)
            self._update_live_image()
            self.doc.notify_structure()

    def move_pin(self, index: int, new_canvas_pos: QPointF) -> None:
        if 0 <= index < len(self.pins):
            local = new_canvas_pos - QPointF(self.base_offset)
            self.pins[index].target_pos = np.array([local.x(), local.y()], dtype=np.float64)
            solve_arap(self.mesh, self.pins, mode=self.mode)
            self._update_live_image()

    def rotate_pin(self, index: int, angle_degrees: float) -> None:
        if 0 <= index < len(self.pins):
            self.pins[index].rotation = angle_degrees
            solve_arap(self.mesh, self.pins, mode=self.mode)
            self._update_live_image()

    def _update_live_image(self) -> None:
        """Update active layer image live for callers/tests reading layer pixels."""
        if not self.pins:
            self.layer.image = QImage(self.base_image)
            return
        warped, local_off, _ = rasterize_mesh(self.base_image, self.mesh, self.pins)
        # Match size if possible or update
        if warped.size() == self.base_image.size() and local_off == QPoint(0, 0):
            self.layer.image = warped
        else:
            self.layer.image = warped
            self.layer.offset = self.base_offset + local_off
        self.doc.notify_pixels(self.layer.bounds())

    def change_pin_depth(self, index: int, delta: int) -> None:
        if 0 <= index < len(self.pins):
            self.pins[index].depth += delta
            self.doc.notify_structure()

    def draw_preview(self, painter: QPainter) -> None:
        """Draw deformed layer preview directly on canvas painter without intermediate buffer."""
        if not self.pins or len(self.mesh.deformed_vertices) == 0:
            painter.drawImage(self.base_offset, self.base_image)
            return

        v_rest = self.mesh.vertices
        v_def = self.mesh.deformed_vertices
        triangles = self.mesh.triangles

        triangle_depths = compute_triangle_depths(self.mesh, self.pins)
        sorted_indices = sorted(range(len(triangles)), key=lambda idx: (triangle_depths[idx], idx))

        off_x, off_y = self.base_offset.x(), self.base_offset.y()

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        for idx in sorted_indices:
            i0, i1, i2 = triangles[idx]
            u0, u1, u2 = v_rest[i0], v_rest[i1], v_rest[i2]
            v0, v1, v2 = v_def[i0], v_def[i1], v_def[i2]

            u_mat = np.array([[u0[0], u0[1], 1.0], [u1[0], u1[1], 1.0], [u2[0], u2[1], 1.0]])
            if abs(np.linalg.det(u_mat)) < 1e-6:
                continue

            # In canvas coords
            c_v0 = [v0[0] + off_x, v0[1] + off_y]
            c_v1 = [v1[0] + off_x, v1[1] + off_y]
            c_v2 = [v2[0] + off_x, v2[1] + off_y]

            v_mat = np.array([c_v0, c_v1, c_v2])
            m_aff = np.linalg.solve(u_mat, v_mat)
            transform = QTransform(
                m_aff[0, 0], m_aff[0, 1], m_aff[1, 0], m_aff[1, 1], m_aff[2, 0], m_aff[2, 1]
            )

            poly = QPolygonF(
                [
                    QPointF(c_v0[0], c_v0[1]),
                    QPointF(c_v1[0], c_v1[1]),
                    QPointF(c_v2[0], c_v2[1]),
                ]
            )
            clip_path = QPainterPath()
            clip_path.addPolygon(poly)

            painter.save()
            painter.setClipPath(clip_path)
            painter.setTransform(transform, True)
            painter.drawImage(QPointF(0, 0), self.base_image)
            painter.restore()

        painter.restore()

    def commit(self) -> None:
        """Apply deformation, push undo command, and free mesh transient memory (DD-001)."""
        if not self.pins:
            return

        new_image, local_offset, new_mask = rasterize_mesh(
            self.base_image,
            self.mesh,
            self.pins,
            mask=self.base_mask,
        )
        new_offset = self.base_offset + local_offset

        self.layer.image = new_image
        self.layer.offset = new_offset
        self.layer.mask = new_mask

        cmd = PuppetWarpCommand(
            self.doc,
            self.layer,
            self.base_image,
            self.base_offset,
            new_image,
            new_offset,
            self.base_mask,
            new_mask,
        )
        self.doc.undo_stack.push(cmd)

    def restore(self) -> None:
        """Cancel and restore the original layer pixels and offset."""
        self.layer.image = QImage(self.base_image)
        self.layer.offset = QPoint(self.base_offset)
        self.layer.mask = QImage(self.base_mask) if self.base_mask is not None else None


class PuppetWarpTool(Tool):
    """Puppet Warp: mesh pin deformation via As-Rigid-As-Possible (ARAP) solver.

    Interactions:
    - Click to place pins
    - Drag a pin to deform
    - Alt+drag a pin to rotate
    - [ / ] to adjust depth (send backward / bring forward)
    - Delete / Backspace to remove selected pin
    - Enter to commit, Escape to cancel
    """

    name = "puppet_warp"

    def __init__(self, options: ToolOptions) -> None:
        super().__init__(options)
        self.session: PuppetSession | None = None
        self._dragging_pin: int | None = None
        self._rotating: bool = False
        self._press_pos = QPointF()
        self._initial_rotation = 0.0

    def begin(self, doc, layer) -> None:
        self.session = PuppetSession(doc, layer)

    def commit(self, canvas=None) -> None:
        if self.session is not None:
            self.session.commit()
            self.session = None
            self._dragging_pin = None
            if canvas is not None and hasattr(canvas.editor.host, "end_puppet_warp"):
                canvas.editor.host.end_puppet_warp()
            elif canvas is not None and hasattr(canvas.editor.host, "end_transform"):
                canvas.editor.host.end_transform()

    def cancel(self, doc=None) -> None:
        if self.session is not None:
            dirty = self.session.layer.bounds()
            self.session.restore()
            self.session.doc.notify_pixels(dirty.united(self.session.layer.bounds()))
            self.session.doc.notify_structure()
            self.session = None
            self._dragging_pin = None

    def has_active_interaction(self) -> bool:
        return self.session is not None

    def _hit_pin(self, canvas, pos: QPointF) -> int | None:
        if self.session is None or not self.session.pins:
            return None
        tol = 10.0 / max(canvas.zoom, 0.01)
        tol_sq = tol * tol
        off = QPointF(self.session.base_offset)
        for i, pin in enumerate(self.session.pins):
            tgt_canvas = QPointF(pin.target_pos[0] + off.x(), pin.target_pos[1] + off.y())
            d_sq = (tgt_canvas.x() - pos.x()) ** 2 + (tgt_canvas.y() - pos.y()) ** 2
            if d_sq <= tol_sq:
                return i
        return None

    def cursor_intent(
        self, doc, canvas, pos, modifiers=Qt.KeyboardModifier.NoModifier, dragging=False
    ):
        if self.session is None or pos is None:
            return CursorIntent("forbidden", valid=False)
        hit = self._hit_pin(canvas, pos)
        if hit is not None:
            if modifiers & Qt.KeyboardModifier.AltModifier:
                return CursorIntent("rotate")
            return CursorIntent("node")
        return CursorIntent("crosshair")

    @property
    def _drag(self) -> int | None:
        return self._dragging_pin

    @_drag.setter
    def _drag(self, val: int | None) -> None:
        self._dragging_pin = val

    @property
    def pins(self) -> list[list[QPointF]]:
        if self.session is None:
            return []
        return [
            [
                QPointF(p.rest_pos[0], p.rest_pos[1]),
                QPointF(p.target_pos[0], p.target_pos[1]),
            ]
            for p in self.session.pins
        ]

    def press(self, doc, canvas, pos, ev):
        if self.session is None:
            if doc.active_layer is None:
                return
            self.begin(doc, doc.active_layer)
        hit = self._hit_pin(canvas, pos)
        alt = ev is not None and bool(ev.modifiers() & Qt.KeyboardModifier.AltModifier)
        if hit is not None:
            self.session.selected_pin_idx = hit
            self._dragging_pin = hit
            self._rotating = alt
            self._press_pos = pos
            self._initial_rotation = self.session.pins[hit].rotation
        else:
            # Clicked canvas: place a new pin
            self.session.add_pin(pos)
            self._dragging_pin = None
            self._rotating = False
            self._press_pos = pos
            self._initial_rotation = 0.0
        doc.notify_structure()
        canvas.update()

    def move(self, doc, canvas, pos, ev):
        if self.session is None or self._dragging_pin is None:
            return
        if self._rotating:
            off = QPointF(self.session.base_offset)
            pin = self.session.pins[self._dragging_pin]
            pin_canvas = QPointF(pin.target_pos[0] + off.x(), pin.target_pos[1] + off.y())
            dy = self._press_pos.y() - pin_canvas.y()
            dx = self._press_pos.x() - pin_canvas.x()
            a0 = math.degrees(math.atan2(dy, dx))
            a1 = math.degrees(math.atan2(pos.y() - pin_canvas.y(), pos.x() - pin_canvas.x()))
            angle = self._initial_rotation + (a1 - a0)
            self.session.rotate_pin(self._dragging_pin, angle)
        else:
            self.session.move_pin(self._dragging_pin, pos)
        doc.notify_structure()
        canvas.update()

    def release(self, doc, canvas, pos, ev):
        self._dragging_pin = None
        self._rotating = False

    def overlay(self, doc, painter, canvas):
        if self.session is None:
            return

        z = canvas.zoom
        off_x, off_y = self.session.base_offset.x(), self.session.base_offset.y()

        # 1. Mesh lines
        if self.session.mesh_visible and len(self.session.mesh.deformed_vertices) > 0:
            v_def = self.session.mesh.deformed_vertices
            triangles = self.session.mesh.triangles
            painter.setPen(QPen(QColor(140, 200, 255, 110), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for i0, i1, i2 in triangles:
                p0 = QPointF((v_def[i0, 0] + off_x) * z, (v_def[i0, 1] + off_y) * z)
                p1 = QPointF((v_def[i1, 0] + off_x) * z, (v_def[i1, 1] + off_y) * z)
                p2 = QPointF((v_def[i2, 0] + off_x) * z, (v_def[i2, 1] + off_y) * z)
                painter.drawLine(p0, p1)
                painter.drawLine(p1, p2)
                painter.drawLine(p2, p0)

        # 2. Control pins
        for i, pin in enumerate(self.session.pins):
            cx = (pin.target_pos[0] + off_x) * z
            cy = (pin.target_pos[1] + off_y) * z
            center = QPointF(cx, cy)
            is_selected = i == self.session.selected_pin_idx

            # Outer ring
            painter.setPen(QPen(QColor(0, 0, 0, 230), 1.5))
            if is_selected:
                painter.setBrush(QColor(255, 190, 20, 240))  # gold/yellow
            else:
                painter.setBrush(QColor(245, 245, 245, 230))  # off-white
            painter.drawEllipse(center, 6, 6)

            # Center core
            painter.setBrush(QColor(40, 40, 40, 240))
            painter.drawEllipse(center, 2, 2)

            # Rotation indicator
            if is_selected and abs(pin.rotation) > 0.1:
                painter.setPen(QPen(QColor(255, 80, 40, 200), 2))
                rad = math.radians(pin.rotation)
                rx = cx + 12 * math.cos(rad)
                ry = cy + 12 * math.sin(rad)
                painter.drawLine(center, QPointF(rx, ry))

            # Depth badge if depth != 0
            if pin.depth != 0:
                painter.setFont(QFont("sans-serif", 8, QFont.Weight.Bold))
                painter.setPen(QPen(QColor(0, 0, 0, 220), 1))
                painter.drawText(
                    QRectF(cx + 8, cy - 8, 24, 16),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    f"{pin.depth:+d}",
                )
