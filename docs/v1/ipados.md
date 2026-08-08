# Photoslop for iPadOS

Photoslop v2.4.0 includes an iOS-native edition targeting iPadOS and iOS 17 and
newer. It is a universal app: iPad and iPhone ship in one binary from `ipados/`,
built with SwiftUI, UIKit, and PencilKit. This is a native
client rather than a repackaging of the desktop Python process: Qt supports
iOS, but Qt for Python does not currently provide a supported iOS deployment
path.

## iPhone and iPad

One binary serves both, adapting to the horizontal size class rather than the
device name, so an iPad in a narrow Split View gets the phone layout too.

- **Regular width** keeps the layer list in a sidebar beside the canvas, and
  every document action on the navigation bar.
- **Compact width** moves the layer list to a sheet reached from **Layers**,
  because `NavigationSplitView` collapses its sidebar into a pushed column
  there, and reaching the layers would otherwise navigate away from the
  drawing.
- A phone's navigation bar holds three controls beside the document title, so
  the compact layout picks them rather than leaving the choice to UIKit:
  **Layers**, a **More Actions** menu holding New, Canvas Size, the text
  actions, Import Image, Photos, and About, and **Export**. Undo and redo move
  to the leading edge of the tool strip, which never has to be scrolled to.
- The tool strip narrows its brush picker and width slider at compact width and
  scrolls horizontally if it still does not fit.

CI runs the simulator suite on both an iPad and an iPhone so neither layout
regresses unnoticed. Toolbar reachability is covered by XCUITest rather than
the unit suite: whether a control survives a real navigation bar is a question
only a running app can answer.

The XCUITests run with `-retry-tests-on-failure -test-iterations 3`. The
flakiness is in the harness rather than the app: relaunching between test
methods intermittently brings the app up on a screen the test did not ask for,
while fifteen consecutive launches inside a single test method never flake.
Settle-waits on sheet dismissal, waiting for `.notRunning` in teardown, and a
launch retry each failed to remove it. A real defect still fails all three
attempts, so the retries buy tolerance for the harness without hiding
regressions.

## Editing workflow

- Draw with Apple Pencil using the Pen, Pencil, Marker, or bitmap Eraser.
  PencilKit supplies pressure and predicted-touch handling. Turn on **Finger**
  to draw with touch; otherwise one finger pans and two fingers pinch to zoom.
- Brushes differ in which Apple Pencil inputs they read. Pen varies with force
  alone, so tilting the Pencil does not change its stroke. Pencil and Marker
  also read the Pencil's altitude and azimuth and broaden as it is laid over,
  which is the tool to reach for when shading. Pen remains the default.
- Set ink color and brush width from the bottom tool strip.
- **Add Text** puts text on its own layer, on top of the stack, centred on the
  canvas and ready to move. The anchor is the text's top-left, the same
  convention as `photoslop-cli --text "X,Y,SIZE[,R,G,B]:TEXT"`.
- Text stays editable. **Edit Text** reopens the words, size, and colour of the
  selected text layer and re-renders it in place, keeping its position in the
  stack along with its visibility and opacity. **Move Text** drags it to a new
  spot, and the whole drag is a single undo step rather than one per touch.
  Drawing is suspended while either mode is armed, so a touch positions rather
  than paints.
- The words, size, colour, and anchor are stored in the document, which is what
  makes that possible. Documents saved before this shipped still open; they
  simply contain no text layers.
- **New** offers a starting canvas size: Standard, Square, HD, 4K UHD, A4 and
  US Letter at 300 DPI, Photo 6x4, or a custom size. **Canvas Size** applies the
  same choice to the open document, padding or cropping around centred content
  exactly as `photoslop-cli --canvas-size` does, and is undoable. Reach for it to
  change a size already in use, or after cancelling the question a new document
  asks.
- **About Photoslop** introduces the app the way the desktop edition does: Le
  Basilisk, the name with no platform attached, and the same one-line
  description, over the licence and repository link. It also reports the
  marketing version and build number, and the open document's canvas size and
  layer count. The sheet opens at half height and can be dragged up.

  The mascot is drawn in code by `photoslop/appicon.py` and has no asset file, so
  `scripts/render-ios-mascot.py` exports the QPainter original into
  `Mascot.imageset` at three scales. Re-run it after changing `draw_mascot`; the
  `quality` CI job fails if the committed asset has drifted from the code. The
  check compares decoded pixels with a tolerance rather than PNG bytes: Qt
  antialiases and packs PNGs slightly differently on Linux than on macOS, so a
  byte comparison fails on the CI runner for an asset that is perfectly current. The
  app icon is not reused for this: it is flattened onto white, which would show
  as a white box in a grouped list and in dark mode.
- Use the layer sidebar to add, duplicate, rename, show/hide, change opacity,
  reorder, merge down, clear, or delete raster layers.
- Open an image from Files or Photos. Imports create a document at the image's
  native pixel dimensions.
- Creating a document asks for its canvas size before you draw. The question
  cannot ride on a flag set when the document is built: creating one writes it to
  disk and reopens it through `init(configuration:)`, so anything set in `init()`
  belongs to a store that never reaches the screen. The opening path recognises
  an untouched new document instead — default canvas, one unedited `Background`
  layer — which is what survives that round trip. Reopening a still-blank
  document therefore asks again; Cancel keeps the size.
- Create, open, autosave, and reopen layered `.photoslop` package documents.
  The package preserves canvas geometry, stable layer IDs/order, names,
  visibility, opacity, raster PNGs, the active layer, and PencilKit strokes.
  Documents are visible in Files under **On My iPhone/iPad → Photoslop**; the
  app declares `UIFileSharingEnabled` alongside
  `LSSupportsOpeningDocumentsInPlace` so that a device with no other local
  provider — a fresh one, or one not signed into iCloud Drive — still has
  somewhere to save.
- Undo and redo drawing, layer lifecycle/reordering, visibility, opacity,
  renaming, clearing, imports, and document replacement with the toolbar or
  `Command-Z` / `Shift-Command-Z`.
- Export a flattened image through the iOS document picker. **Export** names
  the file and picks PNG, JPEG, HEIC, TIFF, GIF, or BMP, with a quality slider
  for the lossy two; formats without an alpha channel are flattened onto white
  first. The exported image includes every visible raster layer and PencilKit
  drawing at its layer opacity.
- Standard document-browser New/Open/Save behavior is available with a hardware
  keyboard; `Shift-Command-E` exports.

Compositing, merge rendering, and PNG export run outside the main actor. A
generation check prevents an older background render from replacing a newer
edit. iPad documents are capped at 16,384 px per side, 100 million pixels,
2,048 layers, 256 MiB per layer payload, and 1 GiB per project package.

## `.photoslop` package layout

```text
Example.photoslop/
  manifest.json
  layers/
    <stable-layer-uuid>/
      image.png
      drawing.data
```

The versioned manifest is the source of layer order and metadata. Opening a
package validates its schema, UUID uniqueness, dimensions, counts, payload
sizes, layer image geometry, opacity, and PencilKit drawing data before the
document is installed.

## Build an iPad device bundle

Requirements:

- macOS with Xcode 15 or newer and the iOS platform installed
- XcodeGen 2.46.0. CI downloads the reviewed release archive and verifies SHA-256
  `4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806`;
  local developers may install that version with their preferred package manager.

From the repository root:

```bash
./scripts/build-ipados.sh
```

The script regenerates `ipados/Photoslop-iPadOS.xcodeproj`, builds the arm64
device app with signing disabled, and writes
`ipados/dist/Photoslop-iPadOS-unsigned.zip`. CI performs the same build and
compiles/runs the iPad simulator tests. `XCODEGEN` may point the script at an
executable; CI uses that hook for the downloaded, checksum-verified binary.

To run on a physical iPad, generate the project, open it in Xcode, select the
`PhotoslopIPad` target, choose your Apple Developer team, and run on the paired
device. The device must be registered in the developer account and must have
Developer Mode enabled (Settings, then Privacy & Security, then Developer Mode)
before an installed development build will launch.

## TestFlight distribution

Tag builds upload to App Store Connect automatically. The `testflight` job in
`.github/workflows/ipados.yml` runs after the unsigned validation build on any
`v*` tag, and delegates to `scripts/publish-ipados-testflight.sh`, which
archives the Release configuration, exports an App Store `.ipa`, validates it,
and uploads it with `altool`.

Signing credentials live in the `testflight` GitHub environment, never in this
repository or in release artifacts:

| Secret | Contents |
| --- | --- |
| `IOS_DISTRIBUTION_CERTIFICATE_P12` | Base64 of the Apple Distribution `.p12` |
| `IOS_DISTRIBUTION_CERTIFICATE_PASSWORD` | Export password for that `.p12` |
| `APP_STORE_CONNECT_KEY_ID` | App Store Connect API key identifier |
| `APP_STORE_CONNECT_ISSUER_ID` | App Store Connect API issuer identifier |
| `APP_STORE_CONNECT_PRIVATE_KEY` | Base64 of the API key `.p8` |

The API key needs the **Admin** role so `-allowProvisioningUpdates` can maintain
the App Store provisioning profile without a committed profile. App Manager is
not sufficient: cloud signing fails with `Cloud signing permission error` and
`No profiles for 'io.ronin48.photoslop.ipad' were found`. An API key's access
cannot be edited after it is generated, so a key with the wrong role has to be
replaced rather than upgraded.

Because `check-version.py` derives `CURRENT_PROJECT_VERSION` from the marketing
version, each upload consumes exactly one build number. App Store Connect
rejects a repeated build number, so re-publishing requires a version bump
rather than a re-run of the same tag.

Once a build finishes processing, internal testers on the App Store Connect
team receive it immediately. External testers, up to 10,000 by email or public
link, require Beta App Review on the first build of a version.

## Initial-edition boundary

The iPad edition currently covers persistent layered raster/PencilKit painting,
image import, document-wide undo, and flattened image export. The desktop edition
remains the authoritative home for OpenRaster round trips, selections,
adjustments, filters, appearance effects, editable vectors/text, automation,
CLI, and MCP. An unsigned GitHub artifact is a reproducible developer build,
not an App Store-signed IPA.

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/
