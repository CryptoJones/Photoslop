# Getting Started

## Install

```bash
pip install photoslop            # core editor
pip install photoslop[raw]       # + camera-raw import (rawpy)
```

From a checkout: `uv sync` then `uv run photoslop`.

## Launch

- **Desktop app**: `photoslop` — opens the editor window. The window title
  shows the running version.
- **Command line**: `photoslop-cli <input> [operations…] --output <path>` —
  the whole engine without a window (see [Command Line](cli.md)). Headless-safe:
  it forces Qt's offscreen platform, so it runs over SSH and in CI.

## First document

File → New (`Ctrl+N`) — paper-size presets (A5/A4/A3, Letter, Legal;
metric first, inches for the freedom-unit crowd) populate the size fields,
and if the clipboard holds an image the dialog opens pre-filled with its
dimensions, ready to paste into. Or open PNG/JPG/ORA/camera-raw files via File → Open
(`Ctrl+O`) — the open dialog previews images and shows every file-detail column
(Name / Size / Kind / Date Modified) in full, never truncated. Drag-and-drop onto the window
also opens files. Save as OpenRaster (`.ora`) to keep layers; use File →
Export As for flattened raster output.

## The surface, in one minute

- Left: the tool bar (31 tools, Photoshop keys — see [Tools](tools.md)).
- Top: the options bar — Zoom In / Zoom Out buttons pinned at the front (always
  visible), then the active tool's options (size, hardness, opacity, flow,
  colours…).
- Right: Layers panel, History panel (undo tree), Adjust panel.
- Rulers cycle units (px / freedom units / mm / cm / picas) via the corner
  button; drag from a ruler to place a guide. Rulers mark the exact image
  edge — even for 100-MP frames at 1/32 zoom.
- Workspaces (View → Workspace) save and restore panel layouts.
