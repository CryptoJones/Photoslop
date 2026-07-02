# Photoslop

<img src="docs/icon.png" width="112" align="right" alt="Le Basilisk, the Photoslop mascot — a doofy green tentacled fellow in a beret, brush in one tentacle, palette in another">

A memory-frugal, multiplatform, layered raster image editor — Photoshop-shaped, Qt-native, zero Electron.

[![Tests](https://github.com/CryptoJones/Photoslop/actions/workflows/test.yml/badge.svg)](https://github.com/CryptoJones/Photoslop/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?logo=apache)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-CryptoJones%2FPhotoslop-181717?logo=github&logoColor=white)](https://github.com/CryptoJones/Photoslop)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v0.32.0-orange)]()

---

<p align="center">
  <img src="docs/le-basilisk.jpg" width="480"
       alt="Le Basilisk — the Photoslop mascot in a green-lit studio: doofy green tentacled painter with a red beret, handlebar mustache, paintbrush, and palette">
  <br>
  <em>Le Basilisk</em>, the Photoslop mascot — rendered in the house rotoscope style.
</p>

## What it does

Photoslop is a small, fast, layered image editor that runs anywhere Qt runs
(Linux, Windows, macOS) and treats RAM like it costs money:

- **Layers** — add, delete, duplicate, reorder, hide/show, per-layer opacity,
  13 blend modes (multiply, screen, overlay, dodge/burn, difference…)
  saved interoperably in `.ora`, non-destructive layer masks (from
  selection or reveal-all; apply/delete), and clipping masks
  (`Ctrl+Alt+G`).
- **Painting** — round brush with size/hardness/opacity and an eraser mode;
  aliased pencil for pixel work; paint
  bucket with adjustable tolerance; linear/radial gradients (`Shift+G`,
  foreground→background); eyedropper (`I`) sampling the merged
  composite; foreground/background colour pair with `X` swap and `D` reset.
- **Selections** — rectangle marquee, freehand lasso, polygonal lasso, and
  magic wand (tolerance-based, Shift adds / Alt subtracts, contiguous
  toggle for colour-range selection), and quick selection (`Shift+W`,
  paint to grow); delete selection, copy
  selection, paste as new layer.
- **Cross-image workflow** — multiple documents in tabs; copy a layer (or a
  selection) in one image and paste it into another.
- **Geometry** — crop to selection, image resize (resamples every layer), canvas
  resize with 9-way anchor; rotate the image 90°/180° or flip it (layers and
  guides come along), rotate/flip individual layers about their centre, and
  Free Transform (`Ctrl+T`) for freehand scale/rotate/move with live preview.
- **Rulers & guides** — rulers in pixels, millimetres, picas, or freedom
  units (inches); drag guides out of the rulers, drag them back off to
  remove. While a guide is dragged, a marker tracks it on the matching ruler
  and a floating label shows its live X/Y position in the current unit;
  guides snap to the visible minor ruler ticks (hold Shift to place freely);
  a grid overlay follows the same spacing, and dragged layers snap their
  edges to guides and canvas edges.
- **Adjust panel** — Lightroom-style Basic sliders (Temp, Tint, Exposure,
  Contrast, Highlights, Shadows, Whites, Blacks, Vibrance, Saturation) in a
  tab next to Layers; live preview, one undo step per Apply. Levels
  (`Ctrl+L`) with auto black/white points; Hue/Saturation (`Ctrl+U`); Color Balance (`Ctrl+B`).
- **Undo/redo** — region-based undo that stores only the pixels a stroke
  touched, with a History panel to click back to any earlier state.
- **Files** — opens and saves layered [OpenRaster](https://www.openraster.org/)
  (`.ora`, interoperable with GIMP and Krita); imports/exports PNG, JPEG, BMP,
  and WebP. The Open dialog shows a live thumbnail preview with dimensions,
  format, layer count, and file size — decoded scaled-down, so browsing huge
  folders stays fast. Export As offers format/quality/scale controls with a
  live preview and the real encoded size.

## Why the memory frugality

Image editors bloat because they cache everything. Photoslop instead:

- keeps exactly **one pixel buffer per layer** (premultiplied ARGB32; pasted
  layers are sized to their content) — no full-canvas mirrors, no flattened
  composite cache;
- composites **only the viewport region** being repainted, at the current zoom;
- relies on Qt's **copy-on-write** image sharing, so duplicating layers and
  copying selections cost nothing until pixels actually change;
- stores undo as **dirty-rect deltas** (just the pixels a stroke touched), with a
  bounded stack depth;
- flood-fills with an **iterative scanline** algorithm — no recursion, no
  per-pixel Python.

## Quick start

```bash
# from a checkout
uv sync
uv run photoslop

# or straight from the forge
uvx --from git+https://github.com/CryptoJones/Photoslop photoslop
```

## Tools & shortcuts

| Tool / action        | Shortcut     |
| -------------------- | ------------ |
| Brush                | `B`          |
| Pencil               | `Shift+B`    |
| Paint bucket         | `G`          |
| Gradient             | `Shift+G` (linear/radial) |
| Eyedropper           | `I` (Shift-click → background) |
| Swap / reset colours | `X` / `D`    |
| Rectangle select     | `M`          |
| Lasso (area) select  | `L`          |
| Polygonal lasso      | `Shift+L`    |
| Magic wand           | `W` (Shift adds, Alt subtracts) |
| Move layer           | `V`          |
| Hand (pan)           | `H` (or hold `Space`) |
| Zoom tool            | `Z` (Alt-click zooms out) |
| Copy selection       | `Ctrl+C`     |
| Paste as new layer   | `Ctrl+V`     |
| Delete selection     | `Del`        |
| Merge down / visible | `Ctrl+E` / `Ctrl+Shift+E` |
| Stamp visible        | `Ctrl+Shift+Alt+E` |
| Copy layer           | `Ctrl+Shift+C` |
| Paste layer          | `Ctrl+Shift+V` |
| Brush size / hardness | `[` / `]` and `Shift+[` / `Shift+]` |
| Undo / redo          | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Zoom in / out / fit  | `Ctrl++` / `Ctrl+-` / `Ctrl+0` |
| Free Transform       | `Ctrl+T` (Enter commits, Esc cancels) |
| Crop tool            | `C` (drag, Enter commits) |
| Crop to selection    | `Ctrl+Alt+C` |

## Development

```bash
uv sync --extra dev
uv run ruff check .
QT_QPA_PLATFORM=offscreen uv run pytest
```

## License

Apache 2.0. See [LICENSE](LICENSE).

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/
