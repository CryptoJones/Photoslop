# Feature Parity — Photoslop vs the Field

An honest, category-by-category comparison of **Photoslop v1.30.0** against six
established editors, researched against each product's official documentation
and release notes in **July 2026** (see [Sources](#sources)).

The six span two families. **Photoshop, GIMP, and Paint.NET** are layered
raster editors — Photoslop's direct peers. **Lightroom Classic, darktable,
and Capture One** are raw developers with digital-asset-management (DAM)
workflows; Photoslop overlaps them only at the edges (camera-raw import,
tonal adjustments), so many of their rows are marked out-of-scope rather
than "missing".

## Photoslop surfaces

Capabilities differ deliberately by surface; a check here does not imply every
client exposes it.

| Capability | Desktop Qt | iPadOS | CLI | MCP |
|---|---:|---:|---:|---:|
| Layered project persistence | ORA | `.photoslop` package | ORA read/write | ORA read/write under root policy |
| Raster/Pencil drawing | ✅ | ✅ PencilKit | — | — |
| Selections/filters/vectors/text | ✅ | — | ✅ shared safe engine operations | ✅ safe subset |
| Native/third-party plugins | local opt-in | — | local opt-in | denied |
| Network model operations | local configured endpoint | — | local configured endpoint | denied |
| Accessibility automation | automated semantics + manual matrix required | native labels + manual matrix required | structured errors | structured tool errors |
| Signed distributable | secret-gated macOS/Windows workflow | no public unsigned release | wheel/sdist CI smoke | installed with Python package |

## Versions compared

| Product | Version (July 2026) | License / price | Platforms |
|---|---|---|---|
| **Photoslop** | 1.30.0 | Apache-2.0, free | Linux / Windows / macOS (Qt), iPadOS |
| Adobe Photoshop | 2026 (27.8) | subscription + generative credits | Windows / macOS |
| GIMP | 3.2.4 | GPL-3.0, free | Linux / Windows / macOS |
| Paint.NET | 5.1.12 | freeware (+$14.99 Store edition) | Windows only |
| Adobe Lightroom Classic | 15.4 | subscription ($11.99+/mo) | Windows / macOS |
| darktable | 5.6.0 | GPL-3.0, free | Linux / Windows / macOS |
| Capture One Pro | 16.8.1 | perpetual $299 or subscription | Windows / macOS (+iPad) |

**Legend:** ✅ complete for the stated row with an end-to-end automated task
and interchange test where applicable · 🟡 useful but incomplete, narrower, or
not manually verified on every platform · ❌ absent · — out of scope. See the
[release verification matrix](verification.md); offscreen CI never substitutes
for the versioned platform screen-reader and visual smoke procedures.

## Tools & painting

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Brush (size/hardness/opacity/flow/spacing/scatter) | ✅ [Tools](tools.md) | ✅ | ✅ (+MyPaint engine) | 🟡 (no flow/scatter) | — | — | — |
| Pencil / aliased pixel work | ✅ | ✅ | ✅ | ✅ | — | — | — |
| Eraser | ✅ | ✅ | ✅ | ✅ | — | — | — |
| Clone stamp | ✅ | ✅ | ✅ | ✅ (plugin) | — | 🟡 (retouch module) | 🟡 (heal/clone layers) |
| Healing brush / spot heal | ✅ | ✅ | ✅ | ❌ | ✅ (Remove: dust/reflections/shadows) | ✅ (retouch) | ✅ |
| Patch tool | ✅ | ✅ | 🟡 | ❌ | — | — | — |
| Dodge / burn | ✅ | ✅ | ✅ | ❌ | — | — | — |
| Smudge / mixer | ✅ | ✅ | ✅ | ❌ | — | — | — |
| Gradient tool | ✅ (linear/radial) | ✅ | ✅ | ✅ | — | — | — |
| Pattern fill | ✅ | ✅ | ✅ | ❌ | — | — | — |
| Liquify / push warp | ✅ | ✅ | 🟡 (IWarp filter) | ❌ | — | 🟡 (liquify module) | ❌ |
| Pressure sensitivity (tablet) | ❌ | ✅ | ✅ | ✅ | — | — | — |

## Layers, masks & effects

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Layers + opacity + 13+ blend modes | ✅ [Layers](layers.md) | ✅ | ✅ | ✅ | — | — | ✅ (adjustment layers) |
| Layer masks | ✅ | ✅ | ✅ | ❌ | ✅ (masking panel) | ✅ (drawn/parametric) | ✅ |
| Clipping masks | ✅ | ✅ | 🟡 | ❌ | — | — | — |
| Layer groups (+group opacity/blend) | ✅ | ✅ | ✅ | ❌ | — | — | — |
| Adjustment layers | 🟡 (LUT-based; one type) | ✅ (~20 types) | 🟡 (NDE filters cover much of it) | ❌ | — | — | — |
| Live layer effects (shadow/glow/stroke) | ✅ | ✅ (full styles engine) | 🟡 (via GEGL filters/script) | 🟡 (effect plugins, baked) | — | — | — |
| Fill opacity (fill fades, effects stay) | ✅ | ✅ | ❌ | ❌ | — | — | — |
| Smart objects (pristine source + restore) | ✅ | ✅ | 🟡 (link layers, GIMP 3.2) | ❌ | — | — | — |
| Smart filters (re-applyable stacks) | ✅ | ✅ | ✅ (non-destructive filters) | ❌ | — | — | — |
| Non-destructive text/vector layers | ✅ text + vectors | ✅ | ✅ (text/vector/link layers) | ❌ | — | — | — |

## Selections

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Rectangle / ellipse marquee | ✅ [Selections](selections.md) | ✅ | ✅ | ✅ | — | — | — |
| Freehand + polygonal lasso | ✅ | ✅ | ✅ | ✅ | — | — | — |
| Magnetic lasso (edge snapping) | ✅ | ✅ | ✅ (scissors) | ❌ | — | — | — |
| Magic wand + color range | ✅ | ✅ | ✅ | ✅ | — | — | — |
| Quick selection (paint to grow) | ✅ | ✅ | 🟡 (foreground select) | ❌ | — | — | — |
| AI subject selection | ✅ (BYO model adapter) | ✅ (on-device/cloud) | ❌ | ❌ | ✅ (Select Subject v5) | ❌ | ✅ (AI masking) |
| Feather / refine edge | ✅ | ✅ | ✅ | 🟡 | ✅ | ✅ | ✅ |
| Content-aware fill | ✅ (diffusion) | ✅ (+generative) | 🟡 (Resynthesizer plugin) | ❌ | ✅ (Remove tool) | ❌ | ❌ |

## Adjustments & color

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Levels (+auto) | ✅ [Adjustments](adjustments.md) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Curves (monotone spline, per-channel) | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Hue / Saturation | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Color balance | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ (color balance rgb) | ✅ |
| Lightroom-style Basic panel (temp/tint/exposure/…10 sliders) | ✅ (Adjust tab + `--adjust`) | 🟡 (Camera Raw) | ❌ | ❌ | ✅ | ✅ | ✅ |
| Layer↔document adjustment scope | ✅ | ✅ | ✅ | — | — | — | — |
| Scene-referred / HDR pipeline | ❌ (8-bit display-referred) | ✅ (32-bit) | ✅ (32-bit float) | 🟡 (HDR display support) | ✅ (HDR edit/export) | ✅ (filmic/sigmoid/AgX) | ✅ |
| Skin-tone / point color tools | ✅ [Adjustments](adjustments.md) | ✅ | ❌ | ❌ | ✅ (Point Color) | 🟡 (color zones) | ✅ (Color Editor) |

## Raw & color management

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Camera-raw import | 🟡 (rawpy, camera WB, 8-bit) [File Formats](file-formats.md) | ✅ (Camera Raw) | 🟡 (via darktable/RawTherapee handoff) | ❌ | ✅ | ✅ | ✅ |
| Full raw develop pipeline | ❌ | ✅ | — | — | ✅ | ✅ | ✅ |
| ICC color management | ✅ (viewport-only, DD-004) [Adjustments](adjustments.md) | ✅ | ✅ | ✅ (5.1+) | ✅ (sRGB/P3/Rec2020 added 15.x) | ✅ | ✅ |
| CMYK mode | 🟡 (export only, DD-005) | ✅ | 🟡 (soft-proof, no native mode) | ❌ | — | — | 🟡 (process recipes) |
| 16/32-bit per channel | ❌ (8-bit premultiplied) | ✅ | ✅ | ❌ (8-bit internal) | ✅ | ✅ (32-bit float) | ✅ |
| Lens corrections | ❌ | ✅ | 🟡 (plugin) | ❌ | ✅ | ✅ | ✅ |
| AI denoise | ❌ (adapter could) | ✅ | ❌ | ❌ | ✅ | 🟡 (5.6 Lua AI models) | ✅ (Enhanced Denoise 16.8) |

## Filters, effects & ML

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Gaussian blur / unsharp mask | ✅ [Filters](filters.md) | ✅ | ✅ | ✅ | ✅ (masked) | ✅ | ✅ |
| Tilt-shift / lens blur | ✅ | ✅ | 🟡 | 🟡 (plugins) | ✅ (Lens Blur AI) | 🟡 | ❌ |
| Big filter library | ✅ (G'MIC + GEGL packs + GIMP bridge) [Filter Plugins](filter-plugins.md) | ✅ (hundreds) | ✅ (GEGL + G'MIC) | ✅ (plugin ecosystem) | — | ✅ (70+ modules) | 🟡 (styles) |
| Generative fill (prompt-based) | ✅ **BYO model** [Model Backends](model-backends.md) | ✅ (Firefly + Flux/Gemini partner models, cloud or local) | ❌ | ❌ | 🟡 (Firefly handoff) | ❌ | ❌ |
| Generative upscale | ❌ (adapter could) | ✅ (Topaz built in) | ❌ | ❌ | 🟡 (Enhance) | 🟡 (Lua AI models) | ❌ |
| Style/look transfer | ❌ | ✅ (Harmonize) | ❌ | ❌ | 🟡 (presets/AI) | 🟡 (styles) | ✅ (Match Look) |
| ML runs without vendor cloud/account | ✅ (any HTTP backend or plugin) | 🟡 (some on-device; credits for the rest) | — | — | ❌ | ✅ (local models) | ✅ (local) |

## Text & vector

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Text tool with font/size/colour | ✅ [Tools](tools.md) | ✅ | ✅ | ✅ | — | 🟡 (watermark) | 🟡 (watermark) |
| Rich text — per-letter colour, bold/italic, WYSIWYG preview | ✅ (GUI editor + `--text-rich` HTML) | ✅ | ✅ | 🟡 (single style) | — | — | — |
| Re-editable text layers | 🟡 (ORA parameters; SVG safe text subset) | ✅ | ✅ | ❌ | — | — | — |
| Ordered text/layer appearance effects and presets | ✅ (10 live effects; ORA + SVG filters) | ✅ | 🟡 | 🟡 | — | — | — |
| Shape tool (rect/ellipse/line) | ✅ (parametric, re-editable) | ✅ (vector) | ✅ (vector layers, 3.2) | ✅ (raster) | — | — | — |
| Pen / path tool | 🟡 (native cubic model; narrower direct editing) | ✅ (full vector) | ✅ | ❌ | — | — | — |
| Parametric (re-editable) vectors | 🟡 [Vector Model](vector-model.md) | ✅ | ✅ (3.2 vector layers) | ❌ | — | — | — |
| Multi-object selection, Boolean, align/distribute, gradients | 🟡 (core engine + selection tools; not Illustrator-level) | ✅ | ✅ | ❌ | — | — | — |
| SVG editable interchange | 🟡 (documented safe subset + fallback) | ✅ | ✅ | ❌ | — | — | — |

## Automation, scripting & headless

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Action/macro recording | ✅ [Actions](actions.md) | ✅ | 🟡 (script instead) | ❌ | 🟡 (presets/batch) | ✅ (styles) | ✅ (styles) |
| Scripting language | ❌ (CLI instead) | ✅ (JS/AppleScript/VBS) | ✅ (Script-Fu, Python 3) | ❌ | ✅ (Lua SDK) | ✅ (Lua + AI API) | 🟡 (AppleScript, Mac) |
| Headless CLI | ✅ **58 shared engine ops** [CLI](cli.md) | ❌ | ✅ (`gimp -i -b`, script-driven) | ❌ | ❌ | ✅ (`darktable-cli`, export-focused) | ❌ |
| Start pipelines from blank docs | ✅ (`--new A4 --dpi 300`) | — | ✅ (script) | ❌ | — | — | — |
| Batch export | ✅ (shell loops + CLI) | ✅ (Actions batch) | ✅ | ❌ | ✅ | ✅ | ✅ (process recipes) |

## Catalog / DAM & tethering

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Catalog / asset management | — | 🟡 (Bridge) | — | — | ✅ (+duplicate finder, keyword sync) | ✅ (lighttable) | ✅ (sessions + catalogs) |
| Tethered capture | — | ❌ | — | — | ✅ (Canon PTP, Fuji…) | ✅ | ✅ (best-in-class; multi-user beta) |
| Culling / review AI | — | ❌ | — | — | ✅ (Assisted Culling) | ❌ | ✅ (Assisted Review) |

Photoslop is an editor, not a DAM — these rows are scope notes, not gaps.

## File formats & export

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Native layered format | ✅ .ora (open standard) [File Formats](file-formats.md) | ✅ .psd/.psb (proprietary) | ✅ .xcf + .ora | ✅ .pdn | — | — | — |
| Layered/vector interchange with other apps | 🟡 (ORA raster fallback + SVG safe subset) | 🟡 (PSD is the de-facto standard) | ✅ (ORA + improved PSD/SVG) | ❌ | — | — | — |
| PNG/JPEG/BMP/WebP | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| AVIF / JPEG XL | ✅ (`[formats]` extra) [File Formats](file-formats.md) | ✅ | ✅ | ❌ | ✅ | 🟡 | ✅ |
| Named export regions (artboards) | ✅ [Artboards](artboards.md) | ✅ | ❌ | ❌ | — | — | — |
| Export quality/scale preview | ✅ (Export As) | ✅ | ✅ | 🟡 | ✅ | ✅ | ✅ |

## Extensibility

| Feature | Photoslop | Photoshop | GIMP | Paint.NET | LR Classic | darktable | Capture One |
|---|---|---|---|---|---|---|---|
| Plugin API | ✅ (model adapters + filters via entry points) [Filter Plugins](filter-plugins.md) | ✅ (UXP ecosystem) | ✅ (huge; G'MIC etc.) | ✅ (large legacy + GPU system) | ✅ (Lua) | ✅ (Lua) | 🟡 |
| Bring-your-own ML backend | ✅ (HTTP contract or Python plugin) [Model Backends](model-backends.md) | ❌ (Adobe-chosen partners) | ❌ | ❌ | ❌ | ✅ (5.6 Lua AI inference) | ❌ |
| Open source | ✅ Apache-2.0 | ❌ | ✅ GPL-3.0 | 🟡 (freeware, source partially closed since 4.x) | ❌ | ✅ GPL-3.0 | ❌ |

## Where Photoslop stands out

- **Headless automation through a shared engine.** All 54 operations are shared
  by CLI and MCP; GUI presentation-only interactions have explicit parity
  rulings. Pipelines compose as ordered operations (`--new A4 --dpi 300 --adjust
  "exposure=1" --select-poly … --clear --output out.png`). None of the six has
  this: Photoshop has no headless mode at all, `darktable-cli` is
  export-focused, and GIMP's batch mode requires writing Script-Fu.
- **Bring-your-own-model AI.** Generative Fill and Select Subject speak a
  documented HTTP contract to *any* backend — local ComfyUI, a corporate
  endpoint, whatever — with no vendor account, no cloud requirement, and no
  generative credits. Photoshop's equivalent is powerful but Adobe-mediated.
- **Memory frugality by design.** One premultiplied buffer per layer,
  copy-on-write sharing, viewport-only compositing, tile-based undo
  ([Architecture](architecture.md)) — a 45 MP file is comfortable on modest
  hardware, and the install is measured in megabytes, not gigabytes.
- **Open format first.** The native format is OpenRaster with documented
  extensions — your layered files open in GIMP and Krita today.
- **Apache-2.0** — permissive, no copyleft obligations, no subscription.

## Notable gaps (the honest list)

Grouped by theme; each line notes rough effort. None of these has a tracker
issue yet — this section is the menu to pick from.

**Color depth & management** — the deepest structural gap.
- 8-bit premultiplied only; no 16/32-bit, no HDR pipeline *(large — touches
  every engine path)*.
- ~~No ICC color management~~ *(shipped v1.9.0 — assign/convert,
  monitor-profile display transform, soft-proof, profile embedding,
  CMYK export; all viewport-only per DD-004)*.
- No CMYK mode or print pipeline *(large; niche for the current audience)*.

**Raw development.**
- Raw import has transient 16-bit exposure/white-balance/highlight/shadow
  development plus optional lens correction and model denoise, but the resident
  document remains 8-bit and is not a scene-referred pipeline *(large)*.

**Editing depth.**
- One adjustment-layer type (LUT) vs Photoshop's ~20 *(medium; the LUT
  plumbing generalizes)*.
- ~~Shapes/pen rasterize on commit~~ *(shipped v1.8.0 — parametric
  vector layers with handle editing and crisp transform re-render)*.
- ~~No plugin API for filters~~ *(shipped v1.4.0 — `photoslop.filters`
  entry points; the library itself grows via the filter packs, #111)*.
- No tablet pressure sensitivity *(small-medium; QTabletEvent, needs hardware
  to verify)*.

**Workflow.**
- No on-disk action files (actions live per-session) *(small)*.
- ~~No AVIF/JPEG XL~~ *(shipped v1.2.0 via the `photoslop[formats]` extra)*.
- History panel is linear; no snapshots *(medium)*.

## Sources

Competitor claims verified July 2026 against:

- Adobe Photoshop: [release notes](https://helpx.adobe.com/photoshop/desktop/whats-new/photoshop-on-desktop-release-notes.html) · [what's new](https://helpx.adobe.com/photoshop/desktop/whats-new/whats-new-in-adobe-photoshop-on-desktop.html) · [tech requirements](https://helpx.adobe.com/photoshop/desktop/get-started/technical-requirements-installation/adobe-photoshop-on-desktop-technical-requirements.html)
- Adobe Lightroom Classic: [what's new](https://helpx.adobe.com/lightroom-classic/help/whats-new.html) · [release notes](https://helpx.adobe.com/lightroom-classic/help/whats-new/release-notes.html) · [features](https://www.adobe.com/products/photoshop-lightroom/features.html)
- darktable: [5.6.0 release](https://www.darktable.org/2026/06/darktable-5.6.0-released/) · [releases](https://github.com/darktable-org/darktable/releases)
- GIMP: [downloads (3.2.4 stable)](https://www.gimp.org/downloads/) · [3.2 release notes](https://www.gimp.org/release-notes/gimp-3.2.html) · [3.2 announcement](https://www.gimp.org/news/2026/03/14/gimp-3-2-released/)
- Paint.NET: [roadmap & changelog](https://paint.net/roadmap.html) · [download](https://paint.net/download.html)
- Capture One: [what's new](https://www.captureone.com/en/explore-features/whats-new) · [16.8.1 release notes](https://support.captureone.com/hc/en-us/articles/36530819608605-Capture-One-16-8-1-release-notes)

Photoslop claims are grounded in this documentation library — every ✅ links
to the guide that describes the shipped feature.

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/
