# Artboards

An artboard is a **named export region** — a rectangle on the document, not a
separate canvas.

- **Image → Artboards → Add Artboard from Selection**: the selection's bounds
  become "Artboard N" (the selection is consumed). Boards draw as labelled
  dash-dot frames on the canvas.
- **Export Artboards…**: pick a folder; the document flattens once and each
  region saves as `<name>.png` (filesystem-unsafe characters sanitised).
- **Clear Artboards** removes them.

Artboards persist in ORA. CLI: `--add-artboard NAME,X,Y,W,H` and
`--export-artboards DIR`.
