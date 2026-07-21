# Architecture — the memory-frugality design

Photoslop's founding constraint: edit big layered images without big memory.
The features this constraint deliberately rules out — and the reasoning —
are recorded in [DESIGNDECISIONS.md](../../DESIGNDECISIONS.md).
Every subsystem answers to it.

## Background task service

Heavy GUI operations use a bounded `TaskService` rather than the Qt event
thread. Every task declares an estimated peak-memory cost; the scheduler starts
work only when both a worker slot and the memory budget are available. A handle
reports lifecycle state and progress and supports cooperative cancellation.
Four priority classes separate interactive previews, project writes, remote
models, and bulk work. FIFO is stable within a class; a runnable small task may
bypass a queue head that cannot fit the remaining memory budget. View →
Background Tasks exposes queue state, progress, session history, and individual,
scope, or global cancellation. Edit → Cancel Background Task is the direct
global shortcut. A blocking backend that cannot stop is prevented from
installing its late result.

Workers receive QImage copy-on-write or metadata-deep document snapshots and
never mutate the live document. GUI-thread completion checks layer/document
generation tokens before installing results and creating undo commands. A
failure, cancellation, or stale completion therefore leaves pixels, dirty
state, and undo history unchanged. CLI and MCP remain synchronous because they
do not own a GUI event loop while sharing the same engine operations.

## Registry and service boundaries

- `ActionRegistry` owns command IDs, labels, shortcuts, help, prerequisites,
  enabled state, menus, and command search metadata.
- `toolregistry` owns tool IDs, groups, SVG icons, shortcuts, labels, and flyout
  ordering; interactive tool classes retain gesture implementation only.
- `WorkspaceController` owns saved dock state, geometry, defaults, and
  current-screen validation.
- `TaskService` owns worker count/memory scheduling and task lifecycle.
- `DiagnosticStore` owns redacted, bounded, durable operation results, failure
  records, and retry guidance; Help → Diagnostics keeps evidence after a status
  message expires.
- `FileService`, `ExportService`, `FilterService`, and `ModelService` accept
  documents/images/data rather than widgets. GUI, CLI, MCP, plugins, and tests
  therefore share engine paths without importing MainWindow.

MainWindow remains the composition root: it creates widgets and dialogs,
captures immutable/COW inputs, invokes services synchronously or through
TaskService, and installs validated results on the GUI thread. Complete
workflows are migrated behind these interfaces without forking headless
behavior or changing existing document/command APIs.

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
- **Live effects** render into layer-local caches keyed on the image's
  generation (`cacheKey`). Moving a layer translates the cached appearance;
  shadows/glows/strokes re-derive only when pixels or effect parameters change.

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
