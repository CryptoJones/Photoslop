# Layers

Every layer is one premultiplied ARGB32 buffer (copy-on-write shared) with a
name, offset, visibility, opacity, and blend mode. The Layers panel manages
the stack; the History panel shows every undoable step.

## Vector layers (parametric Shape and Pen)
Shape and Pen layers remember their geometry (`vector_data`, saved in .ora
as `photoslop-vector`): click with the same tool to re-edit with drag
handles, and document scale/rotate/flip **re-render from the parameters**
instead of resampling pixels — edges stay crisp at any size. Painting on a
vector layer keeps the pixels but geometry edits will re-render over them;
arbitrary-angle layer rotation drops the layer to plain raster.

## Blend modes
13 modes with OpenRaster interop: normal, multiply, screen, overlay, darken,
lighten, color-dodge, color-burn, hard-light, soft-light, difference,
exclusion, plus (addition).

## Masks & clipping
- **Layer masks** (Layer → Add Mask): Grayscale8, white = opaque; paint the
  mask like any layer; Apply Mask bakes it.
- **Clipping masks** (`Ctrl+Alt+G`): confine a layer to the alpha of the
  layer below.

## Groups
`Ctrl+G` groups selected layers (flat tag model — members move as one unit
with the Move tool). Groups can carry **group opacity and blend mode**
(Layer → Group Opacity/Blend), composited as a single unit.

## Live layer effects (styles)
Layer Style → **Drop Shadow… / Outer Glow… / Stroke…** attach non-destructive
effects rendered at composite time — shadow/glow beneath the fill, stroke
above. The layer's own pixels never change; effects follow every edit and Move
tool drag. Appearance caches use layer-local coordinates, so movement is cheap
and effects re-derive only when pixels change. **Layer Style → Clear** removes
all. Effects persist in ORA.

## Fill opacity
Layer Style → **Fill Opacity…** scales only the layer's own pixels — effects
keep full strength. Fill 0% + Stroke = outlined shapes/text with an invisible
interior. Distinct from layer opacity, which scales everything.

## Smart objects & smart filters
- **Convert to Smart Object** snapshots the layer's pristine pixels;
  **Restore Smart Object Original** brings them back (undoable).
- Filters applied to a smart object **record themselves**; **Re-apply Smart
  Filters** restores the source and replays the stack as one undo step.
  Both the source and the filter stack persist in ORA.

## Adjustment layers
Layer → New Adjustment Layer (Levels): a non-destructive LUT applied to the
composite below it, honoured by the canvas, flatten, and the colour sampler.

## Merging
`Ctrl+E` merge down · `Ctrl+Shift+E` merge visible · `Ctrl+Shift+Alt+E`
stamp visible to a new layer.
