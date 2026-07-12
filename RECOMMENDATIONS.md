# Photoslop Code Review and Recommendations

Reviewed: July 2026

## Executive summary

Photoslop has a strong functional core and an unusually broad automated test
suite, but its interaction design has not kept pace with its image-processing
features. The engine is generally disciplined about copy-on-write images,
viewport rendering, bounded layers, and undo storage. The largest problems are
instead at the boundary between that engine and the user:

1. The text-size control is actively broken for keyboard entry. Its change
   handler moves focus into the text editor after the first accepted value, and
   the control is capped at 400 rather than 999.
2. The toolbox is an ungrouped column of 30 small, low-contrast icons. It
   overflows at modest window heights, depends heavily on tooltips, and exposes
   too much of the program at once.
3. Most tools technically assign a cursor, but many inherit the same crosshair
   and interactive modes do not update the cursor for handles, valid targets,
   modifiers, or operation state. This does not provide meaningful tool
   feedback.
4. Accessibility is almost entirely implicit. Standard Qt widgets provide a
   useful starting point, but icon-only controls, custom canvas widgets,
   visual-only overlays, status messages, and drag-only operations are not
   exposed adequately to keyboard and assistive-technology users.
5. Expensive image processing, file operations, subprocesses, and HTTP model
   requests run synchronously on the GUI thread. Debouncing limits frequency
   in a few dialogs but does not prevent the application from freezing.
6. The current “vector” implementation retains a small amount of geometry but
   rasterizes each object into a layer. It is useful parametric raster content,
   not yet a professional vector object model.

The recommended direction is a cross-platform, WCAG 2.2 AA-informed workspace
overhaul, a memory-bounded background-task system, and a real vector-object
foundation. Photoslop should remain raster-first and memory-first while making
its vector workflow comparable to the core workflows shared by Illustrator,
Inkscape, Affinity Designer, and CorelDRAW.

## Review method and current baseline

The review covered the application entry points, main window, tool and canvas
event flow, dialogs and panels, document/layer model, rendering and compositing,
undo commands, vector and text representations, file I/O, filters, external
process integrations, model adapters, CLI/MCP separation, tests, and published
feature documentation.

The current automated baseline is healthy:

- `QT_QPA_PLATFORM=offscreen uv run pytest -q`: **2,377 passed, 38 skipped**.
- The skips are optional-dependency/platform cases plus intentionally skipped
  malformed CLI forms, rather than unexpected core failures.
- The run reports 89 deprecation warnings from `QImage.mirrored()` in a CLI
  path.
- `uv run ruff check .` could not run in the base environment because the
  development extra, and therefore `ruff`, was not installed.

This test suite gives the processing engine good regression protection. It does
not currently establish accessibility, interaction latency, visual quality, or
keyboard workflow guarantees.

## Priority definitions

- **P0 — correctness/access blocker:** prevents an ordinary interaction or
  excludes a user from a primary workflow.
- **P1 — foundational usability:** should be resolved before adding more tools
  to the existing workspace.
- **P2 — professional workflow depth:** substantial capability needed for core
  vector-program parity.
- **P3 — advanced parity:** valuable but intentionally outside the first core
  vector target.

These are dependency and impact priorities, not sprint or release assignments.

## Implementation issue map

The actionable recommendations are tracked in GitHub as bounded implementation
issues and mirrored in `BACKLOG.md`:

- [#147](https://github.com/CryptoJones/Photoslop/issues/147) — text-size
  keyboard entry up to 999 pt
- [#148](https://github.com/CryptoJones/Photoslop/issues/148) — contextual tool
  cursors and pointer states
- [#149](https://github.com/CryptoJones/Photoslop/issues/149) — iconography and
  grouped toolbox flyouts
- [#150](https://github.com/CryptoJones/Photoslop/issues/150) — workspace action
  state and contextual options
- [#151](https://github.com/CryptoJones/Photoslop/issues/151) — cross-platform
  accessibility semantics and keyboard workflows
- [#152](https://github.com/CryptoJones/Photoslop/issues/152) — cancellable
  background task service
- [#153](https://github.com/CryptoJones/Photoslop/issues/153) — repaint and
  preview performance
- [#154](https://github.com/CryptoJones/Photoslop/issues/154) — UI/tool/action
  registry boundaries
- [#155](https://github.com/CryptoJones/Photoslop/issues/155) — versioned native
  vector object model
- [#156](https://github.com/CryptoJones/Photoslop/issues/156) — vector selection,
  node editing, appearance, and construction
- [#157](https://github.com/CryptoJones/Photoslop/issues/157) — SVG import/export
  and editable artboards
- [#158](https://github.com/CryptoJones/Photoslop/issues/158) — verification
  matrix and honest feature-parity documentation

## P0: Fix text-size keyboard entry

### Finding

`TextDialog.size` is a `QSpinBox` with a range of 6–400. Its `valueChanged`
signal calls `_on_size()`, which calls `_merge()`. `_merge()` always calls
`self.edit.setFocus()`. As a result, keyboard focus leaves the size field as
soon as an intermediate value is accepted. This is why multi-digit typing
appears to stop or “carriage return” into the editor.

### Recommendation

- Change the accepted point-size range to **6–999**.
- Do not change focus inside the generic formatting merge function.
- Preserve the selection/caret in the rich-text editor while a formatting
  control has focus; applying formatting must not require moving focus.
- Let explicit toolbar actions such as Bold or Italic return focus to the
  editor only when that behavior is useful. Numeric and font-family controls
  must retain focus throughout keyboard entry.
- Ensure the spinner is wide enough to display `999 pt` without clipping at
  supported UI scale factors.
- Enter while the spinner is focused must commit the numeric edit. It must not
  insert a newline in the document or accidentally accept the entire dialog.
- Keep invalid, empty, pasted, and out-of-range values under normal `QSpinBox`
  validation rather than silently truncating them.

### Required regression cases

- Select the existing value and type `9`, `99`, and `999`; focus stays in the
  spinner after every digit and the final value is applied.
- Type or paste `100`, `400`, `401`, and `999`.
- Verify values below 6 and above 999 are rejected or clamped visibly.
- Apply a size to selected text and to subsequent typing with no selection.
- Press Enter and Tab from the field and verify predictable focus order.
- Reopen a text layer containing 999-point text and round-trip its metadata.

## P0/P1: Replace cursor assignment with tool feedback

### Finding

The main window does call `setCursor()` when the active tool changes. The user
report is nevertheless accurate at the interaction level: most drawing and
selection tools inherit `CrossCursor`, and the cursor remains static when the
pointer moves across handles or changes operation. Transform always reports
`SizeAllCursor`; Pen and Shape always report a crosshair; Eyedropper and Zoom
inherit the generic cursor; and modifier states are usually visible only in
documentation or the status bar.

### Recommendation

Create one cursor controller driven by declarative tool metadata and live hit
testing. A tool should be able to return a cursor for its current context rather
than exposing one class constant.

At minimum, provide:

- Brush, Pencil, Eraser, healing, clone, dodge/burn, smudge, and liquify:
  a high-contrast circular outline representing the effective radius, with a
  small central precision mark at very large sizes.
- Bucket, Gradient, Eyedropper, Text, Pen, Shape, Crop, selection tools, Hand,
  Zoom, and Move: distinct tool-glyph cursors with tested hotspots.
- Transform and vector editing: directional resize cursors, rotate cursor,
  move cursor, node/handle cursor, add/delete/convert-node indicators, and an
  invalid-action state.
- Clone/heal: source-set and source-required feedback.
- Zoom: plus/minus state when Alt/Option is held.
- Selection tools: add/subtract/intersect modifier badges.
- Spacebar pan: Open Hand before dragging, Closed Hand while dragging, and
  restoration to the exact contextual cursor on release.
- Platform-appropriate fallbacks when a custom cursor is unavailable.

Cursor assets must render correctly at 1× and 2× scale, use a contrasting
outline so they remain visible over light and dark artwork, and stay small
enough not to obscure the target.

## P1: Replace the icon system and regroup the toolbox

### Findings

- Icons are painted into a single 22×22 pixmap using a hard-coded dark gray.
  They do not provide theme-specific, disabled, hover, or high-contrast forms.
- At ordinary window heights the one-column toolbar cannot display all 30
  actions and falls back to an overflow arrow.
- Many icons are visually similar at their rendered size. Specialized tools
  are especially difficult to identify without hovering.
- The top options bar exposes controls as compact suffix-heavy spin boxes with
  no persistent labels. At narrower widths it becomes a dense row of numbers.
- The layer panel uses text glyphs (`+`, `−`, arrows, and other symbols) as
  controls. Their meaning and appearance depend on the active font.

### Icon recommendation

Use a bundled, version-pinned subset of **Tabler Icons** as the base visual
language. Tabler provides an MIT-licensed 24×24 SVG outline family. Draw custom
icons for graphics-specific tools that do not have a clear equivalent, using
the same grid, stroke width, caps, joins, and optical alignment.

- Bundle only the selected SVG sources; do not add a runtime network or package
  dependency.
- Record upstream source, version/commit, modifications, and license in the
  repository’s third-party notices.
- Render icons from palette-aware SVG or paths rather than fixed-color pixmaps.
- Support normal, hover, checked, disabled, light, dark, and high-contrast
  states from the same source geometry.
- Supply accessible action text independently of the icon.
- Test every icon at its actual 16, 20, 24, and 32 logical-pixel uses rather
  than judging only the source SVG.

### Toolbox recommendation

Group related tools into familiar flyouts while keeping the last-used tool
visible:

- Move / direct selection / transform
- Marquee selections
- Lasso selections
- Automatic selections
- Crop / perspective / warp
- Brush / pencil / eraser
- Heal / clone / patch
- Smudge / dodge / burn / liquify
- Bucket / gradient
- Pen / node editing
- Shapes
- Text
- Eyedropper
- Hand / zoom

The tool registry should be the single source for ID, display name, icon,
cursor provider, shortcuts, group, options, help text, and accessibility text.
This removes the current duplication among tool construction, toolbar ordering,
shortcut dictionaries, label dictionaries, option visibility, and cursor
classes.

Allow users to choose compact icons, comfortable icons, or icons with text.
Maintain the existing keyboard shortcuts unless a conflict is documented and
migrated. A flyout must be reachable and usable from the keyboard.

## P1: Streamline the workspace

### Contextual options

Replace the anonymous show/hide list in the top toolbar with named, contextual
groups. The active tool name and its primary action should always be visible.
For example, Brush should show labeled controls for Size, Hardness, Opacity,
Flow, Spacing, and Scatter; Pen should show Fill, Stroke, Width, Node Mode, and
path actions.

Tool options should:

- reflow or move into an overflow menu at narrow widths;
- retain user values without retaining stale visibility;
- expose labels and value units to assistive technology;
- accept direct keyboard entry without global single-key shortcuts firing;
- provide Reset to Defaults per tool;
- avoid changing the canvas merely because a control receives focus.

### Panels and actions

- Add a contextual Properties panel rather than distributing layer and object
  properties across menus and modal dialogs.
- Store important actions and update their enabled/disabled state when the
  document, selection, active layer, clipboard, task state, or tool changes.
  Currently many impossible commands remain enabled and silently return.
- Add a searchable command palette that presents command names, shortcuts,
  availability, and a short explanation when disabled.
- Retain configurable docks and saved workspaces, but validate restored layouts
  against the current screen geometry and UI scale.
- Provide a first-run/default workspace that works at laptop resolutions
  without hidden tools or clipped controls.
- Use menus for commands, toolbars for frequent actions, and contextual panels
  for editable state; avoid exposing the same operation in several unrelated
  places without a clear reason.

### Feedback and errors

Transient status-bar messages are too easy to miss and are not a substitute for
command state or accessible announcements.

- Disable impossible actions when the prerequisite is stable and obvious.
- For recoverable failures, show a persistent, keyboard-focusable notification
  with a concise recovery action.
- Reserve modal dialogs for decisions that must block progress.
- Announce successful state changes and errors to assistive technologies.
- Show progress and cancellation for work that can exceed roughly 250 ms.

## P1: Accessibility for people with disabilities

The target should be WCAG 2.2 AA principles adapted to a native desktop editor,
plus native Qt accessibility semantics on Windows, macOS, and Linux. WCAG is
not a desktop conformance certification here; it is the interaction and visual
quality bar.

### Names, roles, values, and relationships

- Give every icon-only button, swatch, preview, toolbar, dock, status value,
  and custom control a unique accessible name and useful description.
- Use visible `QLabel` buddies or explicit accessibility relationships for all
  spin boxes, combo boxes, sliders, and line edits.
- Expose slider values in meaningful units, such as “Exposure plus 1.25 EV,”
  rather than only the underlying integer.
- Announce checked state, mixed state, selection count, active layer, hidden
  state, clipping/group membership, and current tool.
- Give tabs and documents unique names that include modified state without
  relying solely on an asterisk.
- Avoid using tooltips as the only accessible name or instruction.

### Custom widgets

Canvas, rulers, curve editor, sampling preview, swatches, vector nodes, and
other hand-painted controls need explicit accessible interfaces or equivalent
semantic companion controls.

The canvas should expose at least:

- document name and dimensions;
- active layer/object and selection state;
- current tool and coordinates;
- available actions for the current object or selection;
- keyboard operations for moving, resizing, rotating, editing nodes, creating
  selections, and confirming/cancelling an operation;
- state/value change events and polite/assertive announcements as appropriate.

A screen reader does not need a verbal description of every pixel. It does
need a usable object/layer structure and access to the same editing commands as
a pointer user.

### Keyboard access

- Establish and test a logical Tab/Shift+Tab focus order in every dialog and
  panel.
- Keep single-letter tool shortcuts inactive while an editable text or numeric
  control has focus.
- Provide keyboard alternatives to all drag-only operations, including guides,
  crop bounds, transform handles, curve points, anchors, and panel reordering.
- Support arrow-key movement, Shift for larger steps, and numeric entry for
  precision operations.
- Ensure Escape cancels only the current operation before clearing unrelated
  document state. The current canvas Escape path also clears the selection.
- Make focus visible against every supported palette and artwork background.
- Document shortcuts in the UI, not only in Markdown documentation.

### Low vision, contrast, and color perception

- Remove fixed 11 px instructional text and other style-sheet font sizes that
  ignore the system font.
- Remove fixed dimensions that clip at large fonts; use layouts and size hints
  except where a scalable drawing surface requires an explicit minimum.
- Provide comfortable and large control-density settings.
- Meet at least 3:1 contrast for control boundaries, focus indicators, nodes,
  handles, guides, and meaningful icons.
- Never encode layer type, selection state, node type, or validity by color
  alone. Pair color with shape, pattern, label, or icon.
- Offer configurable guide, grid, selection, node, and handle colors with a
  high-contrast preset.
- Render nodes and handles with a two-tone outline so they remain visible over
  arbitrary artwork.
- Allow small, medium, and large nodes/handles and pointer targets.

### Motion and timing

- Add a reduced-motion preference and respect the operating-system preference
  when available.
- Stop or simplify marching-ants animation under reduced motion.
- Do not use a disappearing message as the sole representation of an error or
  completed action.
- Do not impose time limits on interactive edits.

### Assistive-technology verification

Maintain manual smoke-test scripts for:

- VoiceOver on macOS;
- NVDA on Windows;
- Orca/AT-SPI on Linux.

Automated accessible-tree tests should verify unique names, roles, values,
relations, focus, checked/disabled state, and emitted change events. Manual
testing remains necessary to assess reading order and actual task completion.

## P1: Performance and responsiveness

### Preserve the good engine constraints

Continue to preserve:

- one resident pixel buffer per ordinary layer;
- copy-on-write sharing where safe;
- viewport/dirty-region compositing;
- bounded layers and dirty-tile undo;
- no permanent full-document flattened cache;
- region-bounded temporary processing where practical.

The memory-first policy should not mean that the GUI event loop is allowed to
block for seconds. Responsiveness can improve without retaining unbounded image
copies.

### Move expensive work off the GUI thread

The following currently execute synchronously from GUI actions or timers and
can freeze interaction:

- opening and saving layered documents;
- RAW preview/development;
- flattening, scaling, encoding, and writing exports;
- full-layer filters and content-aware scaling/fill;
- adjustment previews across one or many full layers;
- GIMP, GEGL, and G'MIC subprocess calls;
- model HTTP requests, including base64 PNG encoding and decoding;
- lens correction and other optional integrations.

Introduce a task service with a small bounded worker pool and a `TaskHandle`
contract for progress, cancellation, completion, and failure. Workers must
operate on immutable/COW snapshots and return a result; only the GUI thread may
install that result into the live document and undo stack.

Requirements:

- Never mutate an image concurrently with canvas painting.
- Reject or reconcile a stale result when the source layer generation changed
  while the task was running.
- Cancellation must terminate or signal subprocess and network work where
  possible and discard late results safely.
- A failed task must leave document pixels, undo history, and dirty state
  unchanged.
- Limit concurrent image tasks based on peak memory, not only CPU count.
- Avoid pre-copying full images when Qt copy-on-write can safely provide the
  task snapshot.

### Canvas repainting

- `mouseMoveEvent()` currently requests a full canvas update for hover
  feedback. Track the old and new overlay bounds and repaint their union.
- Apply the same dirty-overlay discipline to brush outlines, pen previews,
  shape previews, transform handles, and guide labels.
- Keep marching-ants repainting to the visible intersection of the selection
  boundary rather than a large selection bounding rectangle where feasible.
- Profile group/adjustment compositing separately. Do not add a flattened cache
  until measurements show that a bounded viewport-tile cache beats direct
  rendering within the memory budget.
- Avoid repeated linear layer lookup in hot compositing paths; pass or cache a
  per-render index/clip relationship map.

### Panels and previews

- The layer panel regenerates every layer thumbnail after every undo index
  change. Associate a thumbnail with the layer image generation and update only
  changed rows.
- Decode open-dialog previews asynchronously and discard stale results when the
  user changes selection rapidly.
- Export preview should generate a small preview from the master once, while
  full-resolution scaling and encoding used for the size estimate runs as a
  cancellable background task.
- Adjustment previews should use a viewport-sized proxy while dragging, then
  perform the exact full-resolution pass on release or Apply.
- Debounce timers should prevent redundant work, and generation IDs should
  prevent an old completion from replacing a newer preview.

### Performance budgets and benchmarks

Add reproducible documents representing:

- a 4K canvas with 50 mixed raster/vector layers;
- a 12K camera image with 20 layers;
- adjustment layers, masks, clipping, groups, effects, and a large selection;
- rapid brush, transform, panel, export-preview, and adjustment interactions.

Recommended acceptance targets on the documented reference machine:

- GUI heartbeat/event-loop delay stays below 100 ms while background work is
  active.
- Common canvas interactions target a 33 ms P95 frame time at fit-to-window.
- A task shows progress or an indeterminate busy state within 250 ms.
- Steady-state caches are explicitly bounded and separately reported from
  `Document.memory_bytes()`.
- No optimization may introduce a resident full-canvas composite cache.
- Benchmark reports include peak RSS and temporary allocation, not just elapsed
  time.

## P1: Maintainability needed to support the overhaul

`mainwindow.py` and `tools.py` carry too many unrelated responsibilities. The
problem is not only their line counts; menu construction, action state, file
workflows, filter orchestration, tool metadata, editing state, and UI feedback
are tightly coupled.

Recommended internal boundaries:

- **Action registry:** command ID, label, shortcut, prerequisites, handler, and
  help text; feeds menus, toolbars, command search, and accessibility.
- **Tool registry:** tool ID, group, icon, cursor provider, shortcuts, option
  schema, and factory.
- **Workspace UI:** toolbox, contextual options, docks, notifications, command
  palette, and saved layout.
- **Task service:** bounded workers, task lifecycle, cancellation, progress,
  stale-result protection, and GUI-thread commit.
- **Document services:** file, export, model, and filter operations independent
  of widget construction.
- **Engine:** document, layers/objects, commands, rendering, and headless
  operations remain usable by GUI, CLI, tests, and MCP.

Avoid a broad rewrite that forks GUI and headless behavior. Move one complete
workflow at a time behind these interfaces and retain existing tests.

## P2: Core professional vector parity

### Current state

Current shape and pen layers store JSON-compatible parameters and a rasterized
image. The design supports re-editing a few points and preserves a fallback in
OpenRaster, which is a useful compatibility mechanism. It does not yet provide:

- arbitrary cubic Bézier segments and direction handles;
- corner, smooth, and symmetric node types;
- independent fill and stroke on every object;
- gradient fills/strokes and full stroke attributes;
- compound paths, Boolean operations, or fill rules;
- multi-object/direct selection;
- persistent object transforms and precise transform fields;
- crisp direct vector rendering at arbitrary view zoom;
- standard SVG import/export;
- professional text objects or text-on-path;
- hierarchical object grouping.

Catmull–Rom interpolation through click points is not a substitute for a Pen
tool with explicit Bézier controls.

### Versioned object model

Introduce a versioned vector schema instead of extending the existing
unversioned dictionaries indefinitely. Each vector object should retain:

- stable object ID, name, type, visibility, lock state, and parent/group ID;
- local geometry and a non-destructive transform matrix;
- one or more subpaths represented by move, line, cubic, and close commands;
- node type and independent/in-linked direction handles;
- fill rule and fill paint (`none`, solid, linear gradient, radial gradient);
- stroke paint, width, alignment, cap, join, miter limit, dash pattern/offset,
  and scale-with-object behavior;
- object opacity and blend mode;
- clipping/masking relationships where supported;
- version and extension fields for forward-compatible persistence.

Text objects should retain Unicode content, font family/style, point size,
color, alignment, line spacing, character spacing, frame geometry, and runs.
Missing fonts must produce a visible warning and deterministic fallback without
destroying the original font metadata.

### Rendering and compatibility

- Render vector geometry directly through `QPainterPath` for interactive view
  and normal document output instead of drawing the stored 1× raster fallback.
- Rasterize only where a raster effect/mask requires it, and only at the target
  region/scale.
- Continue writing a raster fallback for every vector/text object in `.ora` so
  other OpenRaster applications display the document.
- Store the versioned vector payload as a Photoslop extension alongside that
  fallback.
- Read and migrate existing rectangle, ellipse, line, path, and text metadata
  in memory. Saving may write the new schema, but opening and resaving must not
  visibly change old documents.
- Preserve unknown future extension fields when possible.

### Selection and object editing

Add a Selection tool and a Direct Selection/Node tool with:

- click, Shift-click, marquee, and select-all for multiple objects;
- cycling/selecting objects under the pointer;
- bounding boxes and configurable transform origins;
- move, rotate, scale, skew, flip, duplicate, and numeric transforms;
- arrow-key nudge and Shift-modified larger steps;
- node marquee selection, add/delete node, split/join path, close/open path,
  convert corner/smooth/symmetric, and handle manipulation;
- keyboard-accessible node lists/properties for users unable to drag precisely;
- snap feedback that states the target, axis, and distance.

Selection must be separate from the active drawing tool. Users should not need
to reactivate the tool that created an object merely to edit or move it.

### Appearance and construction

Core parity requires:

- independent Fill and Stroke controls in the contextual bar and Properties
  panel;
- linear/radial gradients with editable stops, midpoint, opacity, and transform;
- rectangle, rounded rectangle, ellipse, line, polygon, and star primitives;
- Pen, Pencil/freehand, and node tools;
- Union, Difference, Intersect, Exclude, Divide/Split, and compound paths;
- group/ungroup, lock/hide, ordering, duplicate, and isolation/edit-in-place;
- align and distribute to selection, key object, canvas, or artboard;
- configurable snapping to grid, guides, nodes, paths, bounds, centers, and
  artboards;
- editable artboards with names, bounds, ordering, and per-artboard export;
- non-destructive text objects, basic character/paragraph formatting, and
  text-on-path.

### SVG interchange

Add SVG import/export as the primary vector interchange format.

Import should support the subset represented by the native object model and
retain unsupported content as a preserved/rasterized fallback with warnings.
Export should preserve paths, transforms, groups, fills, strokes, gradients,
text where safe, artboard/view-box bounds, and object names/IDs. Test exported
files in at least Inkscape and a browser, with Illustrator/Affinity smoke tests
when available.

Do not claim vector parity until SVG round trips preserve editable geometry and
appearance for the documented supported subset.

### Explicitly deferred P3 vector features

The following are advanced gaps, not part of the selected core target:

- mesh/freeform gradients;
- variable-width profiles and full vector-brush engines;
- reusable symbols/components and instance overrides;
- automatic bitmap tracing;
- advanced OpenType typography and variable-font axes;
- envelopes, live repeat/pattern systems, and advanced distortions;
- data merge, charting, packaging, and linked assets;
- full CMYK spot-color, trapping, separation, and print/prepress workflow.

These should remain visible in the parity document rather than being implied by
a generic “vector supported” checkmark.

## Documentation and feature-parity accuracy

The existing parity document is detailed but treats retained vector parameters
as full non-destructive vector parity. Revise future claims to distinguish:

- retained editable parameters;
- crisp vector rendering at arbitrary zoom;
- standard vector interchange;
- professional object/node editing;
- complete versus partial workflow parity.

Use official current documentation from Illustrator, Inkscape, Affinity
Designer, and CorelDRAW as the comparison baseline. Record product/document
versions and the date of comparison. Avoid comparing only the presence of a
tool name; compare whether a user can complete the same end-to-end task.

## Required verification matrix

### Accessibility

- Complete representative workflows using keyboard only.
- Inspect the accessible tree for every main window, dock, toolbar, dialog, and
  custom widget.
- Run VoiceOver, NVDA, and Orca smoke tests.
- Verify 200% system text/UI scale without clipped controls or lost actions.
- Verify light, dark, high-contrast, and common color-vision-deficiency views.
- Verify reduced motion and non-animated selection feedback.

### UI and iconography

- Screenshot tests at laptop and desktop sizes, 1× and 2× device pixel ratios.
- Every tool remains discoverable without toolbar overflow.
- Checked, disabled, hover, focus, and high-contrast icon states are distinct.
- Tool groups and contextual controls are fully keyboard accessible.
- No global tool shortcut changes an active text or numeric input.

### Cursor behavior

- Verify every tool’s default cursor and hotspot.
- Verify hover over every transform edge/corner, vector node/segment, guide,
  crop edge, and valid/invalid target.
- Verify all relevant modifier-key states.
- Verify Spacebar Hand override before, during, and after a drag.
- Verify custom cursor visibility over black, white, detailed, and transparent
  checkerboard backgrounds.

### Performance

- Record P50/P95 frame and input latency on standardized documents.
- Record total duration, peak RSS, cancellation latency, and result correctness
  for filters, RAW, save/export, external processes, and model calls.
- Verify stale background results cannot overwrite newer edits.
- Verify task failure/cancellation does not add an undo command or dirty the
  document.
- Verify cache limits and recovery under memory pressure.

### Vector workflows

- Create and edit straight/corner/smooth Bézier paths.
- Apply independent fill/stroke, gradients, caps, joins, dashes, and transforms.
- Select and transform multiple objects and nodes numerically and by keyboard.
- Exercise all Boolean operations and compound-path fill rules.
- Align/distribute and snap against all supported targets.
- Edit artboards and export them.
- Import/export SVG and compare editable geometry and rendered output.
- Open legacy `.ora` vector/text layers and resave without visual regressions.
- Open Photoslop `.ora` files in a non-Photoslop OpenRaster application and
  confirm raster fallbacks remain visible.

## Recommended acceptance definition

The overhaul should be considered successful when:

1. Point size 6–999 is reliably keyboard-enterable with no focus theft.
2. Every tool has recognizable iconography and meaningful contextual cursor
   feedback.
3. Primary workflows are possible with keyboard alone and usable with the
   three target screen readers.
4. The workspace remains legible and complete at laptop sizes and 200% scale.
5. Long work no longer blocks the GUI thread and can be cancelled safely.
6. Performance improvements retain bounded memory and do not add a persistent
   flattened canvas cache.
7. Vector objects remain crisp and editable, support the documented core
   appearance/editing operations, and round-trip through SVG within the stated
   subset.
8. Existing `.ora`, CLI, MCP, shortcuts, and raster editing behavior remain
   compatible or have explicit, tested migrations.

## Reference standards and product baselines

- [W3C Web Content Accessibility Guidelines 2.2](https://www.w3.org/TR/WCAG22/)
- [Qt accessibility overview](https://doc.qt.io/qt-6/accessible.html)
- [Qt accessibility for QWidget applications](https://doc.qt.io/qt-6/accessible-qwidget.html)
- [Adobe Illustrator paths overview](https://helpx.adobe.com/ca/illustrator/desktop/draw-shapes-and-paths/learn-drawing-basics/paths-overview.html)
- [Adobe Illustrator keyboard shortcuts](https://helpx.adobe.com/ca/illustrator/using/default-keyboard-shortcuts.html)
- [Inkscape advanced tutorial](https://inkscape.org/doc/tutorials/advanced/tutorial-advanced.html)
- [Affinity Designer 2 help](https://affinity.help/designer2/en-US.lproj/index.html)
- [CorelDRAW toolbox reference](https://product.corel.com/help/CorelDRAW/Documentation-Windows/CorelDRAW-en/CorelDRAW-Toolbox.html)
- [Tabler Icons repository and MIT license](https://github.com/tabler/tabler-icons)
