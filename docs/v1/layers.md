# Layers

Every layer is one premultiplied ARGB32 buffer (copy-on-write shared) with a
name, offset, visibility, opacity, and blend mode. The Layers panel manages
the stack; the History panel shows every undoable step.

## New layer from an image file
**Layer ▸ New Layer from Image…** (`Ctrl+Shift+I`) brings image files into the
document you already have open — select several and each becomes its own layer
on top of the stack, in one undo step for the whole selection. This is separate
from **File ▸ Open** on purpose: Open is how a file *becomes* a document, this
is how one *joins* the document already open, so neither command has to guess
which you meant.

An imported layer keeps every source pixel at its own size and is centred, so
a photo larger than the canvas hangs off the edges rather than being
downscaled — reach for Free Transform (`Ctrl+T`) to fit it. When that
happens, the import asks whether to **Expand Canvas** — grow the canvas to
the union of itself and every imported layer, one undo step with the import —
or **Keep Canvas Size**, which drops nothing: the layer overhangs at full
size and only *looks* cropped. Layered sources (`.ora`, `.svg`) arrive
flattened into the single layer.

The same command sits on the layer list's own **right-click menu**, next to
New Layer, Duplicate, Delete and Merge Down — the stack operations reachable
where the stack already is, rather than only up in the Layer menu.

Headless mirror: `photoslop-cli in.png --import-layer photo.jpg`
(add `--expand-canvas` for the prompt's expand choice — it reveals every
overhanging layer pixel, and is a no-op when everything fits)
([CLI](cli.md)). The iOS edition has the same command as **new layer from
photo** in the layer list, but scales each photo to fit the canvas — a
`.photoslop` layer image must be exactly canvas-sized
([iPadOS](ipados.md#importing-a-photo-as-a-layer)).

## Cropping one layer
The Crop tool (`C`) resizes the *document* by default: the canvas shrinks to
the box and every layer keeps all of its pixels, shifted (nothing is thrown
away, which is what makes it instant). Tick **Layer only** in the tool options
and the same rectangle does the opposite — it trims the **active layer** to
the box and discards the pixels outside it, while the canvas size and every
other layer stay exactly as they were.

Because it is a layer-local geometry change, a cropped Shape, Pen or Text
layer drops to plain raster, the same way an arbitrary-angle layer rotation
does — a cropped shape is no longer the shape its parameters describe. Undo
restores the pixels *and* the parametric record. A box that misses the active
layer entirely is refused rather than cropping it to nothing; the rectangle
stays up so you can redraw it.

Headless mirror: `photoslop-cli in.png --crop-layer X,Y,W,H` (add
`--all-layers` to trim every visible layer, `--layer N` to pick one) — the
rectangle is in document coordinates, exactly like `--crop`
([CLI](cli.md)).

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

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
