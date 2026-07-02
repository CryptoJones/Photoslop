# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows [SemVer](https://semver.org).

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
