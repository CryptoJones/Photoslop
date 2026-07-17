# Changelog

All notable changes to this project are documented in this file. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning
follows [SemVer](https://semver.org).

## [1.29.0] — 2026-07-16

### Added
- A native iPadOS 17+ edition built with SwiftUI and PencilKit, with Apple
  Pencil pressure-aware drawing, optional finger drawing, one-finger pan,
  pinch zoom, pen/eraser tools, adjustable ink color and width, and an
  iPad-native split workspace.
- Raster layer controls for add, duplicate, reorder, rename, visibility,
  opacity, clear, merge down, and delete; flattened output preserves the
  visible stack and PencilKit strokes.
- Image import through both Photos and Files plus flattened PNG export through
  the system document picker, including security-scoped file access.
- A reproducible XcodeGen project, iPad-only application metadata and icon,
  unit coverage for document/layer/compositing behavior, and a macOS CI build
  that attaches the unsigned arm64 developer app to tagged GitHub releases.

### Changed
- The project version is now shared by the desktop/automation edition and the
  initial native iPad edition. Desktop behavior is otherwise unchanged.

### Fixed
- Ruler cursor hairlines stay aligned with horizontal guides when a platform
  layout pass recenters the canvas after zooming, including 200% zoom on macOS.

## [1.28.0] — 2026-07-16

### Added
- File → Open Recent remembers the last four successfully opened or saved
  documents, newest first, with deduplication and automatic missing-file cleanup.

### Fixed
- Moving a text or raster layer with a cached live effect now translates the
  complete appearance, including drop shadows, instead of leaving effect
  planes behind at their previous canvas position.
- Open and layered Save/Save As now share the last successfully used document
  directory and default to the user's home directory before one is recorded,
  rather than starting in the process launch directory.
- The CLI guide now documents the released structured Appearance operations
  for all ten effects, with an ordered text-effect recipe and exhaustive tests.

## [1.27.0] — 2026-07-15

### Added
- **Non-destructive Appearance effects** for raster, vector, and editable text
  layers: ordered multi-instance Drop/Inner Shadow, Outer/Inner Glow, Outline,
  Color/Gradient Overlay, Bevel/Emboss, Gaussian Blur, and Feather effects.
- A dockable Appearance panel supports live editing, enable/disable, duplicate,
  reorder, delete, Fill Opacity, six built-in text styles, and user presets.
- Structured `--effect`, `--set-effects`, `--clear-effects`, and
  `--appearance-preset` CLI/MCP operations; legacy style flags remain compatible.
- SVG export now carries appearance filters, styled text runs, embedded raster
  layers, and Photoslop metadata for editable round trips.

### Changed
- OpenRaster appearance data uses a validated, versioned object schema. Existing
  Drop Shadow, Glow, and Stroke tuples migrate automatically when opened.

## [1.26.0] — 2026-07-12

### Added
- **Release verification matrix** ([#158](https://github.com/CryptoJones/Photoslop/issues/158))
  — keyboard/accessibility-tree assertions, 1x/2x light/dark/high-contrast icon
  and cursor renders, expanded vector/SVG evidence, and versioned
  VoiceOver/NVDA/Orca plus cross-application SVG smoke procedures.
- CI publishes JUnit and scaled 4K/12K benchmark artifacts with P50/P95,
  document bytes, peak RSS, cancellation latency, and explicit cache budgets.

### Fixed
- Palette SVG icons now encode alpha in standards-compatible SVG attributes;
  the verification render matrix caught previously invisible icon pixels.

### Changed
- Feature-parity claims now require end-to-end and interchange evidence, mark
  professional vector/text/interchange breadth as partial, and identify manual
  platform checks that offscreen CI cannot prove.

## [1.25.0] — 2026-07-12

### Added
- **SVG and editable artboard interchange** ([#157](https://github.com/CryptoJones/Photoslop/issues/157))
  — import/export of the safe native subset (rectangles, ellipses, cubic/line
  paths, affine matrices, solid/gradient fill and stroke, IDs/names, and safe
  Unicode text), with canvas bounds and ordered artboards retained.
- Unsupported SVG elements are reported in `Document.import_warnings` and the
  source render is retained as a hidden raster fallback rather than discarded.
- Named artboards can be added, renamed/resized, deleted, reordered, cleared,
  and undone through a shared GUI/CLI/MCP-capable engine.

## [1.24.0] — 2026-07-12

### Added
- **Native vector construction workflows** ([#156](https://github.com/CryptoJones/Photoslop/issues/156))
  — Selection (`A`) and Direct Selection (`Shift+A`) tools, persistent
  multi-object/node selection, undoable affine transforms, grouping,
  fill/stroke editing, gradient paints, dashes/caps/joins, node conversion,
  Boolean paths, alignment/distribution, and guide/object snapping.
- Structured `--vector-op JSON` automation mirrored by MCP, with vector IDs and
  types exposed by `--info`; native payloads retain editable Unicode text
  metadata and render text objects without flattening their model.

## [1.23.0] — 2026-07-12

### Added
- **Versioned native vector schema** ([#155](https://github.com/CryptoJones/Photoslop/issues/155))
  — stable IDs, hierarchy, affine transforms, explicit move/line/cubic/close
  geometry and node handles, independent fill/stroke appearance, fill rules,
  caps/joins/dashes, object opacity/blend, text metadata, and extension fields.
- Legacy Shape/Pen dictionaries migrate in memory and preserve unknown data.
  Vector-backed layers render directly at viewport/output scale for crisp zoom;
  ORA still stores a visible raster fallback for other applications and for
  masks/effects that require rasterization.

## [1.22.0] — 2026-07-12

### Changed
- **UI/service responsibility split** ([#154](https://github.com/CryptoJones/Photoslop/issues/154))
  — action and tool registries are joined by a Workspace controller and
  widget-independent File, Export, Filter, and Model services. MainWindow now
  orchestrates dialogs and GUI-thread commits instead of owning engine work.
- GUI background tasks, synchronous CLI pipelines, MCP tools, tests, and plugin
  calls reuse the same service/engine functions. Existing command IDs,
  shortcuts, document APIs, ORA behavior, and headless operations remain
  compatible during the migration.

## [1.21.0] — 2026-07-12

### Changed
- **Bounded canvas repainting and previews** ([#153](https://github.com/CryptoJones/Photoslop/issues/153))
  — hover/tool overlays repaint only old/new visible bounds; marching ants are
  clipped to the visible region. Layer thumbnails are keyed by QImage generation
  and cached only for live layers.
- Open-dialog decoding is asynchronous and stale-safe. Export previews use a
  512 px proxy while exact scaling/size encoding runs in a cancellable worker;
  prior preview generations cannot replace newer choices.

### Added
- Standardized `4k-50` and `12k-20` benchmark fixtures report P50/P95 viewport
  latency, document bytes, peak RSS, and the documented 33 ms frame / 100 ms
  heartbeat targets, with a scaled deterministic CI smoke mode.

## [1.20.0] — 2026-07-12

### Added
- **Cancellable memory-bounded background tasks** ([#152](https://github.com/CryptoJones/Photoslop/issues/152))
  — a small worker pool schedules by declared peak bytes as well as worker
  count, with queued/running/success/failure/cancel states, progress messages,
  cooperative cancellation, traceback isolation, and late-result disposal.
- Large filters, ORA save/open, raster decode, RAW development, final exports,
  subprocess-backed filters, and model denoise/fill/selection now operate on
  immutable or Qt copy-on-write snapshots. Only the GUI thread installs pixels,
  documents, selections, undo commands, paths, and clean state; generation
  tokens reject results after newer edits.

## [1.19.0] — 2026-07-12

### Added
- **Cross-platform accessibility layer** ([#151](https://github.com/CryptoJones/Photoslop/issues/151))
  — custom canvas/ruler widgets, icon controls, flyouts, Properties, and options
  expose explicit names, descriptions, values, and native Qt interfaces. Status
  changes produce polite accessibility announcements.
- **Keyboard and low-vision alternatives** — centered guides can be created
  without dragging; Preferences adds high contrast, reduced motion, and
  persistent 100–200% control scaling with visible focus treatment.
- **Repeatable screen-reader verification** — `docs/v1/accessibility.md` versions
  a shared VoiceOver, NVDA, and Orca workflow alongside automated tree tests.

## [1.18.0] — 2026-07-12

### Added
- **Command registry and palette** ([#150](https://github.com/CryptoJones/Photoslop/issues/150))
  — menu commands now carry stable IDs, labels, shortcuts, help, and document,
  selection, clipboard, or idle prerequisites. `Ctrl+Shift+P` searches the same
  metadata and explains unavailable commands instead of letting them silently
  fail.
- **Contextual Properties dock** — exposes the active raster/vector layer's
  name, visibility, opacity, and blend mode with explicit accessible labels.
- **Responsive tool options** — the active tool is named, numeric controls have
  explicit units/accessibility names, Reset Tool Options restores defaults,
  native toolbar overflow handles narrow widths, and off-screen saved workspace
  geometry is recovered onto a current display.

## [1.17.0] — 2026-07-12

### Added
- **Grouped, keyboard-accessible toolbox flyouts** ([#149](https://github.com/CryptoJones/Photoslop/issues/149))
  — the former 30-button column is now 14 related tool groups that retain the
  last-used tool on the button. A declarative tool registry owns IDs, names,
  shortcuts, groups, and icons. Compact, comfortable, and icon-plus-label
  density modes persist between launches.
- **Palette-aware SVG iconography** — a pinned MIT-licensed Tabler Icons v3.44.0
  subset replaces fixed 22 px dark pixmaps. Normal, active, selected, disabled,
  light/dark, and HiDPI renderings come from the same bundled geometry; source
  and license details are recorded in `THIRD_PARTY_NOTICES.md`.

## [1.16.0] — 2026-07-12

### Added
- **Contextual, high-contrast tool cursors** ([#148](https://github.com/CryptoJones/Photoslop/issues/148))
  — one cursor controller now resolves live tool state instead of relying on
  static crosshairs. Paint tools show their effective zoomed brush radius;
  tool glyphs distinguish selection, fill, sampling, vector, crop, navigation,
  and warp operations; modifiers expose selection/zoom/source modes; transform
  handles show directional resize, move, rotate, node, or invalid-target state.
  Custom cursors render at 1×/2× with contrasting outlines and tested hotspots.
  Holding Space temporarily switches to Open/Closed Hand and restores the exact
  contextual cursor on release.

## [1.15.1] — 2026-07-12

### Fixed
- **Text point-size keyboard entry** ([#147](https://github.com/CryptoJones/Photoslop/issues/147))
  — the rich-text size field now accepts values from 6 through **999 pt**.
  Typing multi-digit values no longer steals focus into the editor, and Enter
  commits the value without adding a newline or accepting the dialog.

## [1.15.0] — 2026-07-05

### Changed
- **Open dialog fills the workable image area** (#144) — the non-native "Open
  images" dialog now opens sized and positioned to the main window's central
  canvas region (between the tool bar and the Layers panel), instead of
  floating as a smaller inset box. It fits on first show and stays freely
  resizable after. GUI chrome only; no change to what can be opened.

## [1.14.0] — 2026-07-05

### Added
- **Rich text tool** — the Text tool (`T`) now opens a modern WYSIWYG rich-text
  editor instead of a plain box. Type and the text previews in the font, size,
  and colour you chose; a formatting toolbar gives a font picker, size,
  **bold**/*italic* toggles, and a colour swatch. Colour the **whole block or
  individual letters** — select a run of characters and pick a colour to tint
  just those. Re-editing an existing text layer re-opens it with all its
  styling intact (the styled HTML persists in `.ora`).
- **`--text-rich "X,Y:<html>"`** — the headless CLI mirror of the styled
  editor: renders an HTML fragment onto a new layer, so per-letter colour,
  font-family, and bold/italic are all reachable from the command line. The
  existing `--text` op is unchanged and backward-compatible.

## [1.13.0] — 2026-07-05

### Added
- **MCP server** (#134) — `photoslop-mcp` (optional `photoslop[mcp]` extra)
  exposes the headless engine over the [Model Context Protocol](https://modelcontextprotocol.io),
  so an LLM/agent can drive the editor. Three tools: `list_operations` (the op
  catalog), `edit_image` (load/create → ordered pipeline → write), and
  `document_info` (read-only inspect). It is a thin surface over the new
  `cli.apply_pipeline`, which reuses the CLI's `OPS` table verbatim — so the
  MCP operation set is automatically in lock-step with `photoslop-cli`, the
  same headless-parity promise. Serves over stdio; new guide `docs/v1/mcp.md`.

## [1.12.1] — 2026-07-05

### Changed
- **Zoom In / Zoom Out moved to the top options bar** (#136) — the two zoom
  buttons are now pinned at the front of the top bar (always visible), instead
  of tucked at the end of the left tool bar. GUI chrome only; the `Ctrl++` /
  `Ctrl+-` shortcuts and the View menu entries are unchanged.
- **Open dialog shows all columns** (#135) — the File → Open dialog opens in
  Detail view with every column (Name / Size / Kind / Date Modified) sized to
  its contents, so nothing is truncated on first open.
- **Credits renamed "Programming" → "Contributors"** (#137) — the About →
  Credits line now reads `Contributors: …`.

## [1.12.0] — 2026-07-04

### Added
- **Retro Console (8-Bit) filter** (#130) — `Filter → Retro Console` gives
  photos an 80s/90s video-game look: chunky pixels (Pixel size), a crushed
  colour palette (Colour levels per channel), and an optional 4×4 ordered
  (Bayer) dither so gradients break into the crosshatch of an old console.
  Dependency-free and alpha-preserving; like every plugin filter it also
  works as a CLI op (`--filter retro-console`) and a replayable smart filter.
- **Consolidated Preferences dialog** (#131) — `Edit → Preferences…` opens one
  tabbed window (Model Backend + Color) instead of two scattered items. The
  action carries `PreferencesRole`, so on macOS it lands in the native
  **Photoslop → Preferences…** slot (⌘,).

### Fixed
- **macOS menu placement** — About/Quit/Preferences now use explicit
  `QAction.MenuRole`s instead of Qt's text heuristics, so Settings no longer
  silently vanish from the Edit menu and the Help/app menus behave predictably
  across platforms.

## [1.11.0] — 2026-07-03

### Added
- **`run.sh` / `run.cmd` launchers** — one-command entry points for
  non-technical users. Each changes to the repo directory, bootstraps `uv`
  from https://astral.sh/uv if it is missing, then runs `uv run photoslop`,
  passing any arguments through to the app (e.g. `./run.sh image.png`).
  Developer tooling with no app-surface change, so no CLI mirror applies;
  documented in the README Quick start.

## [1.10.0] — 2026-07-03

### Added
- **Raw develop** (DD-007; 16-bit transient in, 8-bit layer out): `rawpy`
  decodes at `output_bps=16` with exposure (`2^EV`), a Kelvin white-balance
  approximation (Tanner Helland fit — higher temp = warmer, Lightroom
  convention), and luma-weighted highlights/shadows tone mapping, all held
  in a transient buffer. Raw Develop dialog with a live half-size preview
  (`probe_raw` validates the file before the dialog; Cancel = camera
  defaults). CLI mirror:
  `--raw-develop "exposure=…,temp=…,tint=…,highlights=…,shadows=…"`.
- **Lens corrections** (`photoslop[lens]` extra — lensfunpy + exifread,
  feature-detected per DD-001): distortion remap + vignetting driven by the
  source file's EXIF, with clear errors when the camera/lens is not in the
  database. Filter menu entry + `--lens-correct`.
- **Denoise**, two flavors: a built-in baseline `DenoiseFilter` (luma
  preserved exactly, chroma box-blurred) and an adapter route (DD-009) —
  `ModelAdapter.denoise` + `POST {base}/denoise` in the HTTP contract,
  surfaced as Filter > Denoise (Model) and `--denoise-model N`.
- Final parity-loop cycle (9/9). Closes #112. Suite: 2280 → 2290 tests.

## [1.9.0] — 2026-07-03

### Added
- **ICC color management** (viewport-only per DD-004; engine is Qt's
  QColorSpace — zero new dependencies): Assign Profile / Convert to
  Profile (presets + any .icc), monitor-profile display transform and
  **Soft Proof** (`Ctrl+Y`) applied to the composited viewport region
  only, profile persistence in .ora (`photoslop-icc`) and embedding in
  PNG/JPEG exports. CLI mirrors: `--assign-profile`, `--convert-profile`,
  `--proof`, and `--cmyk-out FILE.icc` (CMYK JPEG/TIFF via littlecms —
  DD-005 export-only). Closes #108.

## [1.8.0] — 2026-07-03

### Added
- **Parametric vector layers**: Shape and Pen layers remember their
  geometry (`vector_data`, persisted in .ora as `photoslop-vector`).
  Click the active layer with the same tool to re-edit — drag
  corner/endpoint handles (or the body to move), pick pen anchors back
  up, append new ones — one undo step per edit (EditVectorLayerCommand).
  Document resize/rotate/flip **re-render from the parameters** instead
  of resampling pixels, so edges stay crisp at any scale (works headless:
  `--shape … --resize …`). Layer flips stay parametric; arbitrary-angle
  layer rotation drops to raster by design. Closes #110.

## [1.7.0] — 2026-07-03

### Added
- **GIMP bridge** (spawn-per-call ONLY, per DD-006): with a `gimp` 3.x
  binary on PATH, **GIMP Oilify / Softglow / Cubism** register (GIMP's
  own GEGL ops that plain gegl doesn't ship) plus **GIMP Script-Fu** —
  a raw hatch binding `image`/`drawable` that reaches any plug-in or PDB
  procedure GIMP has. Each run launches a fresh `gimp -i`, applies, and
  exits; errors surface the batch text and runaway scripts are killed at
  a timeout. Completes the #111 filter-ecosystem trilogy.

## [1.6.0] — 2026-07-03

### Added
- **GEGL filter pack** (Linux, system-library gated — install python3-gi
  and gir1.2-gegl-0.4 from your distro, nothing bundled per DD-001):
  Vignette, Bloom, Pixelize, Newsprint, Posterize, Motion Blur, Edge
  Detect, plus **GEGL Operation** — a raw escape hatch to all ~200
  operations with `key=val` properties. Runs **spawn-per-call** in a
  short-lived worker (the venv's python if it has gi, else the system
  python3), so GEGL never enters Photoslop's resident memory. Second of
  the #111 packs.

## [1.5.0] — 2026-07-03

### Added
- **G'MIC filter pack** via the optional `photoslop[gmic]` extra (gmic-py
  wheel; a `gmic` binary on PATH works as a subprocess fallback): seven
  curated filters (Cartoon, Old Photo, Drawing, Stencil, Spread, Solarize,
  anisotropic Smooth) plus **G'MIC Command** — a raw escape hatch to the
  entire G'MIC library including the community `fx_*` set. Auto-registers
  on the filter plugin API, so menu, params dialogs, `--filter`, selections,
  and smart replay all work. Alpha is protected (RGB-only hand-off);
  DD-008 float transients documented. First of the #111 packs.

## [1.4.0] — 2026-07-03

### Added
- **Filter plugin API** (`photoslop.filters` entry-point group): a filter is
  one class — name, label, ParamSpecs, `apply(image, params)` — and Photoslop
  generates the rest: Filter-menu entry with an auto-built parameter dialog,
  `--filter "name:key=val,..."` CLI op, selection/feather awareness through
  the shared plumbing, action recording, and smart-filter replay. Built-ins
  **Sepia** and **Pixelate** ship in the box; a complete installable
  reference plugin lives in `examples/photoslop-invert-filter/`. New guide:
  docs/v1/filter-plugins.md. Closes #109.

## [1.3.0] — 2026-07-03

### Added
- **Point Color** (`Ctrl+Shift+U`, Image → Adjustments): targeted hue-band
  HSL with click-to-sample from the composite thumbnail, smooth cosine
  falloff, near-gray protection, a Uniformity slider that evens hues toward
  the band centre, and a Skin Tones preset. Scope toggle (layer ↔ full
  image), live preview, single undo macro. CLI mirror: `--point-color
  "hue=20,range=28,dh=…"` — selection- and feather-aware. Closes #114.

## [1.2.0] — 2026-07-03

### Added
- **AVIF + JPEG XL** import/export via the optional `photoslop[formats]`
  extra (Pillow ≥11 for AVIF, pillow-jxl-plugin for JXL), feature-detected:
  Open (with dialog preview), Export As (quality slider, live size), and the
  CLI accepts `.avif`/`.jxl` as both input and `--output`. Alpha preserved
  both directions. Without the extra, the exact install command is shown
  instead of an error. Closes #115.

## [1.1.4] — 2026-07-03

### Added
- `DESIGNDECISIONS.md` — the append-only record of what Photoslop
  deliberately won't do and why, anchored on DD-001 (memory performance
  beats features). Documents the backlog re-triage: deep bit depth and the
  scene-referred/HDR pipeline rejected; ICC accepted as viewport-only work;
  CMYK export-only; GIMP-bridge spawn-per-call only; raw develop transient
  16-bit with 8-bit results; G'MIC float transients accepted with eyes open.
  Linked from the README and the architecture guide.

## [1.1.3] — 2026-07-03

### Added
- `docs/v1/feature-parity.md` — an honest, sourced feature-parity matrix
  comparing Photoslop v1.1.2 against Photoshop 2026, GIMP 3.2, Paint.NET 5.1,
  Lightroom Classic 15.4, darktable 5.6, and Capture One 16.8 (all versions
  verified against official July 2026 documentation), with stand-out
  strengths and a grouped gap list.

## [1.1.2] — 2026-07-03

### Added
- CLI `--rotate-layer DEG` — rotate the target layer(s) about their centre,
  the headless mirror of Edit/Layer → Rotate 90° CW/CCW (any angle works;
  scope with `--layer` / `--all-layers`). `--rotate` remains the
  whole-image rotation.

## [1.1.1] — 2026-07-03

### Added
- Edit menu: Rotate 90° CW, Rotate 90° CCW, Flip Horizontal, Flip Vertical —
  layer transforms in the transform section next to Free Transform/Warp
  (Photoshop's Edit → Transform placement). Same commands as the Layer menu
  entries.

## [1.1.0] — 2026-07-03

Full GUI↔CLI parity restored: every headless gap from the post-1.0 patch run
is closed.

### Added
- CLI `--select-poly "X,Y X,Y X,Y..."` — polygon selection (the lasso
  family's headless mirror).
- CLI `--adjust "KEY=VAL,..."` — the Adjust panel's Lightroom Basic sliders
  (temperature, tint, exposure, contrast, highlights, shadows, whites,
  blacks, vibrance, saturation), selection-gated like every adjustment op.
- CLI `--clear` — erase the selection to transparency (the headless half of
  Edit → Cut).
- CLI `--new WxH|PRESET` with `--dpi N` — start pipelines from a blank
  document instead of an input file; presets match the GUI's paper sizes
  (A5/A4/A3/Letter/Legal). `PAPER_SIZES` now lives in `photoslop.units`,
  shared by the dialog and the CLI.

## [1.0.7] — 2026-07-03

### Added
- Adjust panel: **Apply to all layers (full image)** checkbox — the same
  layer↔document scope toggle the adjustment dialogs have. Live preview
  re-scopes on the fly; Apply commits one undo step for all changed layers.
- Edit → **Cut Selection** (`Ctrl+X`): copies the selection to the clipboard
  and clears it, as a single "Cut" undo step.

## [1.0.6] — 2026-07-03

### Changed
- Model Backend… moved into the settings menu (Edit → Options), next to
  Rulers — it configures the app, so it lives with the app options.

## [1.0.5] — 2026-07-03

### Added
- New Document dialog: paper-size preset radio buttons — A5, A4, A3
  (metric first) plus Letter and Legal, labelled like
  `A4 — 210×297 mm (8.3×11.7″)`. Picking one fills the size in mm at the
  chosen DPI; editing the size flips back to Custom; changing units keeps
  the preset.
- File → New pre-fills width/height from the clipboard image (in-app copy
  or system clipboard), so New → Paste just fits.
- Dedicated **Select** menu (All, Deselect, Subject (Model), Feather…,
  Refine…) — moved out of Edit, shortcuts unchanged.

### Changed
- About window: Credits button now sits to the left of OK.

## [1.0.4] — 2026-07-03

### Changed
- README hero art is now CryptoJones's hand-drawn `docs/photoslop.png` —
  made in Photoslop itself, 100% human-made slop — replacing the
  FLUX-rendered `docs/le-basilisk.jpg`.

## [1.0.3] — 2026-07-02

### Changed
- About window now shows Le Basilisk — the QPainter original from
  `photoslop/appicon.py`, not the FLUX-rendered hero art.

## [1.0.2] — 2026-07-02

### Fixed
- Polygonal Lasso: `Enter` now closes the selection (it previously did
  nothing, leaving the tool collecting vertices until `Esc`). Double-click
  and clicking the first vertex still close it; the toolbar tooltip and docs
  now say so.

### Added
- Elliptical Marquee tool (`Shift+M`): drag an ellipse selection; hold Shift
  while dragging for a perfect circle.
- CLI: `--select-ellipse X,Y,W,H` — elliptical selection inscribed in the
  given box, gating following ops exactly like `--select`.

## [1.0.1] — 2026-07-02

### Added

- Text dialog: colour swatch button that opens a colour picker (defaults to
  the foreground colour, as before).
- Text tool: clicking inside the active text layer re-opens the dialog
  pre-filled with its text, font, size, and colour, and replaces the layer
  content in place (one undo step) instead of adding a new layer. Text
  parameters persist in `.ora` files (`photoslop-text`), so layers stay
  editable across save/load — including layers created by the CLI.
- CLI: `--text` accepts an optional colour — `"X,Y,SIZE[,R,G,B]:TEXT"`;
  the three-value form still renders black.

## [1.0.0] — 2026-07-02

Photoslop 1.0 — the flagship. One day, 77 releases, v0.1.0 → v1.0.0.

### Added

- `docs/v1/` — the authoritative documentation library: every GUI and CLI
  feature (getting started, all 31 tools, the complete keymap, layers,
  adjustments, selections, transforms, filters, actions, artboards, file
  formats, model backends, the full CLI reference, and the memory-frugality
  architecture).

### Changed

- Development status graduates to Production/Stable.

## [0.78.0] — 2026-07-02

### Added

- Headless CLI (`photoslop-cli`): the full engine as ordered pipeline
  options — geometry, adjustments, filters, selections (with feather),
  layer styles, layers, text/shapes, smart objects, artboards, camera-raw
  input, ORA in/out, and the model-adapter ops. GUI/CLI feature parity
  (interactive brushes excepted); documented in the README.
- ~1180 new tests: every option alone (with a completeness guard pinning
  the op catalog to the tests), every ordered pair of operations (1122
  pairwise cases), order-sensitivity pixel assertions, a kitchen-sink
  pipeline, model ops against a live local server, and I/O/error paths.

## [0.77.0] — 2026-07-02

### Added

- Live layer effects: Drop Shadow, Outer Glow, and Stroke are now
  non-destructive layer styles rendered at composite time (cached per
  image generation) instead of baked pixel layers. Layer Style → Clear
  removes them; effects persist in ORA.
- Fill Opacity (Layer Style → Fill Opacity…): scales the layer's own
  pixels while effects keep full strength — the classic PS semantic,
  now possible because styles are live.

## [0.76.0] — 2026-07-02

### Added

- Fill Layer (Edit menu, `Alt+Backspace`): fills the entire active layer
  with the foreground colour — one undo step, unaffected by any selection.
- Credits button in Help → About, opening a credits window.

## [0.75.0] — 2026-07-02

### Added

- Generative Fill (Edit → Generative Fill… (Model)): select a region, type
  a prompt, and the configured model backend paints it — composited through
  the standard selection plumbing (feather respected), one undo step. Works
  with any backend via the v0.74.0 adapter framework.

## [0.74.0] — 2026-07-02

### Added

- Model-adapter framework: model-assisted features route through a
  pluggable ModelAdapter — connect any backend via the generic HTTP
  adapter (JSON/base64-PNG contract, Edit → Model Backend…) or a pip
  plugin registered under the photoslop.model_adapters entry-point group.
- Select Subject (Model) on the Edit menu: the configured backend returns
  a mask that becomes the live selection.

## [0.73.0] — 2026-07-02

### Added

- Camera-raw import (`pip install photoslop[raw]`): open NEF/CR2/CR3/DNG/
  ARW/RAF and friends straight from File → Open — decoded via rawpy with
  camera white balance. Without the extra installed, raw files give an
  actionable install hint instead of a failure.

## [0.72.0] — 2026-07-02

### Added

- Artboards (Image → Artboards): turn a selection into a named export
  region, see dashed frames with labels on the canvas, and Export
  Artboards… writes each region as its own PNG. Artboards persist in ORA.

## [0.71.0] — 2026-07-02

### Added

- Smart Filters: filters applied to a smart-object layer record themselves
  (Gaussian Blur, Unsharp Mask, Tilt-Shift with exact parameters); Layer →
  Re-apply Smart Filters restores the pristine source and replays the stack
  as one undo step. The filter stack survives ORA save/load.

## [0.70.0] — 2026-07-02

### Added

- Pen tool (`P`) — the last PS keymap row: click to place anchors, the path
  smooths through them (Catmull-Rom), Enter strokes it onto a new bounded
  layer at brush size, Ctrl+Enter fills the closed path, double-click
  commits, Escape cancels (31 tools).

## [0.69.0] — 2026-07-02

### Added

- Shape tool (`U`): drag to draw a rectangle, ellipse, or line onto a new
  layer — foreground fill, brush-size line width, dashed live preview,
  `Shift+U` cycles the shape. Layers are bounded to the shape, not the
  canvas (30 tools).

## [0.68.0] — 2026-07-02

### Added

- Centimetres join the ruler units — switch metric between mm and cm from
  Edit → Options → Rulers (or the View menu / ruler-corner button). Ticks,
  snapping, guide readouts, and the end-of-image marker all follow.

### Fixed

- Tests clear saved settings between cases (window geometry persisted by
  one test's close no longer leaks into the next).

## [0.67.0] — 2026-07-02

### Added

- Zoom In/Out buttons on the toolbar — magnifier icons with +/− glyphs.

### Fixed

- `Ctrl` + the plus key now zooms in on US keyboards: the unshifted key is
  `=`, so Zoom In binds `Ctrl+=`, `Ctrl++`, and `Ctrl+Shift+=` (Zoom Out
  gains `Ctrl+Shift+-`).
- Tests no longer read the live app's saved settings (workspace, grid,
  units) — QSettings is redirected to a temp path per test session.

## [0.66.0] — 2026-07-02

### Added

- Levels, Curves, Hue/Saturation, and Color Balance gain an "Apply to all
  layers (full image)" checkbox — preview updates live across every visible
  layer, OK lands as one undo step for the whole image, Cancel restores
  every touched layer exactly.

## [0.65.0] — 2026-07-02

### Added

- Rulers now mark the exact end of the image: a full-height tick and the
  true extent label (8192, 11648, …) at the boundary, with colliding round
  labels suppressed — the scale reads to the edge on any camera's frame.
- Zoom levels extend down to 1/32 so Fit fits 100MP-class images (Fuji GFX
  11648px and up) inside an ordinary viewport.

## [0.64.0] — 2026-07-02

### Added

- Actions (Edit → Actions): record a sequence of parametrised operations —
  Gaussian Blur, Unsharp Mask, Tilt-Shift — and play it back (`F9`) on any
  layer or document. Playback lands as one undoable macro step.

## [0.63.1] — 2026-07-02

### Fixed

- LICENSE replaced with the verbatim Apache-2.0 text from apache.org (the
  previous file was a paraphrase, so GitHub's license detection reported
  "Other"/NOASSERTION). Only the appendix boilerplate line carries the
  copyright fill-in, which the detector tolerates.

## [0.63.0] — 2026-07-02

### Added

- Smart objects (Layer menu): Convert to Smart Object snapshots the layer's
  pristine pixels; Restore Smart Object Original brings them back after any
  amount of destructive editing — undoable, cloned with the layer, and
  saved in `.ora`.

## [0.62.0] — 2026-07-02

### Added

- Group opacity & blend (Layer → Group Opacity/Blend…): a group now
  composites into a single buffer and blends as one unit — overlapping
  members no longer double-blend at reduced opacity, exactly like nesting
  in Photoshop. Default-value groups keep the zero-copy fast path.

## [0.61.0] — 2026-07-02

### Added

- Perspective Warp (`Shift+P`): click four corners to define a plane, then
  drag them to their rectified positions — the layer warps by that
  homography with live preview. Enter commits, Escape cancels exactly.
  This completes the transforms tracker.

## [0.60.0] — 2026-07-02

### Added

- Puppet Warp (`Shift+Y`): click to drop pins, drag one and the image bends
  around the anchored others — live preview, Enter commits (one undo step),
  Escape cancels exactly.

## [0.59.0] — 2026-07-02

### Added

- Filter → Tilt-Shift…: the miniature-faking gradient blur — a sharp
  horizontal band with blur ramping smoothly above and below (centre, band
  height, transition, and blur radius in the dialog). One undo step.

## [0.58.0] — 2026-07-02

### Added

- Warp (`Ctrl+Shift+T`): a 3×3 control grid over the active layer — drag any
  of the nine points and the image bends through four projective patches
  with a live preview. Enter commits (single smooth resample), Esc cancels
  exactly. Also enterable from inside a Free Transform session.

## [0.57.0] — 2026-07-02

### Added

- Content-Aware Scale can now grow (up to 4×): the lowest-energy seams are
  found distinctly and duplicated with blending — flat areas stretch,
  detail stays put. Same dialog, both directions, exact undo.

## [0.56.0] — 2026-07-02

### Added

- Feather Selection (`Ctrl+Alt+D`): give the active selection a soft edge —
  filters (and future fills) blend smoothly across the feather radius
  instead of cutting hard. Border-normalised so weights stay exact at image
  edges; replacing the selection clears the feather.

## [0.55.0] — 2026-07-02

### Added

- Liquify (`Y`): the forward-warp push brush — drag to shove pixels along
  the stroke with a smooth falloff (bilinear resample, local region only).
  Strength = opacity, one undo step per stroke.

## [0.54.0] — 2026-07-02

### Added

- Filter menu: Gaussian Blur… (1–100 px) and Unsharp Mask… (10–500%) — both
  selection-aware (filter only inside the selection when one exists),
  premultiplication-safe, one undo step.

## [0.53.0] — 2026-07-02

### Added

- Adjustment layers (Layer → New Adjustment Layer: Levels…): a
  non-destructive LUT layer that recolours everything below it — live
  spinbox editing, toggle its visibility to compare, reorder it in the
  stack, and it round-trips in `.ora`. When adjustment layers are present
  the canvas composites through a viewport-bounded offscreen buffer;
  otherwise the zero-copy fast path is unchanged.

## [0.52.0] — 2026-07-02

### Added

- Magnetic Lasso (`Alt+L`): click anchors like the polygonal lasso, but each
  segment is a livewire — a minimum-cost Dijkstra path that hugs strong
  edges between your clicks. Double-click or click the first anchor to
  close; Escape cancels.

## [0.51.0] — 2026-07-02

### Changed

- `G` now cycles Bucket ↔ Gradient, Photoshop's same-key tool-group
  behaviour (`Shift+G` still jumps straight to Gradient).

## [0.50.0] — 2026-07-02

### Added

- Brush scattering (0–200% of brush size): stamps jitter randomly around
  the stroke for sprays, foliage, and texture work — brush and eraser,
  deterministic per stroke, undo covers the whole scattered stroke.

## [0.49.0] — 2026-07-02

### Added

- Patch tool (`Alt+Shift+J`): select a blemish with any selection tool, then
  drag from inside the selection to a clean source area — the selection
  heals with the sampled texture, tone-matched to its surroundings. Ghost
  outline follows the drag; one undo step.

## [0.48.0] — 2026-07-02

### Added

- Layer Styles: Outer Glow… and Stroke… join Drop Shadow — glow is a
  zero-offset tinted halo, stroke is an exact-width dilated outline ring;
  both land as undoable generated layers below the active one.

## [0.47.0] — 2026-07-02

### Added

- Healing Brush (`Shift+J`): Alt+click a source like the clone stamp, but
  stamps transplant the source's texture onto the destination's tone
  (src − blur(src) + blur(dst)) — repairs blend instead of pasting.

## [0.46.0] — 2026-07-02

### Added

- Layer Style: Drop Shadow… (Layer menu): builds a blurred, tinted
  silhouette of the active layer as a shadow layer just below it — offset,
  blur, and opacity in the dialog; one undoable insert.

## [0.45.0] — 2026-07-02

### Added

- Content-Aware Scale (Image menu): shrink the active layer by seam
  carving — the lowest-energy seams vanish first, so detail survives while
  flat areas give way. Width and height, exact undo.

## [0.44.0] — 2026-07-02

### Added

- Text tool (`T`): click the canvas, type in the dialog (any font, 6–400 pt,
  multiline), and the text rasterises onto a new tightly-sized layer at the
  click point in the foreground colour — movable, transformable, blendable
  like any layer. Undoable insert.

## [0.43.0] — 2026-07-02

### Added

- Rotate View (`R` / `Shift+R`, View menu): rotate the canvas display in 90°
  steps — pixels untouched, every tool keeps working through the rotated
  view, Reset View Rotation snaps back. Rulers keep showing unrotated
  space.

## [0.42.0] — 2026-07-02

### Added

- Content-Aware Fill (Edit → Fill Selection, `Shift+F5`): select anything
  and fill it from its surroundings using the diffusion inpaint engine —
  object removal in one keystroke. One undo step, selection preserved.

## [0.41.0] — 2026-07-02

### Added

- Spot Healing Brush (`J`): paint over a blemish (translucent highlight
  shows the coverage) and on release the region fills by diffusion from its
  boundary, then blends in — great for dust, spots, and small defects.
  Works on the mask's bounding box only; one undo step.

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
