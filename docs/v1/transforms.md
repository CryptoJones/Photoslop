# Transforms

All transform sessions preview via painter transforms (no resampling until
commit — one resample total) and land as a single undoable command. `Enter`
commits, `Esc` cancels.

- **Free Transform** (`Ctrl+T`): scale/rotate/translate with handles;
  `Ctrl`-drag corners for skew/distort/perspective (quad-to-quad).
- **Warp** (`Ctrl+Shift+T`): a 3×3 mesh of control points; piecewise
  projective patches.
- **Perspective Warp** (`Shift+P` tool): define the plane's quad, then drag
  corners — bounded projective re-render (safe across the vanishing line).
- **Puppet Warp** (`Shift+Y` tool): click pins (anchors hold, drags bend);
  inverse-distance-weighted displacement with bilinear sampling.
- **Liquify** (`Y` tool): brush-local pixel pushing.
- **Rotate**: Image → Rotate 90°/180°/flip (exact), or **arbitrary angle**
  (canvas grows to the rotated bounding box; undo restores pre-rotation
  refs exactly).
- **Content-Aware Scale** (Image menu): seam carving, shrink *and* grow
  (distinct-seam insertion), up to ~4× per pass.
