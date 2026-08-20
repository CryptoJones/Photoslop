# Backlog

A second view of the GitHub [Issues](https://github.com/CryptoJones/Photoslop/issues)
tab. Every backlog item has a matching issue and vice versa; the two stay in
sync — check an item here when its issue closes.

## Open

### iPadOS / iOS

- [ ] The ⋯ More Actions menu on iPhone holds 15 actions and scrolls, with
  nothing to say that it scrolls — the Finger toggle and everything below the
  fold are effectively invisible. It is a system `UIMenu`, so no scroll
  affordance can be added; the menu has to get shorter
  ([#313](https://github.com/CryptoJones/Photoslop/issues/313))
- [ ] The default brush is invisible on the default canvas: width is a
  hardcoded 8 px that never scales with canvas size, so at fit zoom on a phone
  a stroke lands about 1.5 pt wide
  ([#314](https://github.com/CryptoJones/Photoslop/issues/314))
- [ ] Coloured drop shadows and embossing on text layers
  ([#316](https://github.com/CryptoJones/Photoslop/issues/316))
- [ ] Tell the user when the device runs out of memory, and explain the app
  disappearing. A jetsam kill is `SIGKILL` — nothing can be caught, no dialog
  shown, and no crash report is written under the app's name, so the app
  simply vanishes mid-tap. Nothing can be said at the moment of the kill, but
  the low-memory warning and the next launch are both usable
  ([#311](https://github.com/CryptoJones/Photoslop/issues/311))

- [ ] A mutable pixel-buffer layer for iOS — the missing foundation under the
  paint bucket, the magic wand and the filter library. Drawing is PencilKit
  (vector strokes) and layers are `UIImage`; the only pixel access in
  `ipados/` is `.cgImage` for export, so no pixel operation is expressible
  today ([#324](https://github.com/CryptoJones/Photoslop/issues/324))
- [ ] iOS paint bucket — port the desktop's iterative scanline `flood_fill`;
  first real user of the pixel seam
  ([#325](https://github.com/CryptoJones/Photoslop/issues/325))
- [ ] iOS magic wand, and the selection model it needs. The wand is the flood
  with the write swapped for a mask; the expensive half is that iOS has no
  image-selection concept at all, and a mask nothing honours is a toy
  ([#326](https://github.com/CryptoJones/Photoslop/issues/326))
- [ ] Port the six filters to Swift — Sepia, Pixelate, Denoise, Retro Console,
  Pixel Sort, Datamosh. Datamosh must keep its seeded position-keyed field or
  it loses parity with the desktop and the CLI
  ([#327](https://github.com/CryptoJones/Photoslop/issues/327))

### Desktop

- [ ] A user reports the desktop version "doesn't work" — no symptom, platform
  or install method yet, and it does not reproduce. The old leading guess is
  dead: the shipped 2.9.0 macOS artifact is Notarized Developer ID, accepted
  by Gatekeeper under a quarantine attribute, and launches (checked
  2026-08-14, details on the issue). New leading suspect: **Windows**, whose
  artifact is literally named UNSIGNED and gets a SmartScreen wall. Held open
  until the reporter supplies platform, install route, and what "doesn't
  work" looked like
  ([#273](https://github.com/CryptoJones/Photoslop/issues/273))

### Filters

- [ ] Pixel Sort (Glitch) filter — luma-band runs sorted along rows or
  columns, the glitch-art staple behind the Cyberpunk 2077 cyberspace dive
  ([#318](https://github.com/CryptoJones/Photoslop/issues/318))
- [ ] Datamosh + Chromatic Aberration filter — macroblock motion vectors that
  accumulate down the frame like a P-frame chain with no keyframe, plus a
  radial colour fringe; seeded so smart-filter replay reproduces the glitch
  ([#319](https://github.com/CryptoJones/Photoslop/issues/319))

### Windows

- [ ] Sign the Windows portable bundle via SignPath Foundation's free OSS code
  signing: policy page is in `docs/code-signing-policy.md`; apply at
  signpath.org, then wire signing into `portable.yml` for `v*` tag builds and
  drop `UNSIGNED` from the artifact name
  ([#287](https://github.com/CryptoJones/Photoslop/issues/287))

### Standing

- [ ] App Store GA — what is needed beyond TestFlight is now prepared in
  `docs/appstore/` (metadata, age-rating answers, Data-Not-Collected privacy
  label, screenshots at both required sizes, and a repeatable staging test to
  retake them). The app is to be **free**. What remains is the maintainer's:
  the paid-agreements acceptance and the final Submit
  ([#257](https://github.com/CryptoJones/Photoslop/issues/257))

- [ ] The iPadOS job still passes `-retry-tests-on-failure -test-iterations 2`,
  for one failure mode only: the XCTest daemon failing to initialise a UI-testing
  session (`XCTDaemonErrorDomain Code=19`, `AXDisableAccessibilityOnTermination`),
  where zero tests execute and no app is involved. All six causes that belonged
  to this project are fixed, and the suite passes with no retries on erased
  simulators. Closing this needs a runner that does not drop the accessibility
  session, or Apple ([#238](https://github.com/CryptoJones/Photoslop/issues/238))

## Done

- [x] Every job ran on GitHub's default six-hour timeout, so a stuck runner
  burned an afternoon instead of failing fast: the `v2.15.1` push had five
  jobs sitting at the 6h ceiling while the same commit passed on its PR
  branch in 21m, and the `portable` release gate failed waiting on the run
  that was hung. All 15 jobs across the five workflows now carry a
  `timeout-minutes` sized to their real runtime
  ([#321](https://github.com/CryptoJones/Photoslop/issues/321))
- [x] A text box larger than the canvas could not be resized — its corner
  handles were drawn out past the artwork where no finger could reach them, so
  the box could only be dragged around. Diagnosed by CryptoJones on iPhone
  (400 pt type on a phone-sized canvas). Placed images keep their canvas of
  slack; text is now held inside the canvas, and a box that opens too large is
  scaled to fit about its centre with the words' proportions preserved. Shipped
  in 2.15.1 ([#315](https://github.com/CryptoJones/Photoslop/issues/315))

- [x] Multi-photo import killed the app on a 6 GB phone. Confirmed on device:
  a `JetsamEvent` showed Photoslop `active, frontmost`, killed for
  `vm-pageshortage` as the system's largest process, 1.65 GB resident with a
  2.44 GB lifetime peak. Measured at a dead-linear 48.9 MB per photo, because
  each source was decoded at full resolution only to be scaled down into a
  canvas-sized layer. Now decodes straight to the fitted size, streams the
  batch one photo at a time, budgets against `os_proc_available_memory()`,
  caps undo, handles the memory warning, and lets a superseded canvas render
  decline to start. Document format version 3 lets a layer carry an origin
  rather than having to be exactly canvas-sized, taking a text layer from
  12.58 MB to 176 KB. Re-verified on the reporting device with its own photo
  library: no new jetsam event, process never restarted. Shipped in 2.14.0
  ([#309](https://github.com/CryptoJones/Photoslop/issues/309), closed by
  [#310](https://github.com/CryptoJones/Photoslop/pull/310))

- [x] `NewDocumentUITests` under local Xcode 26.5 — bisected on makemake:
  the iOS 26 SDK's state restoration of held documents raced the launch
  scene and tore down the editor Create Document had just opened; the sheet
  itself always presented. Launch-scene tests now start from an empty store
  (`-PhotoslopFreshDocumentStore`), 6/6 green where 3/3 failed. Residual
  dirty-store user-flow risk noted on the issue for when CI's Xcode rolls
  forward ([#290](https://github.com/CryptoJones/Photoslop/issues/290))

- [x] Cross-platform parity asymmetries after 2.11.0 — all three closed:
  `--text` FAMILY field and desktop Centre on Canvas import in 2.13.0;
  desktop Free Transform re-rendering scaled text from `text_data` (and
  honestly rasterising what type cannot absorb) in 2.13.1
  ([#294](https://github.com/CryptoJones/Photoslop/issues/294))

- [x] Nothing launched a real window — a `windowed` CI job now runs
  `tests/test_windowed.py` against xvfb's X server on Linux and the native
  window server on macOS: real window exposure, scale factor and DPI, a
  forced `QT_SCALE_FACTOR=2` HiDPI check, and a real menu bar. The rest of
  the suite stays offscreen
  ([#274](https://github.com/CryptoJones/Photoslop/issues/274))

- [x] Files shows a generic icon for every `.photoslop` document — saving now
  writes a flattened `preview.png` (≤1024 px long side) into the package and
  a QuickLook thumbnail extension serves it to Files; pre-preview documents
  still open and get a preview at their next save. Verified in the simulator:
  the browser shows the canvas instead of the mascot icon
  ([#267](https://github.com/CryptoJones/Photoslop/issues/267))

- [x] CI mints an Apple development certificate per tagged release and never
  revokes it — two-part fix on 2026-08-14: the TestFlight archive now signs
  with the imported Apple Distribution identity so cloud signing has nothing
  to mint, and a post-upload step revokes any `Created via API` development
  certificates that accumulate anyway (stdlib+openssl JWT, warnings never fail
  a shipped release; dry-run against the live account found the expected four)
  ([#255](https://github.com/CryptoJones/Photoslop/issues/255))

- [x] Create Document cannot be tapped in landscape on iPhone — tried by hand
  on 2026-08-14, as the item asked, and it does not affect a person: in compact
  height iOS 18 swaps the launch scene for the system document browser, whose
  own + button creates a document fine under a finger. Only XCUITest is locked
  out — both Create Document copies report unhittable and synthesized taps
  misfire against the browser's remote view under rotation — so the landscape
  skip stays, with its comment corrected. No layout was changed
  ([#252](https://github.com/CryptoJones/Photoslop/issues/252))

- [x] Pinch-zoom and pan died the moment a crop started, because suspending
  drawing switched off hit-testing for the whole scroll view. Fixed in 2.9.0 by
  moving the overlay inside the scroll view's content, in document coordinates —
  which dissolved #260 and #268 with it (DD-012, LESSONSLEARNED L-005)
  ([#270](https://github.com/CryptoJones/Photoslop/issues/270))

- [x] No way to scale a document — Canvas Size padded and Crop discarded, but
  nothing resampled. **Resize Document** shipped in 2.9.0, reusing the New
  document size sheet and agreeing with `photoslop-cli --resize`
  ([#269](https://github.com/CryptoJones/Photoslop/issues/269))

- [x] A second crop started from the pre-crop canvas
  ([#268](https://github.com/CryptoJones/Photoslop/issues/268))

- [x] Crop took a different region than the rectangle you drew. Fixed in 2.8.0
  by having the canvas publish where it is drawn; closed by construction in
  2.9.0, which removed the conversion entirely rather than correcting it
  ([#260](https://github.com/CryptoJones/Photoslop/issues/260))

- [x] New layer from image scaled the layer to fill the canvas. It now arrives
  at original size in a placement box, constrain proportions on by default
  ([#266](https://github.com/CryptoJones/Photoslop/issues/266))

- [x] Import Image only reached Files, never the Photos library
  ([#265](https://github.com/CryptoJones/Photoslop/issues/265))

- [x] Placed text had no sizable box — **Fit Text…** now scales the type to span
  a box you drag ([#261](https://github.com/CryptoJones/Photoslop/issues/261))

- [x] An imported layer could not be resized after the fact — **Resize Layer…**
  opens the same placement box
  ([#262](https://github.com/CryptoJones/Photoslop/issues/262))

- [x] Pen and pencil had a width slider but no opacity control; opacity was
  reachable only through the alpha slider buried in the system colour sheet.
  Colour and opacity now share one popover and one tool-strip slot
  ([#271](https://github.com/CryptoJones/Photoslop/issues/271))


- [x] iOS could not export into the Photos library — `.fileExporter` only reaches the
  Files hierarchy, so a finished picture has to be saved to Files and imported
  from the Photos app by hand. Needs a destination choice in the export sheet,
  `NSPhotoLibraryAddUsageDescription`, add-only authorisation, and a format list
  that narrows to what Photos accepts
  ([#248](https://github.com/CryptoJones/Photoslop/issues/248))

- [x] iOS had no crop — Canvas Size takes a size but not a region, so there was
  no way to choose which part of the picture to keep or see what you were about
  to lose. Shipped a draggable crop rectangle with edge and corner handles, a
  dimmed surround, a live pixel readout, a Free/Original/1:1/3:2/4:3/16:9 aspect
  lock, and a single undoable apply that agrees with `photoslop-cli --crop`
  ([#249](https://github.com/CryptoJones/Photoslop/issues/249))
- [x] Ink colour and brush width were off-screen on iPhone and iPad mini — the
  tool strip overflows its width and scrolls with no indicator, so the two
  controls a painting app touches most are simply not there. Measured: the width
  slider sits at x=415.7 on a 402pt iPhone and x=773.5 on a 744pt iPad mini, and
  the ink well and Finger toggle are not in the accessibility tree at all. Third
  instance this month of a control that exists in code, passes its tests, and
  cannot be reached on the device
  ([#246](https://github.com/CryptoJones/Photoslop/issues/246)) — the tool
  picker is a palette now, options are contextual, Finger and Clear moved to the
  menu, and two tests fail if any control leaves the window

- [x] Every project-side cause of the XCUITest flakiness is fixed, and the retry
  budget is down from three iterations to two. The premise that the app was
  reliable and the harness racy was wrong: six causes were hiding behind the flag
  — a narrow iPad overflowing its bar and losing Export, every test inheriting the
  last one's documents, a layer-count assertion racing an async decode, queries
  too expensive for XCTest to snapshot, a cold simulator charging its
  first-document cost to whichever test ran first, and the canvas-size question
  being asked twice. Verified with no retries at all on erased simulators
  ([#238](https://github.com/CryptoJones/Photoslop/issues/238))

- [x] Export Image left the navigation bar on a narrow iPad — an iPad mini in
  portrait is 744pt and reports the regular size class, so it took the nine-item
  iPad layout (eleven with a text layer active) and UIKit collapsed the trailing
  group behind an unlabelled chevron. #227 one size class up. One bar layout per
  idiom now, budgeted for the narrowest device and with an item count that cannot
  change with the document's contents
  ([#238](https://github.com/CryptoJones/Photoslop/issues/238))

- [x] Import an image as a layer on the desktop and the CLI — **Layer ▸ New Layer
  from Image…** (`Ctrl+Shift+I`) and `--import-layer FILE`, the 59th shared engine
  operation, both separate from opening a file the way iOS keeps them separate.
  The desktop keeps the import at native size and centres it, overhanging the
  canvas rather than downscaling, because a desktop layer carries its own offset
  and extent where a `.photoslop` layer image must be canvas-sized
  ([#237](https://github.com/CryptoJones/Photoslop/issues/237))

- [x] Add "new layer from photo" to iOS — a multiple selection from the photo
  library, each photo its own layer over the open document in one undo step.
  Importing used to replace the whole document, so a second image threw the first
  away and a double exposure was impossible
  ([#234](https://github.com/CryptoJones/Photoslop/pull/234)) — shipped v2.4.0

- [x] iPhone had no way to export — every document action went on one bar, and at
  compact width UIKit collapsed the leading group into an overflow menu and
  dropped the trailing `ToolbarItem` outright, taking Undo, Redo, Export, and
  About with it. Compact width now picks its own three: Layers, a More Actions
  menu, and Export, with undo/redo in the tool strip
  ([#227](https://github.com/CryptoJones/Photoslop/issues/227)) — shipped v2.4.0

- [x] A device with no local Files location could not create a document at all —
  `LSSupportsOpeningDocumentsInPlace` without `UIFileSharingEnabled` left
  `DocumentGroup` nowhere to save on a fresh device or one not signed into iCloud
  Drive
  ([#228](https://github.com/CryptoJones/Photoslop/issues/228)) — shipped v2.4.0

- [x] The canvas-size question was never asked for a created document — creating
  one writes it to disk and reopens it through `init(configuration:)`, so the flag
  `init()` set was spent on a store that never reached the screen. The opening
  path now recognises an untouched new document instead
  ([#229](https://github.com/CryptoJones/Photoslop/issues/229)) — shipped v2.4.0

- [x] About said "Photoslop for iPad" on every device, including every iPhone. It
  now names no platform at all, matching the desktop edition, and carries the
  mascot, description and licence the desktop About carries
  ([#230](https://github.com/CryptoJones/Photoslop/issues/230)) — shipped v2.4.0

- [x] Update the MCP harness for the 2026-07-28 ("v2") protocol standard — capped
  `mcp` while the code used the 1.x API, added Streamable HTTP and SSE transports
  alongside stdio, then migrated `FastMCP` → `MCPServer` once 2.0.0 shipped as a
  stable release
  ([#182](https://github.com/CryptoJones/Photoslop/issues/182))

- [x] Fix the suite-wide segfault that red-lighted unrelated pull requests — a
  TaskService use-after-free, not a flaky test: QRunnable auto-deletes, so the
  thread pool freed each worker while TaskService still held it
  ([#192](https://github.com/CryptoJones/Photoslop/issues/192)) — shipped v2.0.1

- [x] Add a native iPhone edition — universal binary, layout driven by the
  horizontal size class, layers in a sheet at compact width
  ([#203](https://github.com/CryptoJones/Photoslop/issues/203)) — shipped v2.1.0

- [x] Automate signed iPad delivery — upload a signed build to App Store Connect
  for TestFlight on every `v*` tag, with signing material held in the
  `testflight` GitHub environment
  ([#196](https://github.com/CryptoJones/Photoslop/issues/196)) — shipped v2.0.0

- [x] Apple Pencil tilt does not change stroke width on iPad — the canvas was
  hardwired to PencilKit's `.pen` ink, which reads force only; Pencil and
  Marker brushes now read tilt
  ([#198](https://github.com/CryptoJones/Photoslop/issues/198)) — shipped v2.0.0

- [x] Carry nested OpenRaster `<stack>` opacity, visibility, and composite-op
  into layer groups, and persist group state across a save
  ([#186](https://github.com/CryptoJones/Photoslop/issues/186)) — PR #191

- [x] Ship `photoslop-cli` and `photoslop-mcp` in the portable macOS and
  Windows builds
  ([#187](https://github.com/CryptoJones/Photoslop/issues/187)) — PR #190

- [x] Stop `test_gui_heartbeat_continues_while_worker_runs` racing a 1.0s
  budget on Windows CI
  ([#188](https://github.com/CryptoJones/Photoslop/issues/188)) — PR #189

- [x] Add a native iPadOS edition with Apple Pencil drawing, touch navigation,
  layered raster editing, Photos/Files import, PNG export, device builds, and
  simulator verification
  ([#173](https://github.com/CryptoJones/Photoslop/issues/173)) — shipped v1.29.0

- [x] Add accessibility, performance, cursor, UI, and vector workflow
  verification plus honest feature-parity documentation
  ([#158](https://github.com/CryptoJones/Photoslop/issues/158)) — shipped v1.26.0

- [x] Add SVG import/export and editable artboard interchange while retaining
  OpenRaster raster fallbacks
  ([#157](https://github.com/CryptoJones/Photoslop/issues/157)) — shipped v1.25.0

- [x] Build vector selection, node editing, appearance, Boolean, alignment,
  snapping, text, and construction workflows
  ([#156](https://github.com/CryptoJones/Photoslop/issues/156)) — shipped v1.24.0

- [x] Introduce a versioned native vector object model with Bézier geometry,
  appearance, transforms, hierarchy, migration, and crisp rendering
  ([#155](https://github.com/CryptoJones/Photoslop/issues/155)) — shipped v1.23.0
- [x] Split UI responsibilities into action, tool, workspace, and service
  registries while preserving GUI/CLI/MCP engine parity
  ([#154](https://github.com/CryptoJones/Photoslop/issues/154)) — shipped v1.22.0
- [x] Reduce canvas repaint and preview overhead with dirty overlays,
  generation-aware thumbnails, proxy previews, and bounded caches
  ([#153](https://github.com/CryptoJones/Photoslop/issues/153)) — shipped v1.21.0
- [x] Add a cancellable, memory-bounded background task service for filters,
  I/O, RAW, exports, subprocesses, and model requests
  ([#152](https://github.com/CryptoJones/Photoslop/issues/152)) — shipped v1.20.0
- [x] Implement cross-platform accessibility semantics and keyboard workflows
  for standard and custom Qt widgets
  ([#151](https://github.com/CryptoJones/Photoslop/issues/151)) — shipped v1.19.0
- [x] Streamline workspace actions and contextual tool options through an
  action registry, command palette, Properties panel, and responsive controls
  ([#150](https://github.com/CryptoJones/Photoslop/issues/150)) — shipped v1.18.0
- [x] Replace toolbox iconography and group tools into keyboard-accessible
  flyouts with theme/HiDPI states and licensed SVG assets
  ([#149](https://github.com/CryptoJones/Photoslop/issues/149)) — shipped v1.17.0
- [x] Add contextual tool cursors and pointer states — brush-radius, tool glyph,
  modifier, handle, target-validity, and temporary-pan cursors
  ([#148](https://github.com/CryptoJones/Photoslop/issues/148)) — shipped v1.16.0
- [x] Fix text-size keyboard entry up to 999 pt — retain numeric-field focus
  during multi-digit edits, validate 6–999, and add regression coverage
  ([#147](https://github.com/CryptoJones/Photoslop/issues/147)) — shipped v1.15.1
- [x] Open dialog: extend the "Open images" window to fill the internal workable
  image area (central canvas region) instead of floating as a smaller inset box
  ([#144](https://github.com/CryptoJones/Photoslop/issues/144)) — shipped v1.15.0
- [x] macOS installer script (`scripts/install-macos.sh`) that builds a clickable
  `Photoslop.app` launcher and installs it into `/Applications`
  ([#142](https://github.com/CryptoJones/Photoslop/issues/142))
- [x] Create MCP server for Photoslop — `photoslop-mcp` exposes the engine as MCP
  tools (`list_operations`, `edit_image`, `document_info`) mirroring `photoslop-cli`
  ([#134](https://github.com/CryptoJones/Photoslop/issues/134)) — shipped v1.13.0
- [x] Open dialog: always show all columns (Name/Size/Kind/Date Modified) without
  truncation ([#135](https://github.com/CryptoJones/Photoslop/issues/135)) — shipped v1.12.1
- [x] Move Zoom In / Zoom Out to the top options bar of the main window,
  alongside the existing top options
  ([#136](https://github.com/CryptoJones/Photoslop/issues/136)) — shipped v1.12.1
- [x] Credits window: rename the "Programming" section heading to "Contributors"
  ([#137](https://github.com/CryptoJones/Photoslop/issues/137)) — shipped v1.12.1
- [x] Retro Console (8-Bit) filter — pixelate + palette crush + dither
  ([#130](https://github.com/CryptoJones/Photoslop/issues/130)) — shipped v1.12.0
- [x] Consolidated Preferences dialog (Model Backend + Color), native macOS ⌘,
  ([#131](https://github.com/CryptoJones/Photoslop/issues/131)) — shipped v1.12.0

---

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
