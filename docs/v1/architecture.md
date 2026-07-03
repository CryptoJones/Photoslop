# Architecture — the memory-frugality design

Photoslop's founding constraint: edit big layered images without big memory.
The features this constraint deliberately rules out — and the reasoning —
are recorded in [DESIGNDECISIONS.md](../../DESIGNDECISIONS.md).
Every subsystem answers to it.

## Pixel model
- One **premultiplied ARGB32** buffer per layer — no per-layer scratch
  copies at rest. numpy views (`view_u32`) operate in place.
- **Copy-on-write everywhere**: pristine copies for dialog previews, undo
  references, and smart-object sources are COW QImage handles — a copy costs
  nothing until someone writes.
- Layers are **bounded**: shape/pen/text layers are sized to their content
  (+ effect margins), not the canvas.

## Compositing
- The canvas paints **viewport-only**: layers composite directly into the
  exposed region (`draw_layer`, mask/clip/effects-aware).
- The **offscreen buffered path** (`render_region`) engages only when
  needed — adjustment layers or group opacity/blend — and renders just the
  exposed region.
- **Live effects** render from per-layer caches keyed on the image's
  generation (`cacheKey`), so shadows/glows/strokes re-derive only when
  pixels change.

## Undo
- Brush-type edits record **128-px tile deltas** (only tiles that changed);
  whole-image operations store refs and recompute on redo where CPU is
  cheaper than holding two resolutions (image resize).
- Crop is an **offset shift** — no pixels copied or dropped, instant undo.

## Transients
Filters, transforms, and selections allocate region-bounded buffers and drop
them immediately; transform sessions preview via painter transforms and
resample exactly once at commit.

## Headless parity
The engine never touches widgets — documents, layers, filters, transforms,
IO, and model adapters run under Qt's offscreen platform, which is what
`photoslop-cli` and the 1400-case test suite use.
