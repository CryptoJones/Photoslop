# Filters

All filters are selection-aware (mask-confined; feathered selections blend at
the edge) and land as one undo step.

- **Gaussian Blur** — radius in px (triple box-blur approximation, cumsum-
  based, O(n) in pixels).
- **Unsharp Mask** — amount in percent over a fixed radius.
- **Tilt-Shift** — keep a horizontal band sharp (centre, band, transition)
  and blur outward to the given radius.

Filters applied to a smart-object layer record themselves for
**Re-apply Smart Filters** — see [Layers](layers.md).
