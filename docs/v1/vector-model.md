# Native vector object model

Photoslop stores vector-backed layers as schema-versioned JSON alongside a
standard OpenRaster PNG fallback. Other ORA applications display the fallback;
Photoslop renders native geometry directly through QPainterPath at the current
viewport/output scale, so zooming no longer enlarges the fallback pixels.

## Schema v1

Each object has a stable `id`, `name`, `type`, optional `parent_id`, local
`geometry`, affine `transform`, `appearance`, object opacity/blend, optional
text metadata, and an `extensions` object. Path geometry is an ordered command
stream:

- `M` and `L` carry an endpoint and node type.
- `C` carries explicit incoming/outgoing cubic control points plus endpoint and
  corner/smooth/symmetric node metadata.
- `Z` closes the subpath.

Appearance independently records fill/stroke paint, winding/even-odd fill rule,
stroke width, cap, join, miter limit, dash pattern/offset, and whether stroke
width scales with the object. Solid paint is implemented in v1.23; gradient
records are forward-compatible and become editable in the construction-tools
release.

## Compatibility and migration

Legacy rect/ellipse/line/path dictionaries migrate in memory. Catmull–Rom paths
become explicit cubic commands with handles; their legacy top-level projection
is retained while existing Pen/Shape interactions migrate. Unknown schema or
vendor fields move into/persist through `extensions`. Object IDs, transforms,
appearance, text metadata, hierarchy, and extensions survive ORA round trips.

Saving writes schema v1 plus the current raster fallback. Opening and resaving a
legacy ORA preserves its visible result. Masks, clipping, and raster-only live
effects intentionally use the fallback at the required target region; ordinary
vector display/output uses direct geometry.
