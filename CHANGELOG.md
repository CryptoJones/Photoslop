# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows [SemVer](https://semver.org).

## [0.40.0] — 2026-07-02

### Added

- Layer groups (first slice): `Ctrl+G` groups the active layer with the one
  below (creating a named group), `Ctrl+Shift+G` ungroups. Grouped layers
  are tinted in the Layers panel, the Move tool drags the whole group as
  one (single undo step), and groups round-trip in `.ora` via a Photoslop
  extension.

## [0.39.0] — 2026-07-02

### Added

- Refine Selection (`Ctrl+Alt+R`): smooth (rounds corners, heals notches)
  and expand/contract (exact pixel morphology) with a live marching-ants
  preview — the working core of Select and Mask. Cancel restores the
  original selection exactly.

## [0.38.0] — 2026-07-02

### Added

- Smudge / Mixer brush (`Shift+S`): drags colour along the stroke — each
  stamp deposits the carried paint (strength = opacity) then picks up
  what's under the brush. Selection-clipped, stroke undo.

## [0.37.0] — 2026-07-02

### Added

- Distort / Skew / Perspective inside Free Transform: Ctrl+drag a corner to
  place it freely (full perspective quad via QTransform.quadToQuad),
  Ctrl+drag an edge to skew it, drag inside to move the quad. Same live
  preview, single resample on commit, exact undo.

## [0.36.0] — 2026-07-02

### Added

- Flow control for brush and eraser, with true Photoshop semantics: flow is
  how much paint each stamp lays down (builds up within a stroke); opacity
  is now a hard per-stroke ceiling — overlapping stamps in one stroke can
  never exceed it. Soft strokes composite through a per-stroke scratch
  buffer; the hard fully-opaque path stays zero-allocation.

## [0.35.0] — 2026-07-02

### Added

- Brush spacing control (5–200% of brush size) in the options bar for the
  brush, eraser, dodge, and burn soft-stamp paths and the clone stamp —
  tight spacing for smooth strokes, wide spacing for dotted/textured ones.

## [0.34.0] — 2026-07-02

### Added

- Image → Adjustments → Curves… (`Ctrl+M`): a proper curve editor — click to
  add points, drag to shape, right-click to remove — with a monotone cubic
  spline (no overshoot), an RGB master curve composing with per-channel
  R/G/B curves, live preview, and one undo step. Rides the shared banded
  LUT engine.

## [0.33.0] — 2026-07-02

### Added

- Image → Image Rotation → Arbitrary…: rotate the whole image by any angle —
  the canvas grows to the rotated bounding box, every layer resamples once
  (smooth) about the canvas centre, and undo restores the stored originals
  exactly (no second resample). Guides/selection clear, as axis-aligned
  concepts should.

## [0.32.0] — 2026-07-02

### Added

- Pattern fill: Edit → Define Pattern from Selection captures the selected
  composite as a tile, and the Paint Bucket gains a color/pattern source
  switch — pattern floods tile seamlessly through the region, with
  tolerance, selection clipping, opacity, and undo unchanged.

## [0.31.0] — 2026-07-02

### Added

- Eraser tool (`E`): a first-class toolbar eraser — hard 100% strokes clear
  outright, soft or partial-opacity strokes fade alpha. The brush/pencil
  eraser checkbox still works; `E` just stops making you hunt for it.

## [0.30.0] — 2026-07-02

### Added

- Crop tool (`C`): drag a rectangle — the discard area darkens and a
  rule-of-thirds grid appears — then Enter or double-click commits (the
  instant offset-shift crop; no pixels copied), Escape clears.

## [0.29.0] — 2026-07-02

### Added

- Dodge (`O`) and Burn (`Shift+O`) brushes: lighten/darken as you paint via
  soft-light white/black stamps — strength follows the opacity slider,
  hardness controls the falloff, full stroke undo.

## [0.28.0] — 2026-07-02

### Added

- Clone Stamp (`S`): Alt+click sets the source, then paint to copy pixels
  from it — aligned mode (the source offset locks on the first stroke),
  brush-size stamps with opacity, selection clipping, full stroke undo.

## [0.27.0] — 2026-07-02

### Added

- Clipping masks (Layer → Clip to Layer Below, `Ctrl+Alt+G`): confine a
  layer's visibility to the alpha of the layer beneath it; consecutive
  clipped layers share one base. Clipped layers show italic in the panel,
  round-trip in `.ora` (Photoslop extension), and the toggle is undoable.
  Compositing is factored into one shared `draw_layer` path (canvas,
  flatten, and sampler all agree), still viewport-bounded.

## [0.26.0] — 2026-07-02

### Added

- Layer masks: non-destructive per-layer visibility (Grayscale8, 1 byte/px).
  Layer → Add Layer Mask (Reveal All or From Selection), Apply (bakes into
  alpha), Delete — all undoable. Masked layers composite through
  viewport-bounded transient buffers, so the memory story holds. Masks
  round-trip in .ora via a Photoslop extension attribute (ignored by
  GIMP/Krita).

## [0.25.0] — 2026-07-02

### Added

- Quick Selection (`Shift+W`): paint over the image and every brush seed
  floods its contiguous colour region (shared tolerance) into the selection,
  live. Plain drags add to the existing selection; Alt-drags subtract.

## [0.24.0] — 2026-07-02

### Added

- Workspaces (View → Workspace): save your dock/toolbar layout, restore it,
  or reset to the built-in default. A saved workspace (and the window
  geometry) applies automatically at startup.

## [0.23.0] — 2026-07-02

### Added

- Free Transform (`Ctrl+T`): scale (handles; Shift = uniform, cross the
  centre to flip), rotate (drag outside; Shift snaps to 15°), and move the
  active layer with a live painter-transform preview — pixels resample only
  once, on commit (Enter or double-click; Esc cancels; Ctrl+T again commits).
  One undo step, exact restore.

## [0.22.0] — 2026-07-02

### Added

- Magic Wand "Contiguous" toggle: uncheck it to select every pixel within
  the colour tolerance across the whole layer — connected or not — i.e.
  colour-range selection. Shift/Alt add/subtract still apply.

## [0.21.0] — 2026-07-02

### Added

- Image → Adjustments → Color Balance… (`Ctrl+B`): shadows/midtones/highlights
  band selector with cyan–red, magenta–green, and yellow–blue sliders (nine
  values stored across bands), smooth tonal weighting, live preview, one undo
  step on OK. Pure per-channel LUTs on the shared banded engine.

## [0.20.0] — 2026-07-02

### Added

- Merge Visible (`Ctrl+Shift+E`): composites every visible layer into one
  (blend modes and opacity baked in), leaving hidden layers untouched; fully
  undoable.
- Stamp Visible (`Ctrl+Shift+Alt+E`): drops the canvas composite onto a new
  top layer without touching the stack.

### Changed

- Merge Down moved to `Ctrl+E` — the keys now match Photoshop.

## [0.19.0] — 2026-07-02

### Added

- Image → Adjustments → Hue/Saturation… (`Ctrl+U`): hue rotation (±180°,
  luminance-preserving), saturation, and lightness with live preview on the
  active layer; one undo step on OK, exact restore on Cancel. Same banded,
  premultiplication-aware engine as Levels.

## [0.18.0] — 2026-07-02

### Added

- Image → Adjustments → Levels… (`Ctrl+L`): input black/white points, gamma,
  and output range with live preview on the active layer; **Auto** derives
  0.1% percentile points from a downsampled luminance histogram. One undo
  step on OK, Cancel restores exactly. Runs on the shared banded LUT engine.

## [0.17.0] — 2026-07-02

### Added

- Export As dialog: format (PNG/JPEG/WebP/BMP), quality slider for lossy
  formats, export scale (1–400%) with live dimensions, a preview thumbnail,
  and the real encoded file size computed in-memory (debounced) so you see
  the trade-off before saving.

## [0.16.0] — 2026-07-02

### Added

- Pencil tool (`Shift+B`): hard-edged aliased strokes — every painted pixel
  is exactly the foreground colour at the shared opacity, no antialiasing,
  no hardness falloff. Includes an aliased eraser mode. Perfect for pixel
  work.

## [0.15.0] — 2026-07-02

### Added

- Gradient tool (`Shift+G`): drag start→end to fill the active layer (or the
  selection) with a foreground→background gradient, linear or radial, at the
  shared opacity; a guide line previews the drag, and the fill lands as one
  undo step.

## [0.14.0] — 2026-07-02

### Added

- History panel: a third tab next to Layers and Adjust listing every undoable
  step of the active document — click any entry to jump the document to that
  state. Follows the active tab automatically.

## [0.13.0] — 2026-07-02

### Added

- Magic Wand (`W`): selects the contiguous colour region under the click
  within the shared tolerance, using the same vectorised scanline engine as
  the paint bucket (now refactored into a non-destructive mask pass).
  Shift-click adds to the selection, Alt-click subtracts.

## [0.12.0] — 2026-07-02

### Added

- Polygonal Lasso (`Shift+L`): click to place vertices with a live rubber-band
  preview and vertex handles; close by clicking the first vertex or
  double-clicking; Escape cancels the in-progress polygon.

## [0.11.0] — 2026-07-02

### Added

- Grid overlay (View → Show Grid, `Ctrl+'`): light grid drawn at the minor
  ruler tick spacing of the current unit — unit-aware and zoom-adaptive,
  automatically hidden when it would be denser than 4px on screen.
- Move-tool snapping (View → Snap, on by default): dragged layers snap their
  edges to guides and to the canvas edges within a 6-screen-px threshold;
  hold Shift to drag freely.

## [0.10.0] — 2026-07-02

### Added

- Hand tool (`H`): drag to pan the view; grab-cursor feedback. Holding
  **Space** gives a temporary hand with any tool active, Photoshop-style.
- Zoom tool (`Z`): click to zoom in one step anchored at the click point,
  Alt-click to zoom out.

## [0.9.0] — 2026-07-02

### Added

- Photoshop-style bracket shortcuts: `[` / `]` step the brush size down/up
  (fine steps at small sizes, coarser as it grows), `Shift+[` / `Shift+]`
  step brush hardness in 25% increments. The toolbar spinboxes stay in sync.

## [0.8.0] — 2026-07-02

### Added

- Eyedropper tool (`I`): samples the merged composite under the cursor
  (composited one pixel at a time — free at any document size); click sets
  the foreground colour, Shift-click sets the background, dragging samples
  live.
- Foreground/background colour pair with two toolbar swatches; `X` swaps,
  `D` resets to black/white (also in the Edit menu). Brush and bucket paint
  with the foreground.

## [0.7.0] — 2026-07-02

### Added

- Layer blend modes: normal, multiply, screen, overlay, darken, lighten,
  color-dodge, color-burn, hard-light, soft-light, difference, exclusion,
  addition — picked from a combo in the Layers panel, applied in both the
  canvas and flatten/export paths, and stored as standard `composite-op`
  values in `.ora` (round-trips with GIMP/Krita).

## [0.6.0] — 2026-07-02

### Added

- Image → Image Rotation: rotate the whole document 90° CW/CCW or 180°, or
  flip the canvas horizontally/vertically — every layer, offset, and guide
  transforms together, and undo is exact and memory-free (rotations invert,
  flips are involutions).
- Layer menu: rotate the active layer 90° CW/CCW/180° about its own centre,
  or flip it horizontally/vertically.

## [0.5.0] — 2026-07-02

### Added

- Image preview in the Open dialog: selecting a file shows a thumbnail plus
  dimensions, format, layer count (for `.ora`), and file size. Previews are
  decoded scaled-down via `QImageReader.setScaledSize` (no full-size decode),
  and `.ora` thumbnails come straight from the zip's embedded thumbnail.

## [0.4.0] — 2026-07-02

### Added

- Guide snapping: dragged guides (both creation from a ruler and Move-tool
  drags) snap to the visible **minor ruler ticks** of the current unit — the
  same spacing the ruler draws, so what you see is what you snap to, and
  zooming in refines the grid. Hold **Shift** for free positioning. The
  drag readout always shows the final (snapped) value.

## [0.3.0] — 2026-07-02

### Added

- **Adjust panel** (tabbed with Layers): Lightroom-style Basic sliders —
  Temperature, Tint, Exposure (±4 stops), Contrast, Highlights, Shadows,
  Whites, Blacks, Vibrance, Saturation. Live debounced preview against a
  pristine copy of the active layer (sliders are absolute, not compounding);
  **Apply** commits the whole session as one undo step, **Reset** discards.
  The tone/white-balance chain folds into three 256-entry LUTs and the image
  is processed in row bands, so transient memory stays bounded on any layer
  size; vibrance/saturation mix in float only per band.

## [0.2.5] — 2026-07-02

### Added

- README hero art: Le Basilisk rendered via FLUX.2-Klein in the house
  rotoscope style (`docs/le-basilisk.jpg`), as chosen by the management.

## [0.2.4] — 2026-07-02

### Added

- Application icon: **Le Basilisk** — a doofy green tentacled mascot in a
  French beret with a mustache, paintbrush in one tentacle and palette in
  another. Drawn entirely in code (`photoslop/appicon.py`), no asset files;
  a render lives in `docs/icon.png` for the README.

## [0.2.3] — 2026-07-02

### Added

- Edit → Options → Rulers: switch ruler units from the Edit menu (same radio
  group as View → Units and the ruler corner button — all three stay in sync).
- Inches are now labelled **freedom units** in the menus, by popular demand.

## [0.2.2] — 2026-07-02

### Added

- The running version now shows in the window title ("docA — Photoslop
  0.2.2"), so you can tell which build you're looking at without opening
  Help → About.

## [0.2.1] — 2026-07-02

### Fixed

- Ruler hairlines, guide markers, and ruler ticks were offset from the canvas
  by the scroll-area frame inset (hairline sat left of vertical guides and
  above horizontal ones). Rulers now compute their origin in their own
  coordinate space and round markers exactly like the canvas rounds guides,
  so a hairline over a guide renders as one continuous line at every zoom.

## [0.2.0] — 2026-07-02

### Added

- Guide-drag feedback: while creating a guide from a ruler or moving one with
  the Move tool, a magenta marker tracks the guide on the matching ruler, a
  floating label next to the cursor shows the live X/Y float value in the
  current unit, and the status bar echoes it.

## [0.1.1] — 2026-07-02

### Removed

- Codeberg badge and "mirrored on both forges" README callout, and the
  Woodpecker CI config — the project is GitHub-only (Codeberg account is at
  its repo cap).

## [0.1.0] — 2026-07-02

### Added

- Initial release: a multiplatform (Linux/Windows/macOS) layered raster
  editor built on PySide6/Qt6 + numpy.
- **Layers**: add, delete, duplicate, reorder, merge down; visibility
  toggles, per-layer opacity, panel with live thumbnails.
- **Tools**: brush (size/hardness/opacity + eraser mode), paint bucket with
  tolerance, rectangle select, lasso select, move (layers and guides).
- **Selections**: delete, copy, paste as new layer — including across
  documents; select all / deselect; animated marching ants.
- **Layer clipboard**: copy a whole layer in one image, paste it into
  another.
- **Geometry**: crop to selection, image resize (resamples every layer),
  canvas resize with 9-way anchor.
- **Rulers & guides**: rulers in pixels, inches, millimetres, or picas with
  zoom-adaptive ticks; guides drag out of the rulers and drag off to remove.
- **Zoom**: 12.5%–1600%, cursor-anchored Ctrl+wheel, fit-to-window.
- **Undo/redo**: region-based (128-px tile deltas), bounded stack, merged
  move nudges.
- **Files**: OpenRaster (`.ora`) save/load (GIMP/Krita-interoperable);
  imports PNG/JPEG/BMP/WebP/GIF/TIFF; exports PNG/JPEG/WebP/BMP.
