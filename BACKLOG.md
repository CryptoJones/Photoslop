# Backlog

A second view of the GitHub [Issues](https://github.com/CryptoJones/Photoslop/issues)
tab. Every backlog item has a matching issue and vice versa; the two stay in
sync — check an item here when its issue closes.

## Open

### Found on a device, 2026-08-14

- [ ] Files shows a generic Photoslop icon for every `.photoslop` document
  instead of a preview. Wants a QuickLook thumbnail extension and a `preview.png`
  in the package. Held back from 2.9.0 deliberately: a new app-extension target
  needs its own bundle id and provisioning profile, and that is the signing path
  that already fails releases (#255)
  ([#267](https://github.com/CryptoJones/Photoslop/issues/267))

### Standing

- [ ] CI mints an Apple development certificate per tagged release and never
  revokes it — the account hit its limit at 15 and the v2.6.0 TestFlight archive
  failed with "choose a certificate to revoke", after the tests had passed and
  the app had built. Ten `Created via API` certs were cleared by hand, which
  buys about ten more releases
  ([#255](https://github.com/CryptoJones/Photoslop/issues/255))

- [ ] Create Document cannot be tapped in landscape on iPhone — found when a
  rotation leaked out of one test and broke every test after it at the same
  point. Unknown whether it affects a person or only the automation; the first
  step is to try it by hand, not to change layout
  ([#252](https://github.com/CryptoJones/Photoslop/issues/252))

- [ ] The iPadOS job still passes `-retry-tests-on-failure -test-iterations 2`,
  for one failure mode only: the XCTest daemon failing to initialise a UI-testing
  session (`XCTDaemonErrorDomain Code=19`, `AXDisableAccessibilityOnTermination`),
  where zero tests execute and no app is involved. All six causes that belonged
  to this project are fixed, and the suite passes with no retries on erased
  simulators. Closing this needs a runner that does not drop the accessibility
  session, or Apple ([#238](https://github.com/CryptoJones/Photoslop/issues/238))

## Done

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
