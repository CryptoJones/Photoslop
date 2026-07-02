# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows [SemVer](https://semver.org).

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
