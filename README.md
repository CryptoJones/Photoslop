# Photoslop

A memory-frugal, multiplatform, layered raster image editor — Photoshop-shaped, Qt-native, zero Electron.

[![Tests](https://github.com/CryptoJones/Photoslop/actions/workflows/test.yml/badge.svg)](https://github.com/CryptoJones/Photoslop/actions/workflows/test.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg?logo=apache)](LICENSE)
[![GitHub](https://img.shields.io/badge/GitHub-CryptoJones%2FPhotoslop-181717?logo=github&logoColor=white)](https://github.com/CryptoJones/Photoslop)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-v0.2.1-orange)]()

---

## What it does

Photoslop is a small, fast, layered image editor that runs anywhere Qt runs
(Linux, Windows, macOS) and treats RAM like it costs money:

- **Layers** — add, delete, duplicate, reorder, hide/show, per-layer opacity.
- **Painting** — round brush with size/hardness/opacity and an eraser mode; paint
  bucket with adjustable tolerance.
- **Selections** — rectangle marquee and freehand lasso; delete selection, copy
  selection, paste as new layer.
- **Cross-image workflow** — multiple documents in tabs; copy a layer (or a
  selection) in one image and paste it into another.
- **Geometry** — crop to selection, image resize (resamples every layer), canvas
  resize with 9-way anchor.
- **Rulers & guides** — rulers in pixels, inches, millimetres, or picas; drag
  guides out of the rulers, drag them back off to remove. While a guide is
  dragged, a marker tracks it on the matching ruler and a floating label shows
  its live X/Y position in the current unit.
- **Undo/redo** — region-based undo that stores only the pixels a stroke touched.
- **Files** — opens and saves layered [OpenRaster](https://www.openraster.org/)
  (`.ora`, interoperable with GIMP and Krita); imports/exports PNG, JPEG, BMP,
  and WebP.

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
| Paint bucket         | `G`          |
| Rectangle select     | `M`          |
| Lasso (area) select  | `L`          |
| Move layer           | `V`          |
| Copy selection       | `Ctrl+C`     |
| Paste as new layer   | `Ctrl+V`     |
| Delete selection     | `Del`        |
| Copy layer           | `Ctrl+Shift+C` |
| Paste layer          | `Ctrl+Shift+V` |
| Undo / redo          | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Zoom in / out / fit  | `Ctrl++` / `Ctrl+-` / `Ctrl+0` |
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
